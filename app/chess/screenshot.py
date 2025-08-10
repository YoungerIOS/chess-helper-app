import mss
import time
import cv2
import numpy as np
import queue
import threading  
import chess.processor as processor
from chess.message import Message, MessageType, MessageContent
from chess.context import context
from tools.utils import resource_path
from chess.board_locator import BoardLocator, BoardLocatorError


class ChessCaptureManager:
    """象棋捕获管理器类，负责截图、发送识别"""
    
    def __init__(self, ui_message_queue):
        self.context = context
        self.manual_trigger = False  # 手动触发标志
        self.max_contour = None  # 用于存储倒计时区域检测到的最大轮廓
        self.process_queue = queue.Queue()  # 新增：识别任务队列
        self.result_queue = queue.Queue()  # 新增：识别和检查结果队列
        self.stop_event = threading.Event()
        self.worker_threads = processor.start_process_worker(
            self.process_queue, self.result_queue, ui_message_queue, self.stop_event
        )
        # 初始化棋盘定位器
        self.board_locator = BoardLocator(self.context)
        self.ui_message_queue = ui_message_queue # 新增：UI消息队列
        
        # 头像状态监测相关变量
        self.avatar_states = {"upper": "unknown", "lower": "unknown"}  # 当前头像状态
        self.normal_duration_start = None  # 开始计时的时间
        self.normal_duration_threshold = 3.0  # 持续3秒的阈值
        
        # 定位状态标志
        self._relocating = False
        self._relocate_lock = threading.Lock()
        
        # 头像监控线程引用
        self.avatar_threads = {"upper": None, "lower": None}
        
        # 订阅重新定位消息
        self.context.subscribe("relocate_board", self.try_locate_board)

    def try_locate_board(self, message_type=None, data=None, manual_coords=None):
        """
        尝试定位棋盘，处理各种异常情况
        Args:
            message_type: 消息类型（回调时使用）
            data: 消息数据（回调时使用）
            manual_coords: 手动定位坐标 (x, y)，自动定位时为 None
        Returns:
            bool: 是否成功定位棋盘
        """
        # 检查是否正在定位中
        with self._relocate_lock:
            if self._relocating:
                print("定位正在进行中，跳过重复请求")
                return False
            self._relocating = True
        
        try:
            # 如果是作为回调函数被调用，打印消息信息
            if message_type is not None:
                print(f"收到重新定位请求: {message_type} = {data}")
                
            # 尝试更新棋盘和头像区域（自动或手动检测模式）
            self.board_locator.update_board_and_avatars_regions(manual_coords=manual_coords)
            print("棋盘定位成功")
            
            # 发送成功消息到UI队列
            self.ui_message_queue.put(Message(MessageType.STATUS, "棋盘定位成功"))
            return True
        except BoardLocatorError as e:
            print(f"棋盘定位失败: {e}")
            # 发送失败消息到UI队列
            self.ui_message_queue.put(Message(MessageType.STATUS, f"{e}"))
            return False
        except Exception as e:
            print(f"棋盘定位时发生未知错误: {e}")
            # 发送错误消息到UI队列
            self.ui_message_queue.put(Message(MessageType.STATUS, f"棋盘定位错误: {e}"))
            return False
        finally:
            # 重置定位状态
            with self._relocate_lock:
                self._relocating = False

    def record_timer_state(self, avatar_name, state):
        """
        记录头像状态并在满足条件时触发重新定位
        Args:
            avatar_name: 头像名称 ("upper" 或 "lower")
            state: 头像状态 ("normal" 或 "countdown")
        """
        if avatar_name in self.avatar_states:
            self.avatar_states[avatar_name] = state
        
        # 检查上下头像同时为normal状态且持续3秒以上
        current_time = time.time()
        
        if self.avatar_states["upper"] == "normal" and self.avatar_states["lower"] == "normal":
            # 如果都是normal状态
            if self.normal_duration_start is None:
                # 开始计时
                self.normal_duration_start = current_time
            else:
                # 检查持续时间
                duration = current_time - self.normal_duration_start
                if duration >= self.normal_duration_threshold:
                    # 重置计时器
                    self.normal_duration_start = None
                    # 触发重新定位
                    print("检测到上下头像均为normal状态持续3秒以上，触发重新定位")
                    # 检查是否正在定位中，避免重复触发
                    with self._relocate_lock:
                        if not self._relocating:
                            threading.Thread(
                                target=self.context.send_message,
                                args=("relocate_board", True),
                                daemon=True
                            ).start()
                        else:
                            print("定位正在进行中，跳过重复触发")
        else:
            # 如果有任何一个不是normal状态，重置计时器
            self.normal_duration_start = None

    def start_capture(self):
        """开始截图任务"""
        self.stop_event.clear()  # 重置停止事件

    def stop_capture(self):
        """停止截图任务"""
        self.stop_event.set()
        # 停止工作线程池
        for _ in range(3):
            self.process_queue.put("STOP")
        self.result_queue.put("STOP")
        for t in self.worker_threads:
            t.join(timeout=2)
        # 停止棋盘定位器
        if hasattr(self, 'board_locator'):
            self.board_locator.stop()
        # 清理头像监控线程引用
        for avatar_name in ["upper", "lower"]:
            if self.avatar_threads[avatar_name] is not None:
                self.avatar_threads[avatar_name] = None
        # 取消订阅
        self.context.unsubscribe("relocate_board", self.try_locate_board)

    def capture_region(self): 
        # 首先进行初始定位
        print("开始初始定位...")
        while not self.stop_event.is_set():
            if self.try_locate_board():
                print("初始定位成功")
                break
            else:
                print("初始定位失败，1秒后重试")
                time.sleep(1)
        
        if self.stop_event.is_set():
            return
        
        # 定位成功后，加载配置并开始截图
        self.context.load_config()
        platform = self.context.get_platform(self.context.platform)

        if self.context.analysis_mode == "continuous":
            print("Debug - 连续截图")

        elif self.context.analysis_mode == "timer":
            print("Debug - 倒计时截图")
            # 启动上方头像监控线程
            self.avatar_threads["upper"] = threading.Thread(
                target=self._monitor_single_avatar,
                args=("upper",),  # 截图参数会被动态获取
                daemon=True
            )
            self.avatar_threads["upper"].start()
            
            # 启动下方头像监控线程
            self.avatar_threads["lower"] = threading.Thread(
                target=self._monitor_single_avatar,
                args=("lower",),  # 截图参数会被动态获取
                daemon=True
            )
            self.avatar_threads["lower"].start()
            
            while not self.stop_event.is_set():
                time.sleep(0.1)
            return
        else:
            print(f"Debug - 未知的分析模式: {self.context.analysis_mode}")

    def _process_continuous_mode(self, board_region):
        """处理连续模式"""
        with mss.mss() as sct:
            screenshot = sct.grab(board_region)

    def _check_timer_state(self, img_path, img_cv):
        """
        用颜色和模型预测,判断头像状态
        """
        color_state = 'countdown' if self._detect_avatar_border(img_cv, self.context.platform) else 'normal'
        return color_state

    def _capture_and_enqueue(self, current_turn, region):
        """截取棋盘区域，使用纳秒级时间戳作为排序依据"""
        capture_time = time.time_ns()
        with mss.mss() as sct:
            board_screenshot = sct.grab(region)
        self.process_queue.put((capture_time, current_turn, board_screenshot))

    def _monitor_single_avatar(self, avatar, interval=0.02):
        def get_turn(avatar_name, avatar_state):
            if avatar_state == 'countdown':
                return 'my_turn' if avatar_name == 'lower' else 'opponent_turn'
            elif avatar_state == 'normal':
                return 'opponent_turn' if avatar_name == 'lower' else 'my_turn'
            else:
                return None
        
        def get_current_regions():
            """动态获取当前区域坐标"""
            # 不重新加载配置，直接获取当前配置
            platform = self.context.get_platform(self.context.platform)
            return (
                platform.regions.get(f"avatar_{avatar}"),
                platform.regions.get("board")
            )
        
        # 获取初始区域坐标
        avatar_region, board_region = get_current_regions()
        if avatar_region is None or board_region is None:
            print(f"警告：{avatar}头像或棋盘区域未配置")
            return
        
        with mss.mss() as sct:
            screenshot = sct.grab(avatar_region)
            img_cv = np.frombuffer(screenshot.bgra, np.uint8).reshape(screenshot.height, screenshot.width, 4)[:, :, :3]
            img_path = f"app/images/board/temp_avatar_{avatar}.png"
            cv2.imwrite(img_path, img_cv)

        last_state = self._check_timer_state(img_path, img_cv)
        print(f"初始化{avatar}: {last_state}")
        
        # 非阻塞截图时机管理
        pending_captures = []  # 待执行的截图任务 [(time, avatar_name, region), ...]
        
        # 如果一开始就有倒计时状态，立即触发一次识别
        if last_state == 'countdown':
            print(f"{avatar} 初始为亮，立即触发识别")
            self._capture_and_enqueue(get_turn(avatar, last_state), board_region)

        while not self.stop_event.is_set():
            current_time = time.time()
            
            # 检查是否有待执行的截图任务
            current_pending = []
            for capture_time, pending_avatar, region in pending_captures:
                if current_time >= capture_time:
                    # 执行截图时重新计算turn信息
                    current_turn = get_turn(pending_avatar, self.avatar_states[pending_avatar])
                    self._capture_and_enqueue(current_turn, region)
                else:
                    current_pending.append((capture_time, pending_avatar, region))
            pending_captures = current_pending
            
            # 动态获取当前区域坐标
            avatar_region, board_region = get_current_regions()
            if avatar_region is None or board_region is None:
                print(f"警告：{avatar}头像或棋盘区域未配置，跳过本次检测")
                time.sleep(interval)
                continue
                
            with mss.mss() as sct:
                screenshot = sct.grab(avatar_region)
                img_cv = np.frombuffer(screenshot.bgra, np.uint8).reshape(screenshot.height, screenshot.width, 4)[:, :, :3]
                img_path = f"app/images/board/temp_avatar_{avatar}.png"
                cv2.imwrite(img_path, img_cv)
                
            state = self._check_timer_state(img_path, img_cv)
            # 记录头像状态
            self.record_timer_state(avatar, state)
            
            # 截图信号1: 灭->亮
            shot_signal1 = (last_state != 'countdown' and state == 'countdown')
            # 截图信号2: 亮->灭
            shot_signal2 = (last_state == 'countdown' and state == 'normal')

            if self.context.platform == "JJ":
                if shot_signal1:
                    # 立即执行第一次截图
                    self._capture_and_enqueue(get_turn(avatar, state), board_region)
                    # 安排0.8秒后的第二次截图
                    pending_captures.append((current_time + 0.8, avatar, board_region))
                    last_state = state
                elif shot_signal2:
                    # 安排0.5秒后的截图
                    pending_captures.append((current_time + 0.5, avatar, board_region))
                    last_state = state
                else:
                    last_state = state

            elif self.context.platform == "TT":
                if shot_signal1:
                    # 安排0.34秒后的第一次截图
                    pending_captures.append((current_time + 0.34, avatar, board_region))
                    # 安排1.84秒后的第二次截图（0.34 + 1.5）
                    pending_captures.append((current_time + 1.84, avatar, board_region))
                    last_state = state
                else:
                    last_state = state
            else:
                raise ValueError(f"不支持的平台: {self.context.platform}")

            time.sleep(interval)

    def _detect_avatar_border(self, img, platform):
        """
        检测头像边框
        Args:
            img: 头像区域的图像
            platform: 平台名称 ('TT' 或 'JJ')
        Returns:
            bool: 是否检测到边框
        """
        # 转换为HSV颜色空间
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        # 定义颜色范围
        if platform == 'TT':
            # TT平台：绿色(前期) -> 黄色(中期)
            color_ranges = [
                # 绿色范围
                (np.array([35, 50, 50]), np.array([85, 255, 255]), "绿色", 150),
                # 黄色范围
                (np.array([20, 100, 100]), np.array([40, 255, 255]), "黄色", 150)
            ]
        else:  # JJ平台
            # JJ平台：黄色(前期) -> 红色(末期)
            color_ranges = [
                # 黄色范围
                (np.array([20, 100, 100]), np.array([40, 255, 255]), "黄色", 250),
                # 红色范围
                (np.array([0, 100, 100]), np.array([10, 255, 255]), "红色", 50),
                (np.array([170, 100, 100]), np.array([180, 255, 255]), "红色", 50)
            ]
        
        # 按顺序检测每个颜色
        for lower, upper, color_name, threshold in color_ranges:
            # 创建当前颜色的掩码
            mask = cv2.inRange(hsv, lower, upper)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            
            # 查找轮廓
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                continue
                
            # 找到面积最大的轮廓
            max_contour_area = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(max_contour_area)
            
            # 根据颜色使用不同的判断标准
            if area > threshold:
                if color_name == "黄色":
                    self.max_contour = max_contour_area
                return True
                
            # 检查当前最大轮廓是否在上一帧的轮廓内部
            if color_name == "黄色" and self.max_contour is not None:
                overlap_ratio = self._get_contour_overlap(max_contour_area, self.max_contour)
                if overlap_ratio > 0.95:
                    return True
        
        return False
    
    def _get_contour_overlap(self, contour1, contour2):
        """
        计算轮廓1中的像素在轮廓2内部的比例
        Args:
            contour1: 当前轮廓
            contour2: 上一帧轮廓
        Returns:
            float: 在轮廓2内部的像素占轮廓1总像素的比例
        """
        if contour2 is None:
            return 0.0
            
        # 获取轮廓的边界框
        x1, y1, w1, h1 = cv2.boundingRect(contour1)
        x2, y2, w2, h2 = cv2.boundingRect(contour2)
        
        # 计算合并后的边界框
        x = min(x1, x2)
        y = min(y1, y2)
        width = max(x1 + w1, x2 + w2) - x
        height = max(y1 + h1, y2 + h2) - y
        
        # 创建掩码
        mask1 = np.zeros((height, width), dtype=np.uint8)
        mask2 = np.zeros((height, width), dtype=np.uint8)
        
        # 调整轮廓坐标到新的坐标系
        contour1_adjusted = contour1 - np.array([x, y])
        contour2_adjusted = contour2 - np.array([x, y])
        
        # 绘制轮廓
        cv2.drawContours(mask1, [contour1_adjusted], -1, 255, -1)
        cv2.drawContours(mask2, [contour2_adjusted], -1, 255, -1)
        
        # 计算重叠区域
        overlap = cv2.bitwise_and(mask1, mask2)
        
        # 计算像素数量
        total_pixels1 = cv2.countNonZero(mask1)
        total_pixels2 = cv2.countNonZero(mask2)
        overlap_pixels = cv2.countNonZero(overlap)
        
        # 计算比例
        overlap_ratio = overlap_pixels / total_pixels1 if total_pixels1 > 0 else 0
        
        return overlap_ratio
    
    def check_turn_order(self, avatar_upper, avatar_lower):#弃用
        """
        检查轮次顺序 - 分别识别上下两个头像
        Args:
            avatar_upper: 上方头像区域
            avatar_lower: 下方头像区域
        Returns:
            bool: 是否轮到我方
        """
        if self.manual_trigger:
            self.manual_trigger = False  # 使用后立即重置
            print("手动触发识别")
            return True
        
        # 检查上下头像区域是否有效
        if avatar_upper is None or avatar_lower is None:
            print("警告: 头像区域未配置，使用颜色检测")
            return False
        
        # 分别截取上下头像区域
        with mss.mss() as sct:
            # 截取上方头像
            upper_screenshot = sct.grab(avatar_upper)
            
            # 截取下方头像
            lower_screenshot = sct.grab(avatar_lower)
            
            # 保存临时图片用于预测 - 使用与训练时相同的方式
            upper_temp_path = "app/images/board/temp_avatar_upper.png"
            lower_temp_path = "app/images/board/temp_avatar_lower.png"
            
            # 使用mss.tools.to_png保存，与训练时保持一致
            mss.tools.to_png(upper_screenshot.rgb, upper_screenshot.size, output=upper_temp_path)
            mss.tools.to_png(lower_screenshot.rgb, lower_screenshot.size, output=lower_temp_path)
            
            # 分别预测上下头像
            try:
                upper_result = self.context.timer_recognizer.predict(upper_temp_path)
                lower_result = self.context.timer_recognizer.predict(lower_temp_path)
                
                print(f"upper头像: {upper_result['class_name']}, 置信度: {upper_result['confidence']:.2f}")
                print(f"lower头像: {lower_result['class_name']}, 置信度: {lower_result['confidence']:.2f}")
                
                # 判断逻辑：如果上方头像显示倒计时，说明轮到我方
                upper_countdown = upper_result['class_name'] == 'countdown' and upper_result['confidence'] > 0.9
                lower_countdown = lower_result['class_name'] == 'countdown' and lower_result['confidence'] > 0.9
                
                # 根据平台判断轮次
                if self.context.platform == "JJ":
                    # JJ平台：上方头像倒计时表示轮到我方
                    return upper_countdown
                else:  # TT平台
                    # TT平台：下方头像倒计时表示轮到我方
                    return lower_countdown
                    
            except Exception as e:
                print(f"预测出错: {e}, 使用颜色检测")
                # 使用颜色检测作为备选方案
                # 重新读取保存的图片进行颜色检测
                try:
                    upper_img = cv2.imread(upper_temp_path)
                    lower_img = cv2.imread(lower_temp_path)
                    
                    upper_border = self._detect_avatar_border(upper_img, self.context.platform)
                    lower_border = self._detect_avatar_border(lower_img, self.context.platform)
                    
                    if self.context.platform == "JJ":
                        return upper_border
                    else:  # TT平台
                        return lower_border
                except Exception as color_e:
                    print(f"颜色检测也失败: {color_e}")
                    return False
            
    def execute_single_capture_cycle(self):
        """
        执行一次完整的监控与截图流程
        从外界调用，执行一次头像监控、状态检测和截图任务
        Returns:
            bool: 是否成功执行截图任务
        """
        try:
            # 获取当前平台配置
            platform = self.context.get_platform(self.context.platform)
            avatar_upper = platform.regions.get("avatar_upper")
            avatar_lower = platform.regions.get("avatar_lower")
            board_region = platform.regions.get("board")
            
            if avatar_upper is None or avatar_lower is None or board_region is None:
                print("警告: 头像或棋盘区域未配置")
                return False
            
            # 执行一次头像状态检测
            current_turn = self._check_single_turn_state(avatar_upper, avatar_lower)
            
            if current_turn is not None:
                # 执行截图任务
                self._capture_and_enqueue(current_turn, board_region)
                print(f"执行单次截图任务完成，轮次: {current_turn}")
                return True
            else:
                print("当前状态无需截图")
                return False
                
        except Exception as e:
            print(f"执行单次截图流程失败: {e}")
            return False
    
    def _check_single_turn_state(self, avatar_upper, avatar_lower):
        """
        检查单次轮次状态
        Args:
            avatar_upper: 上方头像区域
            avatar_lower: 下方头像区域
        Returns:
            str or None: 轮次状态 ('my_turn', 'opponent_turn') 或 None
        """
        # 手动触发优先
        if self.manual_trigger:
            self.manual_trigger = False
            print("手动触发识别")
            return 'my_turn'
        
        # 分别截取上下头像区域
        with mss.mss() as sct:
            # 截取上方头像
            upper_screenshot = sct.grab(avatar_upper)
            
            # 截取下方头像
            lower_screenshot = sct.grab(avatar_lower)
            
            # 保存临时图片用于颜色检测
            upper_temp_path = "app/images/board/temp_avatar_upper.png"
            lower_temp_path = "app/images/board/temp_avatar_lower.png"
            
            # 使用mss.tools.to_png保存
            mss.tools.to_png(upper_screenshot.rgb, upper_screenshot.size, output=upper_temp_path)
            mss.tools.to_png(lower_screenshot.rgb, lower_screenshot.size, output=lower_temp_path)
            
            # 使用颜色检测
            try:
                upper_img = cv2.imread(upper_temp_path)
                lower_img = cv2.imread(lower_temp_path)
                
                upper_border = self._detect_avatar_border(upper_img, self.context.platform)
                lower_border = self._detect_avatar_border(lower_img, self.context.platform)
                
                print(f"单次检测 - upper头像倒计时: {upper_border}")
                print(f"单次检测 - lower头像倒计时: {lower_border}")
                
                # 统一判断逻辑：下方头像倒计时表示轮到我方
                if lower_border:
                    return 'my_turn'
                elif upper_border:
                    return 'opponent_turn'
                    
            except Exception as color_e:
                print(f"单次检测颜色检测失败: {color_e}")
        
        return None