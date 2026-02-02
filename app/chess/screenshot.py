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
        
        # 取消消息订阅
        message_bus.unsubscribe(MessageType.RETRY_CAPTURE, self._on_retry_capture)

    def _capture_and_enqueue(self, region, force_output=False):
        """
        截取棋盘区域，使用纳秒级时间戳作为排序依据
        Returns:
            bool: 是否成功入队
        """
        capture_time = time.time_ns()
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
                
                capture_time = time.time_ns()
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
                    time.sleep(0.6)
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
            # 1. 停止引擎当前活动
            self.context.get_engine()._send_command('stop')
            
            # 2. 彻底重置所有状态
            self.context.reset_checker()
            self.context.history.clear()
            self.context.base_fen = None # 显式清除锚点
            print("Debug - 手动刷新 (Hard Reset): History, BaseFen, Checker Cleared.")
            
            # 3. 复用重试截图逻辑（自动检测头像状态并强制截图）
            if self._execute_retry_capture('手动刷新重置'):
                 return True
            return False
                
        except Exception as e:
            print(f"执行单次截图流程失败: {e}")
            return False
    