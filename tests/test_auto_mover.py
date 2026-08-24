import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app.chess.auto_mover import (
    AutoMoveCancelled,
    AutoMoveController,
    AutoMoveUserBusy,
    grid_to_screen,
    move_to_grid,
)


BOARD_COORDS = {
    "x": [44, 133, 222, 311, 400, 489, 578, 667, 756],
    "y": [44, 130, 216, 302, 388, 474, 560, 646, 732, 818],
}
BOARD_REGION = {"left": 100, "top": 200, "width": 400, "height": 429}


class FakePlatform:
    board_coords = BOARD_COORDS
    regions = {"board": BOARD_REGION}


class FakeChecker:
    def __init__(self, is_red=False):
        self.is_red = is_red
        self.in_settlement_screen = False
        self.settlement_visual_confirmations = 0
        self.last_board_array_for_engine = [["-"] * 9 for _ in range(10)]
        self.last_board = [["-"] * 9 for _ in range(10)]

    def confirm_settlement_visual(self):
        self.settlement_visual_confirmations += 1
        self.in_settlement_screen = True
        return True


class FakeContext:
    def __init__(self, is_red=False):
        self.platform = "JJ"
        self.auto_move_enabled = True
        self.analysis_token = 7
        self.checker = FakeChecker(is_red)

    def get_checker(self):
        return self.checker

    def get_platform(self, _platform):
        return FakePlatform()

    def is_analysis_token_current(self, token):
        return token == self.analysis_token


class FakeMouse:
    def __init__(self):
        self._position = (10, 20)
        self.moves = []

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, value):
        self._position = value
        self.moves.append(value)


