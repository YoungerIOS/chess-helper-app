import unittest

from app.chess.checker import PositionChecker


class TurnDetectionTests(unittest.TestCase):
    def test_black_start_tolerates_same_color_piece_type_error(self):
        checker = PositionChecker()
        board = [row[:] for row in checker.START_BLACK]
        board[7][7] = "k"  # 现场复现：黑炮被CNN误识别成黑将

        status = checker.check_board(board)

        self.assertTrue(status.is_black_start)
        self.assertFalse(status.is_red_start)
        self.assertFalse(checker.is_red)
        self.assertEqual(board, checker.START_BLACK)

    def test_move_owner_uses_latched_player_color(self):
        checker = PositionChecker()
        start = [row[:] for row in checker.START_BLACK]
        self.assertTrue(checker.check_board(start).is_black_start)

        after_red_move = [row[:] for row in checker.START_BLACK]
        after_red_move[4][0] = after_red_move[3][0]
        after_red_move[3][0] = "-"
        red_status = checker.check_board(after_red_move)
        self.assertTrue(red_status.is_opponent_step)
        self.assertFalse(red_status.is_my_step)

        after_black_move = [row[:] for row in after_red_move]
        after_black_move[5][0] = after_black_move[6][0]
        after_black_move[6][0] = "-"
        black_status = checker.check_board(after_black_move)
        self.assertTrue(black_status.is_my_step)
        self.assertFalse(black_status.is_opponent_step)

    def test_side_does_not_flip_from_noisy_king_prediction(self):
        checker = PositionChecker()
        start = [row[:] for row in checker.START_BLACK]
        checker.check_board(start)

        noisy = [row[:] for row in start]
        noisy[0][4] = "-"
        noisy[1][4] = "k"
        checker.update_side_detection(noisy)

        self.assertFalse(checker.is_red)


if __name__ == "__main__":
    unittest.main()
