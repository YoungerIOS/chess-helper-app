import os
import queue
import threading
import sys
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QApplication, QMenu, QGraphicsDropShadowEffect)
from PySide6.QtCore import Qt, QSize, QPoint, QTimer, QEvent, QObject, Signal
from PySide6.QtGui import QFont, QKeyEvent, QCursor, QPixmap, QIcon, QColor, QPainter, QPainterPath, QPen
from pynput import mouse
from app.tools.utils import resource_path, get_local_ip
from app.tools.log_config import get_logger
from app.chess.screenshot import ChessCaptureManager
from app.chess.board_locator import BoardLocator
from app.chess.engine import ChessEngine
from app.chess.checker import PositionChecker
from app.chess.history import MoveHistory
from app.chess.message import Message, MessageType
from app.chess.message_bus import message_bus
from app.chess.context import context
from app.server.mobile_api import MobileServerThread
from app.ui.board_display import BoardDisplay
from app.chess.processor import ChessProcess
from app.themes.theme_manager import ThemeManager
from app.ui.qr_dialog import QRCodeDialog
from app.server.tunnel_manager import TunnelManager

logger = get_logger(__name__)

class TextDisplay(QLabel):
    """
    顶部拟物机甲终端显示面板
    支持高精切片背景与 8px 抗锯齿平滑圆角自适应裁剪
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        bg_path = resource_path('images', 'ui', 'top_text_bg.png')
        self.bg_pixmap = QPixmap(bg_path) if os.path.exists(bg_path) else None
        self.corner_radius = 8

    def paintEvent(self, event):
        # 1. 绘制抗锯齿圆角背景与切片
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, self.width() - 1.0, self.height() - 1.0, self.corner_radius, self.corner_radius)
        painter.setClipPath(path)
        
        if self.bg_pixmap and not self.bg_pixmap.isNull():
            scaled = self.bg_pixmap.scaled(self.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap(0, 0, scaled)
            
        # 绘制微弱的 1px 金属边框，赋予精致装配边框感
        painter.setPen(QPen(QColor(84, 88, 97, 100), 1))
        painter.drawPath(path)
        painter.end()
        
        # 2. 绘制 QLabel 文本内容
        super().paintEvent(event)

class MainWindow(QMainWindow):
    resume_polling_signal = Signal()  # 定义信号用于在主线程恢复轮询
    tunnel_url_ready_signal = Signal(str)  # 隧道外网URL就绪信号
    tunnel_error_signal = Signal(str)  # 隧道错误信号


    def __init__(self):
        super().__init__()
        self.setWindowTitle("象棋助手")
        
        # 获取屏幕信息
        screen = QApplication.primaryScreen()
        screen_height = screen.size().height()
        screen_width = screen.size().width()
        
        # 将屏幕尺寸保存到上下文对象中，供其他模块使用
        context.screen_size = (screen_width, screen_height)
        
        # 使用屏幕高度 x 80% 作为基准参考
        nice_height = int(screen_height * 0.8)
        # 对照设计图比例，设置自适应宽度 (453px)
        width = int(nice_height * 0.63)
        
        # 棋盘容器宽度为 width - 24 (扣除左右外边距 12*2 = 24)
        # 棋盘高度严格按照机甲外框 633 x 668 比例精确缩放
        board_w = width - 24
        board_height = int(round(board_w * 668 / 633))
        
        # 计算其他UI元素的总高度 (顶部文本64 + 中间按钮34 + 底部控制38 + 垂直间距10*3 + 上下边距22)
        other_heights = 64 + 34 + 38 + 30 + 22
        
        # 设置窗口高度为棋盘高度加上其他UI元素的高度 (精确对应 641px)
        height = board_height + other_heights
        
        print(f"Screen size: {screen_width}x{screen_height}")
        print(f"Window size: {width}x{height}")
        
        # 设置窗口固定大小
        self.setFixedSize(width, height)
        
        # 设置窗口初始位置（屏幕左上角，距离左边缘20像素，距离上边缘50像素）
        window_x = 20
        window_y = 50
        self.move(window_x, window_y)
        
        # 创建中央部件
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QVBoxLayout(central_widget)
        
        # 统一规范边距与组件间距
        self.spacing_base = 12
        self.spacing_tight = 3
        
        main_layout.setSpacing(10)  # 垂直间距设为 10px
        main_layout.setContentsMargins(12, 10, 12, 12)
        
        # 初始化上下文
        context.load_config()
        self.engine_params = context.get_engine_params()
        
        # 连接信号与槽
        self.resume_polling_signal.connect(lambda: self.check_platform_change(notify_always=False, schedule_next=True))
        self.tunnel_url_ready_signal.connect(self._on_tunnel_url_ready)
        self.tunnel_error_signal.connect(self._on_tunnel_error)
        self.tunnel_manager = TunnelManager(local_port=5050)
        
        # 顶部文本显示区域（高精原图机甲终端切片背景 + 8px平滑抗锯齿圆角 + 紧凑高度 64px）
        self.text_display = TextDisplay()
        self.text_display.setAlignment(Qt.AlignCenter)
        self.text_display.setFont(QFont("Arial", 12, QFont.Bold))
        self.text_display.setFixedHeight(64)  # 设置紧凑高度
        self.text_display.setObjectName("textDisplay")
        self.text_display.setStyleSheet("""
            QLabel#textDisplay {
                background-color: transparent;
                border: none;
                padding: 4px 12px;
                color: #E0E0E0;
            }
        """)
        main_layout.addWidget(self.text_display)
        
        # 添加中间按钮栏（支持异形边缘咬合排布）
        self.middle_buttons_bar = QWidget()
        self.middle_buttons_bar.setFixedHeight(34)
        usable_w = width - self.spacing_base * 2
        self.middle_buttons_bar.setFixedWidth(usable_w)
        
        # 按钮统一宋体字体族（兼顾 macOS / Windows / Linux 跨平台古典衬线质感，所有按钮统一字号）
        songti_families = ["Songti SC", "SimSun", "STSong", "Songti TC", "serif"]
        songti_font_12 = QFont()
        songti_font_12.setFamilies(songti_families)
        songti_font_12.setPointSize(12)
        songti_font_12.setBold(True)

        # 中部 4 按钮高精度原图切片资产
        refresh_normal = resource_path('images', 'ui', 'btn_mid_refresh_normal.png').replace('\\', '/')
        refresh_hover = resource_path('images', 'ui', 'btn_mid_refresh_hover.png').replace('\\', '/')
        refresh_pressed = resource_path('images', 'ui', 'btn_mid_refresh_pressed.png').replace('\\', '/')

        change_normal = resource_path('images', 'ui', 'btn_mid_change_normal.png').replace('\\', '/')
        change_hover = resource_path('images', 'ui', 'btn_mid_change_hover.png').replace('\\', '/')
        change_pressed = resource_path('images', 'ui', 'btn_mid_change_pressed.png').replace('\\', '/')

        mobile_normal = resource_path('images', 'ui', 'btn_mid_mobile_normal.png').replace('\\', '/')
        mobile_hover = resource_path('images', 'ui', 'btn_mid_mobile_hover.png').replace('\\', '/')
        mobile_pressed = resource_path('images', 'ui', 'btn_mid_mobile_pressed.png').replace('\\', '/')

        start_normal = resource_path('images', 'ui', 'btn_mid_start_normal.png').replace('\\', '/')
        start_hover = resource_path('images', 'ui', 'btn_mid_start_hover.png').replace('\\', '/')
        start_pressed = resource_path('images', 'ui', 'btn_mid_start_pressed.png').replace('\\', '/')

        # 计算异形斜切咬合排布坐标
        scale = usable_w / 633.0
        x1 = 0
        w1 = int(round(140 * scale))
        x2 = int(round(128 * scale))
        w2 = int(round(122 * scale))
        x3 = int(round(255 * scale))
        w3 = int(round(129 * scale))
        x4 = int(round(390 * scale))
        w4 = usable_w - x4

        # 创建刷新按钮（按钮1，右侧斜切异形边缘）
        self.manual_refresh_btn = QPushButton("刷新", self.middle_buttons_bar)
        self.manual_refresh_btn.setGeometry(x1, 0, w1, 34)
        self.manual_refresh_btn.setFont(songti_font_12)
        self.manual_refresh_btn.setCursor(Qt.PointingHandCursor)
        self.manual_refresh_btn.setObjectName("refreshBtn")
        self.manual_refresh_btn.setStyleSheet(f"""
            QPushButton#refreshBtn {{
                border-image: url("{refresh_normal}") 0 0 0 0 stretch stretch;
                background-color: transparent;
                border: none;
                color: #E0E1E6;
                font-family: "Songti SC", "SimSun", "STSong", "Songti TC", serif;
                font-size: 12pt;
                font-weight: bold;
                padding-bottom: 6px;
                padding-right: 6px;
            }}
            QPushButton#refreshBtn:hover {{
                border-image: url("{refresh_hover}") 0 0 0 0 stretch stretch;
                color: #FFFFFF;
                padding-bottom: 6px;
                padding-right: 6px;
            }}
            QPushButton#refreshBtn:pressed {{
                border-image: url("{refresh_pressed}") 0 0 0 0 stretch stretch;
                color: #9DA0A8;
                padding-top: 2px;
                padding-bottom: 4px;
                padding-right: 6px;
            }}
        """)
        pix_r = QPixmap(refresh_normal).scaled(w1, 34, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self.manual_refresh_btn.setMask(pix_r.mask())
        self.manual_refresh_btn.clicked.connect(self.on_manual_capture)

        # 创建变招/支招按钮（按钮2，左侧与刷新右侧斜切咬合）
        self.change_move_btn = QPushButton("变招", self.middle_buttons_bar)
        self.change_move_btn.setGeometry(x2, 0, w2, 34)
        self.change_move_btn.setFont(songti_font_12)
        self.change_move_btn.setCursor(Qt.PointingHandCursor)
        self.change_move_btn.setObjectName("changeMoveBtn")
        self.change_move_btn.setStyleSheet(f"""
            QPushButton#changeMoveBtn {{
                border-image: url("{change_normal}") 0 0 0 0 stretch stretch;
                background-color: transparent;
                border: none;
                color: #E0E1E6;
                font-family: "Songti SC", "SimSun", "STSong", "Songti TC", serif;
                font-size: 12pt;
                font-weight: bold;
                padding-bottom: 6px;
                padding-left: 6px;
            }}
            QPushButton#changeMoveBtn:hover {{
                border-image: url("{change_hover}") 0 0 0 0 stretch stretch;
                color: #FFFFFF;
                padding-bottom: 6px;
                padding-left: 6px;
            }}
            QPushButton#changeMoveBtn:pressed {{
                border-image: url("{change_pressed}") 0 0 0 0 stretch stretch;
                color: #9DA0A8;
                padding-top: 2px;
                padding-bottom: 4px;
                padding-left: 6px;
            }}
        """)
        pix_c = QPixmap(change_normal).scaled(w2, 34, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self.change_move_btn.setMask(pix_c.mask())
        self.change_move_btn.clicked.connect(self.on_change_move)

        # 创建手机按钮（按钮3，功能暂时搁置）
        self.mobile_btn = QPushButton("手机", self.middle_buttons_bar)
        self.mobile_btn.setGeometry(x3, 0, w3, 34)
        self.mobile_btn.setFont(songti_font_12)
        self.mobile_btn.setCursor(Qt.PointingHandCursor)
        self.mobile_btn.setObjectName("mobileBtn")
        self.mobile_btn.setStyleSheet(f"""
            QPushButton#mobileBtn {{
                border-image: url("{mobile_normal}") 0 0 0 0 stretch stretch;
                background-color: transparent;
                border: none;
                color: #E0E1E6;
                font-family: "Songti SC", "SimSun", "STSong", "Songti TC", serif;
                font-size: 12pt;
                font-weight: bold;
                padding-bottom: 6px;
            }}
            QPushButton#mobileBtn:hover {{
                border-image: url("{mobile_hover}") 0 0 0 0 stretch stretch;
                color: #FFFFFF;
                padding-bottom: 6px;
            }}
            QPushButton#mobileBtn:pressed {{
                border-image: url("{mobile_pressed}") 0 0 0 0 stretch stretch;
                color: #9DA0A8;
                padding-top: 2px;
                padding-bottom: 4px;
            }}
        """)
        self.mobile_btn.clicked.connect(self.on_mobile_clicked)
        
        # 添加开始按钮（按钮4，主操作按钮）
        self.start_btn = QPushButton("开始", self.middle_buttons_bar)
        self.start_btn.setGeometry(x4, 0, w4, 34)
        self.start_btn.setFont(songti_font_12)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setStyleSheet(f"""
            QPushButton#startBtn {{
                border-image: url("{start_normal}") 0 0 0 0 stretch stretch;
                background-color: transparent;
                border: none;
                color: #E0E1E6;
                font-family: "Songti SC", "SimSun", "STSong", "Songti TC", serif;
                font-size: 12pt;
                font-weight: bold;
                padding-bottom: 6px;
            }}
            QPushButton#startBtn:hover {{
                border-image: url("{start_hover}") 0 0 0 0 stretch stretch;
                color: #FFFFFF;
                padding-bottom: 6px;
            }}
            QPushButton#startBtn:pressed {{
                border-image: url("{start_pressed}") 0 0 0 0 stretch stretch;
                color: #9DA0A8;
                padding-top: 2px;
                padding-bottom: 4px;
            }}
        """)
        self.start_btn.clicked.connect(self.on_start)
        
        main_layout.addWidget(self.middle_buttons_bar)
        
        # 中间棋盘区域
        self.board_display = BoardDisplay()
        # 移除固定高度设置，让棋盘自适应图片大小
        main_layout.addWidget(self.board_display)
        
        # 底部控制区域
        control_layout = QHBoxLayout()
        control_layout.setSpacing(6)
        control_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建退出按钮（高精拟物底图切片 + 动态文字渲染，统一高度 38px）
        self.exit_btn = QPushButton("退出")
        self.exit_btn.setFixedSize(84, 38)
        self.exit_btn.setCursor(Qt.PointingHandCursor)
        self.exit_btn.setFont(songti_font_12)
        self.exit_btn.setObjectName("exitBtn")
        
        # 兼容打包环境与自定义路径的动态绝对路径样式绑定
        normal_path = resource_path('images', 'ui', 'btn_exit_normal.png').replace('\\', '/')
        hover_path = resource_path('images', 'ui', 'btn_exit_hover.png').replace('\\', '/')
        pressed_path = resource_path('images', 'ui', 'btn_exit_pressed.png').replace('\\', '/')
        
        self.exit_btn.setStyleSheet(f"""
            QPushButton#exitBtn {{
                border-image: url("{normal_path}") 0 0 0 0 stretch stretch;
                background: transparent;
                border: none;
                color: #D88D88;
                font-family: "Songti SC", "SimSun", "STSong", "Songti TC", serif;
                font-size: 12pt;
                font-weight: bold;
                padding: 0px 0px 7px 0px;
                margin: 0px;
            }}
            QPushButton#exitBtn:hover {{
                border-image: url("{hover_path}") 0 0 0 0 stretch stretch;
                color: #FFA49E;
            }}
            QPushButton#exitBtn:pressed {{
                border-image: url("{pressed_path}") 0 0 0 0 stretch stretch;
                color: #B86E6A;
                padding-top: 2px;
                padding-bottom: 5px;
            }}
        """)
        self.exit_btn.clicked.connect(self.on_exit)
        control_layout.addWidget(self.exit_btn)
        
        # 兼容次级拟物切片按钮样式绑定
        board_normal_path = resource_path('images', 'ui', 'btn_board_normal.png').replace('\\', '/')
        board_hover_path = resource_path('images', 'ui', 'btn_board_hover.png').replace('\\', '/')
        board_pressed_path = resource_path('images', 'ui', 'btn_board_pressed.png').replace('\\', '/')
        
        param_normal_path = resource_path('images', 'ui', 'btn_param_normal.png').replace('\\', '/')
        param_hover_path = resource_path('images', 'ui', 'btn_param_hover.png').replace('\\', '/')
        param_pressed_path = resource_path('images', 'ui', 'btn_param_pressed.png').replace('\\', '/')

        # “外观”与“其他”（2字，使用 96px 优雅比例切片）
        two_char_style = f"""
            QPushButton#boardBtn, QPushButton#settingsBtn {{
                border-image: url("{param_normal_path}") 0 0 0 0 stretch stretch;
                background: transparent;
                border: none;
                color: #C5C6CB;
                font-family: "Songti SC", "SimSun", "STSong", "Songti TC", serif;
                font-size: 12pt;
                font-weight: bold;
                padding: 0px 0px 7px 0px;
                margin: 0px;
            }}
            QPushButton#boardBtn:hover, QPushButton#settingsBtn:hover {{
                border-image: url("{param_hover_path}") 0 0 0 0 stretch stretch;
                color: #FFFFFF;
            }}
            QPushButton#boardBtn:pressed, QPushButton#settingsBtn:pressed {{
                border-image: url("{param_pressed_path}") 0 0 0 0 stretch stretch;
                color: #9DA0A8;
                padding-top: 2px;
                padding-bottom: 5px;
            }}
        """

        # “参数”按钮样式（更名为“参数”后与“外观”、“其他”同为2字，统一 12pt 宋体与拟物切片）
        param_style = f"""
            QPushButton#paramBtnSelect {{
                border-image: url("{param_normal_path}") 0 0 0 0 stretch stretch;
                background: transparent;
                border: none;
                color: #C5C6CB;
                font-family: "Songti SC", "SimSun", "STSong", "Songti TC", serif;
                font-size: 12pt;
                font-weight: bold;
                padding: 0px 0px 7px 0px;
                margin: 0px;
            }}
            QPushButton#paramBtnSelect:hover {{
                border-image: url("{param_hover_path}") 0 0 0 0 stretch stretch;
                color: #FFFFFF;
            }}
            QPushButton#paramBtnSelect:pressed {{
                border-image: url("{param_pressed_path}") 0 0 0 0 stretch stretch;
                color: #9DA0A8;
                padding-top: 2px;
                padding-bottom: 5px;
            }}
        """

        # 创建“外观”按钮（增加宽度与“退出”按钮等宽 84px，统一高度 38px）
        self.board_btn = QPushButton("外观")
        self.board_btn.setFixedSize(84, 38)
        self.board_btn.setCursor(Qt.PointingHandCursor)
        self.board_btn.setFont(songti_font_12)
        self.board_btn.setObjectName("boardBtn")
        self.board_btn.setIconSize(QSize(13, 13))
        self.board_btn.setStyleSheet(two_char_style)
        self.board_btn.clicked.connect(self.show_board_menu)
        control_layout.addWidget(self.board_btn)
        
        # 创建棋盘设置菜单
        self.board_menu = QMenu(self)
        self.board_menu.setStyleSheet("")
        self.board_menu.aboutToShow.connect(lambda: self._set_arrow_state(self.board_btn, True))
        self.board_menu.aboutToHide.connect(lambda: self._set_arrow_state(self.board_btn, False))
        self.manual_position_action = self.board_menu.addAction("手动定位")
        self.change_board_action = self.board_menu.addAction("更换棋盘")
        self.manual_position_action.triggered.connect(self.on_reposition)
        self.change_board_action.triggered.connect(self.on_change_board_bg)
        
        self.change_pieces_action = self.board_menu.addAction("更换棋子")
        self.change_pieces_action.triggered.connect(self.on_change_pieces)
        
        # 创建"其他"按钮（增加宽度与“退出”按钮等宽 84px，统一高度 38px）
        self.settings_btn = QPushButton("其他") 
        self.settings_btn.setFixedSize(84, 38)
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.setFont(songti_font_12)
        self.settings_btn.setObjectName("settingsBtn")
        self.settings_btn.setIconSize(QSize(13, 13))
        self.settings_btn.setStyleSheet(two_char_style)
        self.settings_btn.clicked.connect(self.show_settings_menu)
        control_layout.addWidget(self.settings_btn)
        
        # 创建设置菜单
        self.settings_menu = QMenu(self)
        self.settings_menu.setStyleSheet("")
        self.settings_menu.aboutToShow.connect(lambda: self._set_arrow_state(self.settings_btn, True))
        self.settings_menu.aboutToHide.connect(lambda: self._set_arrow_state(self.settings_btn, False))
        self.continuous_action = self.settings_menu.addAction("连续识别")
        self.timer_action = self.settings_menu.addAction("计时识别")
        self.continuous_action.setCheckable(True)
        self.timer_action.setCheckable(True)
        self.continuous_action.setChecked(context.analysis_mode == "continuous")
        self.timer_action.setChecked(context.analysis_mode == "timer")
        self.continuous_action.triggered.connect(self.toggle_continuous)
        self.timer_action.triggered.connect(self.toggle_timer)
        
        self.settings_menu.addSeparator()
        self.mobile_assist_action = self.settings_menu.addAction("手机协助")
        self.mobile_assist_action.setCheckable(True)
        self.mobile_assist_action.triggered.connect(self.toggle_mobile_assist)
        self.mobile_server_thread = None
        self.qr_dialog = None
        
        # 手机心跳状态机维护
        self.mobile_has_ever_connected = False
        self.mobile_last_heartbeat_time = None
        self.mobile_last_heartbeat_data = None
        self.mobile_heartbeat_timer = QTimer(self)
        self.mobile_heartbeat_timer.timeout.connect(self._check_mobile_heartbeat_timeout)
        
        self.show_qr_action = self.settings_menu.addAction("连接二维码")
        self.show_qr_action.triggered.connect(self.show_qr_dialog)
        
        # 创建“参数”按钮（统一高度 38px，字体统一 11pt 宋体粗体）
        self.param_btn = QPushButton("参数")
        self.param_btn.setFixedHeight(38)
        self.param_btn.setCursor(Qt.PointingHandCursor)
        self.param_btn.setFont(songti_font_12)
        self.param_btn.setObjectName("paramBtnSelect")
        self.param_btn.setIconSize(QSize(13, 13))
        self.param_btn.setStyleSheet(param_style)
        self.param_btn.clicked.connect(self.show_param_menu)
        control_layout.addWidget(self.param_btn, 1)
        
        # 创建参数菜单
        self.param_menu = QMenu(self)
        self.param_menu.setStyleSheet("")
        self.param_menu.aboutToShow.connect(lambda: self._set_arrow_state(self.param_btn, True))
        self.param_menu.aboutToHide.connect(lambda: self._set_arrow_state(self.param_btn, False))
        self.depth_action = self.param_menu.addAction("depth")
        self.movetime_action = self.param_menu.addAction("movetime")
        self.depth_action.setCheckable(True)
        self.movetime_action.setCheckable(True)
        self.depth_action.triggered.connect(lambda: self.on_param_selected("depth"))
        self.movetime_action.triggered.connect(lambda: self.on_param_selected("movetime"))
        
        # 设置初始选中状态
        if self.engine_params["goParam"] == "depth":
            self.depth_action.setChecked(True)
        else:
            self.movetime_action.setChecked(True)
        
        # 创建参数调整按钮（三段式无缝拟物胶囊步进器）
        param_layout = QHBoxLayout()
        param_layout.setSpacing(0)
        param_layout.setContentsMargins(0, 0, 0, 0)
        
        # 兼容打包环境与自定义路径的动态绝对路径样式绑定
        minus_normal_path = resource_path('images', 'ui', 'stepper_minus_normal.png').replace('\\', '/')
        minus_hover_path = resource_path('images', 'ui', 'stepper_minus_hover.png').replace('\\', '/')
        minus_pressed_path = resource_path('images', 'ui', 'stepper_minus_pressed.png').replace('\\', '/')
        
        disp_path = resource_path('images', 'ui', 'stepper_display.png').replace('\\', '/')
        
        plus_normal_path = resource_path('images', 'ui', 'stepper_plus_normal.png').replace('\\', '/')
        plus_hover_path = resource_path('images', 'ui', 'stepper_plus_hover.png').replace('\\', '/')
        plus_pressed_path = resource_path('images', 'ui', 'stepper_plus_pressed.png').replace('\\', '/')
        
        dec_style = f"""
            QPushButton#paramDecBtn {{
                border-image: url("{minus_normal_path}") 0 0 0 0 stretch stretch;
                background: transparent;
                border: none;
                color: #C5C6CB;
                font-size: 15pt;
                font-weight: bold;
                padding: 0px 0px 7px 0px;
                margin: 0px;
            }}
            QPushButton#paramDecBtn:hover {{
                border-image: url("{minus_hover_path}") 0 0 0 0 stretch stretch;
                color: #FFFFFF;
            }}
            QPushButton#paramDecBtn:pressed {{
                border-image: url("{minus_pressed_path}") 0 0 0 0 stretch stretch;
                color: #9DA0A8;
                padding-top: 2px;
                padding-bottom: 5px;
            }}
        """
        
        disp_style = f"""
            QLabel#paramLabel {{
                border-image: url("{disp_path}") 0 0 0 0 stretch stretch;
                background: transparent;
                border: none;
                color: #D4D5DA;
                font-size: 12pt;
                font-weight: bold;
                padding: 0px 0px 7px 0px;
                margin: 0px;
            }}
        """
        
        inc_style = f"""
            QPushButton#paramIncBtn {{
                border-image: url("{plus_normal_path}") 0 0 0 0 stretch stretch;
                background: transparent;
                border: none;
                color: #C5C6CB;
                font-size: 15pt;
                font-weight: bold;
                padding: 0px 0px 7px 0px;
                margin: 0px;
            }}
            QPushButton#paramIncBtn:hover {{
                border-image: url("{plus_hover_path}") 0 0 0 0 stretch stretch;
                color: #FFFFFF;
            }}
            QPushButton#paramIncBtn:pressed {{
                border-image: url("{plus_pressed_path}") 0 0 0 0 stretch stretch;
                color: #9DA0A8;
                padding-top: 2px;
                padding-bottom: 5px;
            }}
        """
        
        self.decrease_btn = QPushButton("−")
        self.decrease_btn.setFixedHeight(38)
        self.decrease_btn.setFixedWidth(24)
        self.decrease_btn.setCursor(Qt.PointingHandCursor)
        self.decrease_btn.setFont(QFont("Arial", 15, QFont.Bold))
        self.decrease_btn.setObjectName("paramDecBtn")
        self.decrease_btn.setStyleSheet(dec_style)
        self.decrease_btn.clicked.connect(self.on_decrease_param)
        param_layout.addWidget(self.decrease_btn)
        
        self.param_label = QLabel(self.engine_params[self.engine_params["goParam"]])
        self.param_label.setAlignment(Qt.AlignCenter)
        self.param_label.setFixedHeight(38)
        self.param_label.setFixedWidth(36)
        self.param_label.setFont(QFont("Arial", 12, QFont.Bold))
        self.param_label.setObjectName("paramLabel")
        self.param_label.setStyleSheet(disp_style)
        param_layout.addWidget(self.param_label)
        
        self.increase_btn = QPushButton("+")
        self.increase_btn.setFixedHeight(38)
        self.increase_btn.setFixedWidth(24)
        self.increase_btn.setCursor(Qt.PointingHandCursor)
        self.increase_btn.setFont(QFont("Arial", 15, QFont.Bold))
        self.increase_btn.setObjectName("paramIncBtn")
        self.increase_btn.setStyleSheet(inc_style)
        self.increase_btn.clicked.connect(self.on_increase_param)
        param_layout.addWidget(self.increase_btn)
        
        control_layout.addLayout(param_layout)  # 步进器尺寸固定，不参与拉伸分流
        main_layout.addLayout(control_layout)
        
        # 初始化UI消息队列和定时器（保持一直运行）
        self.ui_message_queue = queue.Queue()
        # 设置全局消息总线
        message_bus.set_ui_queue(self.ui_message_queue)
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_queue)
        self.check_timer.start(100)  # 100ms间隔，性能开销极小

        # 初始化线程和队列
        self.capture_thread = None
        # 初始化截图管理器
        self.capture_manager = ChessCaptureManager()
        # 初始化手动定位器
        self.manual_positioner = ManualPositioner(self)

        # 初始化状态
        self.is_running = False
        self.is_stopping = False  # 添加停止标志，防止手动停止与自动停止冲突
        self._is_exiting = False   # 退出流程防重入标志
        self.lines = ["", "", ""]
        self.update_text("等待获取棋局...", MessageType.STATUS)
        
        # 应用固定深色机甲主题（#212123）
        ThemeManager.apply_theme()
        
        # 初始化图标
        self.update_icons()
        
        # 初始化状态
        self.last_detected_platform = None
        
        # 初始化平台检测器
        self.platform_detector = BoardLocator(context)
        
        # 启动时执行一次平台检测（延迟执行以确保窗口完全加载），并强制显示结果，未检测到则开启轮询
        QTimer.singleShot(100, lambda: self.check_platform_change(notify_always=True, schedule_next=True))

    def check_platform_change(self, notify_always=False, schedule_next=False):
        """
        检测当前运行的游戏平台并自动切换
        Args:
            notify_always: 是否即使平台未变化也显示通知
            schedule_next: 如果未检测到，是否调度下一次检测（2秒后）
        """
        print(f"DEBUG: check_platform_change is_running={self.is_running}, schedule_next={schedule_next}")
        try:
            # 1. 尝试查找当前平台窗口
            current_found = self.platform_detector.find_game_window(context.platform)
            
            result = current_found
            
            if result:
                detected_platform = result['platform']
                platform_display_name = result.get('platform_name', detected_platform)
                
                # 更新最后检测到的平台状态
                self.last_detected_platform = detected_platform

                # 手机协助开启且桌面未运行时，顶部优先显示手机协助连接状态，避免被后台轮询覆盖
                is_mobile_showing = (
                    hasattr(self, 'mobile_assist_action') 
                    and self.mobile_assist_action.isChecked() 
                    and not self.is_running
                )

                # 如果检测到的平台与当前上下文不一致，则切换
                if detected_platform != context.platform:
                    print(f"Auto-switch platform: {context.platform} -> {detected_platform}")
                    context.set_platform(detected_platform)
                    if not is_mobile_showing:
                        self.update_text(f"自动切换到游戏: {platform_display_name}", MessageType.STATUS)
                else:
                    # 即使未变化，也显示当前检测到的平台（因为可能是启动时的确认，或者是轮询成功的通知）
                    if not is_mobile_showing:
                        self.update_text(f"检测到游戏: {platform_display_name}", MessageType.STATUS)
            else:
                is_mobile_showing = (
                    hasattr(self, 'mobile_assist_action') 
                    and self.mobile_assist_action.isChecked() 
                    and not self.is_running
                )
                # 情况1: 之前检测到了游戏，现在没了 -> 游戏被关闭
                if self.last_detected_platform is not None:
                    if not is_mobile_showing:
                        self.update_text("游戏窗口已关闭，等待重新启动...", MessageType.ERROR)
                    self.last_detected_platform = None
                
                # 情况2: 强制通知（如启动时或点击开始时）
                elif notify_always:
                    if not is_mobile_showing:
                        self.update_text("未检测到象棋游戏窗口", MessageType.ERROR)
                    if schedule_next:
                        print("未检测到象棋游戏窗口，2秒后重试...")
                
            # 只要不是正在运行状态，且要求调度，就继续轮询（允许用户先开一个游戏再换另一个）
            if schedule_next and not self.is_running:
                QTimer.singleShot(2000, lambda: self.check_platform_change(notify_always=False, schedule_next=True))
                    
        except Exception as e:
            print(f"自动检测平台失败: {e}")

    
    def on_engine_param_changed(self, param):
        """处理引擎参数改变"""
        self.engine_params["goParam"] = param
        self.param_label.setText(self.engine_params[param])
        context.update_engine_params(self.engine_params)

    def on_increase_param(self):
        """增加参数值"""
        # 获取当前参数
        engine_params = context.get_engine_params()
        key = engine_params["goParam"]
        param_value = int(engine_params[key])
        
        if key == "depth" and param_value < 200:
            param_value += 1
        elif key == "movetime" and param_value < 20000:
            param_value += 2000
        
        # 更新参数
        engine_params[key] = str(param_value)
        context.update_engine_params(engine_params)
        
        # 更新显示
        self.param_label.setText(str(param_value))

    def on_decrease_param(self):
        """减少参数值"""
        # 获取当前参数
        engine_params = context.get_engine_params()
        key = engine_params["goParam"]
        param_value = int(engine_params[key])
        
        if key == "depth" and param_value > 1:
            param_value -= 1
        elif key == "movetime" and param_value > 2000:
            param_value -= 2000
        
        # 更新参数
        engine_params[key] = str(param_value)
        context.update_engine_params(engine_params)
        
        # 更新显示
        self.param_label.setText(str(param_value))

    def on_start(self):
        """开始/停止按钮事件"""
        if not self.is_running:
            self.is_running = True
            context.is_desktop_running = True
            self.start_btn.setText("停止")
            
            # 点击开始时，再次确认一下平台并显示结果 (不需要轮询)
            self.check_platform_change(notify_always=True, schedule_next=False)
            self.create_queue()
        else:
            self.on_stop()
 
    def on_stop(self):
        """停止事件"""
        if self.is_stopping: 
            return
        self.is_stopping = True
        # 立即更新UI状态
        self.is_running = False
        context.is_desktop_running = False
        self.start_btn.setText("开始")
        
        # 清空界面状态
        self.board_display.clear_board()
        self.lines[2] = "" # 确保清除着法缓存
        
        # 如果手机协助处于开启状态，自动恢复显示手机协助的状态；否则显示默认开始提示
        if hasattr(self, 'mobile_assist_action') and self.mobile_assist_action.isChecked():
            self._update_mobile_status_display()
        else:
            self.update_text("点击开始，为你推荐最佳着法~", MessageType.STATUS)
        
        # 异步执行停止操作，避免阻塞UI
        def stop_worker():
            try:
                # 只停止非Qt对象
                if self.capture_manager is not None:
                    self.capture_manager.stop_capture()  # 停止截图和工作线程
                context.quit_engine()  # 线程安全地退出引擎
                context.reset_checker() # 线程安全地重置检查器
                context.history.clear()  # 停止时清空历史
            except Exception as e:
                print(f"停止操作失败: {e}")
            finally:
                self.is_stopping = False
                # 停止完成后，通过信号触发主线程恢复平台轮询检测
                print("停止完成，正在恢复平台轮询...")
                self.resume_polling_signal.emit()
        
        # 在后台线程中执行停止操作
        import threading
        stop_thread = threading.Thread(target=stop_worker, daemon=True)
        stop_thread.start() 
        
    def create_queue(self):
        """创建队列和启动分析线程"""
        # 异步执行所有耗时操作，避免阻塞UI
        def start_worker():
            try:
                # 强制停止旧实例，确保消息订阅被清理
                if self.capture_manager is not None:
                    self.capture_manager.stop_capture()  # 调用截图模块的方法停止
                    self.capture_manager = None

                # 关键：每次都new新的ChessCaptureManager，保证识别线程能重启
                self.capture_manager = ChessCaptureManager()
                self.capture_manager.start_capture()
                
                # 启动引擎
                context.set_engine(ChessEngine())
                if context.engine.start():
                    print("引擎已启动")
                else:
                    print("引擎启动失败")
                
                # 初始化局面检查器和历史记录
                context.set_checker(PositionChecker())
                context.history = MoveHistory()
                
                # 执行主处理流程（阻塞调用）
                self.capture_manager.main_process_flow()
            except Exception as e:
                print(f"开始操作发生错误: {e}")
        
        # 在后台线程中执行所有操作
        start_thread = threading.Thread(target=start_worker, daemon=True)
        start_thread.start()

    def check_queue(self):
        """检查结果队列"""
        if not self.ui_message_queue.empty():
            result = self.ui_message_queue.get()

            if isinstance(result, Message):
                if result.type == MessageType.STOP:
                    if not self.is_stopping:  # 防止手动停止与自动停止冲突
                        self.on_stop()
                    return
                if result.type == MessageType.CHANGE:
                    self.board_display.update_board(
                        result.kwargs['array'], 
                        step_info=result.kwargs.get('step_info')
                    )
                    self.update_text(result.content, result.type)
                elif result.type == MessageType.PIECES:
                    # 更新棋子位置
                    self.board_display.update_pieces(result.kwargs['array'])
                elif result.type == MessageType.MOVE_CODE:
                    # 更新着法箭头
                    self.board_display.update_arrow(result.content, result.kwargs['is_red'])
                elif result.type == MessageType.MOVE_TEXT:
                    # 显示着法文本
                    self.update_text(result.content, result.type)
                elif result.type == MessageType.STATUS:
                    # 显示状态消息
                    self.update_text(result.content, result.type)
                elif result.type == MessageType.ERROR:
                    # 显示错误消息
                    self.update_text(result.content, result.type)
                elif result.type == MessageType.NON_GAME_SCREEN:
                    # 非棋局画面：清空棋盘并显示提示
                    self.board_display.clear_board()
                    self.update_text(result.content, MessageType.STATUS)
                elif result.type == MessageType.HEARTBEAT:
                    # 处理手机端心跳消息
                    import time
                    self.mobile_has_ever_connected = True
                    self.mobile_last_heartbeat_time = time.time()
                    self.mobile_last_heartbeat_data = result.kwargs
                    self._update_mobile_status_display()
    
    def close_queue(self):
        """销毁截图线程"""
        if self.capture_manager is not None:
            mgr = self.capture_manager
            self.capture_manager = None
            mgr.stop_capture()

    def update_text(self, text, message_type=None, color=None):
        """
        更新显示文本
        Args:
            text: 要显示的文本内容
            message_type: 消息类型，用于确定显示颜色和样式
            color: 自定义文本颜色（可选）
        """
        # 定义不同消息类型的颜色和样式
        message_styles = {
            MessageType.MOVE_TEXT: {
                'color': '#2C3E50',  # 深蓝灰色，更易读
                'font_size': '34pt',
                'is_move': True
            },
            MessageType.STATUS: {
                'color': '#3498DB',  # 明亮蓝色
                'font_size': '13pt',
                'is_move': False
            },
            MessageType.ERROR: {
                'color': '#FFFFFF',  # 白色
                'font_size': '13pt',
                'is_move': False
            },
            MessageType.CHANGE: {
                'color': '#27AE60',  # 明亮绿色
                'font_size': '13pt',
                'is_move': False
            }
        }
        
        # 默认样式
        default_style = {
            'color': '#3498DB',  # 明亮蓝色
            'font_size': '13pt',
            'is_move': False
        }
        
        # 获取样式配置
        style = dict(message_styles.get(message_type, default_style))
        if color:
            style['color'] = color
        
        # 处理多行文本
        lines = text.split('\n') if '\n' in text else [text]
        
        # 限制最多显示2行
        if len(lines) > 2:
            lines = lines[:2]
        
        # 根据消息类型更新显示内容
        if style['is_move']:
            # 着法消息：显示在第3行（大字体）
            self.lines = ["", "", lines[0]]
        else:
            # 状态消息：显示在第1行和第2行
            if message_type in (MessageType.ERROR, MessageType.NON_GAME_SCREEN) or any(k in text for k in ("等待", "重置", "未检测到", "已关闭", "点击开始")):
                self.lines = [lines[0], lines[1] if len(lines) > 1 else "", ""]
            elif len(lines) == 1:
                self.lines = [lines[0], "", self.lines[2]]  # 保留第3行的着法
            else:
                self.lines = [lines[0], lines[1], ""] 
        
        # 生成HTML显示文本（适配 64px 紧凑高度，彻底消除溢出）
        has_status0 = bool(self.lines[0])
        has_status1 = bool(self.lines[1])
        has_move = bool(self.lines[2])
        
        display_text = ""
        if has_move:
            if has_status0:
                # 状态 + 着法 双行布局（招法文本上移约 3 像素，提升至 34pt，底部保留舒适间距）
                status_html = f'<div style="color: {style["color"]}; font-size: 10pt; font-weight: normal; margin-top: 1px; margin-bottom: 0px; line-height: 85%;">{self.lines[0]}</div>'
                move_html = f'<div style="font-family: \'Songti SC\', \'SimSun\', \'STSong\', serif; font-weight: bold; font-size: 34pt; margin-top: 0px; line-height: 100%;">{self.lines[2]}</div>'
                display_text = f'<div style="text-align: center; margin: 0; padding: 0;">{status_html}{move_html}</div>'
            else:
                # 单独显示着法（上移约 3 像素，34pt）
                move_html = f'<span style="font-family: \'Songti SC\', \'SimSun\', \'STSong\', serif; font-weight: bold; font-size: 34pt; line-height: 1;">{self.lines[2]}</span><div style="font-size: 4pt; line-height: 1;">&nbsp;</div>'
                display_text = f'<div style="text-align: center; margin: 0; padding: 0;">{move_html}</div>'
        else:
            if has_status0 and has_status1:
                line0_html = f'<span style="color: {style["color"]}; font-size: 11pt;">{self.lines[0]}</span>'
                line1_html = f'<span style="color: {style["color"]}; font-size: 11pt;">{self.lines[1]}</span>'
                display_text = f'<div style="text-align: center; margin: 0; padding: 0; line-height: 120%;">{line0_html}<br>{line1_html}</div>'
            elif has_status0:
                display_text = f'<div style="text-align: center; margin: 0; padding: 0;"><span style="color: {style["color"]}; font-size: 13pt;">{self.lines[0]}</span></div>'
            elif has_status1:
                display_text = f'<div style="text-align: center; margin: 0; padding: 0;"><span style="color: {style["color"]}; font-size: 13pt;">{self.lines[1]}</span></div>'
        
        self.text_display.setText(display_text)

    
    def create_position_dot(self, is_temp=False, x=None, y=None):
        """
        创建定位点
        Args:
            is_temp: 是否为临时定位点（跟随光标）
            x, y: 指定位置坐标（如果为None且is_temp=False，则从配置读取）
        """
        if self.position_dot:
            # 移除事件过滤器（如果存在）
            if hasattr(self.position_dot, 'removeEventFilter'):
                self.position_dot.removeEventFilter(self)
            self.position_dot.close()
            self.position_dot = None
        
        # 创建定位点
        self.position_dot = QLabel(None)
        
        # 设置窗口标志
        if is_temp:
            # 临时定位点：增强的窗口标志
            self.position_dot.setWindowFlags(
                Qt.FramelessWindowHint | 
                Qt.WindowStaysOnTopHint | 
                Qt.Tool |
                Qt.X11BypassWindowManagerHint |  # 绕过窗口管理器
                Qt.NoDropShadowWindowHint
            )
            self.position_dot.setAttribute(Qt.WA_ShowWithoutActivating)  # 显示但不激活
            # 标记为临时定位点
            self.position_dot.setProperty("is_temp", True)
            # 安装事件过滤器
            self.position_dot.installEventFilter(self)
        else:
            # 正常定位点：基本窗口标志
            self.position_dot.setWindowFlags(
                Qt.FramelessWindowHint | 
                Qt.WindowStaysOnTopHint | 
                Qt.Tool |
                Qt.NoDropShadowWindowHint
            )
        
        # 通用属性设置
        self.position_dot.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.position_dot.setAttribute(Qt.WA_TranslucentBackground)
        
        # 加载定位点图片
        pixmap = QPixmap(resource_path('images', 'dingwei.png'))
        scaled_pixmap = pixmap.scaledToHeight(25, Qt.SmoothTransformation)
        width = scaled_pixmap.width()
        height = scaled_pixmap.height()
        
        # 确定位置
        if is_temp:
            # 临时定位点：跟随光标
            cursor_pos = QCursor.pos()
            window_x = cursor_pos.x() - width/2
            window_y = cursor_pos.y() - height/2
        elif x is not None and y is not None:
            # 指定坐标
            window_x = x - width/2
            window_y = y - height/2
        else:
            # 从配置读取坐标
            try:
                platform = context.get_platform(context.platform)
                board_region = platform.regions.get("board")
                
                if not board_region or 'left' not in board_region or 'top' not in board_region:
                    print("棋盘区域配置无效，无法创建定位点")
                    return
                    
                x = board_region['left']
                y = board_region['top']
                window_x = x - width/2
                window_y = y - height/2
            except Exception as e:
                print(f"创建定位点失败: {e}")
                # 如果创建失败，尝试创建临时定位点
                self.create_position_dot(is_temp=True)
                return
        
        # 设置位置和显示
        self.position_dot.setGeometry(window_x, window_y, width, height)
        self.position_dot.setStyleSheet("background: transparent;")
        self.position_dot.setPixmap(scaled_pixmap)
        self.position_dot.show()
        self.position_dot.raise_()
        
        # 临时定位点的特殊处理
        if is_temp:
            # 强制保持在最前面
            self.position_dot.setWindowState(Qt.WindowActive)
        elif self.follow_cursor:
            # 正常定位点：如果启用了光标跟踪
            self.start_cursor_tracking()

    # 定位点相关方法已移至ManualPositioner类中
    
    def show_settings_menu(self):
        """显示设置菜单"""
        self.settings_menu.exec_(self.settings_btn.mapToGlobal(self.settings_btn.rect().bottomLeft()))



    def toggle_continuous(self):
        """切换连续识别模式"""
        # 如果已经是连续模式，保持选中状态
        if context.analysis_mode == "continuous":
            self.continuous_action.setChecked(True)
            return
            
        # 切换到连续模式
        self.continuous_action.setChecked(True)
        self.timer_action.setChecked(False)
        context.analysis_mode = "continuous"
        context.save_config()

    def toggle_timer(self):
        """切换计时识别模式"""
        # 如果已经是计时模式，保持选中状态
        if context.analysis_mode == "timer":
            self.timer_action.setChecked(True)
            return
            
        # 切换到计时模式
        self.timer_action.setChecked(True)
        self.continuous_action.setChecked(False)
        context.analysis_mode = "timer"
        context.save_config()

    def _get_local_ip(self) -> str:
        """获取真实局域网私有 IP (自动穿透代理与多物理网卡)"""
        return get_local_ip()

    def show_qr_dialog(self):
        """显示或刷新手机协助连接二维码卡片"""
        # 如果手机协助服务未启动，先自动帮用户启动服务
        if hasattr(self, 'mobile_assist_action') and not self.mobile_assist_action.isChecked():
            self.mobile_assist_action.setChecked(True)
            self.toggle_mobile_assist()

        ip = self._get_local_ip()
        tunnel_url = self.tunnel_manager.tunnel_url if self.tunnel_manager else None
        pairing_id = self.tunnel_manager.pairing_id if self.tunnel_manager else "CHESS-DEFAULT"
        
        if self.qr_dialog is None:
            self.qr_dialog = QRCodeDialog(
                ip=ip, 
                port=5050, 
                pairing_id=pairing_id,
                tunnel_url=tunnel_url, 
                parent=self
            )
        else:
            self.qr_dialog.ip = ip
            self.qr_dialog.lan_api_url = f"http://{ip}:5050/api/analyze"
            self.qr_dialog.pairing_id = pairing_id
            self.qr_dialog.update_tunnel_url(tunnel_url)

        # 居中对齐在主窗口正上方
        geo = self.geometry()
        x = geo.x() + (geo.width() - self.qr_dialog.width()) // 2
        y = geo.y() + (geo.height() - self.qr_dialog.height()) // 2
        self.qr_dialog.move(max(10, x), max(10, y))

        self.qr_dialog.show()
        self.qr_dialog.raise_()
        self.qr_dialog.activateWindow()

    def _on_tunnel_url_ready(self, url: str):
        """外网隧道静默就绪，更新二维码数据"""
        logger.info(f"Cloudflare Tunnel Ready: {url}")
        if self.qr_dialog:
            self.qr_dialog.update_tunnel_url(url)

    def _on_tunnel_error(self, err_msg: str):
        """外网隧道异常日志 (静默处理，不弹窗打扰用户)"""
        logger.warning(f"Cloudflare Tunnel Notice: {err_msg}")

    def _update_mobile_status_display(self):
        """根据心跳维护的状态机更新顶部面板状态显示"""
        # 如果桌面分析正在运行，不显示手机协助状态，保持桌面对局提示信息
        if self.is_running:
            return

        # 如果手机协助未勾选开启，不处理
        if not (hasattr(self, 'mobile_assist_action') and self.mobile_assist_action.isChecked()):
            return

        import time
        now = time.time()
        
        # 8 秒内是否收到过心跳
        if self.mobile_last_heartbeat_time is not None and (now - self.mobile_last_heartbeat_time <= 8.0):
            data = self.mobile_last_heartbeat_data or {}
            network = str(data.get("network", "wifi")).lower()
            latency = data.get("latency", 0)
            
            if network == "wifi":
                text = f"🟢 手机已连接 · Wi-Fi 直连 ({latency} ms)"
                color = "#16A34A"  # 绿色
            else:
                text = f"🟡 手机已连接 · 蜂窝网络 ({latency} ms)"
                color = "#D97706"  # 琥珀黄
            self.update_text(text, MessageType.STATUS, color=color)
        else:
            if self.mobile_has_ever_connected:
                text = "⚪ 手机已断开连接"
                color = "#94A3B8"  # 灰色
            else:
                text = "⚪ 等待手机连接 (首次连接需扫码配对)"
                color = "#64748B"  # 浅灰色
            self.update_text(text, MessageType.STATUS, color=color)

    def _check_mobile_heartbeat_timeout(self):
        """每秒检查一次心跳是否超时"""
        self._update_mobile_status_display()

    def toggle_mobile_assist(self):
        """切换手机协助服务 (一键开启，内网+公网全自动静默就绪)"""
        is_checked = self.mobile_assist_action.isChecked()
        if is_checked:
            if self.mobile_server_thread is None:
                self.mobile_server_thread = MobileServerThread(port=5050)
                self.mobile_server_thread.start()
            
            # 初始化心跳状态机并启动 8 秒超时检测定时器
            self.mobile_has_ever_connected = False
            self.mobile_last_heartbeat_time = None
            self.mobile_last_heartbeat_data = None
            self._update_mobile_status_display()
            self.mobile_heartbeat_timer.start(1000)
            
            # 后台静默启动公网隧道 (用户无需手动配置)
            if self.tunnel_manager and not self.tunnel_manager.is_running:
                self.tunnel_manager.start(
                    on_url_ready=lambda url: self.tunnel_url_ready_signal.emit(url),
                    on_error=lambda err: self.tunnel_error_signal.emit(err)
                )

        else:
            self.mobile_heartbeat_timer.stop()
            self.mobile_has_ever_connected = False
            self.mobile_last_heartbeat_time = None
            self.mobile_last_heartbeat_data = None
            
            if self.tunnel_manager and self.tunnel_manager.is_running:
                self.tunnel_manager.stop()
            if self.qr_dialog is not None:
                self.qr_dialog.close()
            if self.mobile_server_thread is not None:
                self.mobile_server_thread.stop()
                self.mobile_server_thread = None
                if not self.is_running:
                    self.update_text("手机协助已关闭", MessageType.STATUS)

    def on_reposition(self):
        """处理重新定位选项"""
        # 手动定位前先停止当前运行的任务
        if self.is_running:
            self.on_stop()
            self.is_running = False
            self.start_btn.setText("开始")
        
        # 使用手动定位器开始定位
        self.manual_positioner.start_positioning()
    
    
    def event(self, event):
        """处理自定义事件"""
        if event.type() == CONFIRM_POSITION_EVENT and hasattr(self, 'cursor_pos_clicked'):
            # 从保存的属性获取光标位置
            cursor_pos = self.cursor_pos_clicked
            # 执行确认操作
            self.manual_positioner.confirm_position(cursor_pos)
            # 删除临时属性
            delattr(self, 'cursor_pos_clicked')
            return True
        elif event.type() == CANCEL_POSITION_EVENT:
            # 取消定位事件
            self.manual_positioner.cancel_positioning()
            return True
        return super().event(event)

    def on_manual_capture(self):
        """手动触发一次完整的监控与截图流程"""
        if self.capture_manager and self.is_running:
            # 设置手动触发标志
            self.capture_manager.manual_trigger = True
            # 执行一次完整的监控与截图流程
            success = self.capture_manager.manually_capture_once()
            if success:
                self.update_text("重置数据并重新分析...", MessageType.STATUS)
            else:
                self.update_text("重置失败", MessageType.ERROR)
        else:
            self.update_text("请先点击开始按钮", MessageType.STATUS)


    def on_change_move(self):
        """请求变招"""
        try:
             # 创建临时的 Processor 实例来处理请求
             # 注意：状态（checker, history）是共享的，所以可以这样做
             process = ChessProcess.from_context(context)
             
             # 异步执行，避免阻塞 UI
             import threading
             threading.Thread(target=process.request_alternative_move, daemon=True).start()
             
             self.update_text("正在计算变招...", MessageType.STATUS)
        except Exception as e:
             print(f"变招请求失败: {e}")
             self.update_text(f"变招失败: {e}", MessageType.ERROR)

    def on_mobile_clicked(self):
        """手机按钮点击（功能暂时搁置）"""
        logger.info("手机协助功能暂时搁置")
        self.update_text("手机功能暂未开放，敬请期待~", MessageType.STATUS)

    def show_param_menu(self):
        """显示参数菜单"""
        self.param_menu.exec_(self.param_btn.mapToGlobal(self.param_btn.rect().bottomLeft()))
    
    def on_param_selected(self, param):
        """处理参数选择"""
        # 更新选中状态
        self.depth_action.setChecked(param == "depth")
        self.movetime_action.setChecked(param == "movetime")
        
        self.engine_params["goParam"] = param
        self.param_label.setText(self.engine_params[param])
        context.update_engine_params(self.engine_params)

    def show_board_menu(self):
        """显示棋盘定位菜单"""
        self.board_menu.exec_(self.board_btn.mapToGlobal(self.board_btn.rect().bottomLeft()))
    
    def on_change_board_bg(self):
        """更换棋盘底图"""
        self.board_display.next_board()
        
    def on_change_pieces(self):
        """更换棋子样式版本"""
        new_style = self.board_display.next_pieces()
        logger.info(f"已切换棋子样式为: {new_style}")

    def _set_arrow_state(self, button, is_open):
        """动态更新按钮小三角状态（菜单展开时逆时针旋转90°，收起时复位）"""
        icon_name = 'arrow_rotated.png' if is_open else 'arrow_down.png'
        icon_path = resource_path('images', 'ui', icon_name)
        if os.path.exists(icon_path):
            button.setIcon(QIcon(icon_path))

    def update_icons(self):
        """更新下拉菜单小三角图标"""
        icon_path = resource_path('images', 'ui', 'arrow_down.png')
        arrow_icon = QIcon(icon_path)
        
        if hasattr(self, 'board_btn'):
            self.board_btn.setIcon(arrow_icon)
        if hasattr(self, 'settings_btn'):
            self.settings_btn.setIcon(arrow_icon)
        if hasattr(self, 'param_btn'):
            self.param_btn.setIcon(arrow_icon)
    
    def on_exit(self):
        """统一触发窗口关闭流程"""
        self.close()
    
    def show_game_menu(self):
        """显示游戏选择菜单"""
        self.game_menu.exec_(self.game_btn.mapToGlobal(self.game_btn.rect().bottomLeft()))
    
    def on_game_selected(self, game):
        """游戏选择回调"""
        # 更新选中状态
        self.jj_action.setChecked(game == "JJ象棋")
        self.tt_action.setChecked(game == "天天象棋")
        
        # 更新平台
        platform = "JJ" if game == "JJ象棋" else "TT"
        context.set_platform(platform)

    def closeEvent(self, event):
        """窗口关闭时处理（统一退出生命周期）"""
        if getattr(self, '_is_exiting', False):
            event.accept()
            return
        self._is_exiting = True

        # 阶段一：视觉即时关闭（0ms 响应感知）
        self.hide()

        # 阶段二：保存关键配置与停止前端定时器
        try:
            if hasattr(self, 'check_timer') and self.check_timer:
                self.check_timer.stop()
            if hasattr(self, 'mobile_heartbeat_timer') and self.mobile_heartbeat_timer:
                self.mobile_heartbeat_timer.stop()
            if hasattr(self, 'manual_positioner') and self.manual_positioner:
                self.manual_positioner.cleanup()
            if hasattr(self, 'qr_dialog') and self.qr_dialog:
                self.qr_dialog.close()

            context.save_config()
        except Exception as e:
            logger.warning(f"退出前置清理异常: {e}")

        # 阶段三：外部资源与后台任务快速清理
        try:
            if hasattr(self, 'tunnel_manager') and self.tunnel_manager:
                self.tunnel_manager.stop(fast=True)
            if hasattr(self, 'mobile_server_thread') and self.mobile_server_thread:
                self.mobile_server_thread.stop(fast=True)

            self.close_queue()
            context.quit_engine(fast=True)
        except Exception as e:
            logger.warning(f"退出后台清理异常: {e}")

        super().closeEvent(event)
        QApplication.quit()

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec()) 


# 定义一个自定义覆盖层类，直接处理鼠标事件
class OverlayWidget(QWidget):
    def __init__(self, parent=None, callback=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)  # 背景透明
        self.setWindowFlags(
            Qt.FramelessWindowHint | 
            Qt.WindowStaysOnTopHint | 
            Qt.Tool |
            Qt.X11BypassWindowManagerHint  # 绕过窗口管理器
        )
        self.callback = callback
        self.setCursor(Qt.CrossCursor)  # 设置十字光标，让用户知道这是可点击区域
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.callback:
            self.callback(QCursor.pos())
        super().mousePressEvent(event)
    
    def showEvent(self, event):
        """窗口显示时调用，确保窗口在最前方"""
        super().showEvent(event)
        self.raise_()  # 保持在最前方
        self.activateWindow()  # 激活窗口
        
    def focusOutEvent(self, event):
        """处理失去焦点的情况，保持窗口在最前方"""
        super().focusOutEvent(event)
        self.raise_()  # 保持在最前方
        self.activateWindow()  # 重新激活窗口

# 定义自定义事件类型
CONFIRM_POSITION_EVENT = QEvent.Type(QEvent.User)
CANCEL_POSITION_EVENT = QEvent.Type(QEvent.User + 1)

class ManualPositioner(QObject):
    """手动定位器 - 封装所有手动定位相关的功能"""
    
    def __init__(self, main_window):
        super().__init__()  # 调用QObject的初始化方法
        self.main_window = main_window
        self.context = context  # 直接使用全局的context
        
        # 定位状态
        self.is_positioning = False
        self.position_dot = None
        self.follow_cursor = False
        self.cursor_timer = None
        self.raise_timer = None
        self.mouse_listener = None
        
        # 手动定位相关状态
        self.positioning_step = 0  # 定位步骤：0-未开始，1-左上角，2-右下角
        self.positioning_coords = []  # 存储2个角的坐标
    
    def start_positioning(self):
        """开始手动定位"""
        print("开始手动定位")
        self.cancel_positioning()
        
        # 重置定位状态
        self.positioning_step = 1
        self.positioning_coords = []
        self.is_positioning = True
        self.follow_cursor = True
        
        # 创建临时定位点，跟随光标移动
        self.create_position_dot(is_temp=True)
        self.start_cursor_tracking()
        
        # 显示第一步提示
        self.main_window.text_display.setText('<span style="color: #FFFFFF;">第1步：点击棋盘左上角顶点<br>右键点击可取消定位</span>')
        
        # 初始化图标
        self.main_window.update_icons()

        # 启动鼠标监听
        self.start_mouse_listener()
        print("手动定位已启动")
    
    def cancel_positioning(self):
        """取消定位过程"""
        self.positioning_step = 0
        self.positioning_coords = []
        self.is_positioning = False
        self.follow_cursor = False
        self.stop_cursor_tracking()
        self.stop_mouse_listener()
        
        # 清理临时定位点
        self.cleanup_position_dot()
        
        self.main_window.text_display.setText('<span style="color: blue;">定位已取消</span>')
        print("手动定位已取消")
    
    def create_position_dot(self, is_temp=False, x=None, y=None):
        """创建定位点"""
        if self.position_dot:
            self.cleanup_position_dot()
        
        # 创建定位点
        self.position_dot = QLabel(None)
        
        # 设置窗口标志
        if is_temp:
            # 临时定位点：增强的窗口标志
            self.position_dot.setWindowFlags(
                Qt.FramelessWindowHint | 
                Qt.WindowStaysOnTopHint | 
                Qt.Tool |
                Qt.X11BypassWindowManagerHint |
                Qt.NoDropShadowWindowHint
            )
            self.position_dot.setAttribute(Qt.WA_ShowWithoutActivating)
            self.position_dot.setProperty("is_temp", True)
            self.position_dot.installEventFilter(self)
        else:
            # 正常定位点：基本窗口标志
            self.position_dot.setWindowFlags(
                Qt.FramelessWindowHint | 
                Qt.WindowStaysOnTopHint | 
                Qt.Tool |
                Qt.NoDropShadowWindowHint
            )
        
        # 通用属性设置
        self.position_dot.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.position_dot.setAttribute(Qt.WA_TranslucentBackground)
        
        # 加载定位点图片
        pixmap = QPixmap(resource_path('images', 'dingwei.png'))
        scaled_pixmap = pixmap.scaledToHeight(25, Qt.SmoothTransformation)
        width = scaled_pixmap.width()
        height = scaled_pixmap.height()
        
        # 确定位置
        if is_temp:
            # 临时定位点：跟随光标
            cursor_pos = QCursor.pos()
            window_x = cursor_pos.x() - width/2
            window_y = cursor_pos.y() - height/2
        elif x is not None and y is not None:
            # 指定坐标
            window_x = x - width/2
            window_y = y - height/2
        else:
            # 从配置读取坐标
            try:
                platform = self.context.get_platform(self.context.platform)
                board_region = platform.regions.get("board")
                
                if not board_region or 'x' not in board_region or 'y' not in board_region:
                    print("棋盘区域配置无效，无法创建定位点")
                    return
                    
                x = board_region['x']
                y = board_region['y']
                window_x = x - width/2
                window_y = y - height/2
            except Exception as e:
                print(f"创建定位点失败: {e}")
                return
        
        # 设置位置和显示
        self.position_dot.setGeometry(window_x, window_y, width, height)
        self.position_dot.setStyleSheet("background: transparent;")
        self.position_dot.setPixmap(scaled_pixmap)
        self.position_dot.show()
        self.position_dot.raise_()
        
        # 临时定位点的特殊处理
        if is_temp:
            self.position_dot.setWindowState(Qt.WindowActive)
    
    def cleanup_position_dot(self):
        """清理定位点"""
        if self.position_dot:
            try:
                if hasattr(self.position_dot, 'removeEventFilter'):
                    self.position_dot.removeEventFilter(self)
                self.position_dot.hide()
                self.position_dot.deleteLater()
                self.position_dot = None
            except Exception as e:
                print(f"清理定位点时出错: {e}")
    
    def is_temp_position_dot(self):
        """检查当前定位点是否为临时定位点"""
        return (self.position_dot and 
                hasattr(self.position_dot, 'property') and 
                self.position_dot.property("is_temp") == True)
    
    def start_cursor_tracking(self):
        """启动光标跟踪"""
        if self.cursor_timer is None:
            self.cursor_timer = QTimer()
            self.cursor_timer.timeout.connect(self.update_dot_position)
            self.cursor_timer.start(10)
            
        if not hasattr(self, 'raise_timer') or self.raise_timer is None:
            self.raise_timer = QTimer()
            self.raise_timer.timeout.connect(self.ensure_dot_on_top)
            self.raise_timer.start(100)
    
    def stop_cursor_tracking(self):
        """停止光标跟踪"""
        if self.cursor_timer:
            self.cursor_timer.stop()
            self.cursor_timer = None
        
        if hasattr(self, 'raise_timer') and self.raise_timer:
            self.raise_timer.stop()
            self.raise_timer = None
    
    def ensure_dot_on_top(self):
        """确保定位点保持在最前面"""
        if self.position_dot and self.is_temp_position_dot() and self.is_positioning:
            self.position_dot.raise_()
            self.position_dot.setWindowState(Qt.WindowActive)
    
    def eventFilter(self, obj, event):
        """事件过滤器，处理定位点的事件"""
        if obj == self.position_dot and self.is_temp_position_dot():
            if event.type() == QEvent.WindowActivate:
                self.position_dot.raise_()
                self.position_dot.setWindowState(Qt.WindowActive)
                return True
            elif event.type() == QEvent.WindowDeactivate:
                self.position_dot.raise_()
                self.position_dot.setWindowState(Qt.WindowActive)
                return True
            elif event.type() == QEvent.Show:
                self.position_dot.raise_()
                self.position_dot.setWindowState(Qt.WindowActive)
                return True
        return False
    
    def update_dot_position(self):
        """更新定位点位置，使图片中心与光标重合"""
        if self.position_dot and self.follow_cursor and self.is_temp_position_dot():
            cursor_pos = QCursor.pos()
            width = self.position_dot.width()
            height = self.position_dot.height()
            window_x = cursor_pos.x() - width/2
            window_y = cursor_pos.y() - height/2
            self.position_dot.move(window_x, window_y)
            self.position_dot.raise_()
            self.position_dot.setWindowState(Qt.WindowActive)
    
    def start_mouse_listener(self):
        """启动全局鼠标监听"""
        if self.mouse_listener:
            self.stop_mouse_listener()
        
        try:
            self.mouse_listener = mouse.Listener(on_click=self.on_mouse_click)
            self.mouse_listener.start()
            
            # 检查监听器线程是否存活 (如果因权限问题立即退出)
            if not self.mouse_listener.is_alive():
                 raise Exception("监听器启动失败(可能未获得辅助功能权限)")
                 
        except Exception as e:
            print(f"启动鼠标监听失败: {e}")
            self.main_window.update_text("无法启动鼠标监听，请检查 系统设置->隐私与安全性->辅助功能", MessageType.ERROR)
            
            # 尝试打开系统设置辅助功能页面 (仅尝试，不保证成功)
            import subprocess
            try:
                subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])
            except:
                pass
                
            self.cancel_positioning()
    
    def stop_mouse_listener(self):
        """停止全局鼠标监听"""
        if self.mouse_listener and self.mouse_listener.is_alive():
            self.mouse_listener.stop()
            self.mouse_listener = None
    
    def on_mouse_click(self, x, y, button, pressed):
        """处理全局鼠标点击事件"""
        if not self.is_positioning:
            return True
            
        # 只处理按下事件
        if not pressed:
            return True

        print(f"Mouse click detected: {button} at {x}, {y}")
            
        if button == mouse.Button.left:
            # 左键点击：确认位置
            cursor_pos = QPoint(int(x), int(y)) # 确保坐标是整数
            # 将该操作切换到主线程执行
            self.main_window.cursor_pos_clicked = cursor_pos
            QApplication.instance().postEvent(self.main_window, QEvent(CONFIRM_POSITION_EVENT))
            return True # 继续监听，直到逻辑决定停止
        elif button == mouse.Button.right:
            # 右键点击：取消定位
            print("Right click detected, posting cancel event")
            QApplication.instance().postEvent(self.main_window, QEvent(CANCEL_POSITION_EVENT))
            return False # 停止监听
        return True
    
    def confirm_position(self, cursor_pos):
        """确认位置，处理2角定位逻辑"""
        x = cursor_pos.x()
        y = cursor_pos.y()
        
        if self.positioning_step == 1:
            # 第1步：左上角
            self.positioning_coords.append((x, y))
            self.positioning_step = 2
            self.main_window.text_display.setText('<span style="color: orange;">第2步：点击棋盘右下角顶点<br>右键点击可取消定位</span>')
            
            # 确保定位点继续跟随光标
            if self.position_dot and self.follow_cursor:
                self.start_cursor_tracking()
            
        elif self.positioning_step == 2:
            # 第2步：右下角
            self.positioning_coords.append((x, y))
            
            # 完成2角定位，计算棋盘区域
            try:
                success = self.process_two_corner_positioning()
            except Exception as e:
                print(f'2角定位处理失败: {e}')
                success = False
            
            # 重置定位状态
            self.is_positioning = False
            self.follow_cursor = False
            self.stop_cursor_tracking()
            self.stop_mouse_listener()
            
            if success:
                # 创建并显示定位点（使用左上角坐标）
                left_top = self.positioning_coords[0]
                self.create_position_dot(is_temp=False, x=left_top[0], y=left_top[1])
                self.main_window.text_display.setText('<span style="color: green;">2角定位完成!</span>')
            else:
                # 定位失败，显示错误信息
                self.main_window.text_display.setText('<span style="color: #FFFFFF;">2角定位失败，请重试</span>')
                # 重置定位状态，允许重新开始
                self.positioning_step = 0
                self.positioning_coords = []
    
    def process_two_corner_positioning(self):
        """处理2角定位，计算棋盘区域并更新配置"""
        if len(self.positioning_coords) != 2:
            print("2角定位坐标不足")
            return False
        
        # 解包2个角的坐标
        left_top = self.positioning_coords[0]
        right_bottom = self.positioning_coords[1]
        
        # 计算棋盘区域
        x = left_top[0]  # 左上角x坐标
        y = left_top[1]  # 左上角y坐标
        width = right_bottom[0] - left_top[0]  # 宽度
        height = right_bottom[1] - left_top[1]  # 高度
        
        # 验证棋盘尺寸的合理性
        if width < 200 or height < 200:
            print(f"棋盘尺寸过小: {width}x{height}")
            return False
        
        # 创建棋盘区域配置（使用x, y, width, height格式）
        board_region = {
            'x': x,
            'y': y,
            'width': width,
            'height': height
        }
        
        try:
            # 更新当前平台的棋盘区域配置
            platform = self.context.get_platform(self.context.platform)
            platform.regions["board"] = board_region
            
            manual_coords = (x, y, width, height)
            self.context.manual_coords = manual_coords
            # 保存配置
            self.context.save_config()
            
            print(f"2角定位成功，棋盘区域: {board_region}")
            return True
            
        except Exception as e:
            print(f"更新棋盘区域配置失败: {e}")
            return False
    
    def cleanup(self):
        """清理资源"""
        self.cancel_positioning()