class AutoMoverTests(unittest.TestCase):
    def test_windows_idle_provider_uses_last_input_api(self):
        with (
            patch("app.chess.auto_mover.platform.system", return_value="Windows"),
            patch("app.chess.windows.user_idle_seconds", return_value=2.75),
        ):
            self.assertEqual(2.75, AutoMoveController._default_user_idle_seconds())

    def test_windows_foreground_provider_uses_window_id(self):
        with (
            patch("app.chess.auto_mover.platform.system", return_value="Windows"),
            patch("app.chess.windows.is_foreground_window", return_value=True) as active,
        ):
            self.assertTrue(AutoMoveController._default_target_window_active({"window_id": 1234}))
        active.assert_called_once_with(1234)

    def test_windows_background_click_uses_window_handle(self):
        with (
            patch("app.chess.auto_mover.platform.system", return_value="Windows"),
            patch("app.chess.windows.click_window_point") as click,
        ):
            AutoMoveController._default_window_clicker(
                {"window_id": 1234, "pid": 99}, (320, 480)
            )
        click.assert_called_once_with(1234, (320, 480))

    def test_default_window_capture_uses_bounded_mss_buffer(self):
        class FakeShot:
            width = 4
            height = 3
            bgra = bytes(range(width * height * 4))

        class FakeCapture:
            def __init__(self):
                self.region = None

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def grab(self, region):
                self.region = region
                return FakeShot()

        capture = FakeCapture()
        with patch("mss.MSS", return_value=capture):
            image = AutoMoveController._default_window_image_provider({
                "region": {"left": 10, "top": 20, "width": 4, "height": 3}
            })

        self.assertEqual(
            {"left": 10, "top": 20, "width": 4, "height": 3},
            capture.region,
        )
        self.assertEqual((3, 4, 3), image.shape)
        self.assertTrue(image.flags["OWNDATA"])

    def test_move_orientation_matches_board_display(self):
        self.assertEqual(((9, 7), (7, 6)), move_to_grid("h0g2", True))
        self.assertEqual(((0, 1), (2, 2)), move_to_grid("h0g2", False))

    def test_grid_to_screen_uses_normalized_board_coordinates(self):
        self.assertEqual(
            (166, 265),
            grid_to_screen(1, 1, BOARD_COORDS, BOARD_REGION),
        )

    def test_execute_clicks_source_then_destination_when_user_is_idle(self):
        context = FakeContext(is_red=False)
        context.checker.last_board_array_for_engine[0][1] = "n"
        mouse = FakeMouse()
        clicks = []

        def clicker(current_mouse):
            clicks.append(current_mouse.position)
            if len(clicks) == 2:
                context.checker.last_board[0][1] = "-"
                context.checker.last_board[2][2] = "n"

        controller = AutoMoveController(
            context,
            window_provider=lambda: {
                "platform": "JJ",
                "region": {"left": 50, "top": 100, "width": 600, "height": 700},
            },
            mouse_factory=lambda: mouse,
            clicker=clicker,
            user_idle_provider=lambda: 99.0,
            target_window_active_provider=lambda _window: True,
            sleeper=lambda _seconds: None,
        )

        start, end = controller.execute("h0g2", False, 7)

        self.assertEqual((166, 222), start)
        self.assertEqual((211, 308), end)
        self.assertEqual([start, end], clicks)
        self.assertEqual((10, 20), mouse.position)

    def test_destination_is_retried_when_first_drop_is_not_observed(self):
        context = FakeContext(is_red=False)
        context.checker.last_board_array_for_engine[0][1] = "n"
        context.checker.last_board[0][1] = "n"
        mouse = FakeMouse()
        clicks = []

        def clicker(current_mouse):
            clicks.append(current_mouse.position)
            if len(clicks) == 3:
                context.checker.last_board[0][1] = "-"
                context.checker.last_board[2][2] = "n"

        controller = AutoMoveController(
            context,
            mouse_factory=lambda: mouse,
            clicker=clicker,
            user_idle_provider=lambda: 99.0,
            target_window_active_provider=lambda _window: True,
            sleeper=lambda _seconds: None,
            verify_timeout=0,
        )

        controller.execute("h0g2", False, 7)

        self.assertEqual([(166, 222), (211, 308), (211, 308)], clicks)

    def test_own_synthetic_input_does_not_cancel_destination_retry(self):
        context = FakeContext(is_red=False)
        context.checker.last_board_array_for_engine[0][1] = "n"
        context.checker.last_board[0][1] = "n"
        mouse = FakeMouse()
        clicks = []
        idle_readings = iter((99.0, 0.0, 0.0))

        def clicker(current_mouse):
            clicks.append(current_mouse.position)
            if len(clicks) == 3:
                context.checker.last_board[0][1] = "-"
                context.checker.last_board[2][2] = "n"

        controller = AutoMoveController(
            context,
            mouse_factory=lambda: mouse,
            clicker=clicker,
            user_idle_provider=lambda: next(idle_readings),
            target_window_active_provider=lambda _window: True,
            sleeper=lambda _seconds: None,
            verify_timeout=0,
        )

        controller.execute("h0g2", False, 7)

        self.assertEqual([(166, 222), (211, 308), (211, 308)], clicks)

    def test_user_mouse_movement_stops_destination_retry(self):
        context = FakeContext(is_red=False)
        context.checker.last_board_array_for_engine[0][1] = "n"
        context.checker.last_board[0][1] = "n"
        mouse = FakeMouse()
        clicks = []

        def clicker(current_mouse):
            clicks.append(current_mouse.position)
            if len(clicks) == 2:
                current_mouse.position = (700, 700)

        controller = AutoMoveController(
            context,
            mouse_factory=lambda: mouse,
            clicker=clicker,
            user_idle_provider=lambda: 99.0,
            target_window_active_provider=lambda _window: True,
            sleeper=lambda _seconds: None,
            verify_timeout=0,
        )

        with self.assertRaisesRegex(AutoMoveUserBusy, "用户移动鼠标"):
            controller.execute("h0g2", False, 7)

        self.assertEqual([(166, 222), (211, 308)], clicks)
        self.assertEqual((10, 20), mouse.position)

    def test_stale_analysis_is_cancelled_before_clicking(self):
        context = FakeContext(is_red=False)
        context.checker.last_board_array_for_engine[0][1] = "n"
        controller = AutoMoveController(context, sleeper=lambda _seconds: None)

        with self.assertRaises(AutoMoveCancelled):
            controller.execute("h0g2", False, 6)

    def test_user_activity_skips_move_before_mouse_is_acquired(self):
        context = FakeContext(is_red=False)
        context.checker.last_board_array_for_engine[0][1] = "n"

        def unexpected_mouse_factory():
            self.fail("用户忙碌时不应获取或移动鼠标")

        controller = AutoMoveController(
            context,
            mouse_factory=unexpected_mouse_factory,
            user_idle_provider=lambda: 0.0,
            target_window_active_provider=lambda _window: True,
            sleeper=lambda _seconds: None,
            idle_wait_timeout=0,
        )

        with self.assertRaises(AutoMoveUserBusy):
            controller.execute("h0g2", False, 7)

    def test_inactive_game_window_skips_move_before_mouse_is_acquired(self):
        context = FakeContext(is_red=False)
        context.checker.last_board_array_for_engine[0][1] = "n"

        def unexpected_mouse_factory():
            self.fail("棋盘不在前台时不应获取或移动鼠标")

        controller = AutoMoveController(
            context,
            mouse_factory=unexpected_mouse_factory,
            user_idle_provider=lambda: 99.0,
            target_window_active_provider=lambda _window: False,
            sleeper=lambda _seconds: None,
        )

        with self.assertRaises(AutoMoveUserBusy):
            controller.execute("h0g2", False, 7)

    def test_window_validation_allows_small_quartz_edge_offset(self):
        context = FakeContext(is_red=False)
        controller = AutoMoveController(
            context,
            window_provider=lambda: {
                "platform": "JJ",
                "region": {"left": 112, "top": 200, "width": 500, "height": 500},
            },
        )
        controller._validate_window(BOARD_REGION)

    def test_window_validation_rejects_stale_board_position(self):
        context = FakeContext(is_red=False)
        controller = AutoMoveController(
            context,
            window_provider=lambda: {
                "platform": "JJ",
                "region": {"left": 160, "top": 200, "width": 500, "height": 500},
            },
        )
        with self.assertRaises(AutoMoveCancelled):
            controller._validate_window(BOARD_REGION)

    def test_background_move_finishes_as_soon_as_board_changes(self):
        context = FakeContext(is_red=False)
        context.checker.last_board_array_for_engine[0][1] = "n"
        context.checker.last_board[0][1] = "n"
        clicks = []

        def window_clicker(_window_info, point):
            clicks.append(point)
            if len(clicks) == 1:
                context.checker._pending_lift_source = (0, 1)
            elif len(clicks) == 2:
                context.checker.last_board[0][1] = "-"
                context.checker.last_board[2][2] = "n"

        controller = AutoMoveController(
            context,
            window_provider=lambda: {
                "platform": "JJ",
                "pid": 1234,
                "region": {"left": 50, "top": 100, "width": 600, "height": 700},
            },
            window_clicker=window_clicker,
            mouse_factory=lambda: self.fail("后台走子不应获取系统鼠标"),
            sleeper=lambda _seconds: None,
        )

        start, end = controller.execute("h0g2", False, 7)

        self.assertEqual([start, end], clicks)

    def test_background_click_without_lift_falls_back_to_compatible_mouse(self):
        context = FakeContext(is_red=False)
        context.checker.last_board_array_for_engine[0][1] = "n"
        context.checker.last_board[0][1] = "n"
        background_clicks = []
        mouse = FakeMouse()
        mouse_clicks = []

        def mouse_clicker(current_mouse):
            mouse_clicks.append(current_mouse.position)
            if len(mouse_clicks) % 2 == 0:
                context.checker.last_board[0][1] = "-"
                context.checker.last_board[2][2] = "n"

        controller = AutoMoveController(
            context,
            window_provider=lambda: {
                "platform": "JJ",
                "pid": 1234,
                "window_id": 5678,
                "region": {"left": 50, "top": 100, "width": 600, "height": 700},
            },
            window_clicker=lambda _window, point: background_clicks.append(point),
            mouse_factory=lambda: mouse,
            clicker=mouse_clicker,
            user_idle_provider=lambda: 99.0,
            target_window_active_provider=lambda _window: True,
            sleeper=lambda _seconds: None,
            selection_observe_timeout=0,
        )

        start, end = controller.execute("h0g2", False, 7)

        self.assertEqual([start], background_clicks)
        self.assertEqual([start, end], mouse_clicks)
        self.assertEqual((10, 20), mouse.position)

        # 同一窗口第二步应直接走兼容路径，不再重复等待后台点击探测。
        context.checker.last_board[0][1] = "n"
        context.checker.last_board[2][2] = "-"
        controller.execute("h0g2", False, 7)

        self.assertEqual([start], background_clicks)
        self.assertEqual([start, end, start, end], mouse_clicks)

    def test_green_play_again_button_is_detected_by_shape_and_position(self):
        image = np.zeros((1000, 1000, 3), dtype=np.uint8)
        image[:] = (30, 20, 50)
        cv2.rectangle(image, (300, 850), (700, 930), (55, 105, 55), -1)

        self.assertEqual(
            (500, 890),
            AutoMoveController.find_rematch_button_in_image(image),
        )

    def test_reward_popup_close_is_detected_by_color_shape_and_position(self):
        image = np.zeros((2200, 1200, 3), dtype=np.uint8)
        image[:] = (35, 30, 40)
        center = (1060, 807)
        color = (80, 220, 255)
        cv2.line(image, (1044, 791), (1076, 823), color, 10)
        cv2.line(image, (1076, 791), (1044, 823), color, 10)

        self.assertEqual(
            center,
            AutoMoveController.find_reward_popup_close_in_image(image),
        )

    def test_reward_popup_close_rejects_same_shape_outside_close_area(self):
        image = np.zeros((2200, 1200, 3), dtype=np.uint8)
        image[:] = (35, 30, 40)
        color = (80, 220, 255)
        cv2.line(image, (944, 791), (976, 823), color, 10)
        cv2.line(image, (976, 791), (944, 823), color, 10)

        self.assertIsNone(
            AutoMoveController.find_reward_popup_close_in_image(image),
        )

    def test_popup_like_shape_is_not_clicked_during_active_game(self):
        context = FakeContext(is_red=False)
        image = np.zeros((2200, 1200, 3), dtype=np.uint8)
        image[:] = (35, 30, 40)
        color = (80, 220, 255)
        cv2.line(image, (1044, 791), (1076, 823), color, 10)
        cv2.line(image, (1076, 791), (1044, 823), color, 10)
        clicks = []

        controller = AutoMoveController(
            context,
            window_provider=lambda: {
                "platform": "JJ",
                "pid": 1234,
                "window_id": 5678,
                "region": {
                    "left": 100,
                    "top": 50,
                    "width": 600,
                    "height": 1100,
                },
            },
            window_image_provider=lambda _window: image,
            window_clicker=lambda _window, point: clicks.append(point),
        )
        controller._button_scan_pending = True

        controller._run_button_scan()

        self.assertEqual([], clicks)
        self.assertFalse(controller._reward_popup_seen)

    def test_reward_popup_is_closed_before_visible_rematch_button(self):
        context = FakeContext(is_red=False)
        image = np.zeros((2200, 1200, 3), dtype=np.uint8)
        image[:] = (35, 30, 40)
        cv2.rectangle(image, (360, 1870), (840, 2046), (55, 105, 55), -1)
        color = (80, 220, 255)
        cv2.line(image, (1044, 791), (1076, 823), color, 10)
        cv2.line(image, (1076, 791), (1044, 823), color, 10)
        clicks = []

        controller = AutoMoveController(
            context,
            window_provider=lambda: {
                "platform": "JJ",
                "pid": 1234,
                "window_id": 5678,
                "region": {
                    "left": 100,
                    "top": 50,
                    "width": 600,
                    "height": 1100,
                },
            },
            window_image_provider=lambda _window: image,
            window_clicker=lambda _window, point: clicks.append(point),
        )
        controller._button_scan_pending = True

        controller._run_button_scan()

        self.assertEqual([(630, 454)], clicks)
        self.assertEqual(1, context.checker.settlement_visual_confirmations)
        self.assertTrue(controller._reward_popup_seen)
        self.assertFalse(controller._rematch_button_seen)

        # 下一帧弹层消失后才允许点击底层“再来一局”。
        image[770:845, 1020:1100] = (35, 30, 40)
        controller._button_scan_pending = True
        controller._run_button_scan()

        self.assertEqual([(630, 454), (400, 1029)], clicks)
        self.assertFalse(controller._reward_popup_seen)
        self.assertTrue(controller._rematch_button_seen)

    def test_visual_button_scan_clicks_detected_center_without_settlement_state(self):
        context = FakeContext(is_red=False)
        self.assertFalse(context.checker.in_settlement_screen)
        image = np.zeros((1000, 1000, 3), dtype=np.uint8)
        image[:] = (30, 20, 50)
        cv2.rectangle(image, (300, 850), (700, 930), (55, 105, 55), -1)
        clicks = []

        controller = AutoMoveController(
            context,
            window_provider=lambda: {
                "platform": "JJ",
                "pid": 1234,
                "window_id": 5678,
                "region": {
                    "left": 100,
                    "top": 50,
                    "width": 500,
                    "height": 1000,
                },
            },
            window_image_provider=lambda _window: image,
            window_clicker=lambda _window, point: clicks.append(point),
        )
        controller._button_scan_pending = True

        controller._run_button_scan()

        self.assertEqual([(350, 940)], clicks)
        self.assertTrue(controller._rematch_button_seen)

if __name__ == "__main__":
    unittest.main()
