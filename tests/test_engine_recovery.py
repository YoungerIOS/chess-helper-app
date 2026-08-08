import unittest
from unittest.mock import patch

from app.chess.checker import BoardStatus, PositionChecker
from app.chess.message import MessageType
from app.chess.message_bus import message_bus
from app.chess.processor import BoardAnalysisState, ChessProcess
from app.tools import utils


class FakeHistory:
    def __init__(self):
        self.clear_count = 0

    def clear(self):
        self.clear_count += 1


class FakeEngine:
    def __init__(self):
        self.stop_count = 0

    def stop_analysis(self):
        self.stop_count += 1


class FakeContext:
    def __init__(self, checker):
        self.checker = checker
        self.base_fen = "old-anchor"
        self.discard_before_timestamp = 0.0
        self.invalidated = 0
        self.recognizer_resets = 0

    def invalidate_analysis(self):
        self.invalidated += 1

    def reset_checker(self):
        self.checker.reset()

    def reset_recognizer(self):
        self.recognizer_resets += 1


class EngineRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.board = [row[:] for row in PositionChecker.START_RED]
        self.checker = PositionChecker()
        self.checker.is_red = True
        self.checker.capture_depth_bonus = 2
        self.context = FakeContext(self.checker)
        self.history = FakeHistory()
        self.engine = FakeEngine()
        self.process = ChessProcess.__new__(ChessProcess)
        self.process.checker = self.checker
        self.process.context = self.context
        self.process.history = self.history
        self.process.engine = self.engine
        self.state = BoardAnalysisState(
            board_array=self.board,
            board_status=BoardStatus(is_opponent_step=True),
        )

    def test_first_invalid_move_reanchors_to_current_visual_fen(self):
        calls = []
        self.process._get_engine_move = (
            lambda *args, **kwargs: calls.append((args, kwargs))
        )
        self.checker._sim_cache = {
            "base_fen": "stale",
            "moves_str": "a0a1",
            "board": self.board,
        }
        published = []

        with patch.object(message_bus, "publish", side_effect=published.append):
            self.process._recover_from_engine_desync(
                move="h8h2",
                state=self.state,
                analysis_board=self.board,
                callback=lambda _message: None,
                desync_retry=0,
            )

        expected_fen, _ = utils.convert_array_to_fen(self.board, True)
        self.assertEqual(expected_fen, self.context.base_fen)
        self.assertEqual(1, self.history.clear_count)
        self.assertEqual(self.board, self.checker.last_board)
        self.assertIsNone(self.checker._sim_cache["board"])
        self.assertEqual(1, len(calls))
        self.assertEqual(expected_fen, calls[0][0][0])
        self.assertEqual("", calls[0][0][1])
        self.assertEqual(1, calls[0][1]["desync_retry"])
        self.assertTrue(any(m.type == MessageType.STATUS for m in published))

    def test_second_invalid_move_runs_hard_refresh_and_preserves_depth_bonus(self):
        published = []

        with patch.object(message_bus, "publish", side_effect=published.append):
            self.process._recover_from_engine_desync(
                move="h8h2",
                state=self.state,
                analysis_board=self.board,
                callback=lambda _message: None,
                desync_retry=1,
            )

        self.assertEqual(1, self.context.invalidated)
        self.assertEqual(1, self.engine.stop_count)
        self.assertEqual(1, self.history.clear_count)
        self.assertIsNone(self.context.base_fen)
        self.assertEqual(1, self.context.recognizer_resets)
        self.assertEqual(2, self.checker.capture_depth_bonus)
        self.assertGreater(self.context.discard_before_timestamp, 0)
        self.assertTrue(any(m.type == MessageType.ERROR for m in published))
        self.assertTrue(any(m.type == MessageType.RETRY_CAPTURE for m in published))


if __name__ == "__main__":
    unittest.main()
