"""从 JJ 回放会话生成可审计的90格棋子分类数据集。"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import imagehash
from PIL import Image

from app.chess.checker import PositionChecker
from .replay import JJReplayDataset


DEFAULT_GRID = {
    "x": [44, 133, 222, 311, 400, 489, 578, 667, 756],
    "y": [44, 130, 216, 302, 388, 474, 560, 646, 732, 818],
}
ACCEPTED_FLAGS = (
    "is_red_start",
    "is_black_start",
    "is_my_step",
    "is_opponent_step",
    "is_same_board",
)
REJECTED_FLAGS = (
    "is_illegal_board",
    "is_illegal_change",
    "is_history_mismatch",
    "is_multi_step",
)
PIECE_DIRECTORIES = {
    **{piece: f"black_{piece}" for piece in "rnbakcp"},
    **{piece: f"red_{piece}" for piece in "RNBAKCP"},
    "-": "empty",
    ".": "marker",
}


@dataclass(frozen=True)
class DatasetBuildSummary:
    sessions: int
    games: int
    accepted_frames: int
    rejected_frames: int
    samples: int
    corrections_applied: int
    quarantined_samples: int
    class_counts: Dict[str, int]
    output_dir: str


class JJDatasetBuilder:
    """
    将回放事件转换为棋子分类样本。

    开局状态使用规则模块中的标准模板作为强标签；其他通过规则状态机的
    棋盘只标记为 pseudo，必须经过审计后才能进入最终训练集。
    """

    def __init__(
        self,
        output_dir: str,
        *,
        normalized_width: int = 800,
        crop_scale: float = 0.85,
        max_per_class: int = 2000,
        duplicate_distance: int = 2,
        corrections_path: Optional[str] = None,
        audit_model_path: Optional[str] = None,
        audit_confidence: float = 0.70,
    ):
        self.output_dir = os.path.abspath(os.path.expanduser(output_dir))
        self.samples_dir = os.path.join(self.output_dir, "samples")
        self.labels_path = os.path.join(self.output_dir, "labels.jsonl")
        self.normalized_width = max(100, int(normalized_width))
        self.crop_scale = float(crop_scale)
        self.max_per_class = max(1, int(max_per_class))
        self.duplicate_distance = max(0, int(duplicate_distance))
        self._hashes: Dict[str, List[int]] = defaultdict(list)
        self._class_counts = Counter()
        self._corrections = self._load_corrections(corrections_path)
        self._applied_corrections = set()
        self.audit_confidence = float(audit_confidence)
        self._audit_session = None
        self._audit_input_name = None
        self._audit_class_map = None
        self._quarantined_samples = 0
        self.quarantine_path = os.path.join(self.output_dir, "quarantined_samples.jsonl")
        if audit_model_path:
            import onnxruntime as ort

            model_path = os.path.abspath(os.path.expanduser(audit_model_path))
            map_path = os.path.join(os.path.dirname(model_path), "jj_piece_map.json")
            with open(map_path, encoding="utf-8") as file:
                self._audit_class_map = json.load(file)
            self._audit_session = ort.InferenceSession(
                model_path, providers=["CPUExecutionProvider"]
            )
            self._audit_input_name = self._audit_session.get_inputs()[0].name
        os.makedirs(self.samples_dir, exist_ok=True)

    @staticmethod
    def _load_corrections(path: Optional[str]) -> Dict[Tuple[str, int, int, int], Dict]:
        if not path:
            return {}
        corrections = {}
        with open(os.path.abspath(os.path.expanduser(path)), encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue
                correction = json.loads(line)
                key = (
                    str(correction["session_id"]),
                    int(round(float(correction["captured_at"]) * 1_000_000)),
                    int(correction["row"]),
                    int(correction["col"]),
                )
                if key in corrections:
                    raise ValueError(f"duplicate correction on line {line_number}: {key}")
                if correction.get("to") not in PIECE_DIRECTORIES:
                    raise ValueError(f"invalid correction label on line {line_number}")
                corrections[key] = correction
        return corrections

    @staticmethod
    def _superseded_start_ids(analyses: List[Dict], window_seconds: float = 30.0):
        """同一局未走子前方向被纠正时，丢弃较早的假开局。"""
        superseded = set()
        start_indices = [
            index for index, event in enumerate(analyses)
            if (event.get("status") or {}).get("is_red_start")
            or (event.get("status") or {}).get("is_black_start")
        ]
        for current, following in zip(start_indices, start_indices[1:]):
            current_time = float(analyses[current]["captured_at"])
            following_time = float(analyses[following]["captured_at"])
            if following_time - current_time > float(window_seconds):
                continue
            moved_between = any(
                (middle.get("status") or {}).get("is_my_step")
                or (middle.get("status") or {}).get("is_opponent_step")
                for middle in analyses[current + 1:following]
            )
            if not moved_between:
                superseded.add(id(analyses[current]))
        return superseded

    @staticmethod
    def _status_accepted(event: Dict) -> bool:
        if event.get("is_settlement_screen"):
            return False
        board = event.get("board")
        status = event.get("status") or {}
        if not (
            isinstance(board, list)
            and len(board) == 10
            and all(isinstance(row, list) and len(row) == 9 for row in board)
        ):
            return False
        if any(bool(status.get(flag)) for flag in REJECTED_FLAGS):
            return False
        return any(bool(status.get(flag)) for flag in ACCEPTED_FLAGS)

    @staticmethod
    def _nearest_capture(captures: List[Dict], captured_at: float) -> Optional[Dict]:
        if not captures:
            return None
        return min(
            captures,
            key=lambda event: abs(float(event["captured_at"]) - captured_at),
        )

    @staticmethod
    def _load_grid(session_dir: str) -> Dict[str, List[int]]:
        metadata_path = os.path.join(session_dir, "session.json")
        try:
            with open(metadata_path, encoding="utf-8") as file:
                metadata = json.load(file)
            grid = metadata.get("grid_coords") or {}
            if len(grid.get("x", [])) == 9 and len(grid.get("y", [])) == 10:
                return {"x": list(grid["x"]), "y": list(grid["y"])}
        except (OSError, json.JSONDecodeError, TypeError):
            pass
        return {"x": list(DEFAULT_GRID["x"]), "y": list(DEFAULT_GRID["y"])}

    def _normalize(self, image: Image.Image) -> Image.Image:
        height = round(image.height * self.normalized_width / image.width)
        return image.convert("RGB").resize(
            (self.normalized_width, height), Image.Resampling.LANCZOS
        )

    def _crop_grid(self, image: Image.Image, grid: Dict[str, List[int]]):
        x_array, y_array = grid["x"], grid["y"]
        for row, center_y in enumerate(y_array):
            for col, center_x in enumerate(x_array):
                left_gap = x_array[col] - x_array[col - 1] if col else x_array[1] - x_array[0]
                right_gap = x_array[col + 1] - x_array[col] if col < 8 else left_gap
                top_gap = y_array[row] - y_array[row - 1] if row else y_array[1] - y_array[0]
                bottom_gap = y_array[row + 1] - y_array[row] if row < 9 else top_gap
                radius = int(
                    ((min(left_gap, right_gap) // 2 + min(top_gap, bottom_gap) // 2) // 2)
                    * self.crop_scale
                )
                adjusted_x = max(radius, min(image.width - 1 - radius, center_x))
                adjusted_y = max(radius, min(image.height - 1 - radius, center_y))
                crop = image.crop((
                    adjusted_x - radius,
                    adjusted_y - radius,
                    adjusted_x + radius,
                    adjusted_y + radius,
                ))
                yield row, col, crop

    def _is_duplicate(self, label: str, crop: Image.Image) -> Tuple[bool, str]:
        hash_value = imagehash.dhash(crop, hash_size=8)
        hash_int = int(str(hash_value), 16)
        duplicate = any(
            (existing ^ hash_int).bit_count() <= self.duplicate_distance
            for existing in self._hashes[label]
        )
        return duplicate, str(hash_value)

    def _save_sample(self, label: str, crop: Image.Image, metadata: Dict) -> bool:
        if self._class_counts[label] >= self.max_per_class:
            return False
        duplicate, hash_text = self._is_duplicate(label, crop)
        if duplicate:
            return False
        safe_label = PIECE_DIRECTORIES.get(label, f"unknown_{label}")
        class_dir = os.path.join(self.samples_dir, safe_label)
        os.makedirs(class_dir, exist_ok=True)
        filename = (
            f"{metadata['session_id']}-g{metadata['game_index']:02d}-"
            f"{metadata['frame_id']}-r{metadata['row']}-c{metadata['col']}.jpg"
        )
        relative_path = os.path.join("samples", safe_label, filename)
        crop.resize((96, 96), Image.Resampling.LANCZOS).save(
            os.path.join(self.output_dir, relative_path),
            format="JPEG",
            quality=95,
        )
        record = {**metadata, "label": label, "hash": hash_text, "path": relative_path}
        with open(self.labels_path, "a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False))
            file.write("\n")
        self._hashes[label].append(int(hash_text, 16))
        self._class_counts[label] += 1
        return True

    def _audit_frame(self, crops: List[Image.Image]):
        if self._audit_session is None:
            return [None] * len(crops)
        import numpy as np

        inputs = []
        for crop in crops:
            image = crop.convert("RGB").resize((80, 80), Image.Resampling.BILINEAR)
            array = np.asarray(image, dtype=np.float32) / 255.0
            inputs.append(array.transpose(2, 0, 1))
        batch = np.ascontiguousarray(np.stack(inputs), dtype=np.float32)
        logits = self._audit_session.run(None, {self._audit_input_name: batch})[0]
        logits -= np.max(logits, axis=1, keepdims=True)
        probabilities = np.exp(logits)
        probabilities /= np.sum(probabilities, axis=1, keepdims=True)
        indices = np.argmax(probabilities, axis=1)
        return [
            {
                "label": self._audit_class_map[str(int(index))],
                "confidence": float(probabilities[row, index]),
            }
            for row, index in enumerate(indices)
        ]

    def _quarantine(self, metadata: Dict, expected: str, prediction: Dict) -> None:
        self._quarantined_samples += 1
        record = {
            **metadata,
            "expected": expected,
            "audit_prediction": prediction["label"],
            "audit_confidence": prediction["confidence"],
            "reason": "high_confidence_teacher_conflict",
        }
        with open(self.quarantine_path, "a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False))
            file.write("\n")

    def build(self, session_dirs: Iterable[str]) -> DatasetBuildSummary:
        accepted_frames = 0
        rejected_frames = 0
        session_count = 0
        total_games = 0

        for session_dir in session_dirs:
            dataset = JJReplayDataset(session_dir)
            session_count += 1
            session_id = os.path.basename(dataset.session_dir)
            grid = self._load_grid(dataset.session_dir)
            captures = [event for event in dataset.events if event.get("type") == "capture"]
            analyses = [event for event in dataset.events if event.get("type") == "analysis"]
            superseded_starts = self._superseded_start_ids(analyses)
            current_game_index = 0

            for event in analyses:
                status = event.get("status") or {}
                if id(event) in superseded_starts:
                    rejected_frames += 1
                    continue
                if status.get("is_red_start") or status.get("is_black_start"):
                    total_games += 1
                    current_game_index = total_games
                if not self._status_accepted(event):
                    rejected_frames += 1
                    continue
                capture = self._nearest_capture(captures, float(event["captured_at"]))
                if capture is None or abs(
                    float(capture["captured_at"]) - float(event["captured_at"])
                ) > 0.001:
                    rejected_frames += 1
                    continue

                board = event["board"]
                label_source = "trusted_state"
                if status.get("is_red_start"):
                    board = PositionChecker.START_RED
                    label_source = "start_template"
                elif status.get("is_black_start"):
                    board = PositionChecker.START_BLACK
                    label_source = "start_template"

                marker_positions = {
                    tuple(position) for position in event.get("marker_coords", [])
                    if isinstance(position, list) and len(position) == 2
                }
                image_path = os.path.join(dataset.session_dir, capture["path"])
                with Image.open(image_path) as source:
                    normalized = self._normalize(source)
                    grid_crops = list(self._crop_grid(normalized, grid))
                    audit_predictions = self._audit_frame(
                        [crop for _, _, crop in grid_crops]
                    )
                    for (row, col, crop), audit_prediction in zip(
                        grid_crops, audit_predictions
                    ):
                        label = "." if (row, col) in marker_positions else board[row][col]
                        sample_label_source = label_source
                        correction_key = (
                            session_id,
                            int(round(float(event["captured_at"]) * 1_000_000)),
                            row,
                            col,
                        )
                        correction = self._corrections.get(correction_key)
                        if correction is not None:
                            if label != correction.get("from"):
                                raise ValueError(
                                    f"correction source mismatch at {correction_key}: "
                                    f"dataset={label!r}, correction={correction.get('from')!r}"
                                )
                            label = correction["to"]
                            sample_label_source = "visual_correction"
                            self._applied_corrections.add(correction_key)
                        sample_metadata = {
                            "session_id": session_id,
                            "game_index": max(1, current_game_index),
                            "frame_id": capture["frame_id"],
                            "captured_at": float(event["captured_at"]),
                            "row": row,
                            "col": col,
                            "label_source": sample_label_source,
                            "status": next(
                                (flag for flag in ACCEPTED_FLAGS if status.get(flag)),
                                "accepted",
                            ),
                        }
                        if (
                            audit_prediction is not None
                            and sample_label_source != "start_template"
                            and label != "."
                            and audit_prediction["label"] != label
                            and audit_prediction["confidence"] >= self.audit_confidence
                        ):
                            self._quarantine(
                                sample_metadata,
                                expected=label,
                                prediction=audit_prediction,
                            )
                            continue
                        self._save_sample(label, crop, sample_metadata)
                accepted_frames += 1

        missing_corrections = set(self._corrections) - self._applied_corrections
        if missing_corrections:
            raise ValueError(f"unused visual corrections: {sorted(missing_corrections)}")
        summary = DatasetBuildSummary(
            sessions=session_count,
            games=total_games,
            accepted_frames=accepted_frames,
            rejected_frames=rejected_frames,
            samples=sum(self._class_counts.values()),
            corrections_applied=len(self._applied_corrections),
            quarantined_samples=self._quarantined_samples,
            class_counts=dict(sorted(self._class_counts.items())),
            output_dir=self.output_dir,
        )
        with open(os.path.join(self.output_dir, "summary.json"), "w", encoding="utf-8") as file:
            json.dump(summary.__dict__, file, ensure_ascii=False, indent=2)
        return summary
