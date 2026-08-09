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


if __name__ == "__main__":
    unittest.main()
