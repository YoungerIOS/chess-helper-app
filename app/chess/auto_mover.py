import re
import threading
import time
import platform

from app.tools.log_config import get_logger
from app.chess.screen_capture import ScreenCaptureBusy, locked_grab


logger = get_logger(__name__)

REFERENCE_BOARD_WIDTH = 800.0
MOVE_PATTERN = re.compile(r"^[a-i][0-9][a-i][0-9]$")


class AutoMoveError(Exception):
    """自动走子无法安全执行。"""


class AutoMoveCancelled(AutoMoveError):
    """自动走子因状态变化被取消，不应作为用户错误提示。"""


class AutoMoveUserBusy(AutoMoveCancelled):
    """用户持续操作电脑时跳过自动走子。"""


class AutoMoveBackgroundUnsupported(AutoMoveError):
    """游戏画布未响应进程定向点击，需要回退到兼容点击。"""


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
        window_clicker=None,
        window_image_provider=None,
        sleeper=time.sleep,
        delay=0.0,
        click_interval=0.16,
        cursor_settle=0.06,
        idle_required=1.5,
        idle_wait_timeout=6.0,
        idle_poll_interval=0.10,
        verify_timeout=1.0,
        verify_interval=0.10,
        selection_observe_timeout=0.55,
        move_response_timeout=8.0,
        action_poll_interval=0.06,
        move_retry_interval=0.45,
        button_scan_interval=0.75,
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
        self.window_clicker = window_clicker or self._default_window_clicker
        self.window_image_provider = (
            window_image_provider or self._default_window_image_provider
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
        self.selection_observe_timeout = selection_observe_timeout
        self.move_response_timeout = move_response_timeout
        self.action_poll_interval = action_poll_interval
        self.move_retry_interval = move_retry_interval
        self.button_scan_interval = button_scan_interval

        self._lock = threading.Lock()
        self._generation = 0
        self._last_key = None
        self._button_scan_pending = False
        self._last_button_scan_at = 0.0
        self._rematch_button_seen = False
        self._rematch_button_click_attempts = 0
        self._background_click_supported = None
        self._background_click_window_key = None

    @staticmethod
    def _default_mouse_factory():
        from pynput.mouse import Controller

        return Controller()

    @staticmethod
    def _default_clicker(controller):
        from pynput.mouse import Button

        controller.press(Button.left)
        time.sleep(0.045)
        controller.release(Button.left)

    @staticmethod
    def _default_user_idle_seconds():
        """返回距离最近一次真实键鼠输入的秒数，不统计合成事件。"""
        try:
            if platform.system() == "Windows":
                from app.chess.windows import user_idle_seconds
                return user_idle_seconds()
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
            if platform.system() == "Windows":
                from app.chess.windows import is_foreground_window
                return is_foreground_window(target_window_id)
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

    @staticmethod
    def _default_window_clicker(window_info, point):
        """向指定进程投递鼠标点击，不移动系统光标也不切换焦点。"""
        if platform.system() == "Windows":
            try:
                from app.chess.windows import click_window_point
                click_window_point(int(window_info.get("window_id")), point)
                return
            except Exception as exc:
                raise AutoMoveError(f"Windows后台点击失败: {exc}") from exc

        try:
            pid = int(window_info.get("pid"))
        except (AttributeError, TypeError, ValueError):
            raise AutoMoveError("游戏窗口缺少进程信息，无法后台点击")

        try:
            import Quartz

            down = Quartz.CGEventCreateMouseEvent(
                None,
                Quartz.kCGEventLeftMouseDown,
                point,
                Quartz.kCGMouseButtonLeft,
            )
            up = Quartz.CGEventCreateMouseEvent(
                None,
                Quartz.kCGEventLeftMouseUp,
                point,
                Quartz.kCGMouseButtonLeft,
            )
            Quartz.CGEventPostToPid(pid, down)
            time.sleep(0.07)
            Quartz.CGEventPostToPid(pid, up)
        except AutoMoveError:
            raise
        except Exception as exc:
            raise AutoMoveError(f"后台点击失败: {exc}") from exc

    @staticmethod
    def _default_window_image_provider(window_info):
        """截取窗口在屏幕上的区域，避免CGWindow截图累积Mach内存。"""
        try:
            region = window_info.get("region", {})
            left = round(float(region["left"]))
            top = round(float(region["top"]))
            width = round(float(region["width"]))
            height = round(float(region["height"]))
            if width <= 1 or height <= 1:
                return None

            import mss
            import numpy as np

            with mss.MSS() as capture:
                shot = locked_grab(capture, {
                    "left": left,
                    "top": top,
                    "width": width,
                    "height": height,
                }, timeout=0.15)
                # 必须复制后再离开mss上下文，避免数组继续引用原生截图缓冲。
                bgra = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(
                    shot.height,
                    shot.width,
                    4,
                )
                return bgra[:, :, :3].copy()
        except ScreenCaptureBusy:
            # 棋盘识别优先；繁忙时跳过本轮结算按钮扫描。
            return None
        except Exception as exc:
            logger.debug(f"无法读取JJ窗口用于按钮检测: {exc}")
            return None

    @staticmethod
    def find_rematch_button_in_image(image):
        """以颜色、位置、面积和形状识别底部绿色“再来一局”按钮。"""
        if image is None or getattr(image, "ndim", 0) != 3:
            return None
        height, width = image.shape[:2]
        if width < 200 or height < 300:
            return None

        try:
            import cv2
            import numpy as np

            # 按钮只会出现在窗口下方；绿色较暗时也要保留，但红框、文字和
            # 游戏背景必须通过后续几何条件排除。
            start_y = int(height * 0.72)
            hsv = cv2.cvtColor(image[start_y:, :, :3], cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(
                hsv,
                np.array((25, 45, 35), dtype=np.uint8),
                np.array((80, 255, 255), dtype=np.uint8),
            )
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            count, _, stats, _ = cv2.connectedComponentsWithStats(mask)

            candidates = []
            for index in range(1, count):
                x, relative_y, box_width, box_height, area = map(int, stats[index])
                y = relative_y + start_y
                if box_height <= 0:
                    continue
                center_x = x + box_width / 2
                center_y = y + box_height / 2
                width_ratio = box_width / width
                height_ratio = box_height / height
                aspect_ratio = box_width / box_height
                fill_ratio = area / (box_width * box_height)

                if not (0.38 <= center_x / width <= 0.62):
                    continue
                if not (0.82 <= center_y / height <= 0.96):
                    continue
                if not (0.28 <= width_ratio <= 0.58):
                    continue
                if not (0.045 <= height_ratio <= 0.12):
                    continue
                if not (2.4 <= aspect_ratio <= 5.2):
                    continue
                if fill_ratio < 0.35:
                    continue

                # 优先选择面积大且更接近窗口水平中心的候选。
                score = area - abs(center_x - width / 2) * 20
                candidates.append((score, round(center_x), round(center_y)))

            if not candidates:
                return None
            _, center_x, center_y = max(candidates)
            return center_x, center_y
        except Exception as exc:
            logger.debug(f"绿色再来一局按钮识别失败: {exc}")
            return None

    def scan_rematch_button(self):
        """异步扫描一次完整JJ窗口；只有看见绿色按钮才点击。"""
        if (
            not self.context.auto_move_enabled or
            self.context.platform != "JJ" or
            not self.can_execute() or
            self.window_provider is None
        ):
            return False

        now = time.monotonic()
        with self._lock:
            if self._button_scan_pending:
                return False
            if now - self._last_button_scan_at < self.button_scan_interval:
                return False
            self._last_button_scan_at = now
            self._button_scan_pending = True

        threading.Thread(target=self._run_button_scan, daemon=True).start()
        return True

    def _run_button_scan(self):
        try:
            window_info = self.window_provider()
            if not window_info or window_info.get("platform") != "JJ":
                return
            image = self.window_image_provider(window_info)
            image_point = self.find_rematch_button_in_image(image)
            if image_point is None:
                if self._rematch_button_seen:
                    self._rematch_button_seen = False
                    self._rematch_button_click_attempts = 0
                    logger.info("绿色再来一局按钮已消失，停止续局点击")
                return

            if (
                not self.context.auto_move_enabled or
                self.context.platform != "JJ" or
                not self.can_execute()
            ):
                return

            image_height, image_width = image.shape[:2]
            window = window_info.get("region", {})
            click_point = (
                round(float(window["left"]) + image_point[0] / image_width * float(window["width"])),
                round(float(window["top"]) + image_point[1] / image_height * float(window["height"])),
            )
            if not self._rematch_button_seen:
                self._rematch_button_seen = True
                logger.info(
                    f"视觉识别到绿色再来一局按钮: image={image_point}, "
                    f"screen={click_point}"
                )
                self._notify(True, "检测到“再来一局”，正在自动续局...")
            self._rematch_button_click_attempts += 1
            if self._rematch_button_click_attempts <= 2:
                self.window_clicker(window_info, click_point)
            else:
                # 微信画布若不接受进程定向事件，连续看见按钮三次后使用
                # 已验证可用的兼容点击；仍先检查用户空闲并恢复原光标。
                self._compatibility_click_point(window_info, click_point)
        except Exception as exc:
            logger.error(f"绿色再来一局按钮自动点击失败: {exc}")
        finally:
            with self._lock:
                self._button_scan_pending = False

    def cancel_pending(self):
        with self._lock:
            self._generation += 1
            self._last_key = None
            self._button_scan_pending = False
            self._rematch_button_seen = False
            self._rematch_button_click_attempts = 0

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
            if self.delay > 0:
                self.sleeper(self.delay)
            self._ensure_current(analysis_token, generation)
            self.execute(move, is_red, analysis_token, generation)
            self._notify(True, f"已自动走子：{move}")
        except AutoMoveUserBusy as exc:
            logger.info(f"本次兼容自动走子流程已停止: {exc}")
            self._notify(
                False,
                f"本次自动走子流程已停止：{exc}；后续建议仍会继续尝试",
            )
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

        # 生产环境使用发往微信进程的后台事件，不占用鼠标，也无需等待用户空闲。
        window_key = (window_info.get("pid"), window_info.get("window_id"))
        if window_key != self._background_click_window_key:
            self._background_click_window_key = window_key
            self._background_click_supported = None

        if window_info.get("pid") and self._background_click_supported is not False:
            try:
                result = self._execute_window_move(
                    window_info,
                    checker,
                    start,
                    end,
                    start_piece,
                    start_point,
                    end_point,
                    analysis_token,
                    generation,
                )
                self._background_click_supported = True
                return result
            except AutoMoveBackgroundUnsupported as exc:
                # 同一个微信窗口无需每一步重复等待探测；窗口变化后会重置。
                self._background_click_supported = False
                logger.warning(f"后台点击未被JJ画布接受，切换兼容点击: {exc}")
        elif self._background_click_supported is False:
            logger.debug("当前JJ窗口已确认不支持后台点击，直接使用兼容点击")

        return self._execute_cursor_move(
            window_info,
            checker,
            start,
            end,
            start_piece,
            start_point,
            end_point,
            analysis_token,
            generation,
        )

    def _execute_cursor_move(
        self,
        window_info,
        checker,
        start,
        end,
        start_piece,
        start_point,
        end_point,
        analysis_token,
        generation,
    ):
        """兼容微信画布的系统点击；完成后恢复用户原光标位置。"""
        self._wait_for_user_idle(analysis_token, generation, window_info)
        controller = self.mouse_factory()
        original_position = controller.position
        last_automatic_position = None
        try:
            attempts = (
                ("完整点击", (start_point, end_point)),
                ("终点重试1", (end_point,)),
                ("终点重试2", (end_point,)),
                ("完整重试", (start_point, end_point)),
            )
            for attempt_index, (attempt_name, points) in enumerate(attempts):
                # 系统空闲时间也可能包含本程序刚发出的合成鼠标事件，不能用它
                # 判断重试期间的用户输入，否则首轮点击会被误报成用户操作。
                # 此处改为检测光标是否偏离了程序最后放置的位置。
                if (
                    attempt_index and
                    last_automatic_position is not None and
                    self._cursor_was_moved(controller.position, last_automatic_position)
                ):
                    raise AutoMoveUserBusy("检测到用户移动鼠标")
                if attempt_index and not self.target_window_active_provider(window_info):
                    raise AutoMoveUserBusy("重试前目标窗口已不在最前面")
                logger.debug(f"空闲自动走子尝试: {attempt_name}, points={points}")
                for index, point in enumerate(points):
                    self._click_point(controller, point)
                    last_automatic_position = point
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
                        f"兼容自动走子确认成功: attempt={attempt_name}, "
                        f"{start_point} -> {end_point}"
                    )
                    return start_point, end_point

            raise AutoMoveError("多次点击后仍未检测到棋子落地")
        finally:
            self.sleeper(0.15)
            controller.position = original_position

    @staticmethod
    def _cursor_was_moved(current_position, expected_position, tolerance=6):
        """判断用户是否在兼容点击的视觉确认期间移动了系统光标。"""
        try:
            return (
                abs(float(current_position[0]) - float(expected_position[0])) > tolerance or
                abs(float(current_position[1]) - float(expected_position[1])) > tolerance
            )
        except (IndexError, TypeError, ValueError):
            # 无法读取光标位置时采取保守策略，停止继续控制系统鼠标。
            return True

    def _execute_window_move(
        self,
        window_info,
        checker,
        start,
        end,
        start_piece,
        start_point,
        end_point,
        analysis_token,
        generation,
    ):
        """根据视觉反馈执行后台走子，网络快慢只影响实际完成时间。"""
        self.window_clicker(window_info, start_point)
        logger.debug(f"后台自动走子已点起点: {start_point}")

        # 以连续截图中的“抬子”状态确认进程定向点击是否被画布接受。
        selection_deadline = time.monotonic() + self.selection_observe_timeout
        lift_observed = False
        while time.monotonic() < selection_deadline:
            self._ensure_current(analysis_token, generation)
            if getattr(checker, "_pending_lift_source", None) == start:
                lift_observed = True
                break
            self.sleeper(self.action_poll_interval)

        if not lift_observed:
            raise AutoMoveBackgroundUnsupported("点击起点后未观察到抬子")

        self.window_clicker(window_info, end_point)
        logger.debug(f"后台自动走子已点终点: {end_point}")
        deadline = time.monotonic() + self.move_response_timeout
        next_retry = time.monotonic() + self.move_retry_interval

        while True:
            self._ensure_current(analysis_token, generation)
            if self._is_move_observed(checker, start, end, start_piece):
                logger.info(
                    f"后台自动走子确认成功: {start_point} -> {end_point}"
                )
                return start_point, end_point

            now = time.monotonic()
            if now >= deadline:
                raise AutoMoveError("等待棋盘确认落子超时")
            if now >= next_retry:
                # 已看到起点悬空时只补终点；否则重新完成一次起点-终点事件。
                if getattr(checker, "_pending_lift_source", None) == start:
                    logger.debug("棋子仍处于抬起状态，补点终点")
                    self.window_clicker(window_info, end_point)
                else:
                    logger.debug("尚未观察到抬子，后台重试完整走子")
                    self.window_clicker(window_info, start_point)
                    self.window_clicker(window_info, end_point)
                next_retry = now + self.move_retry_interval
            self.sleeper(self.action_poll_interval)

    def _compatibility_click_point(self, window_info, point):
        """在目标窗口前台且用户空闲时点击一点，随后恢复原光标。"""
        if not self.target_window_active_provider(window_info):
            raise AutoMoveUserBusy("JJ窗口不在最前面，暂不执行兼容点击")
        if self.user_idle_provider() < self.idle_required:
            raise AutoMoveUserBusy("用户正在操作电脑，暂不执行兼容点击")
        controller = self.mouse_factory()
        original_position = controller.position
        try:
            self._click_point(controller, point)
        finally:
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
        self.sleeper(0.08)

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
            if self._is_move_observed(checker, start, end, start_piece):
                return True
            if time.monotonic() >= deadline:
                break
            self.sleeper(self.verify_interval)
        return False

    @staticmethod
    def _is_move_observed(checker, start, end, start_piece):
        board = getattr(checker, "last_board", None)
        if not board:
            return False
        source_piece = board[start[0]][start[1]]
        destination_piece = board[end[0]][end[1]]
        return source_piece == "-" and destination_piece == start_piece

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
