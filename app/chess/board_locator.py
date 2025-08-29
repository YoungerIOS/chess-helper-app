"""
棋盘定位器模块 (Board Locator)

作用：
    自动检测和定位象棋游戏窗口中的棋盘位置，支持跨平台窗口检测。
    主要用于天天象棋(TT)和JJ象棋(JJ)两个平台的棋盘自动定位。

处理流程：
    1. 窗口检测：检测游戏窗口位置
       - macOS: 使用 Quartz API 搜索窗口
       - Windows: 使用 win32gui API 搜索窗口
       - 其他平台: 降级到全屏检测模式
    
    2. 棋盘定位：在检测到的窗口区域内寻找棋盘
       - 使用霍夫圆检测算法识别棋子
       - 寻找"将"和"帅"的位置关系
       - 根据将帅位置计算棋盘左上角坐标
    
    3. 区域计算：根据棋盘位置计算各个功能区域
       - 棋盘区域：用于棋子识别
       - 上方头像区域：用于倒计时检测
       - 下方头像区域：用于倒计时检测
    
    4. 配置更新：将计算出的区域坐标保存到配置文件
       - 更新当前平台的区域配置
       - 保存头像检测区域
       - 保存棋盘截图区域
"""

import mss
import cv2
import numpy as np
import threading
import queue
import time
import platform
from concurrent.futures import ThreadPoolExecutor, as_completed
from tools.utils import resource_path
from chess.context import context as global_context
from chess.recognizer import ChessRecognizer

# 跨平台窗口检测
WIN32GUI_AVAILABLE = False
_win32gui_module = None

if platform.system() == "Darwin":  # macOS
    import Quartz
elif platform.system() == "Windows":  # Windows
    try:
        import importlib
        _win32gui_module = importlib.import_module('win32gui')
        WIN32GUI_AVAILABLE = True
    except ImportError:
        print("警告: win32gui模块不可用，请安装: pip install pywin32")
else:  # Linux或其他系统
    print("警告: 当前系统不支持窗口检测，将使用全屏检测")

class BoardLocatorError(Exception):
    """棋盘定位器异常类"""
    pass

