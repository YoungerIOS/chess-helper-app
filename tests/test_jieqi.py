import unittest
from unittest.mock import MagicMock

from app.chess.checker import PositionChecker
from app.chess.recognizer import RecognitionDetail, RecognitionErrorType
from app.chess.screenshot import ChessCaptureManager
from app.chess.simulation import ChessSimulation


class JieqiModeTests(unittest.TestCase):
    def test_initial_visual_board_is_normalized_to_dark_pieces(self):
        checker = PositionChecker(variant="jieqi")
        raw = [row[:] for row in PositionChecker.START_RED]

        normalized = checker.normalize_visual_board(raw)

        self.assertEqual(normalized, PositionChecker.START_JIEQI_RED)
        self.assertEqual(normalized[0][4], "k")
        self.assertEqual(normalized[0][0], "x")
        self.assertEqual(normalized[9][0], "X")

    def test_dark_pawn_move_records_revealed_piece_and_passes_history_check(self):
        checker = PositionChecker(variant="jieqi")
        checker.is_red = True
        checker.last_board = [row[:] for row in PositionChecker.START_JIEQI_RED]
        checker.last_counts = checker.start_counts
        current = [row[:] for row in checker.last_board]
        current[6][6] = "-"  # g3
        current[5][6] = "R"  # g4，揭为红车

        status = checker.check_board(current, history_moves="")

        self.assertTrue(status.is_my_step)
        self.assertFalse(status.is_history_mismatch)
        self.assertEqual(status.step_info["piece"], "X")
        self.assertEqual(status.step_info["revealed_piece"], "R")

    def test_revealed_move_recovers_source_hidden_by_dark_piece_fallback(self):
        checker = PositionChecker(variant="jieqi")
        checker.is_red = False  # 截图场景：我方黑棋在底部，对方红方走棋
        checker.last_board = [row[:] for row in PositionChecker.START_JIEQI_BLACK]
        checker.last_counts = checker.start_counts
        checker._last_visual_hashes = [["old"] * 9 for _ in range(10)]

        # 红方左士名义位置(0,3)斜行至(1,4)，并揭示为仕。CNN把已经
        # 变空的起点误识别成同色棋子，这正是此前“只有一个格子变化”。
        raw = [row[:] for row in checker.last_board]
        raw[0][3] = "A"
        raw[1][4] = "A"
        hashes = [["old"] * 9 for _ in range(10)]
        hashes[0][3] = "source-changed"
        hashes[1][4] = "target-changed"

        normalized = checker.normalize_visual_board(
            raw, hashes, marker_coords=[(0, 3), (1, 4)]
        )
        status = checker.check_board(normalized, history_moves="")

        self.assertEqual(normalized[0][3], "-")
        self.assertEqual(normalized[1][4], "A")
        self.assertTrue(status.is_opponent_step)
        self.assertEqual(status.step_info["from_pos"], (0, 3))
        self.assertEqual(status.step_info["to_pos"], (1, 4))
        self.assertEqual(status.step_info["revealed_piece"], "A")

    def test_revealed_rook_move_recovers_low_confidence_destination(self):
        checker = PositionChecker(variant="jieqi")
        checker.is_red = True
        board = [["-"] * 9 for _ in range(10)]
        board[0][4] = "k"
        board[9][3] = "K"
        board[5][7] = "r"
        checker.last_board = [row[:] for row in board]
        _, _, checker.last_counts = checker.check_pieces_count(board)
        checker._last_visual_hashes = [["old"] * 9 for _ in range(10)]
        checker._sim_cache = {
            "base_fen": None,
            "moves_str": "",
            "board": [row[:] for row in board],
        }

        # 黑车从右侧平移到中路。起点光圈被识别为空，但落点受高亮影响
        # 置信度不足，被Recognizer回退成上一帧空格并留下None哈希。
        raw = [row[:] for row in board]
        raw[5][7] = "-"
        hashes = [["old"] * 9 for _ in range(10)]
        hashes[5][7] = "source-changed"
        hashes[5][4] = None
        details = [RecognitionDetail(
            type=RecognitionErrorType.LOW_CONFIDENCE,
            position=(5, 4),
            message="高亮落点低置信度",
            confidence=0.55,
            piece_type="r",
        )]

        normalized = checker.normalize_visual_board(
            raw, hashes, marker_coords=[(5, 7)], details=details
        )
        status = checker.check_board(normalized, history_moves="")

        self.assertEqual(normalized[5][7], "-")
        self.assertEqual(normalized[5][4], "r")
        self.assertTrue(status.is_opponent_step)
        self.assertFalse(status.is_history_mismatch)
        self.assertEqual(status.step_info["from_pos"], (5, 7))
        self.assertEqual(status.step_info["to_pos"], (5, 4))

    def test_lifted_piece_never_updates_trusted_board(self):
        checker = PositionChecker()
        checker.is_red = True
        checker.last_board = [row[:] for row in PositionChecker.START_RED]
        checker.last_counts = checker.start_counts
        lifted = [row[:] for row in checker.last_board]
        lifted[6][0] = "-"

        status = checker.check_board(lifted, history_moves="")

        self.assertTrue(status.is_illegal_change)
        self.assertTrue(status.step_info["transient_single_change"])
        self.assertTrue(status.step_info["is_lifted_piece"])
        self.assertEqual(checker.last_board[6][0], "P")

    def test_simulation_applies_jieqi_reveal_suffix(self):
        board = [row[:] for row in PositionChecker.START_JIEQI_RED]

        ChessSimulation.apply_uci_move(board, "g3g4R")

        self.assertEqual(board[6][6], "-")
        self.assertEqual(board[5][6], "R")

    def test_revealed_advisor_is_allowed_outside_palace(self):
        checker = PositionChecker(variant="jieqi")
        board = [["-"] * 9 for _ in range(10)]
        board[0][4] = "k"
        board[9][3] = "K"
        board[5][7] = "a"

        valid, _ = checker.check_pieces_position(board, True)

        self.assertTrue(valid)

    def test_manual_refresh_preserves_jieqi_history_and_checker(self):
        manager = ChessCaptureManager.__new__(ChessCaptureManager)
        manager.context = MagicMock()
        manager.context.game_variant = "jieqi"
        manager.context.get_engine.return_value = MagicMock()
        manager.context.get_checker.return_value = MagicMock()
        manager._execute_retry_capture = MagicMock(return_value=True)

        self.assertTrue(manager.manually_capture_once())

        manager.context.history.clear.assert_not_called()
        manager.context.reset_checker.assert_not_called()
        manager.context.reset_recognizer.assert_called_once()
        manager._execute_retry_capture.assert_called_once_with('揭棋软刷新（保留历史）')


if __name__ == "__main__":
    unittest.main()
