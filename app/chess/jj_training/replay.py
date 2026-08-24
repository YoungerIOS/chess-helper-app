"""读取 JJ 采集会话，并生成兼容现有识别器的 MSS 风格帧。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Iterator, List

from PIL import Image


@dataclass(frozen=True)
class ReplayFrame:
    frame_id: str
    captured_at: float
    stable: bool
    board_region: Dict
    width: int
    height: int
    bgra: bytes
    path: str


class JJReplayDataset:
    """对一个采集会话进行确定性、按时间排序的离线回放。"""

    def __init__(self, session_dir: str):
        self.session_dir = os.path.abspath(os.path.expanduser(session_dir))
        self.manifest_path = os.path.join(self.session_dir, "manifest.jsonl")
        if not os.path.isfile(self.manifest_path):
            raise FileNotFoundError(f"missing replay manifest: {self.manifest_path}")
        self.events = self._load_events()

    def _load_events(self) -> List[Dict]:
        events = []
        with open(self.manifest_path, encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"invalid manifest line {line_number}: {exc}"
                    ) from exc
                events.append(event)
        return events

    def analysis_events(self) -> Iterator[Dict]:
        return (event for event in self.events if event.get("type") == "analysis")

    def frames(self, *, stable_only: bool = False) -> Iterator[ReplayFrame]:
        captures = [event for event in self.events if event.get("type") == "capture"]
        captures.sort(key=lambda event: (float(event["captured_at"]), event["frame_id"]))
        for event in captures:
            stable = bool(event.get("stable", False))
            if stable_only and not stable:
                continue
            relative_path = event["path"]
            image_path = os.path.join(self.session_dir, relative_path)
            with Image.open(image_path) as image:
                rgba = image.convert("RGBA")
                bgra = rgba.tobytes("raw", "BGRA")
                width, height = rgba.size
            yield ReplayFrame(
                frame_id=event["frame_id"],
                captured_at=float(event["captured_at"]),
                stable=stable,
                board_region=dict(event.get("board_region") or {}),
                width=width,
                height=height,
                bgra=bgra,
                path=image_path,
            )
