import queue
import threading
import unittest
from unittest.mock import patch

from app.chess.message import Message, MessageType
from app.chess.message_bus import MessageBus
from app.chess.screenshot import ChessCaptureManager


class BackpressureTests(unittest.TestCase):
    def test_frame_queue_keeps_only_the_latest_frames(self):
        manager = ChessCaptureManager.__new__(ChessCaptureManager)
        manager.process_queue = queue.Queue(maxsize=2)
        manager.stop_event = threading.Event()
        manager._dropped_frames = 0

        self.assertTrue(manager._enqueue_latest_frame((1, "oldest")))
        self.assertTrue(manager._enqueue_latest_frame((2, "middle")))
        self.assertTrue(manager._enqueue_latest_frame((3, "latest")))

        self.assertEqual(2, manager.process_queue.qsize())
        self.assertEqual((2, "middle"), manager.process_queue.get_nowait())
        self.assertEqual((3, "latest"), manager.process_queue.get_nowait())
        self.assertEqual(1, manager._dropped_frames)

    def test_retry_requests_are_coalesced(self):
        manager = ChessCaptureManager.__new__(ChessCaptureManager)
        manager.retry_queue = queue.Queue(maxsize=1)
        message = Message(MessageType.RETRY_CAPTURE, "retry")

        manager._on_retry_capture(message)
        manager._on_retry_capture(message)

        self.assertEqual(1, manager.retry_queue.qsize())

    def test_ui_queue_is_bounded_without_blocking_publishers(self):
        bus = MessageBus()
        ui_queue = queue.Queue(maxsize=1)
        bus.set_ui_queue(ui_queue)
        bus.publish(Message(MessageType.ENGINE_INFO, {"depth": 1}))
        bus.publish(Message(MessageType.ENGINE_INFO, {"depth": 2}))

        self.assertEqual(1, ui_queue.qsize())

        bus.publish(Message(MessageType.ERROR, "important"))
        delivered = ui_queue.get_nowait()
        self.assertEqual(MessageType.ERROR, delivered.type)

    def test_capture_workers_start_lazily(self):
        with (
            patch("app.chess.screenshot.BoardLocator"),
            patch("app.chess.screenshot.processor.start_process_worker", return_value=[]) as start,
        ):
            manager = ChessCaptureManager()
            self.assertEqual([], manager.worker_threads)
            start.assert_not_called()

            manager.start_capture()
            start.assert_called_once_with(
                manager.process_queue,
                manager.result_queue,
                manager.stop_event,
            )
            manager.stop_capture(timeout=0)

    def test_capture_workers_exit_on_stop(self):
        with patch("app.chess.screenshot.BoardLocator"):
            manager = ChessCaptureManager()
            manager.start_capture()
            workers = list(manager.worker_threads)

            manager.stop_capture(timeout=1)

            self.assertTrue(workers)
            self.assertTrue(all(not worker.is_alive() for worker in workers))


if __name__ == "__main__":
    unittest.main()
