from enum import Enum, auto
import threading

class MessageType(Enum):
    """消息类型枚举"""
    CHANGE = auto()         # 局面变化消息
    PIECES = auto()         # 棋子位置消息
    MOVE_CODE = auto()      # 着法代码消息
    MOVE_TEXT = auto()      # 着法文本消息
    STATUS = auto()         # 状态消息
    ERROR = auto()          # 错误消息

class Message:
    """消息类"""
    def __init__(self, type: MessageType, content, **kwargs):
        self.type = type
        self.content = content
        self.kwargs = kwargs 

class MessageContent:
    """统一管理所有消息内容"""
    # 状态消息
    WAITING = "等待获取棋局..."
    RECOGNIZING = "正在识别局面..."
    MY_TURN = "轮到我方走棋"
    MY_MOVING = "我方思考中..."
    OPPONENT_TURN = "轮到对方走棋"
    OPPONENT_MOVING = "对方思考中..."
    ENGINE_THINKING = "引擎正在计算..."

    ANIMATION_COVERED = "检测到动画遮挡，等待1秒..."
    POSITIONING = "将光标移到棋盘左上角，<br>点击鼠标左键或按S键确认"
    POSITION_COMPLETE = "定位完成!"
    
    # 错误消息
    RECOGNITION_FAILED = "识别失败，请重试"
    ENGINE_ERROR = "引擎错误，请重试" 

# 事件驱动的消息管理器
class MessageManager:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._callbacks = {}  # 消息类型 -> 回调函数列表
            self._state_lock = threading.Lock()
            self._initialized = True
    
    def subscribe(self, message_type, callback):
        """订阅消息"""
        with self._state_lock:
            if message_type not in self._callbacks:
                self._callbacks[message_type] = []
            self._callbacks[message_type].append(callback)
    
    def unsubscribe(self, message_type, callback):
        """取消订阅"""
        with self._state_lock:
            if message_type in self._callbacks and callback in self._callbacks[message_type]:
                self._callbacks[message_type].remove(callback)
    
    def send_message(self, message_type, data=None):
        """发送消息并立即通知所有订阅者"""
        with self._state_lock:
            if message_type in self._callbacks:
                callbacks = self._callbacks[message_type].copy()  # 复制避免回调中修改列表
                # 异步执行回调，避免阻塞
                for callback in callbacks:
                    try:
                        callback(message_type, data)
                    except Exception as e:
                        print(f"回调执行错误: {e}")

    def get_subscribers(self, message_type):
        """获取指定消息类型的订阅者数量"""
        with self._state_lock:
            return len(self._callbacks.get(message_type, []))


# 全局实例
message_manager = MessageManager() 