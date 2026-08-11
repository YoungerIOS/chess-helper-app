import unittest

from app.chess.checker import PositionChecker
from app.chess.move_tracker import LegalMoveMatcher


class LegalMoveMatcherTests(unittest.TestCase):
    BASE_HASH = "0000000000000000"

    def setUp(self):
        self.matcher = LegalMoveMatcher()
        self.board = [row[:] for row in PositionChecker.START_RED]
        self.trusted_hashes = [
            [self.BASE_HASH] * 9 for _ in range(10)
        ]

    def current_hashes(self, changes):
        hashes = [row[:] for row in self.trusted_hashes]
        for position, value in changes.items():
            row, col = position
            hashes[row][col] = value
        return hashes

    def test_matches_normal_move_without_classifying_pieces(self):
        current = self.current_hashes({
            (6, 0): "ffffffffffffffff",
            (5, 0): "00000000ffffffff",
        })

        match = self.matcher.match(
            self.board, self.trusted_hashes, current, is_red_at_bottom=True
        )

        self.assertIsNotNone(match)
        self.assertEqual((6, 0), match.from_pos)
        self.assertEqual((5, 0), match.to_pos)
        self.assertEqual("P", match.piece)
        self.assertEqual("-", match.board[6][0])
        self.assertEqual("P", match.board[5][0])

    def test_matches_capture_and_preserves_captured_piece(self):
        board = [["-"] * 9 for _ in range(10)]
        board[0][4] = "k"
        board[9][4] = "K"
        board[5][4] = "P"
        board[5][0] = "R"
        board[2][0] = "n"
        current = self.current_hashes({
            (5, 0): "ffffffffffffffff",
            (2, 0): "0fffffffffffffff",
        })

        match = self.matcher.match(
            board, self.trusted_hashes, current, is_red_at_bottom=True
        )

        self.assertIsNotNone(match)
        self.assertEqual((5, 0), match.from_pos)
        self.assertEqual((2, 0), match.to_pos)
        self.assertEqual("n", match.captured_piece)
        self.assertEqual("R", match.board[2][0])

    def test_ignores_extra_jj_marker_changes(self):
        current = self.current_hashes({
            (6, 0): "ffffffffffffffff",
            (5, 0): "00000000ffffffff",
            (7, 4): "000000000000ffff",
            (8, 4): "00000000000000ff",
        })

        match = self.matcher.match(
            self.board, self.trusted_hashes, current, is_red_at_bottom=True
        )

        self.assertIsNotNone(match)
        self.assertEqual(((6, 0), (5, 0)), (match.from_pos, match.to_pos))

    def test_rejects_ambiguous_equal_scoring_moves(self):
        current = self.current_hashes({
            (6, 0): "000000000000ffff",
            (5, 0): "000000000000ffff",
            (6, 2): "000000000000ffff",
            (5, 2): "000000000000ffff",
        })

        match = self.matcher.match(
            self.board, self.trusted_hashes, current, is_red_at_bottom=True
        )

        self.assertIsNone(match)

    def test_respects_expected_side_to_move(self):
        current = self.current_hashes({
            (3, 0): "ffffffffffffffff",
            (4, 0): "00000000ffffffff",
        })

        rejected = self.matcher.match(
            self.board,
            self.trusted_hashes,
            current,
            is_red_at_bottom=True,
            side_to_move="red",
        )
        accepted = self.matcher.match(
            self.board,
            self.trusted_hashes,
            current,
            is_red_at_bottom=True,
            side_to_move="black",
        )

        self.assertIsNone(rejected)
        self.assertIsNotNone(accepted)
        self.assertEqual("p", accepted.piece)

    def test_rejects_massive_change_for_full_recognition_fallback(self):
        changes = {
            (row, col): "ffffffffffffffff"
            for row in range(3)
            for col in range(3)
        }
        current = self.current_hashes(changes)

        match = self.matcher.match(
            self.board, self.trusted_hashes, current, is_red_at_bottom=True
        )

        self.assertIsNone(match)


if __name__ == "__main__":
    unittest.main()
