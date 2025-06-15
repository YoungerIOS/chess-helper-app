from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QApplication, QMenu)
from PySide6.QtCore import Qt, QSize, QPoint, QTimer, QEvent
from PySide6.QtGui import QFont, QKeyEvent, QCursor, QPixmap, QIcon
import os
import queue
import threading
import sys
from chess.screenshot import capture_region, get_position, trigger_manual_recognition
from chess import engine
from ui.board_display import BoardDisplay
from chess.message import Message, MessageType
from chess.context import context
from ui.board_display import BoardDisplay
from pynput import mouse

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

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("象棋助手")
        
        # 获取屏幕信息
        screen = QApplication.primaryScreen()
        screen_height = screen.size().height()
        
        # 加载棋盘图片并计算其宽高比
        board_img = QPixmap(os.path.join('app', 'images', 'media', 'chessboard.png'))
        board_ratio = board_img.width() / board_img.height()
        
        # 使用屏幕高度 x 80% x 0.56 计算窗口宽度, 不为什么, 就是觉得协调,
        nice_height = int(screen_height * 0.8)
        width = int(nice_height * 0.56)
        
        # 计算棋盘图片在窗口中的实际高度
        board_height = int(width / board_ratio)
        
        # 计算其他UI元素的总高度
        other_heights = (
            100 +  # 顶部文本显示区域
            35 +   # 中间按钮行
            35 +   # 底部控制区域
            30     # 布局间距
        )
        
        # 设置窗口高度为棋盘高度加上其他UI元素的高度
        height = board_height + other_heights
        
        print(f"Screen height: {screen_height}")
        print(f"Window size: {width}x{height}")
        
        # 设置窗口固定大小
        self.setFixedSize(width, height)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)  # 减小整体间距
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 初始化上下文
        context.load_config()
        self.engine_params = context.get_engine_params()
        
        # 顶部文本显示区域
        self.move_display = QLabel('<span style="color: red;">等待获取棋局...</span>')
        self.move_display.setAlignment(Qt.AlignCenter)
        self.move_display.setFont(QFont("Arial", 18, QFont.Bold))
        self.move_display.setFixedHeight(100)  # 设置固定高度
        self.move_display.setStyleSheet("""
            QLabel {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 3px;
                line-height: 1.2;  /* 减小行间距 */
            }
        """)
        main_layout.addWidget(self.move_display)
        
        # 添加中间按钮行
        middle_buttons_layout = QHBoxLayout()
        middle_buttons_layout.setSpacing(5)
        middle_buttons_layout.setContentsMargins(0, 0, 0, 0)  # 移除底部边距，保持与主布局间距一致
        
        # 创建游戏选择按钮
        self.game_btn = QPushButton("游戏平台")
        self.game_btn.setFixedSize(75, 35) 
        self.game_btn.setFont(QFont("Arial", 11))
        # 加载并设置箭头图标
        arrow_icon = QIcon('app/images/pulldown_arrow.png')
        self.game_btn.setIcon(arrow_icon)
        self.game_btn.setIconSize(QSize(12, 12))
        self.game_btn.setStyleSheet("""
            QPushButton {
                background-color: #1874CD;
                color: white;
                border: 1px solid #1874CD;
                border-radius: 5px;
                text-align: center;
                padding: 0px 8px;  /* 左右padding设为8px */
                margin: 0px;
            }
            QPushButton:hover {
                background-color: #1565c0;
                border: 1px solid #1565c0;
            }
            QPushButton:pressed {
                background-color: #0d47a1;
                border: 1px solid #0d47a1;
            }
        """)
        self.game_btn.clicked.connect(self.show_game_menu)
        middle_buttons_layout.addWidget(self.game_btn)
        
        # 创建游戏选择菜单
        self.game_menu = QMenu(self)
        self.game_menu.setStyleSheet("""
            QMenu {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 2px;
            }
            QMenu::item {
                padding: 5px 10px;
                min-height: 20px;
                color: black;
            }
            QMenu::item:selected {
                background-color: #e0e0e0;
            }
            QMenu::item:checked {
                background-color: #e0e0e0;
            }
        """)
        self.jj_action = self.game_menu.addAction("JJ象棋")
        self.tt_action = self.game_menu.addAction("天天象棋")
        self.jj_action.setCheckable(True)
        self.tt_action.setCheckable(True)
        self.jj_action.triggered.connect(lambda: self.on_game_selected("JJ象棋"))
        self.tt_action.triggered.connect(lambda: self.on_game_selected("天天象棋"))
        
        # 设置初始选中状态
        if context.platform == "JJ":
            self.jj_action.setChecked(True)
        else:
            self.tt_action.setChecked(True)
        
        # 创建棋盘定位按钮 - 改为普通按钮直接调用重新定位功能
        self.board_btn = QPushButton("棋盘定位")
        self.board_btn.setFixedSize(75, 35)  # 与游戏平台按钮保持一致
        self.board_btn.setFont(QFont("Arial", 11))
        self.board_btn.setStyleSheet("""
            QPushButton {
                background-color: #1874CD;
                color: white;
                border: 1px solid #1874CD;
                border-radius: 5px;
                text-align: center;
                padding: 0px;
                margin: 0px;
            }
            QPushButton:hover {
                background-color: #1565c0;
                border: 1px solid #1565c0;
            }
            QPushButton:pressed {
                background-color: #0d47a1;
                border: 1px solid #0d47a1;
            }
        """)
        # 直接连接到重新定位功能
        self.board_btn.clicked.connect(self.on_reposition)
        middle_buttons_layout.addWidget(self.board_btn)
        
        # 添加其他按钮
        other_buttons = [
            ("开始", self.on_start),  # 将开始/停止功能移到按钮3
        ]
        
        for text, callback in other_buttons:
            btn = QPushButton(text)
            btn.setMinimumHeight(35)
            btn.setFont(QFont("Arial", 11))
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #1874CD;
                    color: white;
                    border: 1px solid #1874CD;
                    border-radius: 5px;
                    padding: 0px;
                    margin: 0px;
                }
                QPushButton:hover {
                    background-color: #1565c0;
                    border: 1px solid #1565c0;
                }
                QPushButton:pressed {
                    background-color: #0d47a1;
                    border: 1px solid #0d47a1;
                }
            """)
            if callback:  # 只有当callback不为None时才连接点击事件
                btn.clicked.connect(callback)
            middle_buttons_layout.addWidget(btn)
        
        main_layout.addLayout(middle_buttons_layout)
        
        # 中间棋盘区域
        self.board_display = BoardDisplay()
        # 移除固定高度设置，让棋盘自适应图片大小
        self.board_display.setStyleSheet("""
            QWidget {
                background-color: #4F4F4F;
                border: 1px solid #4F4F4F;
                border-radius: 5px;
            }
        """)
        main_layout.addWidget(self.board_display)
        
        # 底部控制区域
        control_layout = QHBoxLayout()
        control_layout.setSpacing(5)
        control_layout.setContentsMargins(0, 0, 0, 0)  # 移除内边距
        
        # 创建控制按钮
        buttons = [
            ("按钮", None),  # 移除回调函数
            ("手动", self.on_manual_analyze),
        ]
        
        for text, callback in buttons:
            btn = QPushButton(text)
            btn.setMinimumHeight(35)
            btn.setFont(QFont("Arial", 11))
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #1874CD;
                    color: white;
                    border: 1px solid #1874CD;
                    border-radius: 5px;
                    padding: 0px;
                    margin: 0px;
                }
                QPushButton:hover {
                    background-color: #1565c0;
                    border: 1px solid #1565c0;
                }
                QPushButton:pressed {
                    background-color: #0d47a1;
                    border: 1px solid #0d47a1;
                }
            """)
            if callback:  # 只有当callback不为None时才连接点击事件
                btn.clicked.connect(callback)
            control_layout.addWidget(btn)
        
        # 创建"其他设置"按钮
        self.settings_btn = QPushButton("其他设置") 
        self.settings_btn.setFixedSize(75, 35)  
        self.settings_btn.setFont(QFont("Arial", 11))
        # 加载并设置箭头图标
        arrow_icon = QIcon('app/images/pulldown_arrow.png')
        self.settings_btn.setIcon(arrow_icon)
        self.settings_btn.setIconSize(QSize(12, 12))
        self.settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #1874CD;
                color: white;
                border: 1px solid #1874CD;
                border-radius: 5px;
                text-align: center;
                padding: 0px 8px;  /* 左右padding设为8px */
                margin: 0px;
            }
            QPushButton:hover {
                background-color: #1565c0;
                border: 1px solid #1565c0;
            }
            QPushButton:pressed {
                background-color: #0d47a1;
                border: 1px solid #0d47a1;
            }
        """)
        # 不再使用checkable属性
        self.is_dot_visible = True # 添加一个状态变量来跟踪原点是否可见
        self.settings_btn.clicked.connect(self.show_settings_menu)
        control_layout.addWidget(self.settings_btn)
        
        # 创建设置菜单
        self.settings_menu = QMenu(self)
        self.settings_menu.setStyleSheet("""
            QMenu {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 2px;
            }
            QMenu::item {
                padding: 5px 10px;
                min-height: 20px;
                color: black;
            }
            QMenu::item:selected {
                background-color: #e0e0e0;
            }
            QMenu::item:checked {
                background-color: #e0e0e0;
            }
        """)
        self.show_dot_action = self.settings_menu.addAction("显示原点")
        self.continuous_action = self.settings_menu.addAction("连续识别")
        self.timer_action = self.settings_menu.addAction("计时识别")
        # 设置菜单项可选中
        self.show_dot_action.setCheckable(True)
        self.continuous_action.setCheckable(True)
        self.timer_action.setCheckable(True)
        # 设置初始选中状态
        self.show_dot_action.setChecked(True)  # 初始时原点显示
        self.continuous_action.setChecked(context.analysis_mode == "continuous")  # 根据配置设置初始状态
        self.timer_action.setChecked(context.analysis_mode == "timer")  # 根据配置设置初始状态
        self.show_dot_action.triggered.connect(self.toggle_show_dot)
        self.continuous_action.triggered.connect(self.toggle_continuous)
        self.timer_action.triggered.connect(self.toggle_timer)
        
        # 创建参数选择按钮
        self.param_btn = QPushButton("参数")
        self.param_btn.setFixedSize(55, 35)  
        self.param_btn.setFont(QFont("Arial", 11))
        # 加载并设置箭头图标
        arrow_icon = QIcon('app/images/pulldown_arrow.png')
        self.param_btn.setIcon(arrow_icon)
        self.param_btn.setIconSize(QSize(12, 12))
        self.param_btn.setStyleSheet("""
            QPushButton {
                background-color: #1874CD;
                color: white;
                border: 1px solid #1874CD;
                border-radius: 5px;
                text-align: center;
                padding: 0px 8px;  /* 左右padding设为8px */
                margin: 0px;
            }
            QPushButton:hover {
                background-color: #1565c0;
                border: 1px solid #1565c0;
            }
            QPushButton:pressed {
                background-color: #0d47a1;
                border: 1px solid #0d47a1;
            }
        """)
        self.param_btn.clicked.connect(self.show_param_menu)
        control_layout.addWidget(self.param_btn)
        
        # 创建参数菜单
        self.param_menu = QMenu(self)
        self.param_menu.setStyleSheet("""
            QMenu {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 2px;
            }
            QMenu::item {
                padding: 5px 10px;
                min-height: 20px;
                color: black;
            }
            QMenu::item:selected {
                background-color: #e0e0e0;
            }
            QMenu::item:checked {
                background-color: #e0e0e0;
            }
        """)
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
        
        # 创建参数调整按钮
        param_layout = QHBoxLayout()
        param_layout.setSpacing(2)
        
        self.decrease_btn = QPushButton("-")
        self.decrease_btn.setFixedSize(20, 35) 
        self.decrease_btn.setFont(QFont("Arial", 11))
        self.decrease_btn.setStyleSheet("""
            QPushButton {
                background-color: #1874CD;
                color: white;
                border: 1px solid #1874CD;
                border-radius: 5px;
                padding: 0px;
                margin: 0px;
            }
            QPushButton:hover {
                background-color: #1565c0;
                border: 1px solid #1565c0;
            }
            QPushButton:pressed {
                background-color: #0d47a1;
                border: 1px solid #0d47a1;
            }
        """)
        self.decrease_btn.clicked.connect(self.on_decrease_param)
        param_layout.addWidget(self.decrease_btn)
        
        self.param_label = QLabel(self.engine_params[self.engine_params["goParam"]])
        self.param_label.setAlignment(Qt.AlignCenter)
        self.param_label.setFixedHeight(35)
        self.param_label.setStyleSheet("""
            QLabel {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 0px;
                margin: 0px;
                color: black;
            }
        """)
        param_layout.addWidget(self.param_label)
        
        self.increase_btn = QPushButton("+")
        self.increase_btn.setFixedSize(20, 35) 
        self.increase_btn.setFont(QFont("Arial", 11))
        self.increase_btn.setStyleSheet("""
            QPushButton {
                background-color: #1874CD;
                color: white;
                border: 1px solid #1874CD;
                border-radius: 5px;
                padding: 0px;
                margin: 0px;
            }
            QPushButton:hover {
                background-color: #1565c0;
                border: 1px solid #1565c0;
            }
            QPushButton:pressed {
                background-color: #0d47a1;
                border: 1px solid #0d47a1;
            }
        """)
        self.increase_btn.clicked.connect(self.on_increase_param)
        param_layout.addWidget(self.increase_btn)
        
        control_layout.addLayout(param_layout)
        main_layout.addLayout(control_layout)
        
        # 初始化定位状态
        self.is_positioning = False
        self.position_dot = None
        self.is_show_dot = True
        self.follow_cursor = False  # 新增：是否跟随光标
        self.cursor_timer = None    # 新增：光标跟踪定时器
        self.mouse_listener = None  # 新增：鼠标事件监听器
        
        # 显示定位点
        self.create_position_dot()
        
        # 初始化线程和队列
        self.stop_event = threading.Event()
        self.result_queue = queue.Queue()
        self.capture_thread = None
        self.check_timer = None

        # 初始化状态
        self.is_running = False
        self.lines = ["", "", ""]
    
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
            self.sender().setText("停止")
            # 初始化局面检查器
            context.init_position_checker()
            self.create_queue()
        else:
            self.is_running = False
            self.sender().setText("开始")
            # 设置事件，通知capture_region线程停止
            self.stop_event.set()
            # 等待线程结束
            if self.capture_thread and self.capture_thread.is_alive():
                self.capture_thread.join()
            # 关闭引擎进程
            engine.terminate_engine()
            # 在所有操作完成后，再清理局面检查器
            context.clear_position_checker()
    
    def on_stop(self):
        """停止分析"""
        self.stop_analysis()
        self.is_running = False
        self.sender().setText("开始")
    
    def create_queue(self):
        """创建队列和启动分析线程"""
        # 首先停止之前的线程（如果有的话）  
        if self.capture_thread is not None and self.capture_thread.is_alive():  
            self.stop_event.set()  # 通知正在运行的线程停止  
            self.capture_thread.join()  # 等待线程结束  
    
        # 重置停止事件  
        self.stop_event.clear() 

        #创建一个线程和队列,用于执行截图和返回引擎计算结果
        self.result_queue = queue.Queue()  
        self.capture_thread = threading.Thread(target=self.capture_func)  
        self.capture_thread.start()
        # 创建一个定时器来定期检查队列  
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_queue)
        self.check_timer.start(100)
    
    def capture_func(self):
        """截图和分析函数"""
        capture_region(self.result_queue, self.stop_event)
    
    def check_queue(self):
        """检查结果队列"""
        if not self.result_queue.empty():
            result = self.result_queue.get()
            if isinstance(result, Message):
                if result.type == MessageType.CHANGE:
                    # 显示棋局
                    self.board_display.update_board_with_array(
                        result.kwargs['position'], 
                        red_changes=result.kwargs.get('red_changes', []),
                        black_changes=result.kwargs.get('black_changes', [])
                    )
                    self.update_text(result.content)
                elif result.type == MessageType.MOVE_CODE:
                    # 显示着法箭头
                    self.board_display.update_move_arrow(result.content, result.kwargs['is_red'])
                elif result.type == MessageType.MOVE_TEXT:
                    # 显示着法文本
                    self.update_text(result.content)
                elif result.type == MessageType.STATUS:
                    # 显示状态消息
                    self.update_text(result.content)
    
    def update_text(self, text):
        """更新显示文本"""
        if len(text) == 4:
            self.lines = ["", "", text]  # 只保留第一行和第三行
        else:
            self.lines = [text, "", self.lines[2]]
        
        # 更新显示
        display_text = ""
        for i, line in enumerate(self.lines):
            if i == 0:
                display_text += f'<span style="color: red; font-size: 18pt; line-height: 1;">{line}</span><br>'
            elif i == 2:
                display_text += f'<span style="color: black; font-size: 45pt; line-height: 1;">{line}</span>'
        
        self.move_display.setText(display_text)
        
        # 如果是着法，闪烁显示
        if len(text) == 4:
            self.flash_text()
    
    def flash_text(self):
        """闪烁显示文本"""
        # 保存原始文本
        original_text = self.move_display.text()
        
        # 闪烁三次
        for i in range(3):
            # 红色
            self.move_display.setStyleSheet("""
                QLabel {
                    background-color: #f0f0f0;
                    border: 1px solid #ccc;
                    border-radius: 5px;
                    padding: 10px;
                    min-height: 45px;
                    color: red;
                }
            """)
            QApplication.processEvents()
            QTimer.singleShot(200, lambda: None)
            
            # 白色
            self.move_display.setStyleSheet("""
                QLabel {
                    background-color: #f0f0f0;
                    border: 1px solid #ccc;
                    border-radius: 5px;
                    padding: 10px;
                    min-height: 45px;
                    color: white;
                }
            """)
            QApplication.processEvents()
            QTimer.singleShot(200, lambda: None)
        
        # 恢复原始样式
        self.move_display.setStyleSheet("""
            QLabel {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 3px;
            }
        """)
        self.move_display.setText(original_text)
    
    def create_position_dot(self):
        """创建定位点"""
        # 移除旧的定位点（如果存在）
        if self.position_dot:
            self.position_dot.close()
            self.position_dot = None
            
        # 从上下文获取区域配置
        platform = context.get_platform(context.platform)
        board_region = platform.regions["board"]
        x = board_region['left']
        y = board_region['top']
            
        self.position_dot = QLabel(None)  # 创建为独立窗口
        # 设置窗口标志：无边框、置顶、不可交互
        self.position_dot.setWindowFlags(
            Qt.FramelessWindowHint | 
            Qt.WindowStaysOnTopHint | 
            Qt.Tool |  # 工具窗口，不显示在任务栏
            Qt.NoDropShadowWindowHint  # 无阴影
        )
        self.position_dot.setAttribute(Qt.WA_TransparentForMouseEvents)  # 鼠标事件穿透
        self.position_dot.setAttribute(Qt.WA_TranslucentBackground)  # 背景透明
        
        # 设置窗口大小为 15x25，保持原始宽高比
        width = 15
        height = 25
        
        # 调整窗口位置，使图片底部中心点与坐标点重合
        window_x = x - width // 2
        window_y = y - height - 5  # 在这里添加偏移
        
        self.position_dot.setGeometry(window_x, window_y, width, height)
        
        # 设置背景透明
        self.position_dot.setStyleSheet("background: transparent;")
        
        # 加载并显示图片
        pixmap = QPixmap('app/images/dingding.png')
        scaled_pixmap = pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.position_dot.setPixmap(scaled_pixmap)
        
        self.position_dot.show()
        self.position_dot.raise_()  # 确保显示在最上层
        
        # 如果处于跟随模式，启动定时器
        if self.follow_cursor:
            self.start_cursor_tracking()
    
    def start_cursor_tracking(self):
        """启动光标跟踪"""
        if self.cursor_timer is None:
            self.cursor_timer = QTimer()
            self.cursor_timer.timeout.connect(self.update_dot_position)
            self.cursor_timer.start(10)  # 每10毫秒更新一次位置
    
    def stop_cursor_tracking(self):
        """停止光标跟踪"""
        if self.cursor_timer:
            self.cursor_timer.stop()
            self.cursor_timer = None
    
    def update_dot_position(self):
        """更新定位点位置"""
        if self.position_dot and self.follow_cursor:
            cursor_pos = QCursor.pos()
            width = 15
            height = 25
            window_x = cursor_pos.x() - width // 2
            window_y = cursor_pos.y() - height - 5  # 保持一致的偏移
            self.position_dot.move(window_x, window_y)
    
    def show_settings_menu(self):
        """显示设置菜单"""
        self.settings_menu.exec_(self.settings_btn.mapToGlobal(self.settings_btn.rect().bottomLeft()))

    def toggle_show_dot(self):
        """切换显示/隐藏原点"""
        if self.is_dot_visible:
            # 当前原点可见，点击后隐藏原点
            if self.position_dot:
                self.position_dot.close()
                self.position_dot = None
            self.is_dot_visible = False
            self.show_dot_action.setChecked(False)
        else:
            # 当前原点隐藏，点击后显示原点
            self.create_position_dot()
            self.is_dot_visible = True
            self.show_dot_action.setChecked(True)

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

    def on_reposition(self):
        """处理重新定位选项"""
        self.move_display.setText('<span style="color: red;">将光标移到棋盘左上角，<br>点击鼠标左键或按S键确认</span>')
        self.is_positioning = True
        self.follow_cursor = True  # 重新定位时跟随光标
        self.start_cursor_tracking()  # 开始跟踪
        
        # 启动鼠标监听
        self.start_mouse_listener()
    
    def start_mouse_listener(self):
        """启动全局鼠标监听"""
        # 如果已经有一个监听器在运行，先停止它
        if self.mouse_listener:
            self.stop_mouse_listener()
        
        # 创建新的监听器
        self.mouse_listener = mouse.Listener(on_click=self.on_mouse_click)
        # 启动监听线程
        self.mouse_listener.start()
    
    def stop_mouse_listener(self):
        """停止全局鼠标监听"""
        if self.mouse_listener and self.mouse_listener.is_alive():
            self.mouse_listener.stop()
            self.mouse_listener = None
    
    def on_mouse_click(self, x, y, button, pressed):
        """处理全局鼠标点击事件"""
        # 只响应鼠标左键按下事件，并且仅在定位模式时生效
        if button == mouse.Button.left and pressed and self.is_positioning:
            # 获取点击位置并调用确认方法
            cursor_pos = QPoint(x, y)
            # 将该操作切换到主线程执行
            QApplication.instance().postEvent(self, QEvent(QEvent.User))
            # 在事件处理函数中处理
            self.cursor_pos_clicked = cursor_pos  # 保存点击位置
            return False  # 停止监听
        return True  # 继续监听
    
    def event(self, event):
        """处理自定义事件"""
        if event.type() == QEvent.User and hasattr(self, 'cursor_pos_clicked'):
            # 从保存的属性获取光标位置
            cursor_pos = self.cursor_pos_clicked
            # 执行确认操作
            self.confirm_position(cursor_pos)
            # 删除临时属性
            delattr(self, 'cursor_pos_clicked')
            return True
        return super().event(event)
    
    def confirm_position(self, cursor_pos):
        """确认位置，处理共同逻辑"""
        # 直接使用光标位置
        x = cursor_pos.x()
        y = cursor_pos.y()
        
        # 使用get_position保存坐标
        get_position(x, y)
        
        # 重置定位状态
        self.is_positioning = False
        self.follow_cursor = False  # 禁用光标跟踪
        self.stop_cursor_tracking()  # 停止跟踪
        
        # 停止鼠标监听
        self.stop_mouse_listener()
        
        # 创建并显示定位点
        if self.position_dot:
            self.position_dot.close()
            self.position_dot = None
        
        self.position_dot = QLabel(None)
        self.position_dot.setWindowFlags(
            Qt.FramelessWindowHint | 
            Qt.WindowStaysOnTopHint | 
            Qt.Tool |
            Qt.NoDropShadowWindowHint
        )
        self.position_dot.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.position_dot.setAttribute(Qt.WA_TranslucentBackground)
        
        width = 15
        height = 25
        window_x = cursor_pos.x() - width // 2
        window_y = cursor_pos.y() - height - 5  # 在这里添加偏移
        
        self.position_dot.setGeometry(window_x, window_y, width, height)
        self.position_dot.setStyleSheet("background: transparent;")
        
        pixmap = QPixmap('app/images/dingding.png')
        scaled_pixmap = pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.position_dot.setPixmap(scaled_pixmap)
        
        self.position_dot.show()
        self.position_dot.raise_()  # 确保显示在最前方
        
        # 更新定位点状态
        self.is_dot_visible = True
        self.move_display.setText('<span style="color: green;">定位完成!</span>')
    
    def keyPressEvent(self, event: QKeyEvent):
        """处理键盘事件"""
        if self.is_positioning and event.key() == Qt.Key_S:
            # 获取当前光标位置
            cursor_pos = QCursor.pos()
            # 使用共同确认逻辑
            self.confirm_position(cursor_pos)
    
    def stop_analysis(self):
        """停止分析线程"""
        if self.capture_thread and self.capture_thread.is_alive():
            self.stop_event.set()
            self.capture_thread.join()
        
        if self.check_timer:
            self.check_timer.stop()
            self.check_timer = None
        
        # 关闭引擎
        engine.terminate_engine() 

    def on_manual_analyze(self):
        """手动触发识别"""
        trigger_manual_recognition()

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
        
        # 更新定位点
        self.create_position_dot()

    def closeEvent(self, event):
        """窗口关闭时处理"""
        # 停止所有线程和监听器
        self.stop_mouse_listener()
        self.stop_analysis()
        super().closeEvent(event)

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec()) 
