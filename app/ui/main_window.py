from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QComboBox, QFrame, QApplication)
from PySide6.QtCore import Qt, QSize, QPoint, QTimer
from PySide6.QtGui import QFont, QKeyEvent, QCursor, QPixmap
import json
import os
import queue
import threading
import sys
from chess.screenshot import capture_region, get_position, update_params
from chess import engine
from chess.board_display import BoardDisplay

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("象棋助手")
        
        # 获取屏幕信息
        screen = QApplication.primaryScreen()
        screen_height = screen.size().height()
        
        # 设置窗口高度为屏幕高度的 80%
        height = int(screen_height * 0.8)
        # 保持宽高比约为 0.56 (814/1448)
        width = int(height * 0.56)
        
        print(f"Screen height: {screen_height}")
        print(f"Window size: {width}x{height}")
        
        # 设置窗口固定大小
        self.setFixedSize(width, height)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 顶部文本显示区域
        self.move_display = QLabel('<span style="color: red;">等待引擎分析...</span>')
        self.move_display.setAlignment(Qt.AlignCenter)
        self.move_display.setFont(QFont("Arial", 20, QFont.Bold))
        self.move_display.setStyleSheet("""
            QLabel {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 10px;
                min-height: 45px;
            }
        """)
        main_layout.addWidget(self.move_display)
        
        # 中间棋盘区域
        self.board_display = BoardDisplay()
        self.board_display.setMinimumHeight(500)  # 调整棋盘高度
        main_layout.addWidget(self.board_display)
        
        # 底部控制区域
        control_layout = QHBoxLayout()
        control_layout.setSpacing(5)
        
        # 创建控制按钮
        buttons = [
            ("显示原点", self.on_position_board),
            ("开始", self.on_start),
            ("停止", self.on_stop),
            ("分析", self.on_analyze),
        ]
        
        for text, callback in buttons:
            btn = QPushButton(text)
            btn.setMinimumHeight(35)  # 调整按钮高度
            btn.setFont(QFont("Arial", 11))  # 调整按钮字体
            btn.clicked.connect(callback)
            control_layout.addWidget(btn)
        
        # 创建下拉菜单
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(["depth", "movetime"])
        self.engine_combo.setMinimumHeight(35)  # 调整下拉菜单高度
        self.engine_combo.setFont(QFont("Arial", 11))  # 调整下拉菜单字体
        self.engine_combo.currentTextChanged.connect(self.on_engine_param_changed)
        control_layout.addWidget(self.engine_combo)
        
        # 创建参数调整按钮
        param_layout = QHBoxLayout()
        param_layout.setSpacing(2)
        
        self.decrease_btn = QPushButton("-")
        self.decrease_btn.setMinimumHeight(35)
        self.decrease_btn.clicked.connect(self.on_decrease_param)
        param_layout.addWidget(self.decrease_btn)
        
        self.param_label = QLabel("28")
        self.param_label.setAlignment(Qt.AlignCenter)
        self.param_label.setMinimumHeight(35)
        param_layout.addWidget(self.param_label)
        
        self.increase_btn = QPushButton("+")
        self.increase_btn.setMinimumHeight(35)
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
        
        # 初始化引擎参数
        self.engine_params = {
            "platform": "TT",
            "movetime": "3000",
            "depth": "28",
            "goParam": "depth"
        }
        update_params(self.engine_params)
        
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
            if isinstance(result, tuple) and len(result) == 3:
                text, fen_str, is_red = result
                self.update_text(text)
                self.board_display.update_board(fen_str, is_red)
            else:
                self.update_text(result)
    
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
                display_text += f'<span style="color: red; font-size: 18pt;">{line}</span><br>'
            elif i == 2:
                display_text += f'<span style="color: black; font-size: 34pt;">{line}</span>'
        
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
                padding: 10px;
                min-height: 45px;
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
            self.move_display.setText("将光标移到棋盘左上角,\n不要点击,\n然后按下S键~")
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
            
            # 更新显示
            self.move_display.setText("定位完成!")
            
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

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec()) 
