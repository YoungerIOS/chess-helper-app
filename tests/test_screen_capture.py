import threading
import unittest

from app.chess.screen_capture import ScreenCaptureBusy, locked_grab, normalize_region


class _BlockingCapture:
    def __init__(self, entered, release):
        self.entered = entered
        self.release = release

    def grab(self, region):
        self.entered.set()
        self.release.wait(timeout=1.0)
        return region


class FakeCapture:
    def __init__(self):
        self.region = None

    def grab(self, region):
        self.region = region
        return region


class ScreenCaptureTests(unittest.TestCase):
    def test_overlapping_capture_times_out_instead_of_queueing(self):
        entered = threading.Event()
        release = threading.Event()
        first = _BlockingCapture(entered, release)
        region = {"left": 0, "top": 0, "width": 10, "height": 10}
        worker = threading.Thread(
            target=lambda: locked_grab(first, region, timeout=0.1),
            daemon=True,
        )
        worker.start()
        self.assertTrue(entered.wait(timeout=0.5))

        with self.assertRaises(ScreenCaptureBusy):
            locked_grab(first, region, timeout=0.01)

        release.set()
        worker.join(timeout=0.5)
        self.assertFalse(worker.is_alive())

    def test_float_board_region_is_rounded_for_mss(self):
        capture = FakeCapture()

        result = locked_grab(capture, {
            "left": -1200.4,
            "top": 335.5,
            "width": 580.4,
            "height": 622.6,
        })

        self.assertEqual(
            {"left": -1200, "top": 336, "width": 580, "height": 623},
            result,
        )
        self.assertTrue(all(isinstance(value, int) for value in result.values()))

    def test_invalid_region_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_region({"left": 0, "top": 0, "width": 0.2, "height": 10})


if __name__ == "__main__":
    unittest.main()
