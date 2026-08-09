import unittest
from unittest.mock import patch

from app.chess.checker import BoardStatus, PositionChecker
from app.chess.engine import ChessEngine
from app.chess.message import MessageType
from app.chess.message_bus import message_bus
from app.chess.processor import BoardAnalysisState, ChessProcess


class AdaptiveDepthTests(unittest.TestCase):
    def test_red_side_only_counts_captured_red_piece(self):
        checker = PositionChecker()
        checker.is_red = True

        self.assertFalse(checker.record_own_piece_captured("p"))
        self.assertTrue(checker.record_own_piece_captured("N"))
        self.assertEqual(1, checker.capture_depth_bonus)

    def test_black_side_only_counts_captured_black_piece(self):
        checker = PositionChecker()
        checker.is_red = False

        self.assertFalse(checker.record_own_piece_captured("P"))
        self.assertTrue(checker.record_own_piece_captured("c"))
        self.assertEqual(1, checker.capture_depth_bonus)

    def test_reset_clears_capture_depth_bonus(self):
        checker = PositionChecker()
        checker.record_own_piece_captured("P")
        checker.reset_capture_depth_bonus()

        self.assertEqual(0, checker.capture_depth_bonus)

    def test_combined_limits_add_bonus_to_depth(self):
        limits = ChessEngine.resolve_search_limits(
            {"goParam": "movetime", "depth": "20", "movetime": "6000"},
            depth_bonus=3,
        )

        self.assertEqual("23", limits["depth"])
        self.assertEqual("6000", limits["movetime"])

    def test_search_override_changes_one_limit_but_keeps_the_other(self):
        limits = ChessEngine.resolve_search_limits(
            {"goParam": "depth", "movetime": "10000", "depth": "20"},
            depth_bonus=2,
            search_override=("movetime", "5000"),
        )

        self.assertEqual("22", limits["depth"])
        self.assertEqual("5000", limits["movetime"])

    def test_go_sends_depth_and_movetime_together(self):
        engine = ChessEngine(engine_path="/tmp/pikafish-test-placeholder")
        commands = []
        engine._send_command = commands.append
        engine._read_output_with_timeout = lambda timeout, callback: ([], "", [])

        engine._go({"depth": "20", "movetime": "10000"})

        self.assertEqual(["go depth 20 movetime 10000"], commands)

    def test_confirmed_opponent_capture_updates_bonus_and_ui_message(self):
        class FakeContext:
            capture_depth_enabled = True

            @staticmethod
            def get_engine_params():
                return {"goParam": "depth", "depth": "20"}

        checker = PositionChecker()
        checker.is_red = True
        process = ChessProcess.__new__(ChessProcess)
        process.context = FakeContext()
        process.checker = checker
        process._handle_opponent_move = lambda state, _callback: state
        state = BoardAnalysisState(
            board_status=BoardStatus(
                is_opponent_step=True,
                step_info={"captured_piece": "N"},
            )
        )
        published = []

        with patch.object(message_bus, "publish", side_effect=published.append):
            process._handle_status(state)

        self.assertEqual(1, checker.capture_depth_bonus)
        updates = [m for m in published if m.type == MessageType.PARAM_UPDATE]
        self.assertEqual(1, len(updates))
        self.assertEqual(21, updates[0].content)
        self.assertEqual(1, updates[0].kwargs["depth_bonus"])


if __name__ == "__main__":
    unittest.main()
