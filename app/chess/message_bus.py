"""
全局消息总线模块

提供统一的消息发布/订阅机制，避免在各个模块间传递ui_message_queue
"""
import queue
import threading
from typing import Callable, Dict
from app.chess.message import Message, MessageType
from app.tools.log_config import get_logger


logger = get_logger(__name__)


class MessageBus:
    """全局消息总线"""
    
    def __init__(self):
        self._subscribers: Dict[MessageType, list] = {}
        self._lock = threading.Lock()
        self._ui_queue = None
        self._telemetry_lock = threading.Lock()
        self._latest_engine_info = None
    
    def set_ui_queue(self, ui_queue: queue.Queue):
        """设置UI消息队列"""
        self._ui_queue = ui_queue
        with self._telemetry_lock:
            self._latest_engine_info = None
    
    def publish(self, message: Message):
        """发布消息"""
        # ENGINE_INFO is high-frequency, replaceable telemetry.  Putting every
        # search update into the FIFO used by turn changes and MOVE_CODE can
        # delay an instant reply by tens of seconds.  Keep only the freshest
        # sample and let the UI consume it once per paint cycle.
        if message.type == MessageType.ENGINE_INFO:
            with self._telemetry_lock:
                self._latest_engine_info = message
        elif self._ui_queue:
            try:
                self._ui_queue.put_nowait(message)
            except queue.Full:
                # 普通消息淘汰最旧消息后立即投递，后台线程不会被UI反压。
                try:
                    self._ui_queue.get_nowait()
                    self._ui_queue.task_done()
                    self._ui_queue.put_nowait(message)
                except (queue.Empty, queue.Full):
                    pass
        
        # 同时通知订阅者
        with self._lock:
            subscribers = list(self._subscribers.get(message.type, []))
        for callback in subscribers:
            try:
                callback(message)
            except Exception as e:
                logger.exception("消息订阅者回调失败")

    def take_latest_engine_info(self):
        """原子取走最新引擎遥测；中间样本没有控制语义，可安全合并。"""
        with self._telemetry_lock:
            message = self._latest_engine_info
            self._latest_engine_info = None
            return message
    
    def subscribe(self, message_type: MessageType, callback: Callable[[Message], None]):
        """订阅特定类型的消息"""
        with self._lock:
            if message_type not in self._subscribers:
                self._subscribers[message_type] = []
            self._subscribers[message_type].append(callback)
    
    def unsubscribe(self, message_type: MessageType, callback: Callable[[Message], None]):
        """取消订阅"""
        with self._lock:
            if message_type in self._subscribers:
                try:
                    self._subscribers[message_type].remove(callback)
                except ValueError:
                    pass
    
    def publish_status(self, content: str):
        """发布状态消息的便捷方法"""
        self.publish(Message(MessageType.STATUS, content))
    
    def publish_error(self, content: str):
        """发布错误消息的便捷方法"""
        self.publish(Message(MessageType.ERROR, content))


# 全局消息总线实例
message_bus = MessageBus()
