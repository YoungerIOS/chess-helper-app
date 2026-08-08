import re
import threading
import time

from app.tools.log_config import get_logger


logger = get_logger(__name__)

REFERENCE_BOARD_WIDTH = 800.0
MOVE_PATTERN = re.compile(r"^[a-i][0-9][a-i][0-9]$")


class AutoMoveError(Exception):
    """自动走子无法安全执行。"""


class AutoMoveCancelled(AutoMoveError):
    """自动走子因状态变化被取消，不应作为用户错误提示。"""


class AutoMoveUserBusy(AutoMoveCancelled):
    """用户持续操作电脑时跳过自动走子。"""


def move_to_grid(move, is_red):
    """把 Pikafish 着法转换成当前屏幕朝向下的两个 (row, col)。"""
    if not isinstance(move, str) or not MOVE_PATTERN.fullmatch(move):
        raise AutoMoveError(f"无效着法格式: {move!r}")

    start_file = ord(move[0]) - ord("a")
    start_rank = int(move[1])
    end_file = ord(move[2]) - ord("a")
    end_rank = int(move[3])

    if is_red:
        start = (9 - start_rank, start_file)
        end = (9 - end_rank, end_file)
    else:
        start = (start_rank, 8 - start_file)
        end = (end_rank, 8 - end_file)

    return start, end


def grid_to_screen(row, col, board_coords, board_region):
    """将标准化为 800 宽的棋盘格点映射到屏幕逻辑坐标。"""
    x_coords = board_coords.get("x", [])
    y_coords = board_coords.get("y", [])
    if len(x_coords) != 9 or len(y_coords) != 10:
        raise AutoMoveError("棋盘格点配置无效")
    if not (0 <= row < 10 and 0 <= col < 9):
        raise AutoMoveError(f"棋盘坐标越界: ({row}, {col})")

    required = ("left", "top", "width", "height")
    if not board_region or any(key not in board_region for key in required):
        raise AutoMoveError("棋盘区域尚未定位")

    left = float(board_region["left"])
    top = float(board_region["top"])
    width = float(board_region["width"])
    height = float(board_region["height"])
    if width <= 0 or height <= 0:
        raise AutoMoveError("棋盘区域尺寸无效")

    scale = width / REFERENCE_BOARD_WIDTH
    x = left + float(x_coords[col]) * scale
    y = top + float(y_coords[row]) * scale

    if not (left <= x <= left + width and top <= y <= top + height):
        raise AutoMoveError("计算出的点击位置超出棋盘")

    return round(x), round(y)


