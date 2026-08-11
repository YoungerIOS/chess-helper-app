from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.chess.checker import PositionChecker


BoardPos = Tuple[int, int]


@dataclass(frozen=True)
class VisualMoveMatch:
    """一次画面变化与合法着法的匹配结果。"""

    board: List[List[str]]
    from_pos: BoardPos
    to_pos: BoardPos
    piece: str
    captured_piece: str
    score: int
    margin: int
    changed_positions: Tuple[BoardPos, ...]


class LegalMoveMatcher:
    """
    从上一可信棋盘出发，寻找最能解释当前视觉变化的合法着法。

    快速路径不识别棋子类别：只使用格子 dHash 差异找到候选
    起点/终点，再交给现有象棋规则校验。
    """

    def __init__(
        self,
        min_cell_distance: int = 5,
        min_total_score: int = 18,
        min_score_margin: int = 4,
        max_changed_cells: int = 8,
    ):
        self.min_cell_distance = min_cell_distance
        self.min_total_score = min_total_score
        self.min_score_margin = min_score_margin
        self.max_changed_cells = max_changed_cells
        self._rules = PositionChecker()

    @staticmethod
    def hash_distance(previous_hash: Optional[str], current_hash: Optional[str]) -> int:
        if not previous_hash or not current_hash:
            return 0
        try:
            previous = int(str(previous_hash), 16)
            current = int(str(current_hash), 16)
        except (TypeError, ValueError):
            return 0
        return (previous ^ current).bit_count()

    @staticmethod
    def _valid_grid(grid, rows: int, cols: int) -> bool:
        return bool(
            grid
            and len(grid) == rows
            and all(len(row) == cols for row in grid)
        )

    def match(
        self,
        trusted_board: List[List[str]],
        trusted_hashes: List[List[str]],
        current_hashes: List[List[str]],
        is_red_at_bottom: bool,
        side_to_move: Optional[str] = None,
    ) -> Optional[VisualMoveMatch]:
        rows, cols = 10, 9
        if not self._valid_grid(trusted_board, rows, cols):
            return None
        if not self._valid_grid(trusted_hashes, rows, cols):
            return None
        if not self._valid_grid(current_hashes, rows, cols):
            return None

        distances: Dict[BoardPos, int] = {}
        for row in range(rows):
            for col in range(cols):
                distance = self.hash_distance(
                    trusted_hashes[row][col], current_hashes[row][col]
                )
                if distance >= self.min_cell_distance:
                    distances[(row, col)] = distance

        # 一步棋通常只有2个端点；JJ旧/新落子标记会额外带来
        # 少量变化。变化过多时不猜测，交给原有CNN/结算页流程。
        if not 2 <= len(distances) <= self.max_changed_cells:
            return None

        changed_positions = tuple(
            pos for pos, _ in sorted(
                distances.items(), key=lambda item: item[1], reverse=True
            )
        )
        candidates = []

        # 起点必须是上一可信棋盘上已有棋子的变化格；终点也
        # 必须有足够的画面变化。这会大幅缩小候选空间。
        for src in changed_positions:
            src_row, src_col = src
            piece = trusted_board[src_row][src_col]
            if piece == '-':
                continue
            if side_to_move == 'red' and not piece.isupper():
                continue
            if side_to_move == 'black' and piece.isupper():
                continue

            for dst in changed_positions:
                if dst == src:
                    continue
                dst_row, dst_col = dst
                captured_piece = trusted_board[dst_row][dst_col]
                step_info = {
                    'from_pos': src,
                    'to_pos': dst,
                    'piece': piece,
                }
                predicted_board = [row[:] for row in trusted_board]
                predicted_board[src_row][src_col] = '-'
                predicted_board[dst_row][dst_col] = piece

                if not self._rules.is_step_legal(
                    trusted_board,
                    predicted_board,
                    is_red_at_bottom,
                    step_info,
                ):
                    continue

                score = distances[src] + distances[dst]
                if score < self.min_total_score:
                    continue
                candidates.append(
                    (score, src, dst, piece, captured_piece, predicted_board)
                )

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0], reverse=True)
        best = candidates[0]
        runner_up_score = candidates[1][0] if len(candidates) > 1 else 0
        margin = best[0] - runner_up_score
        if len(candidates) > 1 and margin < self.min_score_margin:
            return None

        score, src, dst, piece, captured_piece, predicted_board = best
        return VisualMoveMatch(
            board=predicted_board,
            from_pos=src,
            to_pos=dst,
            piece=piece,
            captured_piece=captured_piece,
            score=score,
            margin=margin,
            changed_positions=changed_positions,
        )
