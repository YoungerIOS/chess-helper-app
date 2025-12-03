"""
全局消息总线模块

提供统一的消息发布/订阅机制，避免在各个模块间传递ui_message_queue
"""
import queue
import threading
from typing import Callable, Any, Dict
from app.chess.message import Message, MessageType


class MessageBus:
    """全局消息总线"""
    
    def __init__(self):
        self._subscribers: Dict[MessageType, list] = {}
        self._lock = threading.Lock()
        self._ui_queue = None
    
    def set_ui_queue(self, ui_queue: queue.Queue):
        """设置UI消息队列"""
        self._ui_queue = ui_queue
    
    def publish(self, message: Message):
        """发布消息"""
        if self._ui_queue:
            self._ui_queue.put(message)
        
        # 同时通知订阅者
        with self._lock:
            subscribers = self._subscribers.get(message.type, [])
            for callback in subscribers:
                try:
                    callback(message)
                except Exception as e:
                    print(f"消息订阅者回调失败: {e}")
    
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
