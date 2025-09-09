from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QApplication, QMenu)
from PySide6.QtCore import Qt, QSize, QPoint, QTimer, QEvent, QObject
from PySide6.QtGui import QFont, QKeyEvent, QCursor, QPixmap, QIcon
import os
import queue
import threading
import sys
from chess.screenshot import ChessCaptureManager
from chess.engine import ChessEngine
from chess.history import MoveHistory
from chess.message import Message, MessageType
from chess.context import context
from ui.board_display import BoardDisplay
from pynput import mouse


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("象棋助手")
        
        # 获取屏幕信息
        screen = QApplication.primaryScreen()
        screen_height = screen.size().height()
        screen_width = screen.size().width()
        
        # 将屏幕尺寸保存到上下文对象中，供其他模块使用
        context.screen_size = (screen_width, screen_height)
        
        # 加载棋盘图片并计算其宽高比
        board_img = QPixmap(os.path.join('app', 'images', 'media', 'chessboard1.png'))
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
        
        # 创建手动刷新按钮
        self.manual_refresh_btn = QPushButton("手动刷新")
        self.manual_refresh_btn.setFixedSize(75, 35)  # 与游戏平台按钮保持一致
        self.manual_refresh_btn.setFont(QFont("Arial", 11))
        self.manual_refresh_btn.setStyleSheet("""
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
        # 连接到手动刷新功能
        self.manual_refresh_btn.clicked.connect(self.on_manual_capture)
        middle_buttons_layout.addWidget(self.manual_refresh_btn)
        
        # 添加其他按钮
        self.start_btn = QPushButton("开始")
        self.start_btn.setMinimumHeight(35)
        self.start_btn.setFont(QFont("Arial", 11))
        self.start_btn.setStyleSheet("""
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
        self.start_btn.clicked.connect(self.on_start)
        middle_buttons_layout.addWidget(self.start_btn)
        
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
        
        # 创建退出按钮
        self.exit_btn = QPushButton("退出")
        self.exit_btn.setMinimumHeight(35)
        self.exit_btn.setFont(QFont("Arial", 11))
        self.exit_btn.setStyleSheet("""
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
        self.exit_btn.clicked.connect(self.on_exit)
        control_layout.addWidget(self.exit_btn)
        
        # 创建棋盘定位按钮 - 改为下拉菜单样式
        self.board_btn = QPushButton("棋盘设置")
        self.board_btn.setFixedSize(75, 35)  
        self.board_btn.setFont(QFont("Arial", 11))
        # 加载并设置箭头图标
        arrow_icon = QIcon('app/images/pulldown_arrow.png')
        self.board_btn.setIcon(arrow_icon)
        self.board_btn.setIconSize(QSize(12, 12))
        self.board_btn.setStyleSheet("""
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
        self.board_btn.clicked.connect(self.show_board_menu)
        control_layout.addWidget(self.board_btn)
        
        # 创建棋盘设置菜单
        self.board_menu = QMenu(self)
        self.board_menu.setStyleSheet("""
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
        """)
        self.manual_position_action = self.board_menu.addAction("手动定位")
        self.change_board_action = self.board_menu.addAction("更换棋盘")
        self.manual_position_action.triggered.connect(self.on_reposition)
        self.change_board_action.triggered.connect(self.on_change_board_bg)
        
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
        self.continuous_action = self.settings_menu.addAction("连续识别")
        self.timer_action = self.settings_menu.addAction("计时识别")
        # 设置菜单项可选中
        self.continuous_action.setCheckable(True)
        self.timer_action.setCheckable(True)
        # 设置初始选中状态
        self.continuous_action.setChecked(context.analysis_mode == "continuous")  # 根据配置设置初始状态
        self.timer_action.setChecked(context.analysis_mode == "timer")  # 根据配置设置初始状态
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
        
        self.decrease_btn = QPushButton("−")
        self.decrease_btn.setFixedSize(20, 35) 
        self.decrease_btn.setFont(QFont("Arial", 16))
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
        self.increase_btn.setFont(QFont("Arial", 16))
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
        
        # 初始化线程和队列
        self.ui_message_queue = queue.Queue()
        self.capture_thread = None
        self.check_timer = None
        # 初始化截图管理器
        self.capture_manager = ChessCaptureManager(self.ui_message_queue)
        # 初始化手动定位器
        self.manual_positioner = ManualPositioner(self)

        # 初始化状态
        self.is_running = False
        self.is_stopping = False  # 添加停止标志，防止手动停止与自动停止冲突
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
            self.start_btn.setText("停止")
            self.create_queue()
        else:
            self.on_stop()
            self.is_running = False
            self.start_btn.setText("开始")
 
    def on_stop(self):
        """停止事件"""
        if self.is_stopping: 
            return
        self.is_stopping = True
        
        self.close_queue()
        if context.engine:
            context.engine.stop()
            context.engine = None
        context.clear_checker() #清理局面检查器
        context.history.clear()  # 停止时清空历史
        
        self.is_stopping = False 

    def create_queue(self):
        """创建队列和启动分析线程"""
        # 首先停止旧线程（如果有的话）  
        if self.capture_thread is not None and self.capture_thread.is_alive():  
            self.capture_manager.stop_capture()  # 调用截图模块的方法停止
            self.capture_thread.join()  # 等待线程结束  
        if self.check_timer:
            self.check_timer.stop()
            self.check_timer = None
        if self.capture_manager is not None:
            self.capture_manager = None

        # 创建队列
        self.ui_message_queue = queue.Queue()

        # 关键：每次都new新的ChessCaptureManager，保证识别线程能重启
        self.capture_manager = ChessCaptureManager(self.ui_message_queue)
        # 启动截图任务
        self.capture_manager.start_capture()
        # 创建截图线程
        self.capture_thread = threading.Thread(target=self.capture_func)
        self.capture_thread.start()
        # UI消息队列检查定时器
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_queue)
        self.check_timer.start(100)

        # 初始化局面检查器和历史记录
        context.init_checker()
        context.history = MoveHistory()

    def capture_func(self):
        """截图和分析函数"""
        # 启动引擎
        try:
            if context.engine is None:
                context.engine = ChessEngine()
                context.engine.start()
            if not context.engine.is_initialized:
                print("引擎启动失败")
                self.ui_message_queue.put(Message(MessageType.STATUS, "引擎启动失败"))
                return
        except Exception as e:
            print(f"capture_func error: {e}")

        # 使用已创建的ChessCaptureManager实例
        self.capture_manager.capture_region()

    def check_queue(self):
        """检查结果队列"""
        if not self.ui_message_queue.empty():
            result = self.ui_message_queue.get()
            # 自动检测识别线程超时停止信号
            if result == "STOP":
                if not self.is_stopping:  # 防止手动停止与自动停止冲突
                    print("检测到自动停止信号，执行停止操作")
                    self.on_stop()
                    self.is_running = False
                    self.start_btn.setText("开始")
                return
            if isinstance(result, Message):
                if result.type == MessageType.CHANGE:
                    # 更新棋局变化
                    self.board_display.update_board(
                        result.kwargs['array'], 
                        step_info=result.kwargs.get('step_info')
                    )
                    self.update_text(result.content)
                elif result.type == MessageType.PIECES:
                    # 更新棋子位置
                    self.board_display.update_pieces(result.kwargs['array'])
                elif result.type == MessageType.MOVE_CODE:
                    # 更新着法箭头
                    self.board_display.update_arrow(result.content, result.kwargs['is_red'])
                elif result.type == MessageType.MOVE_TEXT:
                    # 显示着法文本
                    self.update_text(result.content)
                elif result.type == MessageType.STATUS:
                    # 显示状态消息
                    self.update_text(result.content)
    
    def close_queue(self):
        """销毁截图线程和定时器"""
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_manager.stop_capture()  # 停止截图和工作线程
            self.capture_thread.join()
        if self.check_timer:
            self.check_timer.stop()
            self.check_timer = None

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
        pixmap = QPixmap('app/images/dingwei.png')
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

    def on_reposition(self):
        """处理重新定位选项"""
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
        if self.capture_manager:
            # 设置手动触发标志
            self.capture_manager.manual_trigger = True
            # 执行一次完整的监控与截图流程
            success = self.capture_manager.manually_capture_once()
            if success:
                self.update_text("手动触发截图完成")
            else:
                self.update_text("手动触发失败，请检查棋盘定位")
        else:
            self.update_text("截图管理器未初始化")

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
    
    def on_exit(self):
        """优雅安全规范地退出程序"""
        # 停止所有线程和监听器
        if hasattr(self, 'manual_positioner'):
            self.manual_positioner.cleanup()
        self.close_queue()
        
        # 保存配置
        context.save_config()
        
        # 优雅退出
        QApplication.quit()
    
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
        """窗口关闭时处理"""
        # 停止所有线程和监听器
        if hasattr(self, 'manual_positioner'):
            self.manual_positioner.cleanup()
        self.close_queue()
        super().closeEvent(event)

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
        self.main_window.move_display.setText('<span style="color: red;">第1步：点击棋盘左上角顶点<br>右键点击可取消定位</span>')
        
        # 启动鼠标监听
        self.start_mouse_listener()
        print("手动定位已启动")
    
    def cancel_positioning(self):
        """取消定位过程"""
        print("取消定位过程")
        self.positioning_step = 0
        self.positioning_coords = []
        self.is_positioning = False
        self.follow_cursor = False
        self.stop_cursor_tracking()
        self.stop_mouse_listener()
        
        # 清理临时定位点
        self.cleanup_position_dot()
        
        self.main_window.move_display.setText('<span style="color: blue;">定位已取消</span>')
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
        pixmap = QPixmap('app/images/dingwei.png')
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
        
        self.mouse_listener = mouse.Listener(on_click=self.on_mouse_click)
        self.mouse_listener.start()
    
    def stop_mouse_listener(self):
        """停止全局鼠标监听"""
        if self.mouse_listener and self.mouse_listener.is_alive():
            self.mouse_listener.stop()
            self.mouse_listener = None
    
    def on_mouse_click(self, x, y, button, pressed):
        """处理全局鼠标点击事件"""
        if not self.is_positioning:
            return True
            
        if button == mouse.Button.left and pressed:
            # 左键点击：确认位置
            cursor_pos = QPoint(x, y)
            # 将该操作切换到主线程执行
            QApplication.instance().postEvent(self.main_window, QEvent(CONFIRM_POSITION_EVENT))
            # 在事件处理函数中处理
            self.main_window.cursor_pos_clicked = cursor_pos
            return True
        elif button == mouse.Button.right and pressed:
            # 右键点击：取消定位
            QApplication.instance().postEvent(self.main_window, QEvent(CANCEL_POSITION_EVENT))
            return False
        return True
    
    def confirm_position(self, cursor_pos):
        """确认位置，处理2角定位逻辑"""
        x = cursor_pos.x()
        y = cursor_pos.y()
        
        if self.positioning_step == 1:
            # 第1步：左上角
            self.positioning_coords.append((x, y))
            self.positioning_step = 2
            self.main_window.move_display.setText('<span style="color: orange;">第2步：点击棋盘右下角顶点<br>右键点击可取消定位</span>')
            
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
                self.main_window.move_display.setText('<span style="color: green;">2角定位完成!</span>')
            else:
                # 定位失败，显示错误信息
                self.main_window.move_display.setText('<span style="color: red;">2角定位失败，请重试</span>')
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
        if width < 100 or height < 100:
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
            
            # 保存配置
            self.context.save_config()
            
            print(f"2角定位成功，棋盘区域: {board_region}")
            
            # 调用截图模块的try_locate_board方法验证定位
            try:
                # 获取截图管理器实例
                capture_manager = getattr(self.main_window, 'capture_manager', None)
                if capture_manager:
                    # 调用try_locate_board方法，传入手动坐标
                    manual_coords = (x, y, width, height)
                    success = capture_manager.try_locate_board(manual_coords=manual_coords)
                    if success:
                        print("截图模块验证定位成功")
                    else:
                        print("截图模块验证定位失败")
                else:
                    print("截图管理器未初始化，跳过验证")
            except Exception as e:
                print(f"调用截图模块验证失败: {e}")
            
            return True
            
        except Exception as e:
            print(f"更新棋盘区域配置失败: {e}")
            return False
    
    def cleanup(self):
        """清理资源"""
        self.cancel_positioning()