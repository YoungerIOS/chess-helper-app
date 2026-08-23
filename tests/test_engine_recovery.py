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
        self.moves = "a0a1 b9b8"

    def clear(self):
        self.clear_count += 1

    def get_moves_str(self):
        return self.moves

    def add_and_get_all(self, _before, move, _after, _is_red):
        self.moves = f"{self.moves} {move}".strip()
        return self.moves


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
        self.game_variant = "xiangqi"

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

    def test_lifted_piece_does_not_accumulate_force_sync_drops(self):
        self.checker.consecutive_drops = 2
        lifted_state = BoardAnalysisState(
            board_array=self.board,
            board_status=BoardStatus(
                is_illegal_change=True,
                step_info={
                    "transient_single_change": True,
                    "is_lifted_piece": True,
                    "position": (6, 0),
                    "piece": "P",
                },
                message="检测到棋子抬起，等待落子",
            ),
        )
        published = []

        with patch.object(message_bus, "publish", side_effect=published.append):
            self.process._handle_illegal_board(lifted_state)

        self.assertEqual(0, self.checker.consecutive_drops)
        self.assertEqual((6, 0), self.checker._pending_lift_source)
        self.assertFalse(any(m.type == MessageType.RETRY_CAPTURE for m in published))

    def test_missing_bestmove_uses_latest_pv(self):
        move = self.process._best_available_engine_move(
            None, ["e3f3", "a0a1"]
        )

        self.assertEqual("e3f3", move)

    def test_empty_engine_result_retries_with_short_movetime(self):
        calls = []
        self.process._get_engine_move = (
            lambda *args, **kwargs: calls.append((args, kwargs))
        )

        self.process._recover_from_empty_engine_move(
            fen_str="3k5/9/9/9/9/9/9/9/9/3K5",
            moves="e3f3",
            state=self.state,
            callback=lambda _message: None,
            engine_retry=0,
        )

        self.assertEqual(1, len(calls))
        self.assertEqual(("movetime", "5000"), calls[0][1]["search_override"])
        self.assertEqual(1, calls[0][1]["engine_retry"])

    def test_confirmed_own_move_invalidates_and_clears_old_recommendation(self):
        state = BoardAnalysisState(
            board_array=self.board,
            board_status=BoardStatus(
                is_my_step=True,
                step_info={
                    "from_pos": (6, 0),
                    "to_pos": (5, 0),
                    "piece": "P",
                    "side": "red",
                },
            ),
        )
        published = []

        with patch.object(message_bus, "publish", side_effect=published.append):
            self.process._handle_my_move(state)

        self.assertEqual(1, self.context.invalidated)
        self.assertTrue(any(
            message.type == MessageType.MOVE_TEXT and message.content == ""
            for message in published
        ))

    def test_turn_mismatch_never_accumulates_force_sync_drops(self):
        self.checker.consecutive_drops = 2
        trusted = [row[:] for row in self.board]
        self.checker.last_board = trusted
        mismatch = [row[:] for row in trusted]
        mismatch[5][0] = mismatch[6][0]
        mismatch[6][0] = "-"
        state = BoardAnalysisState(
            board_array=mismatch,
            board_status=BoardStatus(
                is_illegal_change=True,
                is_turn_mismatch=True,
                step_info={"side": "red"},
                message="wrong turn",
            ),
        )
        published = []

        with patch.object(message_bus, "publish", side_effect=published.append):
            self.process._handle_illegal_board(state)

        self.assertEqual(0, self.checker.consecutive_drops)
        self.assertEqual(trusted, self.checker.last_board)
        self.assertTrue(any(
            message.type == MessageType.RETRY_CAPTURE for message in published
        ))


if __name__ == "__main__":
    unittest.main()