class BoardLocator:
    def __init__(self, context=None):
        self.num_workers = 3
        self.stop_event = threading.Event()
        self.executor = None
        self.context = context or global_context
        self.recognizer = ChessRecognizer()
        
        # 游戏窗口标题关键词
        self.game_titles = {
            "JJ": ["JJ象棋"],
            "TT": ["天天象棋"]
        }
        
        # 基准游戏窗口尺寸（JJ象棋在标准分辨率下的窗口尺寸）
        self.base_window_width = 414
        self.base_window_height = 736
        
        # 基准尺寸参数（在414x736游戏窗口下的实际值）
        # 这些值需要根据实际测量调整
        self.base_sizes = {
            'board_width': 375,      # 棋盘宽度
            'board_height': 415,     # 棋盘高度
            'region_height': 135,    # 头像区域高度
            'square_size': 72,       # 头像尺寸
            'king_offset_x': 188,    # 将帅中心到棋盘左边的偏移
            'king_offset_y_ratio': 1.2  # 将帅中心到棋盘上边的偏移比例
        }
        
        # 当前窗口信息，用于缩放计算
        self._current_window_info = None
    
    def _get_scale_factor(self, window_info):
        """
        根据游戏窗口尺寸计算缩放因子
        基于414x736基准游戏窗口尺寸
        """
        if not window_info:
            return 1.0
            
        window_width = window_info['region']['width']
        window_height = window_info['region']['height']
        
        # 从上下文对象获取屏幕尺寸
        screen_size = getattr(self.context, 'screen_size', None)
        
        if screen_size:
            screen_width, screen_height = screen_size
            print(f"从上下文获取屏幕尺寸: {screen_width}x{screen_height}")
        
        # 使用游戏窗口尺寸计算缩放因子
        # 这是正确的逻辑：当前游戏窗口尺寸相对于基准游戏窗口尺寸的缩放
        scale_x = window_width / self.base_window_width
        scale_y = window_height / self.base_window_height
        scale = min(scale_x, scale_y)  # 取较小的缩放因子，保持比例
        scale = max(0.5, min(2.0, scale))  # 限制缩放范围
        
        print(f"游戏窗口尺寸: {window_width}x{window_height}, 基准: {self.base_window_width}x{self.base_window_height}, 缩放因子: {scale:.3f}")
        return scale
    
    def _get_scaled_size(self, base_size, scale):
        """获取缩放后的尺寸"""
        scaled_size = int(round(base_size * scale))
        return scaled_size

    def find_window_by_title_macos(self, keyword):
        """使用Quartz查找窗口（macOS）"""
        try:
            options = Quartz.kCGWindowListOptionOnScreenOnly
            window_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
            matches = []

            for win in window_list:
                title = win.get('kCGWindowName', '')
                if title and keyword.lower() in title.lower():
                    bounds = win.get('kCGWindowBounds', {})
                    matches.append({
                        "title": title,
                        "bounds": (
                            bounds.get('X'),
                            bounds.get('Y'),
                            bounds.get('Width'),
                            bounds.get('Height')
                        )
                    })
            return matches
        except Exception as e:
            print(f"Quartz窗口检测失败: {e}")
            return []

    def find_window_by_title_windows(self, keyword):
        """使用win32gui查找窗口（Windows）"""
        if not WIN32GUI_AVAILABLE:
            return []
            
        matches = []

        def callback(hwnd, extra):
            if _win32gui_module.IsWindowVisible(hwnd):
                title = _win32gui_module.GetWindowText(hwnd)
                if keyword.lower() in title.lower():
                    rect = _win32gui_module.GetWindowRect(hwnd)
                    # rect格式: (left, top, right, bottom)
                    x, y, right, bottom = rect
                    width = right - x
                    height = bottom - y
                    matches.append({
                        "title": title,
                        "bounds": (x, y, width, height)
                    })

        _win32gui_module.EnumWindows(callback, None)
        return matches

    def find_window_by_title(self, keyword):
        """跨平台窗口查找"""
        system = platform.system()
        
        if system == "Darwin":  # macOS
            return self.find_window_by_title_macos(keyword)
        elif system == "Windows":  # Windows
            return self.find_window_by_title_windows(keyword)
        else:
            print(f"不支持的操作系统: {system}")
            return []

    def save_window_screenshot(self, window_info):
        """保存检测到的窗口截图"""
        if not window_info:
            return
            
        region = window_info['region']
        platform_name = window_info['platform']
        title = window_info['title']
        
        try:
            with mss.mss() as sct:
                screenshot = sct.grab(region)
            
            # 转换为OpenCV格式
            img_np = np.frombuffer(screenshot.bgra, np.uint8).reshape(screenshot.height, screenshot.width, 4)
            img_np = img_np[:, :, :3].copy()
            
            # 保存截图
            filename = f"window_{platform_name}_{title.replace(' ', '_')}.jpg"
            # cv2.imwrite(filename, img_np)
            
            return filename
            
        except Exception as e:
            print(f"保存窗口截图失败: {e}")
            return None

    def find_game_window(self, platform_name):
        """查找游戏窗口"""
        system = platform.system()
        
        if system not in ["Darwin", "Windows"]:
            print(f"当前系统 {system} 不支持窗口检测，跳过窗口检测")
            return None
            
        # print(f"使用{system}系统API检测游戏窗口...")
        
        # 构建检测平台列表：先检测指定平台，检测不到时检测所有其他平台
        platforms_to_check = []
        
        # 1. 首先检测指定的平台（如果提供了）
        if platform_name in self.game_titles:
            platforms_to_check.append(platform_name)
        
        # 2. 添加所有备用平台（排除已添加的指定平台）
        for p in self.game_titles.keys():
            if p not in platforms_to_check:
                platforms_to_check.append(p)
        
        for p in platforms_to_check:
            if p not in self.game_titles:
                continue
                
            titles = self.game_titles[p]
            
            for title in titles:
                # print(f"搜索窗口标题: {title}")
                matches = self.find_window_by_title(title)
                
                if matches:
                    # print(f"找到 {len(matches)} 个匹配窗口:")
                    # for i, match in enumerate(matches):
                        # print(f"  {i+1}. 标题: {match['title']}")
                        # print(f"     位置: {match['bounds']}")
                    
                    # 返回第一个匹配的窗口
                    match = matches[0]
                    x, y, width, height = match['bounds']
                    
                    window_info = {
                        'platform': p,
                        'title': match['title'],
                        'region': {
                            'left': int(x),
                            'top': int(y),
                            'width': int(width),
                            'height': int(height)
                        },
                        'confidence': 1.0
                    }
                    
                    # 保存当前窗口信息，用于后续缩放计算
                    self._current_window_info = window_info
                    
                    # print(f"检测到窗口: {window_info['title']}")
                    # print(f"窗口尺寸: {window_info['region']['width']}x{window_info['region']['height']}")
                    # print(f"计算缩放因子: {self._get_scale_factor(window_info):.3f}")
                    
                    # 更新上下文中的平台为检测到的平台（只在平台真正变化时）
                    if self.context and self.context.platform != p:
                        self.context.set_platform(p)
                    
                    # 保存窗口截图
                    self.save_window_screenshot(window_info)
                    
                    return window_info
        
        print("未找到游戏窗口")
        return None

    def find_kings_on_screen(self):
        """
        截取整个屏幕，使用线程池检测所有圆，识别棋子，寻找"将"或"帅"，返回其圆心坐标列表。
        Returns:
            List[Tuple[int, int]]: 所有检测到的"将"或"帅"的圆心坐标
        """
        # 1. 首先尝试检测游戏窗口
        # print("=== 步骤1: 检测游戏窗口 ===")
        window_info = self.find_game_window(self.context.platform)
        
        if window_info:
            # 2. 获取棋盘搜索区域
            region = window_info['region']
            search_region = {
                'left': region['left'],
                'top': region['top'],
                'width': region['width'],
                'height': region['height']
            }
            
            # 3. 在游戏窗口内检测将帅
            return self._find_kings_in_window(search_region, window_info)
        else:
            print("未检测到游戏窗口，使用全屏检测")
            return self._find_kings_fullscreen()

    def _find_kings_fullscreen(self):
        """全屏检测将帅（原有逻辑）"""
        # print("使用全屏检测模式")
        
        # 1. 截取全屏
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # 全屏
            screenshot = sct.grab(monitor)
        
        # 2. 转为OpenCV格式
        img_np = np.frombuffer(screenshot.bgra, np.uint8).reshape(screenshot.height, screenshot.width, 4)
        img_np = img_np[:, :, :3].copy()  # 去掉alpha，并变成可写
        
        # 3. 根据平台选择不同的预处理策略
        gray = cv2.cvtColor(img_np, cv2.COLOR_BGR2GRAY)
        
        platform = self.context.platform if self.context else "JJ"
        
        if platform == "TT":
            # TT平台：使用更温和的预处理，因为棋子可能更小更模糊
            blurred = cv2.GaussianBlur(gray, (3, 3), 0)  # 更小的核
            # 不使用形态学操作，避免过度平滑
            processed = blurred
            # TT平台的参数
            minRadius = 10
            maxRadius = 20
            minDist = 25
            param1 = 60  # 降低边缘检测阈值
            param2 = 25  # 降低圆检测阈值
        else:  # JJ平台
            # JJ平台：使用原来的预处理
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            processed = cv2.morphologyEx(blurred, cv2.MORPH_CLOSE, kernel)
            # JJ平台的参数
            minRadius = 15
            maxRadius = 25
            minDist = 30
            param1 = 80
            param2 = 40
        
        # print(f"平台: {platform}, 参数: minRadius={minRadius}, maxRadius={maxRadius}, param1={param1}, param2={param2}")
        
        # 4. 霍夫圆检测
        circles = cv2.HoughCircles(processed, cv2.HOUGH_GRADIENT, 1, minDist,
                                  param1=param1, param2=param2,
                                  minRadius=minRadius, maxRadius=maxRadius)
        
        if circles is None:
            print("未检测到任何圆形")
            # 即使没有检测到圆形，也保存图片
            cv2.imwrite("detected_circles.jpg", img_np)
            return []
            
        circles = np.round(circles[0, :]).astype("int")
        # print(f"霍夫圆检测到 {len(circles)} 个圆形")
        
        # 5. 使用线程池处理圆检测
        king_centers = self._process_circles_with_threadpool(circles, img_np)
        
        # 6. 保存可视化结果
        # cv2.imwrite("detected_circles.jpg", img_np)
        # print("已保存所有检测到圆的图片为 detected_circles.jpg")
        
        return king_centers

    def _find_kings_in_window(self, search_region, window_info):
        """在指定游戏窗口内检测将帅"""
        print("使用游戏窗口内检测模式")
        
        # 1. 截取搜索区域
        with mss.mss() as sct:
            screenshot = sct.grab(search_region)
        
        # 2. 转为OpenCV格式
        img_np = np.frombuffer(screenshot.bgra, np.uint8).reshape(screenshot.height, screenshot.width, 4)
        img_np = img_np[:, :, :3].copy()
        
        # 保存搜索区域截图
        platform_name = window_info['platform']
        title = window_info['title']
        search_filename = f"search_region_{platform_name}_{title.replace(' ', '_')}.jpg"
        cv2.imwrite(search_filename, img_np)
        
        # 3. 根据平台选择不同的预处理策略
        gray = cv2.cvtColor(img_np, cv2.COLOR_BGR2GRAY)
        
        platform = window_info['platform']
        
        if platform == "TT":
            # TT平台：使用更温和的预处理
            blurred = cv2.GaussianBlur(gray, (3, 3), 0)
            processed = blurred
            # TT平台的参数（在较小区域内可以更精确）
            minRadius = 8
            maxRadius = 18
            minDist = 20
            param1 = 50
            param2 = 20
        else:  # JJ平台
            # JJ平台：使用原来的预处理
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            processed = cv2.morphologyEx(blurred, cv2.MORPH_CLOSE, kernel)
            # JJ平台的参数
            minRadius = 12
            maxRadius = 22
            minDist = 25
            param1 = 70
            param2 = 30
        
        # print(f"区域检测 - 平台: {platform}, 参数: minRadius={minRadius}, maxRadius={maxRadius}, param1={param1}, param2={param2}")
        
        # 4. 霍夫圆检测
        circles = cv2.HoughCircles(processed, cv2.HOUGH_GRADIENT, 1, minDist,
                                  param1=param1, param2=param2,
                                  minRadius=minRadius, maxRadius=maxRadius)
        
        if circles is None:
            print("在游戏窗口内未检测到任何圆形")
            # cv2.imwrite("detected_circles.jpg", img_np)
            return []
            
        circles = np.round(circles[0, :]).astype("int")
        # print(f"游戏窗口内霍夫圆检测到 {len(circles)} 个圆形")
        
        # 5. 使用线程池处理圆检测
        king_centers = self._process_circles_with_threadpool(circles, img_np)
        
        # 6. 将相对坐标转换为绝对坐标
        absolute_king_centers = []
        for x, y, r, piece_type in king_centers:
            abs_x = x + search_region['left']
            abs_y = y + search_region['top']
            absolute_king_centers.append((abs_x, abs_y, r, piece_type))
        
        # 7. 保存可视化结果
        # 在全屏图像上绘制检测结果
        with mss.mss() as sct:
            full_screenshot = sct.grab(sct.monitors[1])
            full_img = np.frombuffer(full_screenshot.bgra, np.uint8).reshape(full_screenshot.height, full_screenshot.width, 4)
            full_img = full_img[:, :, :3].copy()
        
        # 绘制搜索区域
        cv2.rectangle(full_img, 
                     (search_region['left'], search_region['top']), 
                     (search_region['left'] + search_region['width'], search_region['top'] + search_region['height']), 
                     (0, 255, 0), 2)
        
        # 绘制检测到的将帅
        for x, y, r, piece_type in absolute_king_centers:
            cv2.circle(full_img, (x, y), r, (0, 255, 0), 2)
            cv2.circle(full_img, (x, y), 2, (0, 0, 255), 3)
        
        # cv2.imwrite("detected_circles.jpg", full_img)
        # print("已保存区域检测结果图片为 detected_circles.jpg")
        
        return absolute_king_centers
    
    def _process_circles_with_threadpool(self, circles, img_np):
        """使用线程池处理圆检测"""
        king_centers = []
        king_centers_lock = threading.Lock()
        
        # 将圆分成多个批次，每个线程处理一部分
        batch_size = max(1, len(circles) // self.num_workers)
        batches = [circles[i:i + batch_size] for i in range(0, len(circles), batch_size)]
        
        def process_batch(batch):
            """处理一批圆"""
            batch_kings = []
            for x, y, r in batch:
                if self.stop_event.is_set():
                    break
                    
                # 截取圆形区域
                x1, y1, x2, y2 = x - r, y - r, x + r, y + r
                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(img_np.shape[1] - 1, x2)
                y2 = min(img_np.shape[0] - 1, y2)
                piece_img = img_np[y1:y2+1, x1:x2+1]
                
                # 识别棋子类型
                piece_type, confidence = self.recognizer.recognize_piece_type(piece_img)
                
                # 先画所有检测到的圆（用蓝色）
                cv2.circle(img_np, (x, y), r, (255, 0, 0), 2)  # 蓝色圆圈
                cv2.circle(img_np, (x, y), 2, (255, 0, 0), 3)  # 蓝色圆心
                
                # 如果是将帅且置信度高，添加到结果中
                if piece_type in ('k', 'K') and confidence > 0.9:
                    batch_kings.append((x, y, r, piece_type))
                    # 将帅用绿色重新标记
                    cv2.circle(img_np, (x, y), r, (0, 255, 0), 2)  # 绿色圆圈
                    cv2.circle(img_np, (x, y), 2, (0, 0, 255), 3)  # 红色圆心
            
            return batch_kings
        
        # 启动线程池
        self.executor = ThreadPoolExecutor(max_workers=self.num_workers)
        futures = []
        
        try:
            # 提交任务
            for batch in batches:
                if self.stop_event.is_set():
                    break
                future = self.executor.submit(process_batch, batch)
                futures.append(future)
            
            # 收集结果
            for future in as_completed(futures):
                if self.stop_event.is_set():
                    break
                    
                try:
                    batch_kings = future.result(timeout=30)  # 30秒超时
                    with king_centers_lock:
                        for x, y, r, piece_type in batch_kings:
                            king_centers.append((x, y, r, piece_type))
                except Exception as e:
                    print(f"处理批次时出错: {e}")
                    
        finally:
            # 优雅关闭线程池
            self._shutdown_executor()
        
        return king_centers
    
    def _shutdown_executor(self):
        """优雅关闭线程池"""
        if self.executor:
            self.executor.shutdown(wait=True)
            self.executor = None
    
    def stop(self):
        """停止检测"""
        self.stop_event.set()
        self._shutdown_executor()
    
    def reset(self):
        """重置状态，允许重新开始检测"""
        self.stop_event.clear()

    def find_king_pairs(self):
        """
        筛选出位置关系正确的将/帅
        """
        k_list = []  # ('k', x, y, r)
        K_list = []  # ('K', x, y, r)
        for x, y, r, piece_type in self.find_kings_on_screen():
            if piece_type == 'k':
                k_list.append((x, y, r))
            elif piece_type == 'K':
                K_list.append((x, y, r))
        filtered_pairs = []
        for x1, y1, r1 in k_list:
            for x2, y2, r2 in K_list:
                mean_r = (r1 + r2) / 2
                dx = abs(x1 - x2)
                dy = abs(y1 - y2)
                dx_ok = dx <= 2 * mean_r
                dy_ok = abs(dy - 18 * mean_r) <= 9 * mean_r
                if dx_ok and dy_ok:
                    filtered_pairs.append(((x1, y1, r1), (x2, y2, r2)))
                else:
                    print(f"未通过: k=({x1},{y1},r={r1}), K=({x2},{y2},r={r2}), dx={dx:.1f}, dy={dy:.1f}, mean_r={mean_r:.1f}, dx_ok={dx_ok}, dy_ok={dy_ok}")
        return filtered_pairs

    def locate_board_from_pairs(self):
        """
        根据正确的将/帅，计算棋盘坐标
        Returns:
            (x_board, y_board) or None
        """
        filtered_pairs = self.find_king_pairs()
        if len(filtered_pairs) == 0:
            raise BoardLocatorError("未检测到棋盘")
        elif len(filtered_pairs) > 1:
            raise BoardLocatorError(f"检测到{len(filtered_pairs)}个棋盘，请仅保留一个")
        else:
            # 只有一对，计算棋盘坐标
            king_pair = filtered_pairs[0]
            (x1, y1, r1), (x2, y2, r2) = king_pair
            mean_r = (r1 + r2) / 2
            
            # 获取当前窗口信息用于计算缩放因子
            scale = self._get_scale_factor(self._current_window_info)
            
            # 动态计算偏移量
            king_offset_x = self._get_scaled_size(self.base_sizes['king_offset_x'], scale)
            king_offset_y_ratio = self.base_sizes['king_offset_y_ratio']  # 比例值不需要缩放
            
            x_board = (x1 + x2) / 2 - king_offset_x
            y_board = min(y1, y2) - king_offset_y_ratio * mean_r
            
            print(f"棋盘左上角坐标: x={x_board:.1f}, y={y_board:.1f}")
            print(f"缩放因子: {scale:.3f}, 偏移量: {king_offset_x:.1f}")
            
            return (x_board, y_board)
        
    def update_board_and_avatars_regions(self, manual_coords=None):   
        """
        根据棋盘左上角坐标，自动计算棋盘区域和上下头像区域。
        
        Args:
            manual_coords: 可选的手动坐标 (x, y)，如果提供则使用手动坐标，否则自动检测
        Returns:
            dict: 包含 board, avatar_upper, avatar_lower
        Raises:
            BoardLocatorError: 棋盘定位相关错误
        """
        if manual_coords is not None:
            # 手动定位模式：使用提供的坐标
            x, y = manual_coords
            print(f"使用手动坐标: ({x}, {y})")
        else:
            # 自动定位模式：检测棋盘位置
            try:
                board_pos = self.locate_board_from_pairs()
                x, y = board_pos
                print(f"自动检测到棋盘坐标: ({x}, {y})")
            except BoardLocatorError:
                # 重新抛出棋盘定位错误
                raise
        
        # 获取当前窗口信息用于计算缩放因子
        scale = self._get_scale_factor(self._current_window_info)
        
        # 动态计算尺寸
        board_width = self._get_scaled_size(self.base_sizes['board_width'], scale)
        board_height = self._get_scaled_size(self.base_sizes['board_height'], scale)
        region_height = self._get_scaled_size(self.base_sizes['region_height'], scale)
        square_size = self._get_scaled_size(self.base_sizes['square_size'], scale)
        
        print(f"动态计算尺寸 - 缩放因子: {scale:.3f}")
        print(f"棋盘: {board_width}x{board_height}, 头像区域: {region_height}, 头像尺寸: {square_size}")
        
        # 棋盘区域
        board_region = {'left': x, 'top': y, 'width': board_width, 'height': board_height}
        print(f"棋盘区域: left={x}, top={y}, width={board_width}, height={board_height}")

        # 上下头像区域
        upper_region = {'left': x, 'top': y - region_height, 'width': board_width, 'height': region_height}
        lower_region = {'left': x, 'top': y + board_height, 'width': board_width, 'height': region_height}
        print(f"上头像区域: left={x}, top={y - region_height}, width={board_width}, height={region_height}")
        print(f"下头像区域: left={x}, top={y + board_height}, width={board_width}, height={region_height}")

        # 截取棋盘区域的图片
        with mss.mss() as sct:
            # 棋盘
            board_screenshot = sct.grab(board_region)
            board_img = np.frombuffer(board_screenshot.bgra, np.uint8).reshape(board_screenshot.height, board_screenshot.width, 4)
            board_img = board_img[:, :, :3]
            cv2.imwrite(resource_path('images/board/board.png'), board_img)

        # 平台判断
        platform_type = self.context.platform

        # 检测头像区域
        avatar_regions = {}
        avatar_rects = {}
        
        # 根据平台设置偏移量（也需要缩放）
        if platform_type == "JJ":
            # JJ平台偏移量
            base_upper_offset_x = 0
            base_upper_offset_y = 5
            base_lower_offset_x = 5
            base_lower_offset_y = -15
        else:  # TT平台
            # TT平台偏移量
            base_upper_offset_x = -5
            base_upper_offset_y = 0
            base_lower_offset_x = 5
            base_lower_offset_y = 0
        
        # 动态计算偏移量
        upper_offset_x = self._get_scaled_size(base_upper_offset_x, scale)
        upper_offset_y = self._get_scaled_size(base_upper_offset_y, scale)
        lower_offset_x = self._get_scaled_size(base_lower_offset_x, scale)
        lower_offset_y = self._get_scaled_size(base_lower_offset_y, scale)
        
        # 统一计算头像区域
        # upper: 取upper_region左上角，应用偏移量
        upper_left = (upper_region['left'] + upper_offset_x, upper_region['top'] + upper_offset_y)
        avatar_regions['upper'] = {
            'left': upper_left[0],
            'top': upper_left[1],
            'width': square_size,
            'height': square_size
        }
        print(f"上头像最终区域: left={upper_left[0]}, top={upper_left[1]}, width={square_size}, height={square_size}")
        
        # lower: 取lower_region右下角，应用偏移量
        lower_right_x = lower_region['left'] + lower_region['width'] + lower_offset_x
        lower_right_y = lower_region['top'] + lower_region['height'] + lower_offset_y
        avatar_regions['lower'] = {
            'left': lower_right_x - square_size,
            'top': lower_right_y - square_size,
            'width': square_size,
            'height': square_size
        }
        print(f"下头像最终区域: left={lower_right_x - square_size}, top={lower_right_y - square_size}, width={square_size}, height={square_size}")
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


if __name__ == "__main__":
    # 测试代码
    print("开始检测棋盘位置...")
    start_time = time.time()
    locator = BoardLocator()
    try:
        board_pos = locator.locate_board_from_pairs()
    finally:
        locator.stop()
    end_time = time.time()
    print(f"检测完成，耗时: {end_time - start_time:.2f}秒")
    print("棋盘坐标：", board_pos)


