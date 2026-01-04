import mss
import time
import queue
import threading  
import app.chess.processor as processor
from app.chess.message import Message, MessageType, AvatarState, TurnState
from app.chess.message_bus import message_bus
from app.chess.context import context
from app.tools.utils import app_cache_path
from app.chess.board_locator import BoardLocator, LocationError, WindowError, PieceError, CombsError
from app.chess.hash_checker import has_border, filter_stable_frame


class ChessCaptureManager:
    """象棋捕获管理器类，负责截图、发送识别"""
    
    def __init__(self):
        self.context = context
        self.manual_trigger = False  # 手动触发标志
        self.stop_event = threading.Event() # 整个截图流程的停止事件
        self.process_queue = queue.Queue()  # 存放识别任务的队列
        self.result_queue = queue.Queue()   # 存放识别和检查结果的队列
        self.worker_threads = processor.start_process_worker(
            self.process_queue, self.result_queue, self.stop_event
        )
        # 初始化棋盘定位器
        self.board_locator = BoardLocator(self.context)
        
        # 连续模式截图线程
        self.continuous_thread = None
        
        # 当前头像状态（初始默认非倒计时）
        self.avatar_states = {"upper": AvatarState.NORMAL, "lower": AvatarState.NORMAL}  
        
        # 头像监控线程引用
        self.avatar_threads = {"upper": None, "lower": None}
        
        # 订阅重试截图消息
        message_bus.subscribe(MessageType.RETRY_CAPTURE, self._on_retry_capture)
        
        # 初始定位完成事件，用于通知截图主循环
        self._located_event = threading.Event()
        
        # 监控截图线程空闲时长
        self.last_capture_time = time.time()
        self.capture_timeout = 120  # 120秒无截图自动停止

    def main_process_flow(self): 
        # 首先进行初始定位,循环尝试,直到成功
        while not self.stop_event.is_set(): 
            # 如果已有定位成功的事件（可能来自手动定位），直接跳出
            if self._located_event.is_set():
                break
            try:
                success = self.board_locator.handle_locating_board_tasks()
                if success:
                    print("初始定位成功")
                    break
            except WindowError as e:
                message_bus.publish_error(f"未检测到游戏窗口\n请确保游戏已打开")
                message_bus.publish(Message(MessageType.STOP))
            except PieceError as e:
                message_bus.publish_error(f"您似乎还没有开始对局~")
                self._located_event.wait(timeout=1.5)
            except CombsError as e:
                message_bus.publish_error(f"无法自动定位棋盘\n请确保已进入对局")
                self._located_event.wait(timeout=1.5)
            except LocationError as e:
                message_bus.publish_error(f"{e}")
                message_bus.publish(Message(MessageType.STOP))
            except Exception as e:
                message_bus.publish_error(f"{e}")   
                message_bus.publish(Message(MessageType.STOP))
        
        if self.stop_event.is_set():
            return
        
        # 重置事件，避免影响后续逻辑
        self._located_event.clear()
        
        # 定位成功后，加载配置并开始截图
        self.context.load_config()

        if self.context.analysis_mode == "timer":
            print("Debug - 倒计时截图")
            # 上方头像监控线程
            self.avatar_threads["upper"] = threading.Thread(
                target=self._monitor_single_avatar,
                args=("upper",),  # 截图参数动态获取
                daemon=True
            )
            self.avatar_threads["upper"].start()
            
            # 下方头像监控线程
            self.avatar_threads["lower"] = threading.Thread(
                target=self._monitor_single_avatar,
                args=("lower",),  # 截图参数动态获取
                daemon=True
            )
            self.avatar_threads["lower"].start()

        elif self.context.analysis_mode == "continuous":
            print("Debug - 连续截图")
            # 启动连续截图线程
            if self.continuous_thread is None or not self.continuous_thread.is_alive():
                self.continuous_thread = threading.Thread(
                    target=self._continuous_capture_worker,
                    daemon=True
                )
                self.continuous_thread.start()
        else:
            print(f"Debug - 未知的分析模式: {self.context.analysis_mode}")
        
        # 启动重试截图线程
        self.retry_queue = queue.Queue()
        self.retry_thread = threading.Thread(
            target=self._retry_capture_worker,
            daemon=True
        )
        self.retry_thread.start()
            
        # 启动窗口移动监控
        try:
            self.board_locator.monitor_window_movement(self.stop_event)
        except WindowError as e:
            message_bus.publish_error(f"未检测到游戏窗口\n请确保游戏已打开")
            message_bus.publish(Message(MessageType.STOP))
        except PieceError as e:
            message_bus.publish_error(f"未检测到象棋棋局\n请确保已开始对局")
            message_bus.publish(Message(MessageType.STOP))
        except CombsError as e:
            message_bus.publish_error(f"无法自动定位棋盘位置\n请使用手动定位")
            message_bus.publish(Message(MessageType.STOP))
        except LocationError as e:
            message_bus.publish_error(f"{e}")
            message_bus.publish(Message(MessageType.STOP))
        except Exception as e:
            message_bus.publish_error(f"{e}")   
            message_bus.publish(Message(MessageType.STOP))

    def start_capture(self):
        """开始截图任务"""
        self.stop_event.clear()  # 重置停止事件
        self.last_capture_time = time.time()  # 重置截图时间
    
    def stop_capture(self):
        """停止截图任务"""
        self.stop_event.set()
        # 停止工作线程池
        for _ in range(3):
            self.process_queue.put("STOP")
        self.result_queue.put("STOP")
        for t in self.worker_threads:
            t.join(timeout=2)

        # 停止重试线程
        if hasattr(self, 'retry_queue'):
            self.retry_queue.put("STOP")
        if hasattr(self, 'retry_thread'):
            self.retry_thread.join(timeout=2)

        # 停止棋盘定位器
        if hasattr(self, 'board_locator'):
            self.board_locator.stop()
        # 停止连续截图线程
        if self.continuous_thread is not None:
            self.continuous_thread.join(timeout=2)
            self.continuous_thread = None
        
        # 清理头像监控线程引用
        for avatar_name in ["upper", "lower"]:
            if self.avatar_threads[avatar_name] is not None:
                self.avatar_threads[avatar_name] = None
        # 取消消息订阅
        message_bus.unsubscribe(MessageType.RETRY_CAPTURE, self._on_retry_capture)

    def _check_avatar_state(self, screenshot, avatar):
        """
        用边框检测,判断头像状态
        """
        # 使用哈希波动检测替代颜色拟合法进行测试
        result, reason = has_border(screenshot, self.context.platform, avatar)
        avatar_state = AvatarState.COUNTDOWN if result else AvatarState.NORMAL
        # if avatar == "lower":
        #     print(f"[{avatar}] 哈希检测: {'计时' if result else '空闲'} - {reason}")
        return avatar_state

    def _capture_and_enqueue(self, current_turn, region, force_output=False):
        """截取棋盘区域，使用纳秒级时间戳作为排序依据"""
        capture_time = time.time_ns()
        with mss.mss() as sct:
            board_screenshot = sct.grab(region)
        
        # 使用全局函数处理截图
        stable_frame, curr_hash = filter_stable_frame(board_screenshot, "[capture]", force_output=force_output)
        
        # 如果检测到稳定帧，则入队
        if stable_frame is not None:
            self.process_queue.put((capture_time, current_turn, board_screenshot))
        
        # 更新最后截图时间
        self.last_capture_time = time.time()

    def _continuous_capture_worker(self, interval=0.2):
        """连续截图线程：每0.2秒截取一次棋盘，使用稳定帧检测，仅将稳定帧入队"""
        def get_current_board_region():
            """动态获取当前棋盘区域坐标"""
            platform = self.context.get_platform(self.context.platform)
            return platform.regions.get("board") if platform else None
        
        while not self.stop_event.is_set():
            try:
                # 动态获取当前棋盘区域
                board_region = get_current_board_region()
                if board_region is None:
                    print("警告：连续截图模式下棋盘区域未配置，跳过本次截图")
                    time.sleep(interval)
                    continue
                
                capture_time = time.time_ns()
                with mss.mss() as sct:
                    board_screenshot = sct.grab(board_region)
                
                # 使用全局函数处理截图
                stable_frame, curr_hash = filter_stable_frame(board_screenshot, "[continuous]")
                
                # 如果检测到稳定帧，则入队
                if stable_frame is not None:
                    current_turn = None # 连续模式下的轮次由 processor 结合 marker 动态推断
                    self.process_queue.put((capture_time, current_turn, board_screenshot))
                    self.last_capture_time = time.time()
                
                time.sleep(interval)
            except Exception as e:
                print(f"[continuous] 捕获异常: {e}")
                time.sleep(interval)

    def _monitor_single_avatar(self, avatar, interval=0.1):
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
        
        # 非阻塞截图时机管理
        pending_captures = []  # 待执行的截图任务 [(time, avatar_name, region), ...]

        while not self.stop_event.is_set():
            # 动态获取当前区域坐标
            avatar_region, board_region = get_current_regions()
            if avatar_region is None or board_region is None:
                print(f"警告：{avatar}头像或棋盘区域未配置，跳过本次检测")
                time.sleep(interval)
                continue
                
            with mss.mss() as sct:
                screenshot = sct.grab(avatar_region)
                # img_cv = np.frombuffer(screenshot.bgra, np.uint8).reshape(screenshot.height, screenshot.width, 4)[:, :, :3]
                # img_path = app_cache_path(f"avatar/temp_avatar_{avatar}.png")
                # cv2.imwrite(img_path, img_cv)

            last_state = self.avatar_states[avatar]    
            curr_state = self._check_avatar_state(screenshot, avatar)
            
            # 截图信号1: 亮
            shot_signal1 = (last_state != AvatarState.COUNTDOWN and curr_state == AvatarState.COUNTDOWN)
            # 截图信号2: 灭
            shot_signal2 = (last_state == AvatarState.COUNTDOWN and curr_state == AvatarState.NORMAL)
            # 一方出现了稳定画面,截图分析;此时该另一方走棋.
            for_thisSide = TurnState.OUR_SIDE if avatar == "upper" else TurnState.OPPONENT 
            for_opponent = TurnState.OUR_SIDE if avatar == "lower" else TurnState.OPPONENT

            current_time = time.time()
            if self.context.platform == "JJ":
                if shot_signal1:
                    # 此方刚亮,可截到对方刚走完棋并已稳定的画面
                    pending_captures.append((current_time, for_opponent, board_region))
                    # 此方亮后0.8秒,如果对方上一步有动画,此时动画刚好结束,可截到对方刚走完棋并已稳定的画面
                    pending_captures.append((current_time + 0.8, for_opponent, board_region))
                # elif shot_signal2:
                #     # 此方灭后0.5秒,可截到此方刚走完棋并已稳定的画面
                #     pending_captures.append((current_time + 0.5, for_thisSide, board_region))

            elif self.context.platform == "TT":
                if shot_signal1:
                    # 安排0.34秒后的第一次截图
                    pending_captures.append((current_time + 0.34, for_thisSide, board_region))
                    # 安排1.84秒后的第二次截图（0.34 + 1.5）
                    pending_captures.append((current_time + 1.84, for_thisSide, board_region))
                    last_state = curr_state
                else:
                    last_state = curr_state  
            else:
                raise ValueError(f"不支持的平台: {self.context.platform}")
            
            # 检查是否有待执行的截图任务
            current_pending = []
            for capture_time, pending_turn, region in pending_captures:
                if time.time() >= capture_time:
                    # 执行截图时重新计算turn信息
                    self._capture_and_enqueue(pending_turn, region)
                else:
                    current_pending.append((capture_time, pending_turn, region))
            pending_captures = current_pending

            # 记录头像状态
            self.avatar_states[avatar] = curr_state

            # 检查是否超过120秒没有截图
            if time.time() - self.last_capture_time > self.capture_timeout:
                print(f"[avatar_monitor] 超过{self.capture_timeout}秒无截图，自动停止监控")
                message_bus.publish(Message(MessageType.STOP))
                break
            
            time.sleep(interval)
            
    def _on_retry_capture(self, message):
        """
        处理重试截图消息
        Args:
            message: 重试截图消息
        """
        if message.type == MessageType.RETRY_CAPTURE:
            # 将重试任务放入队列
            if hasattr(self, 'retry_queue'):
                # print("Debug - 收到重试截图请求，安排重新截图")
                self.retry_queue.put(message)
            else:
                print("警告：重试队列不存在，无法处理重试截图")
                
    def _retry_capture_worker(self):
        """专门的重试截图线程"""
        while True:
            if self.stop_event.is_set():
                break
            try:
                retry_data = self.retry_queue.get(timeout=0.1)
                if retry_data == "STOP":
                    break
                elif retry_data.type == MessageType.RETRY_CAPTURE:
                    # 延时1秒，等待棋盘画面稳定
                    time.sleep(1)
                    # 执行重试截图
                    self._execute_retry_capture()
                self.retry_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"重试线程出错: {e}")
    
    def _execute_retry_capture(self):
        """执行重试截图"""
        # 获取当前棋盘区域
        platform = self.context.get_platform(self.context.platform)
        board_region = platform.regions.get("board") if platform else None
        
        if board_region is None:
            print("警告：棋盘区域未配置，无法重试截图")
            return
        
        # 获取当前轮次（根据头像状态判断）
        current_turn = None
        if self.avatar_states.get("lower") == AvatarState.COUNTDOWN:
            current_turn = TurnState.OUR_SIDE
        elif self.avatar_states.get("upper") == AvatarState.COUNTDOWN:
            current_turn = TurnState.OPPONENT
        else:
            current_turn = TurnState.OUR_SIDE
        
        print(f"执行重试截图任务，轮次: {current_turn}")
        self._capture_and_enqueue(current_turn, board_region, force_output=True)
    
    def manually_capture_once(self):
        """
        执行一次完整的监控与截图流程
        从外界调用，执行一次头像监控、状态检测和截图任务
        Returns:
            bool: 是否成功执行截图任务
        """
        try:
            # 手动刷新时，重置检查器状态
            self.context.reset_checker()
            print("Debug - 手动刷新，重置检查器状态")
            
            # 获取当前平台配置
            platform = self.context.get_platform(self.context.platform)
            avatar_upper = platform.regions.get("avatar_upper")
            avatar_lower = platform.regions.get("avatar_lower")
            board_region = platform.regions.get("board")
            
            if avatar_upper is None or avatar_lower is None or board_region is None:
                print("头像或棋盘区域未配置")
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
            TurnState or None: 轮次状态 (TurnState.OUR_SIDE, TurnState.OPPONENT) 或 None
        """
        # 手动触发优先
        if self.manual_trigger:
            self.manual_trigger = False
            print("手动触发识别")
            return TurnState.OUR_SIDE
        
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
                    return TurnState.OUR_SIDE
                elif upper_border:
                    return TurnState.OPPONENT
                    
            except Exception as color_e:
                print(f"单次检测边框检测失败: {color_e}")
        
        return None