class AutoMoveController:
    """等待用户空闲后，延迟并安全地执行一次 click-click 走子。"""

    def __init__(
        self,
        context,
        *,
        window_provider=None,
        can_execute=None,
        result_callback=None,
        mouse_factory=None,
        clicker=None,
        user_idle_provider=None,
        target_window_active_provider=None,
        sleeper=time.sleep,
        delay=0.35,
        click_interval=0.32,
        cursor_settle=0.12,
        idle_required=1.5,
        idle_wait_timeout=6.0,
        idle_poll_interval=0.10,
        verify_timeout=1.0,
        verify_interval=0.10,
    ):
        self.context = context
        self.window_provider = window_provider
        self.can_execute = can_execute or (lambda: True)
        self.result_callback = result_callback
        self.mouse_factory = mouse_factory or self._default_mouse_factory
        self.clicker = clicker or self._default_clicker
        self.user_idle_provider = user_idle_provider or self._default_user_idle_seconds
        self.target_window_active_provider = (
            target_window_active_provider or self._default_target_window_active
        )
        self.sleeper = sleeper
        self.delay = delay
        self.click_interval = click_interval
        self.cursor_settle = cursor_settle
        self.idle_required = idle_required
        self.idle_wait_timeout = idle_wait_timeout
        self.idle_poll_interval = idle_poll_interval
        self.verify_timeout = verify_timeout
        self.verify_interval = verify_interval

        self._lock = threading.Lock()
        self._generation = 0
        self._last_key = None

    @staticmethod
    def _default_mouse_factory():
        from pynput.mouse import Controller

        return Controller()

    @staticmethod
    def _default_clicker(controller):
        from pynput.mouse import Button

        controller.press(Button.left)
        time.sleep(0.07)
        controller.release(Button.left)

    @staticmethod
    def _default_user_idle_seconds():
        """返回距离最近一次真实键鼠输入的秒数，不统计合成事件。"""
        try:
            import Quartz

            return Quartz.CGEventSourceSecondsSinceLastEventType(
                Quartz.kCGEventSourceStateHIDSystemState,
                Quartz.kCGAnyInputEventType,
            )
        except Exception:
            # 无法可靠判断时采取保守策略，不抢占用户鼠标。
            return 0.0

    @staticmethod
    def _default_target_window_active(window_info):
        """确认目标棋盘窗口是最前面的普通窗口，避免抢走其他应用焦点。"""
        target_window_id = window_info.get("window_id") if window_info else None
        try:
            target_window_id = int(target_window_id)
        except (TypeError, ValueError):
            return False

        try:
            import Quartz

            options = (
                Quartz.kCGWindowListOptionOnScreenOnly
                | Quartz.kCGWindowListExcludeDesktopElements
            )
            windows = Quartz.CGWindowListCopyWindowInfo(
                options,
                Quartz.kCGNullWindowID,
            )
            for window in windows:
                if int(window.get('kCGWindowLayer', 0) or 0) != 0:
                    continue
                bounds = window.get('kCGWindowBounds', {})
                if float(bounds.get('Width', 0) or 0) <= 1:
                    continue
                if float(bounds.get('Height', 0) or 0) <= 1:
                    continue
                return int(window.get('kCGWindowNumber', -1)) == target_window_id
        except Exception:
            return False
        return False

    def cancel_pending(self):
        with self._lock:
            self._generation += 1
            self._last_key = None

    def schedule(self, move, is_red, analysis_token):
        """安排一次自动走子；重复消息或过期分析不会再次执行。"""
        key = (analysis_token, move, bool(is_red))
        with self._lock:
            if key == self._last_key:
                logger.debug(f"忽略重复自动走子请求: {key}")
                return False
            self._generation += 1
            generation = self._generation
            self._last_key = key

        thread = threading.Thread(
            target=self._run_scheduled,
            args=(move, bool(is_red), analysis_token, generation),
            daemon=True,
        )
        thread.start()
        return True

    def _run_scheduled(self, move, is_red, analysis_token, generation):
        try:
            self.sleeper(self.delay)
            self._ensure_current(analysis_token, generation)
            self.execute(move, is_red, analysis_token, generation)
            self._notify(True, f"已自动走子：{move}")
        except AutoMoveUserBusy as exc:
            logger.info(f"用户正在操作电脑，跳过自动走子: {exc}")
            self._notify(False, "检测到你正在使用电脑，已跳过自动走子")
        except AutoMoveCancelled as exc:
            logger.debug(f"自动走子已取消: {exc}")
        except Exception as exc:
            logger.error(f"自动走子失败: {exc}")
            self._notify(False, f"自动走子失败：{exc}")

    def execute(self, move, is_red, analysis_token, generation=None):
        """同步执行一次走子，供后台线程和测试调用。"""
        if generation is None:
            with self._lock:
                generation = self._generation
        self._ensure_current(analysis_token, generation)

        start, end = move_to_grid(move, is_red)
        checker = self.context.get_checker()
        if checker is None or getattr(checker, "in_settlement_screen", False):
            raise AutoMoveCancelled("棋局当前不可操作")
        if bool(getattr(checker, "is_red", is_red)) != bool(is_red):
            raise AutoMoveCancelled("棋盘朝向已经变化")

        board = getattr(checker, "last_board_array_for_engine", None)
        if not board:
            raise AutoMoveCancelled("缺少引擎分析时的棋盘快照")
        start_piece = board[start[0]][start[1]]
        is_own_piece = start_piece != "-" and (
            (is_red and start_piece.isupper()) or
            (not is_red and start_piece.islower())
        )
        if not is_own_piece:
            raise AutoMoveCancelled("推荐着法起点已不再是我方棋子")

        platform = self.context.get_platform(self.context.platform)
        board_region = platform.regions.get("board")
        window_info = self._validate_window(board_region) or {}
        start_point = grid_to_screen(*start, platform.board_coords, board_region)
        end_point = grid_to_screen(*end, platform.board_coords, board_region)

        self._wait_for_user_idle(analysis_token, generation, window_info)
        controller = self.mouse_factory()
        original_position = controller.position
        try:
            attempts = (
                ("完整点击", (start_point, end_point)),
                ("终点重试1", (end_point,)),
                ("终点重试2", (end_point,)),
                ("完整重试", (start_point, end_point)),
            )
            for attempt_index, (attempt_name, points) in enumerate(attempts):
                # 第一次已等待空闲；重试前若用户恢复操作则立即放弃。
                if attempt_index and self.user_idle_provider() < self.idle_required:
                    raise AutoMoveUserBusy("重试前检测到新的键鼠输入")
                if attempt_index and not self.target_window_active_provider(window_info):
                    raise AutoMoveUserBusy("重试前目标窗口已不在最前面")
                logger.debug(f"空闲自动走子尝试: {attempt_name}, points={points}")
                for index, point in enumerate(points):
                    self._click_point(controller, point)
                    if index < len(points) - 1:
                        self.sleeper(self.click_interval)
                    self._ensure_current(analysis_token, generation)

                if self._wait_until_move_observed(
                    checker,
                    start,
                    end,
                    start_piece,
                    analysis_token,
                    generation,
                ):
                    logger.info(
                        f"空闲自动走子确认成功: {move}, attempt={attempt_name}, "
                        f"{start_point} -> {end_point}"
                    )
                    return start_point, end_point

            raise AutoMoveError("多次点击后仍未检测到棋子落地")
        finally:
            self.sleeper(0.15)
            controller.position = original_position

    def _wait_for_user_idle(self, analysis_token, generation, window_info):
        deadline = time.monotonic() + self.idle_wait_timeout
        while True:
            self._ensure_current(analysis_token, generation)
            if not self.target_window_active_provider(window_info):
                raise AutoMoveUserBusy("棋盘窗口不是当前最前面的窗口")
            if self.user_idle_provider() >= self.idle_required:
                return
            if time.monotonic() >= deadline:
                raise AutoMoveUserBusy("等待用户空闲超时")
            self.sleeper(self.idle_poll_interval)

    def _click_point(self, controller, point):
        controller.position = point
        self.sleeper(self.cursor_settle)

        actual_x, actual_y = controller.position
        if abs(actual_x - point[0]) > 3 or abs(actual_y - point[1]) > 3:
            controller.position = point
            self.sleeper(self.cursor_settle)

        self.clicker(controller)
        self.sleeper(0.16)

    def _wait_until_move_observed(
        self,
        checker,
        start,
        end,
        start_piece,
        analysis_token,
        generation,
    ):
        deadline = time.monotonic() + self.verify_timeout
        while True:
            self._ensure_current(analysis_token, generation)
            board = getattr(checker, "last_board", None)
            if board:
                source_piece = board[start[0]][start[1]]
                destination_piece = board[end[0]][end[1]]
                if source_piece == "-" and destination_piece == start_piece:
                    return True
            if time.monotonic() >= deadline:
                break
            self.sleeper(self.verify_interval)
        return False

    def _ensure_current(self, analysis_token, generation):
        if not self.context.auto_move_enabled:
            raise AutoMoveCancelled("自动走子已关闭")
        if not self.can_execute():
            raise AutoMoveCancelled("助手已停止")
        if not self.context.is_analysis_token_current(analysis_token):
            raise AutoMoveCancelled("引擎建议已经过期")
        with self._lock:
            if generation != self._generation:
                raise AutoMoveCancelled("已有更新的自动走子任务")

    def _validate_window(self, board_region):
        if self.window_provider is None:
            return
        if not board_region:
            raise AutoMoveCancelled("棋盘区域尚未定位")
        window_info = self.window_provider()
        if not window_info or window_info.get("platform") != self.context.platform:
            raise AutoMoveCancelled("未找到当前游戏窗口")

        window = window_info.get("region", {})
        board_left = float(board_region["left"])
        board_top = float(board_region["top"])
        board_right = board_left + float(board_region["width"])
        board_bottom = board_top + float(board_region["height"])
        window_left = float(window.get("left", 0))
        window_top = float(window.get("top", 0))
        window_right = window_left + float(window.get("width", 0))
        window_bottom = window_top + float(window.get("height", 0))
        # 微信小程序的棋子会压在内容窗口边缘，Quartz 窗口边界与棋盘
        # 检测区域通常存在约 10px 偏差；容差随窗口尺寸缩放但保持有限。
        window_short_side = min(
            float(window.get("width", 0)),
            float(window.get("height", 0)),
        )
        tolerance = max(20.0, window_short_side * 0.04)
        if not (
            board_left >= window_left - tolerance and
            board_top >= window_top - tolerance and
            board_right <= window_right + tolerance and
            board_bottom <= window_bottom + tolerance
        ):
            raise AutoMoveCancelled("棋盘位置与游戏窗口不一致")
        return window_info

    def _notify(self, success, message):
        if self.result_callback:
            self.result_callback(success, message)
