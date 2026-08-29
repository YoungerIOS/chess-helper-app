import queue
import json
import threading
import unittest
from unittest.mock import mock_open, patch

from app.chess.context import ChessContext, Platform
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

    def test_engine_telemetry_is_coalesced_outside_control_queue(self):
        bus = MessageBus()
        ui_queue = queue.Queue(maxsize=1)
        bus.set_ui_queue(ui_queue)
        first = Message(MessageType.ENGINE_INFO, {"depth": 1})
        latest = Message(MessageType.ENGINE_INFO, {"depth": 2})
        bus.publish(first)
        bus.publish(latest)

        self.assertEqual(0, ui_queue.qsize())
        self.assertIs(latest, bus.take_latest_engine_info())
        self.assertIsNone(bus.take_latest_engine_info())

        bus.publish(Message(MessageType.ERROR, "important"))
        delivered = ui_queue.get_nowait()
        self.assertEqual(MessageType.ERROR, delivered.type)

    def test_control_messages_keep_fifo_order_while_telemetry_is_busy(self):
        bus = MessageBus()
        ui_queue = queue.Queue(maxsize=3)
        bus.set_ui_queue(ui_queue)

        bus.publish(Message(MessageType.CHANGE, "轮到我方"))
        for depth in range(100):
            bus.publish(Message(MessageType.ENGINE_INFO, {"depth": depth}))
        bus.publish(Message(MessageType.MOVE_CODE, "c7c9"))

        self.assertEqual(MessageType.CHANGE, ui_queue.get_nowait().type)
        self.assertEqual(MessageType.MOVE_CODE, ui_queue.get_nowait().type)
        self.assertEqual(
            {"depth": 99}, bus.take_latest_engine_info().content
        )

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

    def test_continuous_capture_reuses_one_mss_instance(self):
        class FakePlatform:
            regions = {"board": {"left": 0, "top": 0, "width": 10, "height": 10}}

        class FakeContext:
            @staticmethod
            def get_platform(_name):
                return FakePlatform()

            platform = "JJ"

        class FakeCapture:
            def __init__(self, stop_event):
                self.stop_event = stop_event
                self.grabs = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def grab(self, _region):
                self.grabs += 1
                if self.grabs == 3:
                    self.stop_event.set()
                return object()

        manager = ChessCaptureManager.__new__(ChessCaptureManager)
        manager.context = FakeContext()
        manager.stop_event = threading.Event()
        manager.last_capture_time = 0
        capture = FakeCapture(manager.stop_event)

        with (
            patch("app.chess.screenshot.mss.MSS", return_value=capture) as factory,
            patch("app.chess.screenshot.filter_stable_frame", return_value=(None, None)),
        ):
            manager._continuous_capture_worker(interval=0)

        factory.assert_called_once_with()
        self.assertEqual(3, capture.grabs)

    def test_config_reload_reuses_loaded_piece_model(self):
        model = object()
        platform = Platform(
            name="JJ",
            board_coords={"x": [1], "y": [2]},
            regions={"board": {"left": 1}},
            _piece_recognizer=model,
        )
        config = {
            "JJ": {
                "board_coords": {"x": [3], "y": [4]},
                "regions": {"board": {"left": 9}},
            },
            "platform": "JJ",
            "engine_params": {},
        }
        current = ChessContext.__new__(ChessContext)
        current._platforms = {"JJ": platform}
        current._engine_params_lock = threading.Lock()

        with (
            patch("app.chess.context.utils.resource_path", return_value="config.json"),
            patch("app.chess.context.utils.user_config_path", return_value="config.json"),
            patch("app.tools.config_store.os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(config))),
        ):
            current.load_config()

        self.assertIs(platform, current._platforms["JJ"])
        self.assertIs(model, current._platforms["JJ"]._piece_recognizer)
        self.assertEqual({"x": [3], "y": [4]}, platform.board_coords)


if __name__ == "__main__":
    unittest.main()
