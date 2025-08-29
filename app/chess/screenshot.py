import mss
import time
import cv2
import numpy as np
import queue
import threading  
import chess.processor as processor
from chess.message import Message, MessageType, MessageContent
from chess.context import context
from tools.utils import resource_path
from chess.board_locator import BoardLocator, BoardLocatorError
from chess.border_detector import has_border, reset_border_cache


class ChessCaptureManager:
    """象棋捕获管理器类，负责截图、发送识别"""
    
    def __init__(self, ui_message_queue):
        self.context = context
        self.manual_trigger = False  # 手动触发标志
        self.max_contour = None  # 用于存储倒计时区域检测到的最大轮廓
        self.process_queue = queue.Queue()  # 新增：识别任务队列
        self.result_queue = queue.Queue()  # 新增：识别和检查结果队列
        self.stop_event = threading.Event()
        self.worker_threads = processor.start_process_worker(
            self.process_queue, self.result_queue, ui_message_queue, self.stop_event
        )
        # 初始化棋盘定位器
        self.board_locator = BoardLocator(self.context)
        self.ui_message_queue = ui_message_queue # 新增：UI消息队列
        
        # 头像状态监测相关变量
        self.avatar_states = {"upper": "unknown", "lower": "unknown"}  # 当前头像状态
        
        # 定位状态标志
        self._relocating = False
        self._relocate_lock = threading.Lock()
        
        # 头像监控线程引用
        self.avatar_threads = {"upper": None, "lower": None}
        
        # 订阅重新定位消息
        self.context.subscribe("relocate_board", self.try_locate_board)
        
        # 保存最近一次手动定位坐标，使手动定位结果可被后续自动调用复用
        self._manual_coords = None
        
        # 初始定位完成事件，用于通知截图主循环
        self._located_event = threading.Event()

    def try_locate_board(self, message_type=None, data=None, manual_coords=None):
        """
        尝试定位棋盘，处理各种异常情况
        Args:
            message_type: 消息类型（回调时使用）
            data: 消息数据（回调时使用）
            manual_coords: 手动定位坐标 (x, y)，自动定位时为 None
        Returns:
            bool: 是否成功定位棋盘
        """
        # 检查是否正在定位中
        with self._relocate_lock:
            if self._relocating:
                print("定位正在进行中，跳过重复请求")
                return False
            self._relocating = True
        
        try:
            # 如果是作为回调函数被调用，打印消息信息
            if message_type is not None:
                print(f"收到重新定位请求: {message_type} = {data}")
                
            # 优先使用本次传入的手动坐标；未提供时复用最近一次手动坐标
            if manual_coords is not None:
                self._manual_coords = manual_coords
            coords_to_use = manual_coords if manual_coords is not None else self._manual_coords

            if coords_to_use is not None:
                # 使用手动坐标更新棋盘和头像区域
                self.board_locator.update_board_and_avatars_regions(manual_coords=coords_to_use)
                print("棋盘定位成功(手动/复用手动)")
            else:
                # 使用自动检测更新棋盘和头像区域
                self.board_locator.update_board_and_avatars_regions(manual_coords=None)
                print("棋盘定位成功(自动)")
            
            # 发送成功消息到UI队列
            self.ui_message_queue.put(Message(MessageType.STATUS, "棋盘定位成功"))
            # 设置定位成功事件（唤醒等待）
            self._located_event.set()
            return True
        except BoardLocatorError as e:
            print(f"棋盘定位失败: {e}")
            # 发送失败消息到UI队列
            self.ui_message_queue.put(Message(MessageType.STATUS, f"{e}"))
            return False
        except Exception as e:
            print(f"棋盘定位时发生未知错误: {e}")
            # 发送错误消息到UI队列
            self.ui_message_queue.put(Message(MessageType.STATUS, f"棋盘定位错误: {e}"))
            return False
        finally:
            # 重置定位状态
            with self._relocate_lock:
                self._relocating = False

    def start_capture(self):
        """开始截图任务"""
        self.stop_event.clear()  # 重置停止事件

    def stop_capture(self):
        """停止截图任务"""
        self.stop_event.set()
        # 停止工作线程池
        for _ in range(3):
            self.process_queue.put("STOP")
        self.result_queue.put("STOP")
        for t in self.worker_threads:
            t.join(timeout=2)
        # 停止棋盘定位器
        if hasattr(self, 'board_locator'):
            self.board_locator.stop()
        # 清理头像监控线程引用
        for avatar_name in ["upper", "lower"]:
            if self.avatar_threads[avatar_name] is not None:
                self.avatar_threads[avatar_name] = None
        # 取消订阅
        self.context.unsubscribe("relocate_board", self.try_locate_board)

    def capture_region(self): 
        # 首先进行初始定位,循环尝试,直到成功
        print("开始初始定位...")
        while not self.stop_event.is_set(): 
            # 如果已有定位成功的事件（可能来自手动定位），直接跳出
            if self._located_event.is_set():
                break
            if self.try_locate_board():
                print("初始定位成功")
                break
            else:
                print("初始定位失败，1秒后重试")
                # 等待1秒，若期间手动定位成功会立即唤醒
                self._located_event.wait(timeout=1)
        
        if self.stop_event.is_set():
            return
        
        # 重置事件，避免影响后续逻辑
        self._located_event.clear()
        
        # 定位成功后，加载配置并开始截图
        self.context.load_config()
        platform = self.context.get_platform(self.context.platform)

        if self.context.analysis_mode == "continuous":
            print("Debug - 连续截图")

        elif self.context.analysis_mode == "timer":
            print("Debug - 倒计时截图")
            # 启动上方头像监控线程
            self.avatar_threads["upper"] = threading.Thread(
                target=self._monitor_single_avatar,
                args=("upper",),  # 截图参数会被动态获取
                daemon=True
            )
            self.avatar_threads["upper"].start()
            
            # 启动下方头像监控线程
            self.avatar_threads["lower"] = threading.Thread(
                target=self._monitor_single_avatar,
                args=("lower",),  # 截图参数会被动态获取
                daemon=True
            )
            self.avatar_threads["lower"].start()
            
            # 窗口移动监控初始化
            last_window_info = self.board_locator.find_game_window(self.context.platform)
            last_window_bounds = last_window_info['region'] if last_window_info else None
            check_interval_s = 2
            next_check_time = time.monotonic()
            move_threshold = 2  # 像素阈值
            # 持续监控窗口移动, 用dx dy 推算出新的棋盘左上角坐标
            while not self.stop_event.is_set():
                now = time.monotonic()
                if now >= next_check_time:
                    next_check_time = now + check_interval_s
                    try:
                        win_info = self.board_locator.find_game_window(self.context.platform)
                        if win_info and 'region' in win_info:
                            current_bounds = win_info['region']
                            if last_window_bounds is not None:
                                dx = int(current_bounds['left']) - int(last_window_bounds['left'])
                                dy = int(current_bounds['top']) - int(last_window_bounds['top'])
                                if abs(dx) >= move_threshold or abs(dy) >= move_threshold:
                                    platform = self.context.get_platform(self.context.platform)
                                    board_region = platform.regions.get('board')
                                    if board_region is not None:
                                        new_top_left = (int(board_region['left']) + dx, int(board_region['top']) + dy)
                                        success = self.try_locate_board(manual_coords=new_top_left)
                                        if success:
                                            # 窗口位置发生有效移动后，重置边框缓存
                                            reset_border_cache(self.context.platform)
                                            last_window_bounds = current_bounds
                            else:
                                last_window_bounds = current_bounds
                    except Exception as e:
                        print(f"窗口移动检测异常: {e}")
                time.sleep(0.1)
            return
        else:
            print(f"Debug - 未知的分析模式: {self.context.analysis_mode}")

    def _check_avatar_state(self, screenshot, avatar):
        """
        用边框检测,判断头像状态
        """
        color_state = 'countdown' if has_border(screenshot, self.context.platform, avatar) else 'normal'
        return color_state

    def _capture_and_enqueue(self, current_turn, region):
        """截取棋盘区域，使用纳秒级时间戳作为排序依据"""
        capture_time = time.time_ns()
        with mss.mss() as sct:
            board_screenshot = sct.grab(region)
        self.process_queue.put((capture_time, current_turn, board_screenshot))

    def _monitor_single_avatar(self, avatar, interval=0.1):
        def get_turn(avatar_name, avatar_state):
            if avatar_state == 'countdown':
                return 'my_turn' if avatar_name == 'lower' else 'opponent_turn'
            elif avatar_state == 'normal':
                return 'opponent_turn' if avatar_name == 'lower' else 'my_turn'
            else:
                return None
        
        def get_current_regions():
            """动态获取当前区域坐标"""
            # 不重新加载配置，直接获取当前配置
            platform = self.context.get_platform(self.context.platform)
            return (
                platform.regions.get(f"avatar_{avatar}"),
                platform.regions.get("board")
            )
        
        # 获取初始区域坐标
        avatar_region, board_region = get_current_regions()
        if avatar_region is None or board_region is None:
            print(f"警告：{avatar}头像或棋盘区域未配置")
            return
        
        with mss.mss() as sct:
            screenshot = sct.grab(avatar_region)

        last_state = self._check_avatar_state(screenshot, avatar)
        print(f"初始化{avatar}: {last_state}")
        
        # 非阻塞截图时机管理
        pending_captures = []  # 待执行的截图任务 [(time, avatar_name, region), ...]
        
        # 如果一开始就有倒计时状态，立即触发一次识别
        if last_state == 'countdown':
            print(f"{avatar} 初始为亮，立即触发识别")
            self._capture_and_enqueue(get_turn(avatar, last_state), board_region)

        while not self.stop_event.is_set():
            current_time = time.time()
            
            # 检查是否有待执行的截图任务
            current_pending = []
            for capture_time, pending_avatar, region in pending_captures:
                if current_time >= capture_time:
                    # 执行截图时重新计算turn信息
                    current_turn = get_turn(pending_avatar, self.avatar_states[pending_avatar])
                    self._capture_and_enqueue(current_turn, region)
                else:
                    current_pending.append((capture_time, pending_avatar, region))
            pending_captures = current_pending
            
            # 动态获取当前区域坐标
            avatar_region, board_region = get_current_regions()
            if avatar_region is None or board_region is None:
                print(f"警告：{avatar}头像或棋盘区域未配置，跳过本次检测")
                time.sleep(interval)
                continue
                
            with mss.mss() as sct:
                screenshot = sct.grab(avatar_region)
                img_cv = np.frombuffer(screenshot.bgra, np.uint8).reshape(screenshot.height, screenshot.width, 4)[:, :, :3]
                img_path = f"app/images/board/temp_avatar_{avatar}.png"
                cv2.imwrite(img_path, img_cv)
                
            state = self._check_avatar_state(screenshot, avatar)
            # 记录头像状态
            self.avatar_states[avatar] = state
            
            # 截图信号1: 灭->亮
            shot_signal1 = (last_state != 'countdown' and state == 'countdown')
            # 截图信号2: 亮->灭
            shot_signal2 = (last_state == 'countdown' and state == 'normal')

            if self.context.platform == "JJ":
                if shot_signal1:
                    # 立即执行第一次截图
                    self._capture_and_enqueue(get_turn(avatar, state), board_region)
                    # 安排0.8秒后的第二次截图
                    pending_captures.append((current_time + 0.8, avatar, board_region))
                    last_state = state
                elif shot_signal2:
                    # 安排0.5秒后的截图
                    pending_captures.append((current_time + 0.5, avatar, board_region))
                    last_state = state
                else:
                    last_state = state

            elif self.context.platform == "TT":
                if shot_signal1:
                    # 安排0.34秒后的第一次截图
                    pending_captures.append((current_time + 0.34, avatar, board_region))
                    # 安排1.84秒后的第二次截图（0.34 + 1.5）
                    pending_captures.append((current_time + 1.84, avatar, board_region))
                    last_state = state
                else:
                    last_state = state
            else:
                raise ValueError(f"不支持的平台: {self.context.platform}")

            time.sleep(interval)
            
    def manually_capture_once(self):
        """
        执行一次完整的监控与截图流程
        从外界调用，执行一次头像监控、状态检测和截图任务
        Returns:
            bool: 是否成功执行截图任务
        """
        try:
            # 手动刷新时，重置检查器状态
            if hasattr(self.context, 'checker') and self.context.checker:
                self.context.checker.reset_state()
                print("Debug - 手动刷新，重置检查器状态")
            
            # 获取当前平台配置
            platform = self.context.get_platform(self.context.platform)
            avatar_upper = platform.regions.get("avatar_upper")
            avatar_lower = platform.regions.get("avatar_lower")
            board_region = platform.regions.get("board")
            
            if avatar_upper is None or avatar_lower is None or board_region is None:
                print("警告: 头像或棋盘区域未配置")
                return False
            
            # 执行一次头像状态检测
            current_turn = self._check_turn_state_once(avatar_upper, avatar_lower)
            
            if current_turn is not None:
                # 执行截图任务
                self._capture_and_enqueue(current_turn, board_region)
                print(f"执行单次截图任务完成，轮次: {current_turn}")
                return True
            else:
                print("当前状态无需截图")
                return False
                
        except Exception as e:
            print(f"执行单次截图流程失败: {e}")
            return False
    
    def _check_turn_state_once(self, avatar_upper, avatar_lower):
        """
        检查单次轮次状态
        Args:
            avatar_upper: 上方头像区域
            avatar_lower: 下方头像区域
        Returns:
            str or None: 轮次状态 ('my_turn', 'opponent_turn') 或 None
        """
        # 手动触发优先
        if self.manual_trigger:
            self.manual_trigger = False
            print("手动触发识别")
            return 'my_turn'
        
        # 分别截取上下头像区域
        with mss.mss() as sct:
            # 截取上方头像
            upper_screenshot = sct.grab(avatar_upper)
            
            # 截取下方头像
            lower_screenshot = sct.grab(avatar_lower)
            
            # 使用边框检测
            try:
                upper_border = has_border(upper_screenshot, self.context.platform, "upper")
                lower_border = has_border(lower_screenshot, self.context.platform, "lower")
                
                print(f"单次检测 - upper头像倒计时: {upper_border}")
                print(f"单次检测 - lower头像倒计时: {lower_border}")
                
                # 统一判断逻辑：下方头像倒计时表示轮到我方
                if lower_border:
                    return 'my_turn'
                elif upper_border:
                    return 'opponent_turn'
                    
            except Exception as color_e:
                print(f"单次检测边框检测失败: {color_e}")
        
        return None