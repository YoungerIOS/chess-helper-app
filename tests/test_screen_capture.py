import threading
import unittest

from app.chess.screen_capture import ScreenCaptureBusy, locked_grab


class _BlockingCapture:
    def __init__(self, entered, release):
        self.entered = entered
        self.release = release

    def grab(self, region):
        self.entered.set()
        self.release.wait(timeout=1.0)
        return region


class ScreenCaptureCoordinationTests(unittest.TestCase):
    def test_overlapping_capture_times_out_instead_of_queueing(self):
        entered = threading.Event()
        release = threading.Event()
        first = _BlockingCapture(entered, release)
        worker = threading.Thread(
            target=lambda: locked_grab(first, {"id": 1}, timeout=0.1),
            daemon=True,
        )
        worker.start()
        self.assertTrue(entered.wait(timeout=0.5))

        with self.assertRaises(ScreenCaptureBusy):
            locked_grab(first, {"id": 2}, timeout=0.01)

        release.set()
        worker.join(timeout=0.5)
        self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
