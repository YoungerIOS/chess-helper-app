from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QComboBox, QFrame, QApplication, QMenu)
from PySide6.QtCore import Qt, QSize, QPoint, QTimer
from PySide6.QtGui import QFont, QKeyEvent, QCursor, QPixmap
import json
import os
import queue
import threading
import sys
from chess.screenshot import capture_region, get_position, update_params, trigger_manual_recognition
from chess import engine
from chess.board_display import BoardDisplay
from chess.template_maker import save_templates
from chess.message import Message, MessageType

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("象棋助手")
        
        # 获取屏幕信息
        screen = QApplication.primaryScreen()
        screen_height = screen.size().height()
        
        # 加载棋盘图片并计算其宽高比
        board_img = QPixmap(os.path.join('app', 'images', 'media', 'chessboard.jpeg'))
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
        
        # 初始化引擎参数
        self.load_params()
        
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
        self.game_btn.setFixedSize(55, 35)
        self.game_btn.setFont(QFont("Arial", 11))
        self.game_btn.setStyleSheet("""
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
        if self.engine_params["platform"] == "JJ":
            self.jj_action.setChecked(True)
        else:
            self.tt_action.setChecked(True)
        
        # 添加其他按钮
        other_buttons = [
            ("按钮2", lambda: None),
            ("按钮3", lambda: None),
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
            ("显示原点", self.on_position_board),
            ("开始", self.on_start),
            ("分析", self.on_analyze),
            ("手动", self.on_manual_analyze),
        ]
        
        for text, callback in buttons:
            btn = QPushButton(text)
            btn.setMinimumHeight(35)  # 调整按钮高度
            btn.setFont(QFont("Arial", 11))  # 调整按钮字体
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
            btn.clicked.connect(callback)
            control_layout.addWidget(btn)
        
        # 创建参数选择按钮
        self.param_btn = QPushButton("参数")
        self.param_btn.setFixedSize(35, 35)
        self.param_btn.setFont(QFont("Arial", 11))
        self.param_btn.setStyleSheet("""
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
        
        update_params(self.engine_params)
        
        # 初始化线程和队列
        self.stop_event = threading.Event()
        self.result_queue = queue.Queue()
        self.capture_thread = None
        self.check_timer = None
        
        # 初始化状态
        self.is_running = False
        self.lines = ["", "", ""]
    
    def load_params(self):
        """从文件加载参数"""
        try:
            with open('app/json/params.json', 'r') as f:
                params = json.load(f)
                self.engine_params = params
        except (FileNotFoundError, json.JSONDecodeError):
            # 如果文件不存在或格式错误，使用默认值
            self.engine_params = {
                "platform": "TT",
                "movetime": "3000",
                "depth": "20",
                "goParam": "depth"
            }
            # 保存默认值到文件
            self.save_params()

    def save_params(self):
        """保存参数到文件"""
        try:
            with open('app/json/params.json', 'w') as f:
                json.dump(self.engine_params, f, indent=4)
        except Exception as e:
            print(f"Error saving params: {e}")

    def on_engine_param_changed(self, param):
        """处理引擎参数改变"""
        self.engine_params["goParam"] = param
        self.param_label.setText(self.engine_params[param])
        self.save_params()
        update_params(self.engine_params)
    
    def on_increase_param(self):
        """增加参数值"""
        key = self.engine_params["goParam"]
        param_value = int(self.engine_params[key])
        
        if key == "depth" and param_value < 200:
            param_value += 1
        elif key == "movetime" and param_value < 20000:
            param_value += 2000
            
        self.engine_params[key] = str(param_value)
        self.param_label.setText(str(param_value))
        self.save_params()
        update_params(self.engine_params)
    
    def on_decrease_param(self):
        """减少参数值"""
        key = self.engine_params["goParam"]
        param_value = int(self.engine_params[key])
        
        if key == "depth" and param_value > 1:
            param_value -= 1
        elif key == "movetime" and param_value > 2000:
            param_value -= 2000
            
        self.engine_params[key] = str(param_value)
        self.param_label.setText(str(param_value))
        self.save_params()
        update_params(self.engine_params)
    
    def on_start(self):
        """开始分析"""
        if not self.is_running:
            self.is_running = True
            self.sender().setText("停止")
            self.create_queue()
        else:
            self.is_running = False
            self.sender().setText("开始")
            # 设置事件，通知capture_region线程停止
            self.stop_event.set() 
            # 关闭引擎进程
            engine.terminate_engine()
    
    def on_stop(self):
        """停止分析"""
        self.stop_analysis()
        self.is_running = False
        self.sender().setText("开始")
    
    def on_analyze(self):
        """重新分析"""
        self.sender().setText("停止") #重新计算实际就是重启while循环,等同于"开始下棋",只是不会重复启动引擎
        self.is_running = False
        if self.check_timer:
            self.check_timer.stop()
        self.stop_event.set()
        self.stop_event.clear()
        self.create_queue()
    
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
                if result.type == MessageType.BOARD_DISPLAY:
                    # 显示棋局
                    self.board_display.update_board(result.kwargs['fen_str'], result.kwargs['is_red'])
                    self.update_text(result.content)
                elif result.type == MessageType.MOVE_CODE:
                    # 显示着法箭头
                    self.board_display.update_board(result.kwargs['fen_str'], result.kwargs['is_red'], result.content)
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
            
        # 创建新的定位点
        with open('app/json/coordinates.json', 'r') as f:
            data = json.load(f)
            x = data['region1']['left']
            y = data['region1']['top']
            
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
    
    def on_position_board(self):
        """处理定位棋盘按钮点击"""
        if self.is_show_dot:
            self.is_show_dot = False
            self.sender().setText("重新定位")
            self.follow_cursor = False  # 显示原点时不跟随光标
            self.create_position_dot()
        else:
            self.move_display.setText('<span style="color: red;">将光标移到棋盘左上角,\n不要点击,\n然后按下S键</span>')
            self.is_positioning = True
            self.follow_cursor = True  # 重新定位时跟随光标
            self.start_cursor_tracking()  # 开始跟踪
    
    def keyPressEvent(self, event: QKeyEvent):
        """处理键盘事件"""
        if self.is_positioning and event.key() == Qt.Key_S:
            # 获取当前光标位置
            cursor_pos = QCursor.pos()
            # 直接使用光标位置，不添加偏移
            x = cursor_pos.x()
            y = cursor_pos.y()
            
            # 使用get_position保存坐标
            get_position(x, y)
            
            # 重置定位状态
            self.is_positioning = False
            self.follow_cursor = False  # 禁用光标跟踪
            self.stop_cursor_tracking()  # 停止跟踪
            
            # 创建并显示定位点，但不启动跟踪
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
            
            # 保存模板
            if save_templates():
                self.move_display.setText('<span style="color: green;">定位完成!\n模板已保存。</span>')
            else:
                self.move_display.setText('<span style="color: red;">定位完成!\n模板保存失败。</span>')
    
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
        self.save_params()
        update_params(self.engine_params)

    def show_game_menu(self):
        """显示游戏选择菜单"""
        self.game_menu.exec_(self.game_btn.mapToGlobal(self.game_btn.rect().bottomLeft()))
    
    def on_game_selected(self, game):
        """处理游戏选择"""
        # 更新选中状态
        self.jj_action.setChecked(game == "JJ象棋")
        self.tt_action.setChecked(game == "天天象棋")
        
        self.engine_params["platform"] = "JJ" if game == "JJ象棋" else "TT"
        self.save_params()
        update_params(self.engine_params)
        print(f"Selected game: {game}")

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec()) 
