import unittest

from app.chess.checker import PositionChecker


class SettlementDetectionTests(unittest.TestCase):
    def test_massive_sparse_result_with_both_kings_is_settlement(self):
        checker = PositionChecker()
        board = [["-"] * 9 for _ in range(10)]
        board[0][4] = "k"
        board[9][4] = "K"
        for row, col, piece in (
            (0, 0, "r"),
            (2, 1, "c"),
            (3, 0, "p"),
            (6, 0, "P"),
            (7, 1, "C"),
            (9, 0, "R"),
        ):
            board[row][col] = piece

        self.assertTrue(checker.check_settlement(board, is_massive_change=True))
        self.assertTrue(checker.in_settlement_screen)
        self.assertEqual("settlement", checker.settlement_reason)

    def test_complete_new_board_is_not_mistaken_for_settlement(self):
        checker = PositionChecker()

        self.assertFalse(
            checker.check_settlement(checker.START_RED, is_massive_change=True)
        )
        self.assertFalse(checker.in_settlement_screen)

    def test_overlay_fallback_to_trusted_board_is_settlement_even_with_many_pieces(self):
        checker = PositionChecker()
        checker.last_board = [row[:] for row in checker.START_RED]

        self.assertTrue(
            checker.check_settlement(checker.START_RED, is_massive_change=True)
        )
        self.assertTrue(checker.in_settlement_screen)

    def test_empty_massive_board_waits_for_confirmation_grace_before_board_loss(self):
        checker = PositionChecker()
        board = [["-"] * 9 for _ in range(10)]

        self.assertTrue(checker.check_settlement(board, is_massive_change=True))
        self.assertEqual("settlement_pending", checker.settlement_reason)
        self.assertTrue(checker.check_settlement(board, is_massive_change=True))
        self.assertEqual("settlement_pending", checker.settlement_reason)
        checker._settlement_pending_since -= checker.BOARD_LOST_GRACE_SECONDS
        self.assertTrue(checker.check_settlement(board, is_massive_change=True))
        self.assertEqual("board_lost", checker.settlement_reason)

    def test_sparse_massive_board_missing_a_king_is_board_loss(self):
        checker = PositionChecker()
        board = [["-"] * 9 for _ in range(10)]
        board[9][4] = "K"
        board[6][0] = "P"

        self.assertTrue(checker.check_settlement(board, is_massive_change=True))
        self.assertEqual("settlement_pending", checker.settlement_reason)
        self.assertTrue(checker.check_settlement(board, is_massive_change=True))
        self.assertEqual("settlement_pending", checker.settlement_reason)
        checker._settlement_pending_since -= checker.BOARD_LOST_GRACE_SECONDS
        self.assertTrue(checker.check_settlement(board, is_massive_change=True))
        self.assertEqual("board_lost", checker.settlement_reason)

    def test_settlement_escalates_to_board_loss_when_board_disappears(self):
        checker = PositionChecker()
        checker.last_board = [row[:] for row in checker.START_RED]
        self.assertTrue(
            checker.check_settlement(checker.START_RED, is_massive_change=True)
        )
        self.assertEqual("settlement", checker.settlement_reason)

        empty = [["-"] * 9 for _ in range(10)]
        self.assertTrue(checker.check_settlement(empty, is_massive_change=True))
        self.assertEqual("settlement_pending", checker.settlement_reason)
        self.assertTrue(checker.check_settlement(empty, is_massive_change=True))
        self.assertEqual("settlement_pending", checker.settlement_reason)
        checker._settlement_pending_since -= checker.BOARD_LOST_GRACE_SECONDS
        self.assertTrue(checker.check_settlement(empty, is_massive_change=True))
        self.assertEqual("board_lost", checker.settlement_reason)

    def test_visible_rematch_confirms_empty_board_as_normal_settlement(self):
        checker = PositionChecker()
        empty = [["-"] * 9 for _ in range(10)]

        self.assertTrue(checker.check_settlement(empty, is_massive_change=True))
        self.assertTrue(checker.confirm_settlement_visual())
        self.assertTrue(checker.check_settlement(empty, is_massive_change=True))

        self.assertEqual("settlement", checker.settlement_reason)
        self.assertTrue(checker._settlement_visually_confirmed)

    def test_static_missing_board_expires_after_confirmation_grace(self):
        checker = PositionChecker()
        empty = [["-"] * 9 for _ in range(10)]

        self.assertTrue(checker.check_settlement(empty, is_massive_change=True))
        checker._settlement_pending_since -= checker.BOARD_LOST_GRACE_SECONDS
        self.assertTrue(checker.check_settlement(empty, is_massive_change=False))

        self.assertEqual("board_lost", checker.settlement_reason)

    def test_recognition_failure_expires_after_confirmation_grace(self):
        checker = PositionChecker()
        empty = [["-"] * 9 for _ in range(10)]

        self.assertTrue(checker.check_settlement(empty, is_massive_change=True))
        checker._settlement_pending_since -= checker.BOARD_LOST_GRACE_SECONDS
        self.assertTrue(checker.check_settlement(None, is_massive_change=False))

        self.assertEqual("board_lost", checker.settlement_reason)

    def test_reset_clears_settlement_reason(self):
        checker = PositionChecker()
        checker.settlement_reason = "board_lost"
        checker.in_settlement_screen = True

        checker.reset()

        self.assertIsNone(checker.settlement_reason)
        self.assertFalse(checker.in_settlement_screen)
        self.assertFalse(checker._settlement_visually_confirmed)
        self.assertEqual(0, checker._board_lost_streak)
        self.assertIsNone(checker._settlement_pending_since)


if __name__ == "__main__":
    unittest.main()
