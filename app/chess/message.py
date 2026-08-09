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
    STOP = auto()           # 停止消息
    RETRY_CAPTURE = auto()  # 重试截图消息
    NON_GAME_SCREEN = auto()  # 非棋局画面（结算画面等）
    PARAM_UPDATE = auto()     # 引擎动态参数显示更新
    ENGINE_INFO = auto()      # 引擎实时局势/搜索遥测



class AvatarState(Enum):
    """头像状态枚举"""
    COUNTDOWN = 1           # 倒计时状态（亮）
    NORMAL = 0              # 正常状态（灭）


class TurnState(Enum):
    """轮次状态枚举"""
    OUR_SIDE = 1       # 我方回合
    OPPONENT = 0       # 对方回合
    MANUAL = 2         # 手动强制分析


class Platform(Enum):
    """平台枚举"""
    JJ = 1                  # 天天象棋
    TT = 0                  # 腾讯象棋

class Message:
    """消息类"""
    def __init__(self, type: MessageType, content=None, **kwargs):
        self.type = type
        self.content = content
        self.kwargs = kwargs 

class MessageContent:
    """统一管理所有消息内容"""
    # 状态消息
    WAITING = "等待获取游戏..."
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
    
    # 非棋局画面
    NON_GAME_SCREEN = "等待对弈开始..."
