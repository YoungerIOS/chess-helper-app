import unittest

import cv2
import numpy as np

from app.chess.processor import ChessProcess
from app.chess.recognizer import (
    ChessRecognizer,
    RecognitionDetail,
    RecognitionErrorType,
)
from app.tools.utils import resource_path


class FakeScreenshot:
    def __init__(self, width=698, height=749):
        self.width = width
        self.height = height
        self.bgra = np.zeros((height, width, 4), dtype=np.uint8).tobytes()


class RecordingPieceRecognizer:
    def __init__(self, low_confidence_first=False):
        self.crop_shapes = []
        self.low_confidence_first = low_confidence_first

    def recognize_batch(self, crops):
        self.crop_shapes = [crop.shape[:2] for crop in crops]
        results = [
            {"class_name": "-", "confidence": 1.0, "class_index": 7}
            for _ in crops
        ]
        if self.low_confidence_first:
            results[0] = {"class_name": "A", "confidence": 0.5, "class_index": 9}
        return results


class FakeContext:
    def __init__(self, platform):
        self.platform = platform
        self.piece_recognizer = RecordingPieceRecognizer()


class FakePlatform:
    board_coords = {"x": [0], "y": [0]}


class ProcessorContext:
    def __init__(self):
        self.discard_before_timestamp = 0.0

    def get_platform(self, _platform):
        return FakePlatform()


class ProcessorRecognizer:
    def recognize_piece_from_grid(self, _img, _x, _y):
        board = [["-"] * 9 for _ in range(10)]
        details = [
            RecognitionDetail(
                type=RecognitionErrorType.MARKER_MISSING,
                position=(-1, -1),
                message="未检测到标记",
                confidence=1.0,
            )
        ]
        return board, [], [], details


class ChessRecognizerTests(unittest.TestCase):
    X_COORDS = [44, 133, 222, 311, 400, 489, 578, 667, 756]
    Y_COORDS = [44, 130, 216, 302, 388, 474, 560, 646, 732, 818]

    def recognize(self, platform):
        context = FakeContext(platform)
        recognizer = ChessRecognizer(context)
        result = recognizer.recognize_piece_from_grid(
            FakeScreenshot(), self.X_COORDS, self.Y_COORDS
        )
        return context, result

    def test_jj_uses_tighter_crops_than_tt(self):
        jj_context, _ = self.recognize("JJ")
        tt_context, _ = self.recognize("TT")

        self.assertEqual({(72, 72)}, set(jj_context.piece_recognizer.crop_shapes))
        self.assertEqual({(80, 80)}, set(tt_context.piece_recognizer.crop_shapes))

    def test_jj_black_cannon_fallback_rejects_red_cannon(self):
        recognizer = ChessRecognizer(FakeContext("JJ"))
        black_cannon = cv2.imread(
            resource_path("images", "media", "black_c.png"),
            cv2.IMREAD_COLOR,
        )
        red_cannon = cv2.imread(
            resource_path("images", "media", "red_C.png"),
            cv2.IMREAD_COLOR,
        )

        self.assertIsNotNone(black_cannon)
        self.assertIsNotNone(red_cannon)
        self.assertTrue(recognizer._recover_jj_black_cannon(black_cannon))
        self.assertFalse(recognizer._recover_jj_black_cannon(red_cannon))

    def test_black_cannon_fallback_is_disabled_for_tt(self):
        recognizer = ChessRecognizer(FakeContext("TT"))
        black_cannon = cv2.imread(
            resource_path("images", "media", "black_c.png"),
            cv2.IMREAD_COLOR,
        )

        self.assertFalse(recognizer._recover_jj_black_cannon(black_cannon))

    def test_low_confidence_prediction_keeps_previous_piece(self):
        context = FakeContext("JJ")
        context.piece_recognizer.low_confidence_first = True
        recognizer = ChessRecognizer(context)
        recognizer.last_grid_hashes = [["old"] * 9 for _ in range(10)]
        recognizer.last_board_array = [["-"] * 9 for _ in range(10)]
        recognizer.last_board_array[0][0] = "R"

        board, _, _, details = recognizer.recognize_piece_from_grid(
            FakeScreenshot(), self.X_COORDS, self.Y_COORDS
        )

        self.assertEqual("R", board[0][0])
        self.assertIsNone(recognizer.last_grid_hashes[0][0])
        self.assertTrue(
            any(detail.type == RecognitionErrorType.LOW_CONFIDENCE for detail in details)
        )

        recognizer.recognize_piece_from_grid(
            FakeScreenshot(), self.X_COORDS, self.Y_COORDS
        )
        self.assertEqual([(72, 72)], context.piece_recognizer.crop_shapes)

    def test_missing_marker_is_not_a_fatal_recognition_error(self):
        process = ChessProcess.__new__(ChessProcess)
        process.context = ProcessorContext()
        process.context.platform = "JJ"
        process.checker = type("Checker", (), {"in_settlement_screen": False})()
        process.recognizer = ProcessorRecognizer()

        board, markers, _, is_massive_change = process._recognize_pieces(object())

        self.assertIsNotNone(board)
        self.assertEqual([], markers)
        self.assertFalse(is_massive_change)


if __name__ == "__main__":
    unittest.main()
