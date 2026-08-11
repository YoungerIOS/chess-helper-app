import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app.chess.processor import ChessProcess
from app.chess.checker import PositionChecker
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
        self.batch_calls = 0
        self.forced_classes = None

    def recognize_batch(self, crops):
        self.batch_calls += 1
        self.crop_shapes = [crop.shape[:2] for crop in crops]
        results = [
            {"class_name": "-", "confidence": 1.0, "class_index": 7}
            for _ in crops
        ]
        if self.forced_classes is not None:
            classes = list(self.forced_classes[:len(crops)])
            classes.extend(["-"] * (len(crops) - len(classes)))
            results = [
                {
                    "class_name": class_name,
                    "confidence": 1.0,
                    "class_index": 0,
                }
                for class_name in classes
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

    def test_jj_legal_move_fast_path_only_confirms_endpoints_with_onnx(self):
        context = FakeContext("JJ")
        context.piece_recognizer.forced_classes = ["-", "P"]
        recognizer = ChessRecognizer(context)
        board = [row[:] for row in PositionChecker.START_RED]
        base_hash = "0000000000000000"
        trusted_hashes = [[base_hash] * 9 for _ in range(10)]
        current_hashes = [row[:] for row in trusted_hashes]
        current_hashes[6][0] = "ffffffffffffffff"
        current_hashes[5][0] = "00000000ffffffff"
        recognizer.commit_tracking_state(
            board, trusted_hashes, is_red_at_bottom=True, side_to_move="red"
        )
        flattened_hashes = [
            value for row in current_hashes for value in row
        ]

        with patch(
            "app.tools.utils.compute_image_hash",
            side_effect=flattened_hashes,
        ):
            recognized, markers, _, _ = recognizer.recognize_piece_from_grid(
                FakeScreenshot(), self.X_COORDS, self.Y_COORDS
            )

        self.assertEqual(1, context.piece_recognizer.batch_calls)
        self.assertEqual("-", recognized[6][0])
        self.assertEqual("P", recognized[5][0])
        self.assertEqual([], markers)

    def test_jj_fast_path_rejects_unconfirmed_legal_candidate(self):
        context = FakeContext("JJ")
        # 画面并没有显示兵到达终点；仅凭哈希与合法性不得
        # 直接更新棋盘。后续会回退到原有局部识别。
        context.piece_recognizer.forced_classes = ["-", "-"]
        recognizer = ChessRecognizer(context)
        board = [row[:] for row in PositionChecker.START_RED]
        base_hash = "0000000000000000"
        trusted_hashes = [[base_hash] * 9 for _ in range(10)]
        current_hashes = [row[:] for row in trusted_hashes]
        current_hashes[6][0] = "ffffffffffffffff"
        current_hashes[5][0] = "00000000ffffffff"
        recognizer.commit_tracking_state(
            board, trusted_hashes, is_red_at_bottom=True, side_to_move="red"
        )
        flattened_hashes = [
            value for row in current_hashes for value in row
        ]

        with patch(
            "app.tools.utils.compute_image_hash",
            side_effect=flattened_hashes,
        ):
            recognized, _, _, _ = recognizer.recognize_piece_from_grid(
                FakeScreenshot(), self.X_COORDS, self.Y_COORDS
            )

        self.assertEqual("-", recognized[6][0])
        self.assertEqual("-", recognized[5][0])
        self.assertGreaterEqual(context.piece_recognizer.batch_calls, 2)


if __name__ == "__main__":
    unittest.main()
