import threading
from typing import List, Optional
import time
import json

class MoveRecord:
    def __init__(self, fen: str, move: str, move_text: str, is_red: bool, timestamp: Optional[float] = None):
        self.fen = fen
        self.move = move
        self.move_text = move_text
        self.is_red = is_red
        self.timestamp = timestamp or time.time()

    def to_dict(self):
        return {
            "fen": self.fen,
            "move": self.move,
            "move_text": self.move_text,
            "is_red": self.is_red,
            "timestamp": self.timestamp
        }

    @staticmethod
    def from_dict(d):
        return MoveRecord(
            fen=d["fen"],
            move=d["move"],
            move_text=d["move_text"],
            is_red=d["is_red"],
            timestamp=d["timestamp"]
        )

class MoveHistory:
    def __init__(self):
        self._history: List[MoveRecord] = []
        self._current_index: int = -1
        self._lock = threading.Lock()

    def add_move(self, fen: str, move: str, move_text: str, is_red: bool):
        with self._lock:
            if self._current_index < len(self._history) - 1:
                self._history = self._history[:self._current_index + 1]
            record = MoveRecord(fen, move, move_text, is_red)
            self._history.append(record)
            self._current_index += 1
 
    def undo(self) -> Optional[MoveRecord]:
        with self._lock:
            if self._current_index > 0:
                self._current_index -= 1
                return self._history[self._current_index]
            return None

    def redo(self) -> Optional[MoveRecord]:
        with self._lock:
            if self._current_index < len(self._history) - 1:
                self._current_index += 1
                return self._history[self._current_index]
            return None

    def jump_to(self, index: int) -> Optional[MoveRecord]:
        with self._lock:
            if 0 <= index < len(self._history):
                self._current_index = index
                return self._history[self._current_index]
            return None

    def current(self) -> Optional[MoveRecord]:
        with self._lock:
            if 0 <= self._current_index < len(self._history):
                return self._history[self._current_index]
            return None

    def all_moves(self) -> List[MoveRecord]:
        with self._lock:
            return list(self._history)

    def clear(self):
        with self._lock:
            self._history.clear()
            self._current_index = -1

    def save_to_file(self, path: str):
        with self._lock:
            data = [rec.to_dict() for rec in self._history]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def load_from_file(self, path: str):
        with self._lock:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._history = [MoveRecord.from_dict(d) for d in data]
            self._current_index = len(self._history) - 1

    def add_and_get_all(self, fen: str, move: str, move_text: str, is_red: bool) -> str:
        self.add_move(fen, move, move_text, is_red)
        return self.get_moves_str()

    def pop_last(self) -> Optional[MoveRecord]:
        """移除最后一步记录"""
        with self._lock:
            if self._history:
                record = self._history.pop()
                self._current_index = len(self._history) - 1
                return record
            return None

    def get_moves_str(self) -> str:
        """获取所有着法字符串"""
        with self._lock:
            all_move_strings = [rec.move for rec in self._history if rec.move.strip()]
            return ' '.join(all_move_strings) 