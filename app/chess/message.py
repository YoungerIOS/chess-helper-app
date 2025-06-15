from enum import Enum, auto

class MessageType(Enum):
    """消息类型枚举"""
    CHANGE = auto()         # 局面变化消息
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
    MY_TURN = "轮到我方走棋..."
    ANIMATION_COVERED = "检测到动画遮挡，等待1秒..."
    POSITIONING = "将光标移到棋盘左上角，<br>点击鼠标左键或按S键确认"
    POSITION_COMPLETE = "定位完成!"
    
    # 错误消息
    RECOGNITION_FAILED = "识别失败，请重试"
    ENGINE_ERROR = "引擎错误，请重试" 