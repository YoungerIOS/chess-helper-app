import unittest

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
        self.last_board_array_for_engine = [["-"] * 9 for _ in range(10)]
        self.last_board = [["-"] * 9 for _ in range(10)]


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


if __name__ == "__main__":
    unittest.main()
