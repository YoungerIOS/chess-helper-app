import mss
import time
import queue
import threading  
import app.chess.processor as processor
from app.chess.message import Message, MessageType, TurnState
from app.chess.message_bus import message_bus
from app.chess.context import context
from app.tools.utils import app_cache_path
from app.tools.log_config import get_logger
from app.chess.board_locator import BoardLocator, LocationError, WindowError, PieceError, CombsError
from app.chess.hash_checker import filter_stable_frame

logger = get_logger(__name__)


class ChessCaptureManager:
    """象棋捕获管理器类，负责截图、发送识别"""

    def __init__(self):
        self.context = context
        self.manual_trigger = False  # 手动触发标志
        self.stop_event = threading.Event() # 整个截图流程的停止事件
        self._stop_lock = threading.Lock()
        self._stopped_event = threading.Event()
        self.process_queue = queue.Queue()  # 存放识别任务的队列
        self.result_queue = queue.Queue()   # 存放识别和检查结果的队列
        self.worker_threads = processor.start_process_worker(
            self.process_queue, self.result_queue, self.stop_event
        )
        # 初始化棋盘定位器
        self.board_locator = BoardLocator(self.context)
        
        # 连续模式截图线程
        self.continuous_thread = None
        
        # 订阅重试截图消息
        message_bus.subscribe(MessageType.RETRY_CAPTURE, self._on_retry_capture)
        
        # 初始定位完成事件，用于通知截图主循环
        self._located_event = threading.Event()
        
        # 监控截图线程空闲时长
        self.last_capture_time = time.time()
        self.capture_timeout = 120  # 120秒无截图自动停止
        
        # 初始化重试队列 
        self.retry_queue = queue.Queue()

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
        # 定位成功后，加载配置并开始截图
        self.context.load_config()

        # 默认使用连续截图模式
        print("Debug - 启动连续截图模式")
        # 启动连续截图线程
        if self.continuous_thread is None or not self.continuous_thread.is_alive():
            self.continuous_thread = threading.Thread(
                target=self._continuous_capture_worker,
                daemon=True
            )
            self.continuous_thread.start()
        
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

    def stop_capture(self, timeout=1.0):
        """停止截图任务，所有线程共享一个总等待时间。"""
        if self._stopped_event.is_set():
            return
        with self._stop_lock:
            if self._stopped_event.is_set():
                return

            self.stop_event.set()
            if hasattr(self, 'board_locator'):
                self.board_locator.stop()

            # 先同时唤醒所有可能阻塞的消费者，再统一等待；不能给每个线程
            # 单独等待2秒，否则4个worker会让关闭时间线性累加。
            for _ in range(2):
                self.process_queue.put("STOP")
            self.result_queue.put("STOP")
            if hasattr(self, 'retry_queue'):
                self.retry_queue.put("STOP")

            deadline = time.monotonic() + max(0.0, float(timeout))
            threads = list(getattr(self, 'worker_threads', []))
            retry_thread = getattr(self, 'retry_thread', None)
            if retry_thread is not None:
                threads.append(retry_thread)
            if self.continuous_thread is not None:
                threads.append(self.continuous_thread)

            for thread in threads:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                if thread is not threading.current_thread():
                    thread.join(timeout=remaining)

            self.continuous_thread = None
            message_bus.unsubscribe(MessageType.RETRY_CAPTURE, self._on_retry_capture)
            self._stopped_event.set()

    def _capture_and_enqueue(self, region, force_output=False):
        """
        截取棋盘区域，使用与重试丢帧基准一致的秒级时间戳排序
        Returns:
            bool: 是否成功入队
        """
        capture_time = time.time()
        with mss.mss() as sct:
            board_screenshot = sct.grab(region)
        
        # 使用全局函数处理截图
        stable_frame, curr_hash = filter_stable_frame(board_screenshot, "[capture]", force_output=force_output)
        
        # 如果检测到稳定帧，则入队
        if stable_frame is not None:
            self.process_queue.put((capture_time, board_screenshot))
            # 更新最后截图时间
            self.last_capture_time = time.time()
            return True
        
        return False

    def _continuous_capture_worker(self, interval=0.18):
        """连续截图线程：每0.18秒截取一次棋盘，使用稳定帧检测，仅将稳定帧入队"""
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
                
                capture_time = time.time()
                with mss.mss() as sct:
                    board_screenshot = sct.grab(board_region)
                
                # 使用全局函数处理截图
                stable_frame, curr_hash = filter_stable_frame(board_screenshot, "[continuous]")
                
                # 如果检测到稳定帧，则入队
                if stable_frame is not None:
                    # current_turn = None # 连续模式下的轮次由 processor 结合 marker 动态推断
                    self.process_queue.put((capture_time, board_screenshot))
                    self.last_capture_time = time.time()
                
                time.sleep(interval)
            except Exception as e:
                print(f"[continuous] 捕获异常: {e}")
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
                    # 延时0.3秒，等待棋盘画面稳定
                    if self.stop_event.wait(timeout=0.6):
                        self.retry_queue.task_done()
                        break
                    # 执行重试截图
                    self._execute_retry_capture(retry_data.content)
                self.retry_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"重试线程出错: {e}")

    def _execute_retry_capture(self, reason):
        """执行重试截图"""
        # 获取当前棋盘区域
        platform = self.context.get_platform(self.context.platform)
        board_region = platform.regions.get("board") if platform else None
        
        if board_region is None:
            print("警告：棋盘区域未配置，无法重试截图")
            return False
        
        # 不再依赖头像状态，直接截图，由Processor根据标记判断轮次
        print(f"执行重试截图任务,理由:--- ({reason})")
        return self._capture_and_enqueue(board_region, force_output=True)
    
    def manually_capture_once(self):
        """
        执行一次完整的监控与截图流程，模拟重试逻辑
        """
        try:
            # 1. 停止并废弃当前分析，保证刷新前的结果不会覆盖新截图。
            self.context.invalidate_analysis()
            engine = self.context.get_engine()
            if engine is not None:
                engine._send_command('stop')

            if self.context.game_variant == "jieqi":
                # 揭棋无法从一张中局截图恢复全部暗子身份，因此刷新只能
                # 重做视觉推理，绝不能清空已积累的暗子状态与带后缀历史。
                self.context.reset_recognizer()
                checker = self.context.get_checker()
                if checker is not None:
                    checker.consecutive_drops = 0
                    checker.consecutive_mismatches = 0
                self.context.discard_before_timestamp = time.time()
                print("Debug - 揭棋软刷新: 保留 History/BaseFen/Checker，仅重置视觉缓存。")
                reason = '揭棋软刷新（保留历史）'
            else:
                # 普通象棋可从当前完整局面FEN重新建立状态，维持原硬刷新语义。
                self.context.reset_checker()
                self.context.history.clear()
                self.context.base_fen = None
                self.context.reset_recognizer()
                print("Debug - 手动刷新 (Hard Reset): History, BaseFen, Checker Cleared.")
                reason = '手动刷新重置'
            
            # 3. 复用重试截图逻辑（自动检测头像状态并强制截图）
            if self._execute_retry_capture(reason):
                 return True
            return False
                
        except Exception as e:
            print(f"执行单次截图流程失败: {e}")
            return False
