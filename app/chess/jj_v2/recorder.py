"""非阻塞记录新版 JJ 对局帧和识别结果，供离线训练与回放。"""

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

from PIL import Image

from app.tools.log_config import get_logger


logger = get_logger(__name__)


class JJV2DatasetRecorder:
    """
    将捕获与分析事件写入一个可回放的数据集会话。

    图像编码在后台线程执行；实时捕获线程只复制 BGRA 字节并入队。
    队列满时丢弃采集样本，不阻塞实际识别流水线。
    """

    FORMAT_VERSION = 1
    QUEUE_SIZE = 64

    def __init__(
        self,
        root_dir: str,
        *,
        session_id: Optional[str] = None,
        include_unstable: bool = True,
        grid_coords: Optional[Dict[str, Any]] = None,
        queue_size: int = QUEUE_SIZE,
    ):
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.session_id = session_id or f"{timestamp}-{uuid.uuid4().hex[:8]}"
        self.root_dir = os.path.abspath(os.path.expanduser(root_dir))
        self.session_dir = os.path.join(self.root_dir, self.session_id)
        self.frames_dir = os.path.join(self.session_dir, "frames")
        self.manifest_path = os.path.join(self.session_dir, "manifest.jsonl")
        self.include_unstable = bool(include_unstable)
        self.grid_coords = dict(grid_coords or {})
        self._queue = queue.Queue(maxsize=max(1, int(queue_size)))
        self._sequence = 0
        self._sequence_lock = threading.Lock()
        self._closed = threading.Event()
        self.dropped_samples = 0
        self.failed_samples = 0
        self.last_write_error = None

        os.makedirs(self.frames_dir, exist_ok=True)
        self._write_session_metadata()
        self._worker = threading.Thread(
            target=self._writer_loop,
            name="jj-v2-dataset-writer",
            daemon=True,
        )
        self._worker.start()

    def _write_session_metadata(self) -> None:
        metadata = {
            "format_version": self.FORMAT_VERSION,
            "session_id": self.session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "platform": "JJ_V2",
            "image_format": "JPEG",
            "grid_coords": self._json_safe(self.grid_coords),
        }
        path = os.path.join(self.session_dir, "session.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2)

    def _next_frame_id(self, captured_at: float) -> str:
        with self._sequence_lock:
            self._sequence += 1
            sequence = self._sequence
        return f"{int(captured_at * 1_000_000):016d}-{sequence:06d}"

    @staticmethod
    def _copy_frame(frame: Any) -> tuple[bytes, int, int]:
        width = int(frame.width)
        height = int(frame.height)
        if width <= 0 or height <= 0:
            raise ValueError("invalid frame dimensions")
        pixels = bytes(frame.bgra)
        expected = width * height * 4
        if len(pixels) != expected:
            raise ValueError(
                f"invalid BGRA buffer: got {len(pixels)}, expected {expected}"
            )
        return pixels, width, height

    def _enqueue(self, event: Dict[str, Any]) -> bool:
        if self._closed.is_set():
            return False
        try:
            self._queue.put_nowait(event)
            return True
        except queue.Full:
            self.dropped_samples += 1
            return False

    def record_frame(
        self,
        frame: Any,
        *,
        captured_at: Optional[float] = None,
        stable: bool,
        board_region: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """排队保存一帧；返回可用于关联分析事件的 frame_id。"""
        if not stable and not self.include_unstable:
            return None
        captured_at = float(captured_at if captured_at is not None else time.time())
        try:
            pixels, width, height = self._copy_frame(frame)
        except (AttributeError, TypeError, ValueError):
            return None
        frame_id = self._next_frame_id(captured_at)
        event = {
            "type": "capture",
            "frame_id": frame_id,
            "captured_at": captured_at,
            "stable": bool(stable),
            "board_region": dict(board_region or {}),
            "width": width,
            "height": height,
            "pixels": pixels,
        }
        return frame_id if self._enqueue(event) else None

    def record_analysis(
        self,
        *,
        captured_at: float,
        board: Optional[list],
        marker_coords: Optional[list],
        status: Any = None,
        is_settlement_screen: bool = False,
    ) -> bool:
        """记录识别和规则校验结果，不把不可序列化的截图对象写入清单。"""
        status_data: Dict[str, Any] = {}
        if status is not None:
            if is_dataclass(status):
                status_data = asdict(status)
            elif hasattr(status, "__dict__"):
                status_data = {
                    key: value
                    for key, value in vars(status).items()
                    if not key.startswith("_")
                }
        return self._enqueue({
            "type": "analysis",
            "captured_at": float(captured_at),
            "board": board,
            "marker_coords": marker_coords or [],
            "status": status_data,
            "is_settlement_screen": bool(is_settlement_screen),
        })

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): JJV2DatasetRecorder._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [JJV2DatasetRecorder._json_safe(item) for item in value]
        return str(value)

    def _write_event(self, event: Dict[str, Any]) -> None:
        serializable = dict(event)
        if event["type"] == "capture":
            pixels = serializable.pop("pixels")
            filename = f"{event['frame_id']}.jpg"
            relative_path = os.path.join("frames", filename)
            image = Image.frombytes(
                "RGBA",
                (event["width"], event["height"]),
                pixels,
                "raw",
                "BGRA",
            ).convert("RGB")
            image.save(
                os.path.join(self.session_dir, relative_path),
                format="JPEG",
                quality=92,
                optimize=True,
            )
            serializable["path"] = relative_path
        with open(self.manifest_path, "a", encoding="utf-8") as file:
            file.write(json.dumps(self._json_safe(serializable), ensure_ascii=False))
            file.write("\n")

    def _writer_loop(self) -> None:
        while True:
            event = self._queue.get()
            try:
                if event is None:
                    return
                self._write_event(event)
            except Exception as exc:
                # 单个样本写盘失败不能杀死整个记录线程，否则后续事件会
                # 永久堆积并让 close/flush 只能等待超时。
                self.failed_samples += 1
                self.last_write_error = str(exc)
                logger.exception(
                    f"JJ v2数据样本写入失败: type={event.get('type')}"
                )
            finally:
                self._queue.task_done()

    def flush(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout))
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        return self._queue.unfinished_tasks == 0

    def close(self, timeout: float = 5.0) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self.flush(timeout=timeout)
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            return
        self._worker.join(timeout=max(0.0, float(timeout)))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
