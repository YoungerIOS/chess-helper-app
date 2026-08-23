"""新版 JJ ONNX 模型的只读影子识别器。"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import cv2
import numpy as np
import onnxruntime as ort

from app.chess.checker import PositionChecker


class JJV2ShadowRunner:
    """
    在独立线程中运行候选模型并写入审计日志。

    本类没有 Checker、Engine、MessageBus 或鼠标控制器引用，因而影子结果
    不可能进入正式棋局状态或触发走子。
    """

    QUEUE_SIZE = 2

    def __init__(
        self,
        model_path: str,
        output_dir: str,
        *,
        grid_coords: Dict[str, Any],
        queue_size: int = QUEUE_SIZE,
        confidence_threshold: float = 0.70,
    ):
        self.model_path = os.path.abspath(os.path.expanduser(model_path))
        self.map_path = os.path.join(
            os.path.dirname(self.model_path), "jj_v2_piece_map.json"
        )
        if not os.path.isfile(self.model_path):
            raise FileNotFoundError(f"missing JJ v2 shadow model: {self.model_path}")
        if not os.path.isfile(self.map_path):
            raise FileNotFoundError(f"missing JJ v2 shadow class map: {self.map_path}")
        with open(self.map_path, encoding="utf-8") as file:
            self.class_map = json.load(file)

        self.grid_coords = {
            "x": [int(value) for value in grid_coords.get("x", [])],
            "y": [int(value) for value in grid_coords.get("y", [])],
        }
        if len(self.grid_coords["x"]) != 9 or len(self.grid_coords["y"]) != 10:
            raise ValueError("JJ v2 shadow requires a 9x10 grid")
        self.confidence_threshold = float(confidence_threshold)
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("JJ v2 shadow confidence threshold must be within [0, 1]")

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.session_id = f"{timestamp}-{uuid.uuid4().hex[:8]}"
        self.output_dir = os.path.abspath(os.path.expanduser(output_dir))
        self.session_dir = os.path.join(self.output_dir, self.session_id)
        self.results_path = os.path.join(self.session_dir, "shadow_results.jsonl")
        os.makedirs(self.session_dir, exist_ok=True)
        with open(os.path.join(self.session_dir, "session.json"), "w", encoding="utf-8") as file:
            json.dump({
                "format_version": 1,
                "session_id": self.session_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "mode": "JJ_V2_SHADOW_READ_ONLY",
                "model_path": self.model_path,
                "grid_coords": self.grid_coords,
                "confidence_threshold": self.confidence_threshold,
            }, file, ensure_ascii=False, indent=2)

        self._queue = queue.Queue(maxsize=max(1, int(queue_size)))
        self._closed = threading.Event()
        self._session = None
        self._input_name = None
        self._session_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self.dropped_frames = 0
        self.processed_frames = 0
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="jj-v2-shadow-worker",
            daemon=True,
        )
        self._worker.start()

    @staticmethod
    def _status_dict(status: Any) -> Dict[str, Any]:
        if status is None:
            return {}
        if isinstance(status, dict):
            return dict(status)
        if is_dataclass(status):
            return asdict(status)
        if hasattr(status, "__dict__"):
            return {
                key: value for key, value in vars(status).items()
                if not key.startswith("_")
            }
        return {}

    @staticmethod
    def _copy_frame(frame: Any) -> Dict[str, Any]:
        width, height = int(frame.width), int(frame.height)
        pixels = bytes(frame.bgra)
        if width <= 0 or height <= 0 or len(pixels) != width * height * 4:
            raise ValueError("invalid shadow frame")
        return {"width": width, "height": height, "pixels": pixels}

    def submit(
        self,
        frame: Any,
        *,
        captured_at: float,
        primary_board: Optional[list],
        primary_status: Any = None,
        is_settlement_screen: bool = False,
    ) -> bool:
        if self._closed.is_set():
            return False
        try:
            item = self._make_item(
                frame,
                captured_at=captured_at,
                primary_board=primary_board,
                primary_status=primary_status,
                is_settlement_screen=is_settlement_screen,
            )
        except (AttributeError, TypeError, ValueError):
            return False
        while not self._closed.is_set():
            try:
                self._queue.put_nowait(item)
                return True
            except queue.Full:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                    self.dropped_frames += 1
                except queue.Empty:
                    continue
        return False

    def _make_item(
        self,
        frame: Any,
        *,
        captured_at: float,
        primary_board: Optional[list],
        primary_status: Any = None,
        is_settlement_screen: bool = False,
    ) -> Dict[str, Any]:
        return {
            **self._copy_frame(frame),
            "captured_at": float(captured_at),
            "primary_board": primary_board,
            "primary_status": self._status_dict(primary_status),
            "is_settlement_screen": bool(is_settlement_screen),
        }

    def analyze_now(
        self,
        frame: Any,
        *,
        captured_at: float,
        primary_board: Optional[list],
        primary_status: Any = None,
        is_settlement_screen: bool = False,
    ) -> Dict[str, Any]:
        """同步分析一帧，供确定性离线回放使用；仍然只写审计结果。"""
        item = self._make_item(
            frame,
            captured_at=captured_at,
            primary_board=primary_board,
            primary_status=primary_status,
            is_settlement_screen=is_settlement_screen,
        )
        result = self._infer(item)
        self._write_result(result)
        self.processed_frames += 1
        return result

    def analyze_candidate(
        self,
        frame: Any,
        *,
        captured_at: float,
        primary_board: Optional[list],
    ) -> Dict[str, Any]:
        """同步生成推荐候选，但暂不写日志或改变正式棋局状态。"""
        item = self._make_item(
            frame,
            captured_at=captured_at,
            primary_board=primary_board,
        )
        return self._infer(item)

    def record_precomputed(
        self,
        result: Dict[str, Any],
        *,
        primary_status: Any = None,
        is_settlement_screen: bool = False,
    ) -> None:
        """在棋规校验后补齐审计上下文并写入同步候选结果。"""
        completed = dict(result)
        completed["primary_status"] = self._status_dict(primary_status)
        completed["is_settlement_screen"] = bool(is_settlement_screen)
        self._write_result(completed)
        self.processed_frames += 1

    @staticmethod
    def _grid_crop(image: np.ndarray, x_values, y_values, row: int, col: int):
        center_x, center_y = x_values[col], y_values[row]
        left_gap = center_x - x_values[col - 1] if col else x_values[1] - center_x
        right_gap = x_values[col + 1] - center_x if col < 8 else left_gap
        top_gap = center_y - y_values[row - 1] if row else y_values[1] - center_y
        bottom_gap = y_values[row + 1] - center_y if row < 9 else top_gap
        x_radius = min(left_gap, right_gap) // 2
        y_radius = min(top_gap, bottom_gap) // 2
        radius = max(1, int((x_radius + y_radius) // 2 * 0.85))
        center_x = max(radius, min(image.shape[1] - 1 - radius, center_x))
        center_y = max(radius, min(image.shape[0] - 1 - radius, center_y))
        return image[
            center_y - radius:center_y + radius,
            center_x - radius:center_x + radius,
        ]

    def _preprocess(self, item: Dict[str, Any]) -> np.ndarray:
        bgra = np.frombuffer(item["pixels"], dtype=np.uint8).reshape(
            item["height"], item["width"], 4
        )
        bgr = bgra[:, :, :3]
        height = round(bgr.shape[0] * 800 / bgr.shape[1])
        normalized = cv2.resize(bgr, (800, height), interpolation=cv2.INTER_LANCZOS4)
        crops = []
        for row in range(10):
            for col in range(9):
                crop = self._grid_crop(
                    normalized,
                    self.grid_coords["x"],
                    self.grid_coords["y"],
                    row,
                    col,
                )
                crop = cv2.resize(crop, (80, 80), interpolation=cv2.INTER_LINEAR)
                crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                crops.append(crop.astype(np.float32).transpose(2, 0, 1) / 255.0)
        return np.ascontiguousarray(np.stack(crops), dtype=np.float32)

    def _ensure_session(self):
        if self._session is not None:
            return
        with self._session_lock:
            if self._session is None:
                self._session = ort.InferenceSession(
                    self.model_path, providers=["CPUExecutionProvider"]
                )
                self._input_name = self._session.get_inputs()[0].name

    @staticmethod
    def _compare(primary_board: Optional[list], shadow_board: list, confidences: list):
        if not primary_board or len(primary_board) != 10:
            return []
        differences = []
        for row in range(10):
            if len(primary_board[row]) != 9:
                return []
            for col in range(9):
                if primary_board[row][col] != shadow_board[row][col]:
                    differences.append({
                        "row": row,
                        "col": col,
                        "primary": primary_board[row][col],
                        "shadow": shadow_board[row][col],
                        "shadow_confidence": confidences[row][col],
                    })
        return differences

    @staticmethod
    def _red_is_at_bottom(board: list) -> bool:
        red_king_row = next(
            (row for row in range(10) if "K" in board[row]), None
        )
        black_king_row = next(
            (row for row in range(10) if "k" in board[row]), None
        )
        return bool(
            red_king_row is not None
            and black_king_row is not None
            and red_king_row > black_king_row
        )

    @classmethod
    def _atomic_gate(
        cls,
        primary_board: Optional[list],
        shadow_board: list,
        confidences: list,
        threshold: float,
    ) -> tuple[list, Dict[str, Any]]:
        """只原子接受完整合法着法，绝不逐格拼出不存在的局面。"""
        if (
            not primary_board
            or len(primary_board) != 10
            or any(len(row) != 9 for row in primary_board)
        ):
            return [list(row) for row in shadow_board], {"mode": "shadow_no_primary"}

        differences = [
            (row, col)
            for row in range(10)
            for col in range(9)
            if primary_board[row][col] != shadow_board[row][col]
        ]
        if not differences:
            return [list(row) for row in primary_board], {"mode": "exact_match"}

        if len(differences) == 2:
            sources = [
                position for position in differences
                if primary_board[position[0]][position[1]] != "-"
                and shadow_board[position[0]][position[1]] == "-"
            ]
            if len(sources) == 1:
                source = sources[0]
                destination = next(pos for pos in differences if pos != source)
                piece = primary_board[source[0]][source[1]]
                destination_piece = shadow_board[destination[0]][destination[1]]
                endpoint_confidences = [
                    float(confidences[row][col])
                    for row, col in (source, destination)
                ]
                confidence_floor = max(0.0, float(threshold) - 0.10)
                confidence_ok = (
                    destination_piece == piece
                    and min(endpoint_confidences) >= confidence_floor
                    and sum(endpoint_confidences) / 2.0 >= float(threshold)
                )
                step_info = {
                    "from_pos": source,
                    "to_pos": destination,
                    "piece": piece,
                }
                legal = confidence_ok and PositionChecker().is_step_legal(
                    primary_board,
                    shadow_board,
                    cls._red_is_at_bottom(primary_board),
                    step_info,
                )
                if legal:
                    return [list(row) for row in shadow_board], {
                        "mode": "atomic_legal_move",
                        **step_info,
                        "endpoint_confidences": endpoint_confidences,
                    }

        return [list(row) for row in primary_board], {
            "mode": "primary_fallback",
            "difference_count": len(differences),
        }

    @classmethod
    def _gated_board(
        cls,
        primary_board: Optional[list],
        shadow_board: list,
        confidences: list,
        threshold: float,
    ) -> list:
        board, _decision = cls._atomic_gate(
            primary_board, shadow_board, confidences, threshold
        )
        return board

    def _infer(self, item: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_session()
        started = time.perf_counter()
        inputs = self._preprocess(item)
        logits = self._session.run(None, {self._input_name: inputs})[0]
        logits -= np.max(logits, axis=1, keepdims=True)
        probabilities = np.exp(logits)
        probabilities /= np.sum(probabilities, axis=1, keepdims=True)
        indices = np.argmax(probabilities, axis=1)
        labels = [self.class_map[str(int(index))] for index in indices]
        confidence_values = [
            float(probabilities[index, class_index])
            for index, class_index in enumerate(indices)
        ]
        raw_board = [labels[row * 9:(row + 1) * 9] for row in range(10)]
        confidences = [
            confidence_values[row * 9:(row + 1) * 9] for row in range(10)
        ]
        marker_coords = [
            [row, col] for row in range(10) for col in range(9)
            if raw_board[row][col] == "."
        ]
        board = [
            ["-" if value == "." else value for value in row]
            for row in raw_board
        ]
        differences = self._compare(item["primary_board"], board, confidences)
        gated_board, gate_decision = self._atomic_gate(
            item["primary_board"],
            board,
            confidences,
            self.confidence_threshold,
        )
        return {
            "type": "shadow_analysis",
            "captured_at": item["captured_at"],
            "processed_at": time.time(),
            "latency_ms": (time.perf_counter() - started) * 1000.0,
            "board": board,
            "gated_board": gated_board,
            "gate_decision": gate_decision,
            "confidence_threshold": self.confidence_threshold,
            "raw_board": raw_board,
            "confidences": confidences,
            "marker_coords": marker_coords,
            "primary_board": item["primary_board"],
            "primary_status": item["primary_status"],
            "is_settlement_screen": item["is_settlement_screen"],
            "difference_count": len(differences),
            "differences": differences,
        }

    def _write_result(self, result: Dict[str, Any]) -> None:
        with self._write_lock:
            with open(self.results_path, "a", encoding="utf-8") as file:
                file.write(json.dumps(result, ensure_ascii=False))
                file.write("\n")

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                self._write_result(self._infer(item))
                self.processed_frames += 1
            except Exception as exc:
                self._write_result({
                    "type": "shadow_error",
                    "captured_at": item.get("captured_at") if item else None,
                    "error": str(exc),
                })
            finally:
                self._queue.task_done()

    def close(self, timeout: float = 3.0) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            return
        self._worker.join(timeout=max(0.0, float(timeout)))
