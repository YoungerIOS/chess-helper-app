import os
import queue
import threading
import sys
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QApplication, QMenu)
from PySide6.QtCore import Qt, QSize, QPoint, QTimer, QEvent, QObject, Signal
from PySide6.QtGui import QFont, QKeyEvent, QCursor, QPixmap, QIcon
from pynput import mouse
from app.tools.utils import resource_path
from app.chess.screenshot import ChessCaptureManager
from app.chess.board_locator import BoardLocator
from app.chess.engine import ChessEngine
from app.chess.checker import PositionChecker
from app.chess.history import MoveHistory
from app.chess.message import Message, MessageType
from app.chess.message_bus import message_bus
from app.chess.context import context
from app.ui.board_display import BoardDisplay
from app.chess.processor import ChessProcess
from app.chess.auto_mover import AutoMoveController
from app.themes.theme_manager import ThemeManager

class MainWindow(QMainWindow):
    resume_polling_signal = Signal()  # 定义信号用于在主线程恢复轮询
    engine_threads_applied_signal = Signal(int, bool, str)


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
        # 使用存在的图片计算比例，避免因文件缺失导致窗口比例异常
        board_img = QPixmap(resource_path('images', 'media', 'chessboard3.png'))
        if board_img.isNull():
            board_ratio = 1.0
        else:
            board_ratio = board_img.width() / board_img.height()
        
        # 使用屏幕高度 x 80% x 0.56 作为窗口宽度, 看着更协调些,
        nice_height = int(screen_height * 0.8)
        width = int(nice_height * 0.56)
        
        # 计算棋盘图片在窗口中的实际高度
        board_height = int(width / board_ratio)
        
        # 计算其他UI元素的总高度
        other_heights = (
            100 +  # 顶部文本显示区域
            35 +   # 中间按钮行
            35 +   # 底部控制区域
            38 +   # 局势分析区域
            30 -   # 布局间距
            11     # 棋盘容器内边距
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
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QVBoxLayout(central_widget)
        
        # 计算动态间距 (约为窗口宽度的 1.5%)
        self.spacing_base = max(5, int(width * 0.015))
        self.spacing_tight = max(2, int(self.spacing_base * 0.4))
        
        main_layout.setSpacing(self.spacing_base * 2)  # 垂直间距稍大
        main_layout.setContentsMargins(self.spacing_base, self.spacing_base, self.spacing_base, self.spacing_base)
        
        # 初始化上下文
        context.load_config()
        self.engine_params = context.get_engine_params()
        
        # 连接信号与槽
        self.resume_polling_signal.connect(lambda: self.check_platform_change(notify_always=False, schedule_next=True))
        self.engine_threads_applied_signal.connect(self.on_engine_threads_applied)
        
        # 顶部文本显示区域
        self.text_display = QLabel()
        self.text_display.setAlignment(Qt.AlignCenter)
        self.text_display.setFont(QFont("Arial", 18, QFont.Bold))
        self.text_display.setFixedHeight(100)  # 设置固定高度
        self.text_display.setObjectName("textDisplay")
        # 移除内联样式，使用主题样式表
        self.text_display.setStyleSheet("")
        main_layout.addWidget(self.text_display)
        
        # 添加中间按钮行
        middle_buttons_layout = QHBoxLayout()
        middle_buttons_layout.setSpacing(5)
        middle_buttons_layout.setContentsMargins(0, 0, 0, 0)  # 移除底部边距，保持与主布局间距一致
        
        
        # 移除游戏选择按钮及菜单
        
        # 创建手动刷新按钮
        self.manual_refresh_btn = QPushButton("刷新")
        self.manual_refresh_btn.setFixedSize(75, 35)  # 与游戏平台按钮保持一致
        self.manual_refresh_btn.setFont(QFont("Arial", 11))
        self.manual_refresh_btn.setObjectName("secondary")
        # 移除内联样式，使用主题样式表
        self.manual_refresh_btn.setStyleSheet("")
        self.manual_refresh_btn.clicked.connect(self.on_manual_capture)
        middle_buttons_layout.addWidget(self.manual_refresh_btn)

        # 创建变招按钮
        self.change_move_btn = QPushButton("变招")
        self.change_move_btn.setFixedSize(75, 35)  # 与其他按钮保持一致
        self.change_move_btn.setFont(QFont("Arial", 11))
        self.change_move_btn.setObjectName("secondary")
        # 移除内联样式，使用主题样式表
        self.change_move_btn.setStyleSheet("")
        self.change_move_btn.clicked.connect(self.on_change_move)
        middle_buttons_layout.addWidget(self.change_move_btn)
        
        # 添加其他按钮
        self.start_btn = QPushButton("开始")
        self.start_btn.setFixedHeight(35)
        self.start_btn.setFont(QFont("Arial", 13))
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.on_start)
        middle_buttons_layout.addWidget(self.start_btn)
        
        main_layout.addLayout(middle_buttons_layout)
        
        # 中间棋盘区域
        self.board_display = BoardDisplay()
        # 移除固定高度设置，让棋盘自适应图片大小
        main_layout.addWidget(self.board_display)
        
        # 底部控制区域
        control_layout = QHBoxLayout()
        control_layout.setSpacing(self.spacing_base)
        control_layout.setContentsMargins(0, 0, 0, 0)  # 移除内边距
        
        # 创建退出按钮
        self.exit_btn = QPushButton("退出")
        self.exit_btn.setFixedHeight(35)
        self.exit_btn.setFont(QFont("Arial", 11))
        self.exit_btn.setObjectName("exitBtn")
        # 移除内联样式，使用主题样式表
        self.exit_btn.setStyleSheet("")
        self.exit_btn.clicked.connect(self.on_exit)
        control_layout.addWidget(self.exit_btn, 1)  # Stretch factor 1
        
        # 创建棋盘定位按钮 - 改为下拉菜单样式
        self.board_btn = QPushButton("设置")
        self.board_btn.setFixedHeight(35)
        self.board_btn.setFont(QFont("Arial", 11))
        self.board_btn.setObjectName("tertiary")
        # 加载并设置箭头图标
        # arrow_icon = QIcon(resource_path('images', 'pulldown_arrow.png'))
        # self.board_btn.setIcon(arrow_icon)
        self.board_btn.setIconSize(QSize(12, 12))
        # 移除内联样式，使用主题样式表
        self.board_btn.setStyleSheet("")
        self.board_btn.clicked.connect(self.show_board_menu)
        control_layout.addWidget(self.board_btn, 2)  # Stretch factor 2 (Wider)
        
        # 创建棋盘设置菜单
        self.board_menu = QMenu(self)
        self.board_menu.setStyleSheet("")
        self.manual_position_action = self.board_menu.addAction("手动定位")
        self.change_board_action = self.board_menu.addAction("更换棋盘")
        self.manual_position_action.triggered.connect(self.on_reposition)
        self.change_board_action.triggered.connect(self.on_change_board_bg)
        
        self.change_theme_action = self.board_menu.addAction("更换主题")
        self.change_theme_action.triggered.connect(self.on_change_theme)
        
        # 创建"其他设置"按钮
        self.settings_btn = QPushButton("其他") 
        self.settings_btn.setFixedHeight(35)
        self.settings_btn.setFont(QFont("Arial", 11))
        self.settings_btn.setObjectName("tertiary")
        # 加载并设置箭头图标
        # arrow_icon = QIcon(resource_path('images', 'pulldown_arrow.png'))
        # self.settings_btn.setIcon(arrow_icon)
        self.settings_btn.setIconSize(QSize(12, 12))
        # 移除内联样式，使用主题样式表
        self.settings_btn.setStyleSheet("")
        # 不再使用checkable属性
        self.settings_btn.clicked.connect(self.show_settings_menu)
        control_layout.addWidget(self.settings_btn, 2)  # Stretch factor 2 (Wider)
        
        # 创建设置菜单
        self.settings_menu = QMenu(self)
        self.settings_menu.setStyleSheet("")
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

        self.settings_menu.addSeparator()
        self.auto_move_action = self.settings_menu.addAction("自动走子")
        self.auto_move_action.setCheckable(True)
        self.auto_move_action.setChecked(context.auto_move_enabled)
        self.auto_move_action.triggered.connect(self.toggle_auto_move)

        self.capture_depth_action = self.settings_menu.addAction("被吃子时深度 +1")
        self.capture_depth_action.setCheckable(True)
        self.capture_depth_action.setChecked(context.capture_depth_enabled)
        self.capture_depth_action.triggered.connect(self.toggle_capture_depth)

        self.settings_menu.addSeparator()
        self.jieqi_action = self.settings_menu.addAction("揭棋模式（实验）")
        self.jieqi_action.setCheckable(True)
        self.jieqi_action.setChecked(context.game_variant == "jieqi")
        self.jieqi_action.triggered.connect(self.toggle_jieqi_mode)
        
        # 创建参数选择按钮
        self.param_btn = QPushButton("引擎参数")
        self.param_btn.setFixedHeight(35)
        self.param_btn.setFont(QFont("Arial", 11))
        self.param_btn.setObjectName("tertiary")
        # 加载并设置箭头图标
        # arrow_icon = QIcon('app/images/pulldown_arrow.png')
        # self.param_btn.setIcon(arrow_icon)
        self.param_btn.setIconSize(QSize(12, 12))
        # 移除内联样式，使用主题样式表
        self.param_btn.setStyleSheet("")
        self.param_btn.clicked.connect(self.show_param_menu)
        control_layout.addWidget(self.param_btn, 2)  # Stretch factor 2 (Wider, same as others)
        
        # 创建参数菜单
        self.param_menu = QMenu(self)
        self.param_menu.setStyleSheet("")
        self.depth_action = self.param_menu.addAction("深度上限")
        self.movetime_action = self.param_menu.addAction("时间上限")
        self.param_menu.addSeparator()
        self.threads_action = self.param_menu.addAction("线程数量")
        self.depth_action.setCheckable(True)
        self.movetime_action.setCheckable(True)
        self.threads_action.setCheckable(True)
        self.depth_action.triggered.connect(lambda: self.on_param_selected("depth"))
        self.movetime_action.triggered.connect(lambda: self.on_param_selected("movetime"))
        self.threads_action.triggered.connect(lambda: self.on_param_selected("threads"))
        
        # 设置初始选中状态
        if self.engine_params["goParam"] == "depth":
            self.depth_action.setChecked(True)
        else:
            self.movetime_action.setChecked(True)
        self.selected_engine_param = self.engine_params["goParam"]
        
        # 创建参数调整按钮
        param_layout = QHBoxLayout()
        param_layout.setSpacing(self.spacing_tight)
        
        self.decrease_btn = QPushButton("−")
        self.decrease_btn.setFixedSize(20, 35) 
        self.decrease_btn.setFont(QFont("Arial", 16))
        self.decrease_btn.setObjectName("paramBtn")
        # 移除内联样式，使用主题样式表
        self.decrease_btn.setStyleSheet("")
        self.decrease_btn.clicked.connect(self.on_decrease_param)
        param_layout.addWidget(self.decrease_btn)
        
        self.param_label = QLabel(self.engine_params[self.engine_params["goParam"]])
        self.param_label.setAlignment(Qt.AlignCenter)
        self.param_label.setFixedHeight(35)
        self.param_label.setObjectName("paramLabel")
        # 移除内联样式，使用主题样式表
        self.param_label.setStyleSheet("")
        param_layout.addWidget(self.param_label)
        
        self.increase_btn = QPushButton("+")
        self.increase_btn.setFixedSize(20, 35) 
        self.increase_btn.setFont(QFont("Arial", 16))
        self.increase_btn.setObjectName("paramBtn")
        # 移除内联样式，使用主题样式表
        self.increase_btn.setStyleSheet("")
        self.increase_btn.clicked.connect(self.on_increase_param)
        param_layout.addWidget(self.increase_btn)
        
        control_layout.addLayout(param_layout, 3)  # Stretch factor 3 (Most space for value)
        main_layout.addLayout(control_layout)

        # 局势分析与算力档位：实时展示引擎深度、评价、节点速度和耗时。
        analysis_layout = QHBoxLayout()
        analysis_layout.setSpacing(self.spacing_tight)
        analysis_layout.setContentsMargins(0, 0, 0, 0)

        self.analysis_btn = QPushButton("局势分析")
        self.analysis_btn.setFixedHeight(32)
        self.analysis_btn.setFont(QFont("Arial", 10))
        self.analysis_btn.setObjectName("tertiary")
        self.analysis_btn.clicked.connect(self.show_analysis_menu)
        analysis_layout.addWidget(self.analysis_btn, 2)

        self.analysis_menu = QMenu(self)
        self.analysis_menu.setStyleSheet("")
        for preset_key, preset_name in (
            ("eco", "省电"),
            ("balanced", "均衡"),
            ("strong", "强力"),
            ("max", "极致"),
        ):
            action = self.analysis_menu.addAction(preset_name)
            action.triggered.connect(
                lambda checked=False, key=preset_key: self.apply_compute_preset(key)
            )

        self.analysis_info_label = QLabel("等待引擎分析…")
        self.analysis_info_label.setAlignment(Qt.AlignCenter)
        self.analysis_info_label.setFixedHeight(32)
        self.analysis_info_label.setObjectName("analysisInfo")
        analysis_layout.addWidget(self.analysis_info_label, 7)
        main_layout.addLayout(analysis_layout)
        
        # 初始化UI消息队列和定时器（保持一直运行）
        self.ui_message_queue = queue.Queue(maxsize=256)
        # 设置全局消息总线
        message_bus.set_ui_queue(self.ui_message_queue)
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_queue)
        self.check_timer.start(100)  # 100ms间隔，性能开销极小

        # 初始化线程和队列
        self.capture_thread = None
        # 初始化截图管理器
        # 截图管理器在点击“开始”后才创建，避免窗口初始化时提前启动
        # 一组永远不会处理截图的识别线程。
        self.capture_manager = None
        # 初始化手动定位器
        self.manual_positioner = ManualPositioner(self)

        # 初始化状态
        self.is_running = False
        self.is_stopping = False  # 添加停止标志，防止手动停止与自动停止冲突
        self._manual_refresh_pending = False
        self._exit_started = False
        self.lines = ["", "", ""]
        self.update_text("等待获取棋局...", MessageType.STATUS)
        
        # 应用当前主题
        ThemeManager.apply_theme(context.theme)
        
        # 初始化图标
        self.update_icons()
        
        # 初始化状态
        self.last_detected_platform = None
        
        # 初始化平台检测器
        self.platform_detector = BoardLocator(context)

        # 自动走子控制器：只在主选着法消息到达后执行，默认关闭。
        self.auto_mover = AutoMoveController(
            context,
            window_provider=lambda: self.platform_detector.find_game_window(context.platform),
            can_execute=lambda: self.is_running and not self.is_stopping,
            result_callback=self.on_auto_move_result,
        )
        
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

                # 如果检测到的平台与当前上下文不一致，则切换
                if detected_platform != context.platform:
                    print(f"Auto-switch platform: {context.platform} -> {detected_platform}")
                    context.set_platform(detected_platform)
                    self.update_text(f"自动切换到游戏: {platform_display_name}", MessageType.STATUS)
                else:
                     # 即使未变化，也显示当前检测到的平台（因为可能是启动时的确认，或者是轮询成功的通知）
                     self.update_text(f"检测到游戏: {platform_display_name}", MessageType.STATUS)
            else:
                # 情况1: 之前检测到了游戏，现在没了 -> 游戏被关闭
                if self.last_detected_platform is not None:
                     self.update_text("游戏窗口已关闭，等待重新启动...", MessageType.ERROR)
                     self.last_detected_platform = None
                
                # 情况2: 强制通知（如启动时或点击开始时）
                elif notify_always:
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
        self.on_param_selected(param)

    def on_increase_param(self):
        """增加参数值"""
        # 获取当前参数
        engine_params = context.get_engine_params()
        key = self.selected_engine_param
        param_value = int(engine_params[key])
        
        if key == "depth" and param_value < 200:
            param_value += 1
        elif key == "movetime" and param_value < 20000:
            param_value += 2000
        elif key == "threads":
            param_value = min(param_value + 1, max(1, os.cpu_count() or 1))
        
        # 更新参数
        engine_params[key] = str(param_value)
        context.update_engine_params(engine_params)
        self.engine_params = engine_params
        
        # 更新显示
        self.refresh_engine_param_label()
        if key == "threads":
            self.apply_engine_threads(param_value)

    def on_decrease_param(self):
        """减少参数值"""
        # 获取当前参数
        engine_params = context.get_engine_params()
        key = self.selected_engine_param
        param_value = int(engine_params[key])
        
        if key == "depth" and param_value > 1:
            param_value -= 1
        elif key == "movetime" and param_value > 2000:
            param_value -= 2000
        elif key == "threads":
            param_value = max(1, param_value - 1)
        
        # 更新参数
        engine_params[key] = str(param_value)
        context.update_engine_params(engine_params)
        self.engine_params = engine_params
        
        # 更新显示
        self.refresh_engine_param_label()
        if key == "threads":
            self.apply_engine_threads(param_value)

    def apply_engine_threads(self, threads: int):
        """异步应用线程数，防止等待当前搜索结束时阻塞界面。"""
        engine = context.get_engine()
        if engine is None or not engine.is_initialized:
            self.update_text(
                f"线程数量已设为 {threads}，启动引擎后生效",
                MessageType.STATUS,
            )
            return

        def worker():
            try:
                # 多次快速点击时，以持久化配置中的最终值为准。
                latest = int(context.get_engine_params().get("threads", threads))
                applied = engine.set_threads(latest)
                self.engine_threads_applied_signal.emit(latest, applied, "")
            except Exception as exc:
                self.engine_threads_applied_signal.emit(threads, False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def on_engine_threads_applied(self, threads: int, applied: bool, error: str):
        """在Qt主线程显示线程配置结果。"""
        if error:
            self.update_text(f"线程数量调整失败: {error}", MessageType.ERROR)
        elif applied:
            self.update_text(f"引擎线程数量已调整为 {threads}", MessageType.STATUS)
        else:
            self.update_text(
                f"线程数量已设为 {threads}，下次启动引擎后生效",
                MessageType.STATUS,
            )

    def on_start(self):
        """开始/停止按钮事件"""
        if not self.is_running:
            # 点击开始时，再次确认一下平台并显示结果 (不需要轮询)
            self.check_platform_change(notify_always=True, schedule_next=False)
            
            self.is_running = True
            self.start_btn.setText("停止")
            self.create_queue()
        else:
            self.on_stop()
 
    def on_stop(self):
        """停止事件"""
        if self.is_stopping: 
            return
        self.is_stopping = True
        context.invalidate_analysis()
        if hasattr(self, 'auto_mover'):
            self.auto_mover.cancel_pending()
        # 立即更新UI状态
        self.is_running = False
        self.start_btn.setText("开始")
        
        # 清空界面状态
        self.board_display.clear_board()
        self.lines[2] = "" # 确保清除着法缓存
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
                engine = ChessEngine()
                context.set_engine(engine)
                if engine.start():
                    print("引擎已启动")
                else:
                    error = engine.last_error or f"无法启动 {engine.engine_path}"
                    print(f"引擎启动失败: {error}")
                    message_bus.publish_error(f"引擎初始化失败\n{error}")
                
                # 初始化局面检查器和历史记录
                context.set_checker(PositionChecker(variant=context.game_variant))
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
        # 独立扫描完整JJ窗口中的绿色“再来一局”按钮。这个入口不依赖
        # 棋盘格点或结算状态，因此结算页缩小棋盘也不会漏掉。
        if (
            self.is_running and
            not self.is_stopping and
            self.capture_manager is not None and
            self.capture_manager.ready_event.is_set() and
            context.auto_move_enabled and
            context.platform == "JJ" and
            hasattr(self, "auto_mover")
        ):
            self.auto_mover.scan_rematch_button()

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
                    if (
                        result.kwargs.get('auto_execute') and
                        context.auto_move_enabled and
                        hasattr(self, 'auto_mover')
                    ):
                        self.auto_mover.schedule(
                            result.content,
                            result.kwargs['is_red'],
                            result.kwargs.get('analysis_token'),
                        )
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
                elif result.type == MessageType.PARAM_UPDATE:
                    # 棋子被吃或新局重置后，刷新动态有效深度。
                    self.refresh_engine_param_label()
                elif result.type == MessageType.ENGINE_INFO:
                    self.update_engine_analysis(result.kwargs or result.content or {})
    
    def close_queue(self):
        """销毁截图线程"""
        if self.capture_manager is not None:
            self.capture_manager.stop_capture()  # 停止截图和工作线程

    def update_text(self, text, message_type=None):
        """
        更新显示文本
        Args:
            text: 要显示的文本内容
            message_type: 消息类型，用于确定显示颜色和样式
        """
        # 定义不同消息类型的颜色和样式
        message_styles = {
            MessageType.MOVE_TEXT: {
                'color': '#2C3E50',  # 深蓝灰色，更易读
                'font_size': '45pt',
                'is_move': True
            },
            MessageType.STATUS: {
                'color': '#3498DB',  # 明亮蓝色
                'font_size': '18pt',
                'is_move': False
            },
            MessageType.ERROR: {
                'color': '#E74C3C',  # 明亮红色
                'font_size': '18pt',
                'is_move': False
            },
            MessageType.CHANGE: {
                'color': '#27AE60',  # 明亮绿色
                'font_size': '18pt',
                'is_move': False
            }
        }
        
        # 默认样式
        default_style = {
            'color': '#3498DB',  # 明亮蓝色
            'font_size': '18pt',
            'is_move': False
        }
        
        # 获取样式配置
        style = message_styles.get(message_type, default_style)
        
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
            if len(lines) == 1:
                self.lines = [lines[0], "", self.lines[2]]  # 保留第3行的着法
            else:
                self.lines = [lines[0], lines[1], ""] 
        
        # 生成HTML显示文本
        display_text = ""
        for i, line in enumerate(self.lines):
            if i == 0 and line:  # 第1行
                display_text += f'<span style="color: {style["color"]}; font-size: {style["font_size"]}; line-height: 1;">{line}</span><br>'
            elif i == 1 and line:  # 第2行
                display_text += f'<span style="color: {style["color"]}; font-size: {style["font_size"]}; line-height: 1;">{line}</span><br>'
            elif i == 2 and line:  # 第3行（着法）
                display_text += f'<span style="font-family: \'Songti SC\', \'SimSun\', \'STSong\', serif; font-weight: bold; font-size: 45pt; line-height: 1;">{line}</span>'
        
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

    def toggle_auto_move(self, checked=None):
        """启用或关闭自动走子；关闭时立即取消尚未执行的任务。"""
        enabled = self.auto_move_action.isChecked() if checked is None else bool(checked)
        self.auto_move_action.setChecked(enabled)
        context.auto_move_enabled = enabled
        if not enabled and hasattr(self, 'auto_mover'):
            self.auto_mover.cancel_pending()
        message = "自动走子已开启（下一次推荐生效）" if enabled else "自动走子已关闭"
        self.update_text(message, MessageType.STATUS)

    def toggle_capture_depth(self, checked=None):
        """切换我方被吃棋子后的动态搜索加深。"""
        enabled = (
            self.capture_depth_action.isChecked()
            if checked is None else bool(checked)
        )
        self.capture_depth_action.setChecked(enabled)
        context.capture_depth_enabled = enabled
        checker = context.get_checker()
        if checker is not None:
            checker.reset_capture_depth_bonus()
        self.refresh_engine_param_label()
        message = (
            "被吃子加深已开启（本局从0重新计数）"
            if enabled else "被吃子加深已关闭"
        )
        self.update_text(message, MessageType.STATUS)

    def toggle_jieqi_mode(self, checked=None):
        """切换普通象棋/揭棋；模式改变后必须重建引擎和棋局状态。"""
        enabled = self.jieqi_action.isChecked() if checked is None else bool(checked)
        self.jieqi_action.setChecked(enabled)
        if self.is_running:
            self.on_stop()
        context.invalidate_analysis()
        if hasattr(self, 'auto_mover'):
            self.auto_mover.cancel_pending()
        context.quit_engine()
        context.history.clear()
        context.base_fen = None
        context.reset_checker()
        context.reset_recognizer()
        context.game_variant = "jieqi" if enabled else "xiangqi"
        self.update_text(
            "已切换到揭棋模式，请从完整新局开始并重新点击开始"
            if enabled else "已切换到普通象棋模式，请重新点击开始",
            MessageType.STATUS,
        )

    def refresh_engine_param_label(self):
        """显示当前参数；固定深度模式同时显示本局吃子加成。"""
        if not hasattr(self, 'param_label') or not hasattr(self, 'selected_engine_param'):
            return
        engine_params = context.get_engine_params()
        key = self.selected_engine_param
        if key != 'depth':
            self.param_label.setText(str(engine_params.get(key, '')))
            return

        try:
            base_depth = int(engine_params.get('depth', 20))
        except (TypeError, ValueError):
            base_depth = 20
        checker = context.get_checker()
        bonus = 0
        if context.capture_depth_enabled and checker is not None:
            bonus = max(0, int(getattr(checker, 'capture_depth_bonus', 0)))
        if bonus:
            self.param_label.setText(f"{base_depth}+{bonus}={base_depth + bonus}")
        else:
            self.param_label.setText(str(base_depth))

    def on_auto_move_result(self, success, message):
        """由自动走子后台线程通过消息队列更新界面。"""
        message_type = MessageType.STATUS if success else MessageType.ERROR
        message_bus.publish(Message(message_type, message))

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
            if not self.capture_manager.ready_event.is_set():
                self.update_text("棋盘正在定位，请稍候...", MessageType.STATUS)
                return
            if self._manual_refresh_pending:
                self.update_text("刷新正在进行，请稍候...", MessageType.STATUS)
                return

            # 设置手动触发标志
            self.capture_manager.manual_trigger = True
            self._manual_refresh_pending = True
            self.update_text("正在获取最新棋盘画面...", MessageType.STATUS)

            def refresh_worker():
                try:
                    success = self.capture_manager.manually_capture_once()
                    if success:
                        message_bus.publish_status(
                            "正在重新识别当前局面（已保留揭棋历史）..."
                            if context.game_variant == "jieqi"
                            else "重置数据并重新分析..."
                        )
                    else:
                        message_bus.publish_error("截图服务繁忙，本次刷新未完成，请稍后重试")
                finally:
                    self._manual_refresh_pending = False

            threading.Thread(
                target=refresh_worker,
                name="manual-refresh",
                daemon=True,
            ).start()
        else:
            self.update_text("请先点击开始按钮", MessageType.STATUS)


    def on_change_move(self):
        """请求变招"""
        try:
             # 用户请求变招时，取消可能尚未落子的首选着法。
             context.invalidate_analysis()
             if hasattr(self, 'auto_mover'):
                 self.auto_mover.cancel_pending()
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

    def show_param_menu(self):
        """显示参数菜单"""
        self.param_menu.exec_(self.param_btn.mapToGlobal(self.param_btn.rect().bottomLeft()))

    def show_analysis_menu(self):
        """显示局势分析算力档位。"""
        self.analysis_menu.exec_(
            self.analysis_btn.mapToGlobal(self.analysis_btn.rect().bottomLeft())
        )

    def apply_compute_preset(self, preset):
        """应用算力档位；搜索量立即保存，线程数安全地异步更新。"""
        cpu_count = max(1, os.cpu_count() or 1)
        presets = {
            "eco": {
                "name": "省电", "threads": max(1, cpu_count // 4),
                "depth": 16, "movetime": 1000,
            },
            "balanced": {
                "name": "均衡", "threads": max(2, cpu_count // 2),
                "depth": 20, "movetime": 2000,
            },
            "strong": {
                "name": "强力", "threads": max(2, (cpu_count * 3) // 4),
                "depth": 24, "movetime": 5000,
            },
            "max": {
                "name": "极致", "threads": cpu_count,
                "depth": 28, "movetime": 10000,
            },
        }
        values = presets.get(preset)
        if values is None:
            return

        engine_params = context.get_engine_params()
        engine_params["threads"] = str(values["threads"])
        engine_params["depth"] = str(values["depth"])
        engine_params["movetime"] = str(values["movetime"])
        context.update_engine_params(engine_params)
        self.engine_params = engine_params
        self.refresh_engine_param_label()
        self.apply_engine_threads(values["threads"])
        self.analysis_info_label.setText(
            f"{values['name']} · {values['threads']}线程 · "
            f"深度{values['depth']} / {values['movetime']}ms"
        )

    @staticmethod
    def _format_engine_rate(value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return "—"
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f}Mn/s"
        if value >= 1_000:
            return f"{value / 1_000:.0f}kn/s"
        return f"{value}n/s"

    def update_engine_analysis(self, info):
        """把UCI实时遥测转换为紧凑的中文局势摘要。"""
        depth = info.get("depth", "—")
        score_type = info.get("score_type")
        score = info.get("score")
        if score_type == "mate" and score is not None:
            evaluation = f"我方将杀{abs(score)}步" if score > 0 else f"对方将杀{abs(score)}步"
        elif score_type == "cp" and score is not None:
            pawns = score / 100.0
            if abs(pawns) < 0.15:
                evaluation = "局势均衡"
            elif pawns > 0:
                evaluation = f"我方 +{pawns:.2f}"
            else:
                evaluation = f"对方 +{abs(pawns):.2f}"
        else:
            evaluation = "评价计算中"

        nps = self._format_engine_rate(info.get("nps"))
        elapsed = info.get("time")
        elapsed_text = f"{int(elapsed) / 1000:.1f}s" if elapsed is not None else "—"
        self.analysis_info_label.setText(
            f"深度 {depth}  |  {evaluation}  |  {nps}  |  {elapsed_text}"
        )
    
    def on_param_selected(self, param):
        """处理参数选择"""
        # 更新选中状态
        self.depth_action.setChecked(param == "depth")
        self.movetime_action.setChecked(param == "movetime")
        self.threads_action.setChecked(param == "threads")
        
        self.selected_engine_param = param
        self.engine_params = context.get_engine_params()
        if param in ("depth", "movetime"):
            self.engine_params["goParam"] = param
            context.update_engine_params(self.engine_params)
        self.refresh_engine_param_label()

    def show_board_menu(self):
        """显示棋盘定位菜单"""
        self.board_menu.exec_(self.board_btn.mapToGlobal(self.board_btn.rect().bottomLeft()))
    
    def on_change_board_bg(self):
        """更换棋盘底图"""
        self.board_display.next_board()
    
    def on_change_theme(self):
        """更换主题"""
        new_theme = ThemeManager.toggle_theme()
        self.update_icons()
        print(f"Theme switched to: {new_theme}")

    def update_icons(self):
        """根据当前主题更新图标"""
        # Determine icon name based on theme
        # Light theme -> black arrow, Dark theme -> white arrow
        icon_name = 'pulldown_arrow_black.png' if context.theme == 'light' else 'pulldown_arrow.png'
        icon_path = resource_path('images', icon_name)
        
        # Check if file exists to avoid crash if generation failed
        if not os.path.exists(icon_path):
            icon_path = resource_path('images', 'pulldown_arrow.png')
            
        arrow_icon = QIcon(icon_path)
        
        # Update buttons if they exist
        if hasattr(self, 'game_btn'):
            self.game_btn.setIcon(arrow_icon)
        if hasattr(self, 'board_btn'):
            self.board_btn.setIcon(arrow_icon)
        if hasattr(self, 'settings_btn'):
            self.settings_btn.setIcon(arrow_icon)
        if hasattr(self, 'param_btn'):
            self.param_btn.setIcon(arrow_icon)
    
    def _start_exit_cleanup(self):
        """启动一次性退出清理，不阻塞Qt主线程。"""
        if self._exit_started:
            return
        self._exit_started = True
        context.invalidate_analysis()
        if hasattr(self, 'auto_mover'):
            self.auto_mover.cancel_pending()
        if hasattr(self, 'check_timer'):
            self.check_timer.stop()
        if hasattr(self, 'manual_positioner'):
            self.manual_positioner.cleanup()
        context.save_config()

        capture_manager = self.capture_manager
        self.capture_manager = None

        def cleanup_worker():
            try:
                if capture_manager is not None:
                    capture_manager.stop_capture(timeout=0.8)
                context.quit_engine(fast=True)
            except Exception as exc:
                print(f"退出清理失败: {exc}")

        # 非daemon保证Python会完成子进程清理，但窗口与Qt事件循环可以先
        # 立即退出，用户不会看到界面卡住。
        threading.Thread(target=cleanup_worker, daemon=False).start()

    def on_exit(self):
        """立即关闭窗口，并在后台清理识别线程和引擎。"""
        self.hide()
        self._start_exit_cleanup()
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
        self.hide()
        self._start_exit_cleanup()
        event.accept()

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
        self.main_window.text_display.setText('<span style="color: red;">第1步：点击棋盘左上角顶点<br>右键点击可取消定位</span>')
        
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
                self.main_window.text_display.setText('<span style="color: red;">2角定位失败，请重试</span>')
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
