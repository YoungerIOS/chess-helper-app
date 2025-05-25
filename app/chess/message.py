from enum import Enum, auto

class MessageType(Enum):
    """消息类型枚举"""
    BOARD_DISPLAY = auto()  # 棋局显示消息
    MOVE_CODE = auto()      # 着法代码消息
    MOVE_TEXT = auto()      # 着法文本消息
    STATUS = auto()         # 状态消息

class Message:
    """消息类"""
    def __init__(self, type: MessageType, content, **kwargs):
        self.type = type
        self.content = content
        self.kwargs = kwargs 