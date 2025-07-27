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


class ChessCaptureManager:
    """象棋捕获管理器类，负责截图、发送识别"""
    
    def __init__(self, ui_message_queue):
        self.context = context
        self.manual_trigger = False  # 手动触发标志
        self.max_contour = None  # 用于存储倒计时区域检测到的最大轮廓
        self.process_queue = queue.Queue()  # 新增：识别任务队列
        self.result_queue = queue.Queue()  # 新增：识别和检查结果队列
        self.seq_id = 0  # 新增：全局递增序号
        self.seq_lock = threading.Lock()  # 新增：序号锁
        self.recognition_thread = processor.start_process_worker(
            self.process_queue, self.result_queue, ui_message_queue
        )

    def capture_region(self, stop_event): 
        self.context.load_config()
        platform = self.context.get_platform(self.context.platform)
        avatar_upper = platform.regions.get("avatar_upper")
        avatar_lower = platform.regions.get("avatar_lower")
        board_region = platform.regions.get("board")

        if self.context.analysis_mode == "continuous":
            print("Debug - 连续截图")
            # while not stop_event.is_set():
            #     self._process_continuous_mode(board_region, ui_message_queue)
        elif self.context.analysis_mode == "timer":
            print("Debug - 倒计时截图")
            t_upper = threading.Thread(
                target=self._monitor_single_avatar,
                args=("upper", avatar_upper, board_region, stop_event),
                daemon=True
            )
            t_lower = threading.Thread(
                target=self._monitor_single_avatar,
                args=("lower", avatar_lower, board_region, stop_event),
                daemon=True
            )
            t_upper.start()
            t_lower.start()
            while not stop_event.is_set():
                time.sleep(0.1)
            return
        else:
            print(f"Debug - 未知的分析模式: {self.context.analysis_mode}")

    def _process_continuous_mode(self, board_region):
        """处理连续模式"""
        with mss.mss() as sct:
            screenshot = sct.grab(board_region)

    def _timer_state_check(self, img_path, img_cv):
        """
        用颜色和模型预测,判断头像状态
        """
        color_state = 'countdown' if self._detect_avatar_border(img_cv, self.context.platform) else 'normal'
        return color_state

    def _capture_and_enqueue(self, current_turn, region):
        """截取棋盘区域，自动分配序号并放入识别队列"""
        with mss.mss() as sct:
            board_screenshot = sct.grab(region)
        with self.seq_lock:
            seq_id = self.seq_id
            self.seq_id += 1
        self.process_queue.put((seq_id, current_turn, board_screenshot))

    def _monitor_single_avatar(self, avatar_name, avatar_region, board_region, stop_event, interval=0.02):
        def get_turn(avatar_name, timer_state):
            if timer_state == 'countdown':
                return 'my_turn' if avatar_name == 'lower' else 'opponent_turn'
            elif timer_state == 'normal':
                return 'opponent_turn' if avatar_name == 'lower' else 'my_turn'
            else:
                return None
        
        with mss.mss() as sct:
            screenshot = sct.grab(avatar_region)
            img_cv = np.frombuffer(screenshot.bgra, np.uint8).reshape(screenshot.height, screenshot.width, 4)[:, :, :3]
            img_path = f"app/images/board/temp_avatar_{avatar_name}.png"
            cv2.imwrite(img_path, img_cv)

        last_state = self._timer_state_check(img_path, img_cv)
        print(f"初始化{avatar_name}: {last_state}")
        # 如果一开始就有倒计时状态，立即触发一次识别
        if last_state == 'countdown':
            print(f"{avatar_name} 初始为亮，立即触发识别")
            self._capture_and_enqueue(get_turn(avatar_name, last_state), board_region)

        while not stop_event.is_set():
            with mss.mss() as sct:
                screenshot = sct.grab(avatar_region)
                img_cv = np.frombuffer(screenshot.bgra, np.uint8).reshape(screenshot.height, screenshot.width, 4)[:, :, :3]
                img_path = f"app/images/board/temp_avatar_{avatar_name}.png"
                cv2.imwrite(img_path, img_cv)
                
            state = self._timer_state_check(img_path, img_cv)
            # 截图信号1: 灭->亮
            shot_signal1 = (last_state != 'countdown' and state == 'countdown')
            # 截图信号2: 亮->灭
            shot_signal2 = (last_state == 'countdown' and state == 'normal')

            if self.context.platform == "JJ":
                if shot_signal1:
                    self._capture_and_enqueue(get_turn(avatar_name, state), board_region)
                    time.sleep(0.8)
                    self._capture_and_enqueue(get_turn(avatar_name, state), board_region)
                    last_state = state
                elif shot_signal2:
                    time.sleep(0.5)
                    self._capture_and_enqueue(get_turn(avatar_name, state), board_region)
                    last_state = state
                else:
                    last_state = state

            elif self.context.platform == "TT":
                if shot_signal1:
                    time.sleep(0.34)
                    self._capture_and_enqueue(get_turn(avatar_name, state), board_region)
                    time.sleep(1.5)
                    self._capture_and_enqueue(get_turn(avatar_name, state), board_region)
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
    
    def get_position(self, x, y):   
        # 棋盘区域
        board_width = 375   
        board_height = 415
        board_region = {'left': x, 'top': y, 'width': board_width, 'height': board_height}

        # 上下头像区域
        region_height = 135
        upper_region = {'left': x, 'top': y - region_height, 'width': board_width, 'height': region_height}
        lower_region = {'left': x, 'top': y + board_height, 'width': board_width, 'height': region_height}

        # 截取三个区域的图片
        with mss.mss() as sct:
            # 棋盘
            board_screenshot = sct.grab(board_region)
            board_img = np.frombuffer(board_screenshot.bgra, np.uint8).reshape(board_screenshot.height, board_screenshot.width, 4)
            board_img = board_img[:, :, :3]
            cv2.imwrite(resource_path('images/board/board.png'), board_img)

            # 上方区域
            upper_avatar_screenshot = sct.grab(upper_region)
            upper_avatar_img = np.frombuffer(upper_avatar_screenshot.bgra, np.uint8).reshape(upper_avatar_screenshot.height, upper_avatar_screenshot.width, 4)
            upper_avatar_img = upper_avatar_img[:, :, :3]
            cv2.imwrite(resource_path('images/board/upper_region.png'), upper_avatar_img)

            # 下方区域
            lower_avatar_screenshot = sct.grab(lower_region)
            lower_avatar_img = np.frombuffer(lower_avatar_screenshot.bgra, np.uint8).reshape(lower_avatar_screenshot.height, lower_avatar_screenshot.width, 4)
            lower_avatar_img = lower_avatar_img[:, :, :3]
            cv2.imwrite(resource_path('images/board/lower_region.png'), lower_avatar_img)

        # 平台判断
        platform_type = self.context.platform

        # 霍夫圆检测函数（JJ平台）
        def detect_avatar_circle(img):
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gray = cv2.medianBlur(gray, 5)
            rows = gray.shape[0]
            circles = cv2.HoughCircles(
                gray, cv2.HOUGH_GRADIENT, 1, rows / 8,
                param1=50, param2=30,
                minRadius=int(rows * 0.2), maxRadius=int(rows * 0.5)
            )
            if circles is not None:
                circles = np.uint16(np.around(circles))
                # 取半径最大的圆
                max_circle = max(circles[0], key=lambda c: c[2])
                x, y, r = max_circle
                return x, y, r
            return None

        # 检测头像区域
        avatar_regions = {}
        avatar_rects = {}
        square_size = 72
        if platform_type == "JJ":
            # JJ平台：圆检测
            upper_shape = detect_avatar_circle(upper_avatar_img)
            lower_shape = detect_avatar_circle(lower_avatar_img)
            for pos, shape, region in [
                ("upper", upper_shape, upper_region),
                ("lower", lower_shape, lower_region)
            ]:
                if shape is not None:
                    cx, cy, r = shape
                    cx_abs = int(region['left'] + cx)
                    cy_abs = int(region['top'] + cy)
                    half = square_size // 2
                    left = cx_abs - half
                    top = cy_abs - half
                    avatar_regions[pos] = {
                        'left': left,
                        'top': top,
                        'width': square_size,
                        'height': square_size
                    }
                    avatar_rects[pos] = {'left': left, 'top': top, 'width': square_size, 'height': square_size}
                else:
                    avatar_regions[pos] = None
                    avatar_rects[pos] = None
        else:  # TT平台，直接用固定区域
            # upper: 取upper_region左上角，偏移5像素
            upper_left = (upper_region['left'] - 5, upper_region['top'])
            avatar_regions['upper'] = {
                'left': upper_left[0],
                'top': upper_left[1],
                'width': square_size,
                'height': square_size
            }
            # lower: 取lower_region右下角，偏移5像素
            lower_right_x = lower_region['left'] + lower_region['width'] + 5
            lower_right_y = lower_region['top'] + lower_region['height']
            avatar_regions['lower'] = {
                'left': lower_right_x - square_size,
                'top': lower_right_y - square_size,
                'width': square_size,
                'height': square_size
            }
            avatar_rects['upper'] = avatar_regions['upper']
            avatar_rects['lower'] = avatar_regions['lower']

        # 统一保存同心矩形区域图片
        with mss.mss() as sct:
            for pos in ["upper", "lower"]:
                rect = avatar_rects.get(pos)
                if rect:
                    rect_img = sct.grab(rect)
                    rect_img_np = np.frombuffer(rect_img.bgra, np.uint8).reshape(rect_img.height, rect_img.width, 4)
                    rect_img_np = rect_img_np[:, :, :3]
                    cv2.imwrite(resource_path(f'images/board/avatar_{pos}_rect.png'), rect_img_np)

        # 统一更新当前平台的区域配置（绝对坐标）
        platform = self.context.get_platform(self.context.platform)
        platform.regions = {
            "board": board_region,
            "avatar_upper": avatar_regions.get("upper"),
            "avatar_lower": avatar_regions.get("lower")
        }
        self.context.save_config()
        return board_region
    
    def check_turn_order(self, avatar_upper, avatar_lower):
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
            
    def trigger_manual_recognition(self):
        """触发一次手动识别"""
        self.manual_trigger = True