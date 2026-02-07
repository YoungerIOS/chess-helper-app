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
       - 寻找("将"、"卒"、"卒")和("帅"、"兵"、"兵")组合
       - 根据兵卒组合计算棋盘坐标和尺寸
    
    3. 区域计算：根据棋盘位置计算各个功能区域
       - 棋盘区域：用于棋子识别
       - 上方头像区域：用于倒计时检测
       - 下方头像区域：用于倒计时检测
    
    4. 配置更新：将计算出的区域坐标保存到配置文件
       - 更新当前平台的区域配置
       - 保存头像检测区域
       - 保存棋盘截图区域
"""
import mss  # type: ignore
import cv2  # type: ignore
import numpy as np  # type: ignore
import threading
import time
import platform
import logging
from app.tools.utils import app_cache_path
from app.chess.context import context as global_context
from app.chess.recognizer import ChessRecognizer
from app.chess.message import Message, MessageType
from app.chess.message_bus import message_bus
from app.chess.border_detector import reset_border_cache

# 跨平台窗口检测
WIN32GUI_AVAILABLE = False
_win32gui_module = None

if platform.system() == "Darwin":  # macOS
    import Quartz  # type: ignore
elif platform.system() == "Windows":  # Windows
    try:
        import importlib
        _win32gui_module = importlib.import_module('win32gui')
        WIN32GUI_AVAILABLE = True
    except ImportError:
        print("警告: win32gui模块不可用，请安装: pip install pywin32")
else:  # Linux或其他系统
    print("警告: 当前系统不支持窗口检测，将使用全屏检测")

class LocationError(Exception):
    """棋盘定位器异常类"""
    pass

class WindowError(LocationError):
    """窗口检测错误"""
    pass

class PieceError(LocationError):
    """棋子检测错误"""
    pass

class CombsError(LocationError):
    """棋子组合错误"""
    pass

class BoardLocator:
    def __init__(self, context=None):
        self.stop_event = threading.Event()
        self.context = context or global_context
        self.recognizer = ChessRecognizer()
        
        # 设置日志记录器
        self.logger = logging.getLogger(__name__)
        
        # 游戏窗口标题关键词
        self.game_titles = {
            "JJ": ["JJ象棋"],
            "TT": ["天天象棋"]
        }
        self.window_size = None
        
        # 定位状态管理
        self._relocating = False
        self._relocate_lock = threading.Lock()
        self._located_event = threading.Event()

        # 棋盘和头像区域的基本参数
        # 这些值需要根据实际测量调整 (默认值在1440x900分辨率/窗口尺寸400x753下测得)
        self.piece_mean_r = 17.5    # 棋子平均半径
        self.board_width = 388      # 棋盘宽度
        self.board_height = 416     # 棋盘高度
        self.square_size = 84       # 头像尺寸
    
    def stop(self):
        """停止检测"""
        self.stop_event.set()
    
    def reset(self):
        """重置状态，允许重新开始检测"""
        self.stop_event.clear()

    def find_window_by_title_macos(self, keyword):
        """使用Quartz查找窗口（macOS）"""
        try:
            options = Quartz.kCGWindowListOptionOnScreenOnly
            window_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
            matches = []

            for win in window_list:
                title = win.get('kCGWindowName', '')
                owner = win.get('kCGWindowOwnerName', '')
                
                # Check match in Title OR Owner
                if (title and keyword.lower() in title.lower()) or \
                   (owner and keyword.lower() in owner.lower()):
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

    def find_game_window(self, platform_name):
        """查找游戏窗口 (Refined Logic)"""
        system = platform.system()
        
        if system not in ["Darwin", "Windows"]:
            print(f"当前系统 {system} 不支持窗口检测，跳过窗口检测")
            return None
        
        # 收集所有匹配的窗口
        # candidates: List of (score, platform, match_info)
        # Score rules:
        # 100: Specific Title (not "微信") + Matches Requested Platform
        # 90:  Specific Title (not "微信") + Matches Other Platform
        # 50:  Generic Title ("微信") + Matches Requested Platform
        # 40:  Generic Title ("微信") + Matches Other Platform
        
        candidates = []
        
        # 遍历所有支持的平台
        for p, titles in self.game_titles.items():
            for title in titles:
                matches = self.find_window_by_title(title)
                
                if matches:
                    score = 100  # 具体标题匹配
                    
                    if p == platform_name:
                        score += 10  # 优先匹配当前请求的平台
                        
                    # 只取第一个匹配项（通常是最上层的）
                    match = matches[0]
                    candidates.append({
                        'score': score,
                        'platform': p,
                        'title': match['title'],
                        'match_info': match
                    })

        if not candidates:
            return None
            
        # 按分数降序排序
        candidates.sort(key=lambda x: x['score'], reverse=True)
        
        # 选择最佳匹配
        best_candidate = candidates[0]
        p = best_candidate['platform']
        match = best_candidate['match_info']
        
        # 构建返回信息
        x, y, width, height = match['bounds']
        self.window_size = (int(width), int(height))
        
        window_info = {
            'platform': p,
            'platform_name': self.game_titles[p][0], # 使用配置的第一个标题作为显示名称
            'title': match['title'],
            'region': {
                'left': int(x),
                'top': int(y),
                'width': int(width),
                'height': int(height)
            },
            'confidence': 1.0 if best_candidate['score'] >= 50 else 0.5
        }

        # 更新上下文中的平台为检测到的平台（只在平台真正变化时）
        if self.context and self.context.platform != p:
            self.context.set_platform(p)
            
        return window_info

    def _find_pieces_in_window(self):
        """在指定游戏窗口内检测将帅"""
        
        # 1. 首先尝试检测游戏窗口
        window_info = self.find_game_window(self.context.platform)
        search_region = None
        
        if window_info:
            # 2. 获取棋盘搜索区域
            region = window_info['region']
            search_region = {
                'left': region['left'],
                'top': region['top'],
                'width': region['width'],
                'height': region['height']
            }
            # 对TT平台：搜索区域左右各收缩25%，更聚焦棋盘区域
            if window_info['platform'] == "TT":
                quarter_w = int(search_region['width'] * 0.25)
                search_region['left'] = int(search_region['left'] + quarter_w)
                search_region['width'] = int(search_region['width'] - 2 * quarter_w)
            # 对JJ平台：搜索区域上下各收缩15%
            elif window_info['platform'] == "JJ":
                shrink_h = int(search_region['height'] * 0.15)
                search_region['top'] = int(search_region['top'] + shrink_h)
                search_region['height'] = int(search_region['height'] - 2 * shrink_h)
        else:
            print("未检测到游戏窗口")
            raise WindowError("未检测到游戏窗口")

        # 1. 截取搜索区域
        with mss.mss() as sct:
            screenshot = sct.grab(search_region)
        
        # 2. 转为OpenCV格式
        img_np = np.frombuffer(screenshot.bgra, np.uint8).reshape(screenshot.height, screenshot.width, 4)
        img_np = img_np[:, :, :3].copy()
        
        # 保存搜索区域截图
        search_path = app_cache_path(f"search_region_{window_info['title'].replace(' ', '_')}.jpg")
        cv2.imwrite(search_path, img_np)
        print(f"已保存搜索区域截图: {search_path}")
        
        # 3. 根据平台选择不同的预处理策略
        gray = cv2.cvtColor(img_np, cv2.COLOR_BGR2GRAY)
        
        platform = window_info['platform']
        
        # 3. 图像放大策略
        # 统一放大2倍（TT平台已在截取前收缩区域，这里无需再次裁剪）
        scale_factor = 2.0
        base_h, base_w = img_np.shape[0], img_np.shape[1]
        target_width = int(base_w * scale_factor)
        target_height = int(base_h * scale_factor)
        
        # 放大图像
        scaled_img = cv2.resize(img_np, (target_width, target_height), interpolation=cv2.INTER_CUBIC)
        scaled_gray = cv2.resize(gray, (target_width, target_height), interpolation=cv2.INTER_CUBIC)
        
        print(f"图像放大: {base_w}x{base_h} -> {target_width}x{target_height}, 缩放比例: {scale_factor:.2f}")
        
        # 动态计算棋子半径范围
        # 假设：标准棋盘通常占满搜索区域宽度（TT稍微收缩过，JJ占大部分）
        # 标准棋盘宽度大约是9个格子的宽度，加上两边边距，大约相当于10-11个棋子直径
        # 估算：一个棋子直径约占 搜索区域宽度 的 1/10 ~ 1/12
        # 我们设定一个较宽的估算范围：
        estimated_diameter = target_width / 10.0
        estimated_radius = estimated_diameter / 2.0
        
        # 设定动态阈值 (基于估算半径的 60% ~ 140%)
        minRadius = int(estimated_radius * 0.6)
        maxRadius = int(estimated_radius * 1.4)
        
        # 确保最小半径至少为8（避免噪点）
        minRadius = max(8, minRadius)
        
        print(f"动态半径计算: 估算半径r={estimated_radius:.1f}px, 搜索范围=[{minRadius}, {maxRadius}]")
        
        # 统一的预处理参数
        # 无论平台，先尝试高斯模糊减少噪点
        blurred = cv2.GaussianBlur(scaled_gray, (5, 5), 0)
        
        if platform == "JJ":
             # JJ平台特定优化
             kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
             processed = cv2.morphologyEx(blurred, cv2.MORPH_CLOSE, kernel)
             param1 = 70
             param2 = 30
             minDist = int(estimated_diameter * 0.8) # 两个棋子圆心最小距离略小于直径
        else:
            # TT平台或其他
             processed = blurred
             param1 = 50
             param2 = 25
             minDist = int(estimated_diameter * 0.8)

        # 5. 霍夫圆检测
        circles = cv2.HoughCircles(processed, cv2.HOUGH_GRADIENT, 1, minDist,
                                  param1=param1, param2=param2,
                                  minRadius=minRadius, maxRadius=maxRadius)
        
        if circles is None:
            # 如果第一次检测失败，尝试放宽范围重试 (0.5 ~ 1.6)
            print("首次检测未发现圆形，尝试放宽范围重试...")
            minRadius_retry = int(estimated_radius * 0.5)
            maxRadius_retry = int(estimated_radius * 1.6)
            circles = cv2.HoughCircles(processed, cv2.HOUGH_GRADIENT, 1, minDist,
                                      param1=param1, param2=int(param2 * 0.8), # 稍微降低阈值
                                      minRadius=minRadius_retry, maxRadius=maxRadius_retry)

        if circles is None:
            print("在游戏窗口内未检测到任何圆形 (重试后)")
            self.logger.warning("霍夫圆检测未发现任何圆形")
            detected_circles_path = app_cache_path("detected_circles.jpg")
            cv2.imwrite(detected_circles_path, img_np)
            print(f"已保存检测结果图片: {detected_circles_path}")
            raise PieceError("未检测到象棋棋子")
            
        circles = np.round(circles[0, :]).astype("int")
        print(f"游戏窗口内霍夫圆检测到 {len(circles)} 个圆形")
        self.logger.info(f"霍夫圆检测结果: 检测到{len(circles)}个圆形")
        
        # 6. 计算Retina缩放因子 (物理像素 / 逻辑像素)
        # search_region['width'] 是逻辑点(Points)，img_np.shape[1] 是物理像素(Pixels)
        retina_scale = img_np.shape[1] / search_region['width']
        print(f"Retina缩放检测: 逻辑宽度={search_region['width']}, 物理像素={img_np.shape[1]}, 缩放因子={retina_scale:.2f}")

        # 7. 将检测到的圆坐标转换回原始图像尺寸 (Physical Pixels)
        # 注意：这里我们得到的 circles 是在 2x 放大后的图像上的
        original_circles = []
        for x, y, r in circles:
            orig_x = int(x / scale_factor)
            orig_y = int(y / scale_factor)
            orig_r = int(r / scale_factor)
            original_circles.append((orig_x, orig_y, orig_r))
        
        # 8. 处理圆检测（使用原始尺寸的坐标 - Physical Pixels）
        piece_centers = self._process_circles(original_circles, img_np)
        
        # 9. 将相对坐标(Pixels)转换为绝对坐标(Points)
        # 必须除以 retina_scale 才能变回逻辑点
        absolute_piece_centers = []
        for x, y, r, piece_type in piece_centers:
            # 先转回逻辑点偏移量
            offset_x_points = x / retina_scale
            offset_y_points = y / retina_scale
            r_points = r / retina_scale
            
            # 再加上窗口得逻辑点原点
            abs_x = offset_x_points + search_region['left']
            abs_y = offset_y_points + search_region['top']
            
            absolute_piece_centers.append((abs_x, abs_y, r_points, piece_type))

        
        # 9. 筛选关键点位置的棋子组合(卒, 将, 卒)/(兵, 帅, 兵)
        filtered_pieces = self._filter_keypoint_pieces(absolute_piece_centers)
        
        # 10. 检测是否为缩小棋盘（JJ的游戏结算界面）
        if filtered_pieces and platform == "JJ":
            self._eliminate_mini_board(absolute_piece_centers, search_region)
        
        # 10. 保存可视化结果（在开发环境和打包环境都保存）
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
        
        # 绘制检测到的所有棋子组合
        for combination in filtered_pieces:
            # 绘制将/帅
            king_x, king_y, king_r, king_type = combination['king']
            # 将逻辑坐标(Float)转回物理像素(Int)用于绘图
            draw_x = int(king_x * retina_scale)
            draw_y = int(king_y * retina_scale)
            draw_r = int(king_r * retina_scale)
            
            cv2.circle(full_img, (draw_x, draw_y), draw_r, (0, 255, 0), 2)
            cv2.circle(full_img, (draw_x, draw_y), 2, (0, 0, 255), 3)
            
            # 绘制兵/卒（如果存在）
            if combination['pawns'] and len(combination['pawns']) >= 2:
                # 绘制左兵/卒
                left_x, left_y, left_r, left_type = combination['pawns'][0]
                lx, ly, lr = int(left_x*retina_scale), int(left_y*retina_scale), int(left_r*retina_scale)
                cv2.circle(full_img, (lx, ly), lr, (0, 255, 255), 2)
                cv2.circle(full_img, (lx, ly), 2, (255, 255, 0), 3)
                
                # 绘制右兵/卒
                right_x, right_y, right_r, right_type = combination['pawns'][1]
                rx, ry, rr = int(right_x*retina_scale), int(right_y*retina_scale), int(right_r*retina_scale)
                cv2.circle(full_img, (rx, ry), rr, (0, 255, 255), 2)
                cv2.circle(full_img, (rx, ry), 2, (255, 255, 0), 3)
                
            # 绘制车（如果存在）
            if combination['rooks'] and len(combination['rooks']) >= 2:
                # 绘制左车
                left_x, left_y, left_r, left_type = combination['rooks'][0]
                lx, ly, lr = int(left_x*retina_scale), int(left_y*retina_scale), int(left_r*retina_scale)
                cv2.circle(full_img, (lx, ly), lr, (255, 0, 255), 2)
                cv2.circle(full_img, (lx, ly), 2, (255, 0, 255), 3)
                
                # 绘制右车
                right_x, right_y, right_r, right_type = combination['rooks'][1]
                rx, ry, rr = int(right_x*retina_scale), int(right_y*retina_scale), int(right_r*retina_scale)
                cv2.circle(full_img, (rx, ry), rr, (255, 0, 255), 2)
                cv2.circle(full_img, (rx, ry), 2, (255, 0, 255), 3)
        
        detected_circles_path = app_cache_path("detected_circles.jpg")
        cv2.imwrite(detected_circles_path, full_img)
        print(f"已保存区域检测结果图片: {detected_circles_path}")
        
        return filtered_pieces
    
    def _filter_keypoint_pieces(self, piece_centers):
        """
        筛选出位置关系正确的将/帅和兵卒组合
        
        Args:
            piece_centers: List[Tuple[int, int, int, str]] 检测到的所有棋子 (x, y, r, piece_type)
        
        Returns:
            List[Dict]: 筛选后的棋子组合列表，每个组合为:
                {
                    'king': (x, y, r, 'k' or 'K'),
                    'rooks': [(左车), (右车)],
                    'pawns': [(左兵/卒), (右兵/卒)]
                }
        """
        # 分类棋子
        kings_black = []   # 黑将 k
        kings_red = []     # 红帅 K
        black_pawns = []   # 黑卒 p
        red_pawns = []     # 红兵 P
        black_rooks = []   # 黑车 r
        red_rooks = []     # 红车 R
        
        for x, y, r, piece_type in piece_centers:
            if piece_type == 'k':
                kings_black.append((x, y, r, piece_type))
            elif piece_type == 'K':
                kings_red.append((x, y, r, piece_type))
            elif piece_type == 'p':
                black_pawns.append((x, y, r, piece_type))
            elif piece_type == 'P':
                red_pawns.append((x, y, r, piece_type))
            elif piece_type == 'r':
                black_rooks.append((x, y, r, piece_type))
            elif piece_type == 'R':
                red_rooks.append((x, y, r, piece_type))
            
        print(f"检测到的棋子统计:")
        print(f"  黑将: {len(kings_black)} 个, 红帅: {len(kings_red)} 个")
        print(f"  黑卒: {len(black_pawns)} 个, 红兵: {len(red_pawns)} 个")
        print(f"  黑车: {len(black_rooks)} 个, 红车: {len(red_rooks)} 个")
        
        # 记录到日志
        self.logger.info(f"棋子检测统计: 黑将={len(kings_black)}, 红帅={len(kings_red)}, 黑卒={len(black_pawns)}, 红兵={len(red_pawns)}, 黑车={len(black_rooks)}, 红车={len(red_rooks)}")
        
        # 1.将帅组合
        king_ok = len(kings_black) == 1 and len(kings_red) == 1
        if not king_ok:
            error_msg = f"将帅数量错误"
            raise PieceError(error_msg)
        king_x_diff = abs(kings_black[0][0] - kings_red[0][0])
        king_y_diff = abs(kings_black[0][1] - kings_red[0][1])
        mean_diameter = kings_black[0][2] + kings_red[0][2]
        if king_x_diff > 3 * mean_diameter or king_y_diff < 5 * mean_diameter:
            error_msg = f"将帅位置错误"
            raise PieceError(error_msg)


        black_king = kings_black[0]
        red_king = kings_red[0]
        
        filtered_combinations = []
        
        # 2.黑方组合
        black_combination = self._filter_combination(
            king=black_king,
            pawns=black_pawns,
            rooks=black_rooks
        )
        if black_combination:
            filtered_combinations.append(black_combination)
            self.logger.info(f"黑方组合筛选成功: 将={black_combination['king'][3]}, 兵/卒={len(black_combination.get('pawns', []))}, 车={len(black_combination.get('rooks', []))}")
        else:
            print("黑方组合筛选失败")
            self.logger.warning("黑方组合筛选失败")
        
        # 3.红方组合
        red_combination = self._filter_combination(
            king=red_king,
            pawns=red_pawns,
            rooks=red_rooks
        )
        if red_combination:
            filtered_combinations.append(red_combination)
            self.logger.info(f"红方组合筛选成功: 将={red_combination['king'][3]}, 兵/卒={len(red_combination.get('pawns', []))}, 车={len(red_combination.get('rooks', []))}")
        else:
            print("红方组合筛选失败")
            self.logger.warning("红方组合筛选失败")
        
        return filtered_combinations
    
    def _eliminate_mini_board(self, piece_centers, search_region):
        """
        排除缩小的棋盘（游戏结算界面）
        """
        if not piece_centers:
            return
            
        # 找出x坐标最小的棋子
        leftmost_piece = min(piece_centers, key=lambda piece: piece[0])
        leftmost_x, leftmost_y, leftmost_r, leftmost_type = leftmost_piece
        
        # 计算该棋子与搜索区域左边界的距离
        distance_to_left = leftmost_x - search_region['left']
        
        # 判断：如果距离超过3倍棋子半径，说明是缩小棋盘
        if distance_to_left > 3 * leftmost_r:
            error_msg = f"检测到缩小棋盘（游戏结算界面），最左棋子距离边界: {distance_to_left:.1f}px，棋子半径: {leftmost_r:.1f}px"
            print(error_msg)
            raise PieceError("检测到游戏结算界面，等待开始对局")
    
    def _filter_combination(self, king, pawns, rooks):
        """
        筛选正确位置关系的将帅兵卒车组合
        
        Args:
            king: Tuple[int, int, int, str] 将/帅 (x, y, r, piece_type)
            pawns: List[Tuple[int, int, int, str]] 兵/卒列表
            rooks: List[Tuple[int, int, int, str]] 车列表
        
        Returns:
            Dict:
                {
                    'king': king,
                    'rooks': [左车, 右车] 或 [],
                    'pawns': [左兵/卒, 右兵/卒] 或 []
                }
        """
        king_x, king_y, king_r, king_type = king
        
        # 1) 计算通用平均半径（使用传入的所有棋子半径：王 + 所有兵/卒 + 所有车）
        radii = [king_r]
        if pawns:
            radii.extend([p[2] for p in pawns])
        if rooks:
            radii.extend([r[2] for r in rooks])
        # 避免除零，至少包含王半径
        mean_r = sum(radii) / max(1, len(radii))
        # 保存为实例变量，供后续棋盘定位与区域计算复用
        self.piece_mean_r = mean_r
        
        selected_pawns = []
        selected_rooks = []
        
        # 2) 兵/卒：必须至少2个。取最左与最右，要求：y大致同一行且 x对称于王
        if pawns and len(pawns) >= 2:
            # 按x排序，取最左与最右
            sorted_pawns = sorted(pawns, key=lambda p: p[0])
            left_pawn = sorted_pawns[0]
            right_pawn = sorted_pawns[-1]   
            if left_pawn != right_pawn:
                # 计算y大致同一行 且 x对称于王
                left_x, left_y, _, _ = left_pawn
                right_x, right_y, _, _ = right_pawn
                y_ok_pawn = abs(left_y - right_y) <= 2 * mean_r
                left_x_diff = abs(left_x - king_x)
                right_x_diff = abs(right_x - king_x)
                x_diff_ok_pawn = abs(left_x_diff - right_x_diff) <= 2 * mean_r and left_x_diff > 6 * mean_r and right_x_diff > 6 * mean_r
                if y_ok_pawn and x_diff_ok_pawn:
                    selected_pawns = [left_pawn, right_pawn]
        
        # 3) 车：必须恰好2个。要求：两车与王y大致同一行，且 x对称于王
        if rooks and len(rooks) == 2:
            rook_a, rook_b = rooks[0], rooks[1]
            # 按x分左右
            left_rook, right_rook = (rook_a, rook_b) if rook_a[0] <= rook_b[0] else (rook_b, rook_a)
            # y与王同行
            y_ok_rook = (abs(left_rook[1] - king_y) <= 2 * mean_r and
                         abs(right_rook[1] - king_y) <= 2 * mean_r)
            # x对称
            left_x_diff_rook = abs(left_rook[0] - king_x)
            right_x_diff_rook = abs(right_rook[0] - king_x)
            x_diff_ok_rook = abs(left_x_diff_rook - right_x_diff_rook) <= 2 * mean_r and left_x_diff_rook > 6 * mean_r and right_x_diff_rook > 6 * mean_r
            if y_ok_rook and x_diff_ok_rook:
                selected_rooks = [left_rook, right_rook]
                
        if not selected_rooks and not selected_pawns:
            error_msg = "缺少定位棋子组合"
            raise CombsError(error_msg)
        
        return {
            'king': king,
            'rooks': selected_rooks,
            'pawns': selected_pawns
        }
    
    def _locate_board_from_combs(self):
        """
        根据兵卒组合计算棋盘坐标和尺寸
        Returns:
            (x_board, y_board, board_width, board_height) or None
        """
        combinations = self._find_pieces_in_window()

        # 分离黑将组合和红帅组合
        black_combination = None  
        red_combination = None    
        for combination in combinations:
            if combination['king'][3] == 'k':
                black_combination = combination
            elif combination['king'][3] == 'K':
                red_combination = combination
    
        if not black_combination or not red_combination:
            error_msg = "缺少定位棋子组合"
            self.logger.error(f"棋盘定位失败: {error_msg}")
            raise CombsError(error_msg)
    
        # 提取棋子信息
        black_king = black_combination.get('king', [])
        red_king = red_combination.get('king', [])
        black_pawns = black_combination.get('pawns', [])
        red_pawns = red_combination.get('pawns', [])
        black_rooks = black_combination.get('rooks', [])
        red_rooks = red_combination.get('rooks', [])

        # 1. 计算平均半径r（优先使用_filter_combination计算的通用半径）
        if hasattr(self, 'piece_mean_r'):
            mean_r = self.piece_mean_r
        else:
            # 回退：计算所有可用棋子的平均半径
            all_radii = [black_king[2], red_king[2]]
            if black_pawns:
                all_radii.extend([p[2] for p in black_pawns])
            if red_pawns:
                all_radii.extend([p[2] for p in red_pawns])
            if black_rooks:
                all_radii.extend([r[2] for r in black_rooks])
            if red_rooks:
                all_radii.extend([r[2] for r in red_rooks])
            mean_r = sum(all_radii) / max(1, len(all_radii))

        # 2. 计算每侧的"王+车"y平均值
        black_y_candidates = [black_king[1]]
        if black_rooks:
            black_y_candidates.extend([r[1] for r in black_rooks])
        black_y_avg = sum(black_y_candidates) / max(1, len(black_y_candidates))

        red_y_candidates = [red_king[1]]
        if red_rooks:
            red_y_candidates.extend([r[1] for r in red_rooks])
        red_y_avg = sum(red_y_candidates) / max(1, len(red_y_candidates))

        # 3. 计算board_y（取较高侧的平均y）
        higher_side_y = min(black_y_avg, red_y_avg)  # y坐标向下为正
        # 4. 计算board_height（两侧平均y的垂直距离）
        king_vertical_distance = abs(black_y_avg - red_y_avg)

        # 计算并在计算时保留一位小数
        board_y = round(higher_side_y - king_vertical_distance / 18, 1)
        board_height = round(king_vertical_distance + king_vertical_distance / 9, 1)

        # 5. 计算board_width（使用可用的水平跨度）
        spans = []
        # 兵/卒的水平跨度
        if black_pawns and len(black_pawns) >= 2:
            black_pawn_span = abs(black_pawns[1][0] - black_pawns[0][0])
            spans.append(black_pawn_span)
        if red_pawns and len(red_pawns) >= 2:
            red_pawn_span = abs(red_pawns[1][0] - red_pawns[0][0])
            spans.append(red_pawn_span)
        
        # 车的水平跨度
        if black_rooks and len(black_rooks) >= 2:
            black_rook_span = abs(black_rooks[1][0] - black_rooks[0][0])
            spans.append(black_rook_span)
        if red_rooks and len(red_rooks) >= 2:
            red_rook_span = abs(red_rooks[1][0] - red_rooks[0][0])
            spans.append(red_rook_span)
        
        avg_span = sum(spans) / max(1, len(spans))
        
        # 如果spans为空，使用默认值
        if not spans:
            raise CombsError("缺少定位棋子, 无法确定棋盘宽度")

        # 6. 计算board_x（最左兵/车x的平均值）
        x_candidates = []
        if black_pawns:
            x_candidates.append(min(p[0] for p in black_pawns))
        if red_pawns:
            x_candidates.append(min(p[0] for p in red_pawns))
        if black_rooks:
            x_candidates.append(min(r[0] for r in black_rooks))
        if red_rooks:
            x_candidates.append(min(r[0] for r in red_rooks))
        # 最左x坐标
        leftmost_x = sum(x_candidates) / max(1, len(x_candidates))
        
        # 计算并在计算时保留一位小数
        board_x = round(leftmost_x - avg_span / 16, 1)
        board_width = round(avg_span + avg_span / 8, 1)

        # 保存参考距离，供后续计算头像位置使用
        self.base_height = king_vertical_distance
        self.base_width = avg_span
        self.base_radius = mean_r
        print(f"已保存参考距离 - 将帅垂直距离: {king_vertical_distance:.1f}, 平均跨度: {self.base_width:.1f}")

        # 输出调试信息
        print(f"棋盘定位计算结果:")
        print(f"  平均半径: {mean_r:.1f}")
        print(f"  黑将位置: ({black_king[0]}, {black_king[1]})")
        print(f"  红帅位置: ({red_king[0]}, {red_king[1]})")
        print(f"  黑侧平均y: {black_y_avg:.1f}")
        print(f"  红侧平均y: {red_y_avg:.1f}")
        print(f"  较高侧y坐标: {higher_side_y:.1f}")
        print(f"  将帅垂直距离: {king_vertical_distance:.1f}")
        print(f"  最左x坐标: {leftmost_x:.1f}")
        print(f"  平均跨度: {avg_span if spans else 8 * mean_r:.1f}")
        print(f"  棋盘坐标: ({board_x:.1f}, {board_y:.1f})")
        print(f"  棋盘尺寸: {board_width:.1f} x {board_height:.1f}")

        # 添加可视化：在detected_circles.jpg上画出棋盘矩形和网格线
        try:
            # 读取现有的detected_circles.jpg图片
            detected_circles_path = app_cache_path("detected_circles.jpg")
            detected_img = cv2.imread(detected_circles_path)
            if detected_img is not None:
                # 绘制棋盘矩形
                board_left = int(board_x)
                board_top = int(board_y)
                board_right = int(board_x + board_width)
                board_bottom = int(board_y + board_height)
                
                # 用红色矩形框画出棋盘区域
                cv2.rectangle(detected_img, 
                             (board_left, board_top), 
                             (board_right, board_bottom), 
                             (0, 0, 255), 1)
                # 保存更新后的图片
                cv2.imwrite(detected_circles_path, detected_img)
                print(f"已更新检测结果图片（添加棋盘矩形）: {detected_circles_path}")
        except Exception as e:
            print(f"可视化过程中出错: {e}")

        return (board_x, board_y, board_width, board_height)

    def _process_circles(self, circles, img_np):
        """处理圆检测（单线程版本，避免模型访问冲突）"""
        piece_centers = []
        
        # 单线程处理，避免PyTorch模型在多线程环境中的访问冲突
        for x, y, r in circles:
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
            result = self.recognizer.recognize_piece_type(piece_img)
            if result is None:
                # 识别失败，跳过这个圆
                self.logger.debug(f"棋子识别失败: 位置({x}, {y}), 半径{r}")
                continue
            
            piece_type, confidence = result
            self.logger.debug(f"棋子识别: 位置({x}, {y}), 类型={piece_type}, 置信度={confidence:.3f}")
            
            # 先画所有检测到的圆（用蓝色）
            cv2.circle(img_np, (x, y), r, (255, 0, 0), 2)  # 蓝色圆圈
            cv2.circle(img_np, (x, y), 2, (255, 0, 0), 3)  # 蓝色圆心
            
            # 如果是将帅或兵卒且置信度高，添加到结果中
            if piece_type in ('k', 'K', 'p', 'P', 'r', 'R') and confidence > 0.9:
                piece_centers.append((x, y, r, piece_type))
                # 将帅用绿色重新标记，兵卒用黄色标记
                if piece_type in ('k', 'K'):
                    cv2.circle(img_np, (x, y), r, (0, 255, 0), 1)  # 绿色圆圈
                    cv2.circle(img_np, (x, y), 2, (0, 0, 255), 3)  # 红色圆心
                elif piece_type in ('p', 'P'):
                    cv2.circle(img_np, (x, y), r, (0, 255, 255), 1)  # 黄色圆圈（兵卒）
                    cv2.circle(img_np, (x, y), 2, (255, 255, 0), 3)  # 青色圆心
                else:  # 车R/r
                    cv2.circle(img_np, (x, y), r, (255, 0, 255), 1)  # 品红色圆圈（车）
                    cv2.circle(img_np, (x, y), 2, (255, 0, 255), 3)  # 品红色圆心
        
        return piece_centers

    def update_board_and_avatars_regions(self, coords=None):   
        """
        根据棋盘左上角坐标，自动计算棋盘区域和上下头像区域。
        
        Args:
            coords: 可选的手动坐标 (x, y, width, height)，如果提供则使用手动坐标，否则自动检测
        Returns:
            dict: 包含 board, avatar_upper, avatar_lower
        """
        if coords is not None:
            # 手动定位模式：使用提供的坐标
            x, y, width, height = coords
            print(f"使用手动坐标: ({x}, {y}, {width}, {height})")
        else:
            # 自动定位模式：检测棋盘位置
            board_pos = self._locate_board_from_combs()
            x, y, width, height = board_pos
            print(f"自动检测到棋盘坐标: ({x}, {y}, {width}, {height})")
        
        # 棋盘区域
        board_region = {'left': x, 'top': y, 'width': width, 'height': height}
        print(f"棋盘区域: left={x}, top={y}, width={width}, height={height}")

        # 截取棋盘区域的图片
        with mss.mss() as sct:
            # 棋盘
            board_screenshot = sct.grab(board_region)
            board_img = np.frombuffer(board_screenshot.bgra, np.uint8).reshape(board_screenshot.height, board_screenshot.width, 4)
            board_img = board_img[:, :, :3]
            cv2.imwrite(app_cache_path('board/board.png'), board_img)
            
            # 将棋盘图片按宽度800缩放
            target_width = 800
            scale_factor = target_width / width
            target_height = int(height * scale_factor)
            scaled_board_img = cv2.resize(board_img, (target_width, target_height))
            
            # 在缩放后的棋盘图片上绘制网格线
            self._draw_grid_on_board_image(scaled_board_img)
            # 保存带网格线的缩放棋盘图片
            cv2.imwrite(app_cache_path('board/board_with_grid.png'), scaled_board_img)

        # 平台判断
        platform_type = self.context.platform

        # 检测头像区域
        avatar_regions = {}
        avatar_rects = {}
        
        # 如果参考基准还未初始化
        has_reference = hasattr(self, 'base_width') and hasattr(self, 'base_height')
        if not has_reference:
            # 获取窗口尺寸作为
            ref_w, ref_h = None, None
            if getattr(self, 'window_size', None):
                ref_w, ref_h = self.window_size
            else:
                info = self.find_game_window(self.context.platform)
                if info and 'region' in info:
                    ref_w, ref_h = info['region']['width'], info['region']['height']
                    self.window_size = (ref_w, ref_h)
            if not ref_w or not ref_h:
                raise LocationError("棋盘定位失败: 无法获取窗口尺寸")
            # 使用窗口尺寸作为参考
            if platform_type == "JJ":
                ref_width, ref_height = 0.86 * ref_w, 0.497 * ref_h
            elif platform_type == "TT":
                ref_width, ref_height = 0.398 * ref_w, 0.739 * ref_h
        else:
            # 使用棋盘检测的参考距离
            ref_width, ref_height = self.base_width, self.base_height
        
        # 根据平台设置头像位置计算逻辑（统一使用 ref_width, ref_height）
        # 防止除零错误
        if ref_width <= 0 or ref_height <= 0:
            raise LocationError(f"无效的参考尺寸: ref_width={ref_width}, ref_height={ref_height}")
            
        if platform_type == "JJ":
            # JJ平台：基于参考尺寸计算头像位置
            square_size = max(1, ref_width // 4)  # 防止除零
            upper_x = round(x, 1)
            upper_y = round(y - (0.36 * ref_height), 1)
            lower_x = round(x + (0.90 * ref_width), 1)
            lower_y = round(y + (1.25 * ref_height), 1)
               
        elif platform_type == "TT":  # TT平台
            # TT平台：基于参考尺寸计算头像位置
            square_size = max(1, ref_width // 5)  # 防止除零
            upper_x = round(x - (0.30 * ref_width), 1)
            upper_y = round(y + (0.03 * ref_width), 1)
            lower_x = round(x + (1.22 * ref_width), 1)
            lower_y = round(y + (0.88 * ref_width), 1)
            print(f"TT平台 - 使用参考距离计算头像位置:")
            print(f"  参考距离: base_width={ref_width:.1f}, base_height={ref_height:.1f}")
            print(f"  头像尺寸: {square_size}")
                
        
        # 计算头像区域
        avatar_regions['upper'] = {
            'left': upper_x,
            'top': upper_y,
            'width': square_size,
            'height': square_size
        }
        print(f"上头像区域: left={upper_x}, top={upper_y}, width={square_size}, height={square_size}")
        
        avatar_regions['lower'] = {
            'left': lower_x,
            'top': lower_y,
            'width': square_size,
            'height': square_size
        }
        print(f"下头像区域: left={lower_x}, top={lower_y}, width={square_size}, height={square_size}")
        
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
                    cv2.imwrite(app_cache_path(f'board/avatar_{pos}_rect.png'), rect_img_np)

            # 统一更新当前平台的区域配置（绝对坐标）
            platform = self.context.get_platform(self.context.platform)
            platform.regions = {
                "board": board_region,
                "avatar_upper": avatar_regions.get("upper"),
                "avatar_lower": avatar_regions.get("lower")
            }
            self.context.save_config()
            return board_region

    def handle_locating_board_tasks(self, message_type=None, data=None, moved_coords=None, fallback_coords=None):
        """
        尝试定位棋盘
        Args:
            message_type: 消息类型（回调时使用）
            data: 消息数据（回调时使用）
            moved_coords: 窗口移动时按移动距离计算的新坐标
            fallback_coords: 自动定位失败时的备用坐标
        Returns:
            bool: 是否成功定位棋盘
        """
        # 检查是否正在定位中
        with self._relocate_lock:
            if self._relocating:
                print("定位正在进行中，跳过重复请求")
                raise LocationError("定位正在进行中，跳过重复请求")
            self._relocating = True

        try:
            # 如果是作为回调函数被调用，打印消息信息
            if message_type is not None:
                print(f"收到重新定位请求: {message_type} = {data}")
            
            # 优先级：自动定位 > 窗口移动坐标 > 自动检测失败后的Fallback > 保存的手动坐标
            if moved_coords is not None:
                # 使用本次窗口移动坐标，清除手动坐标记录
                # self.context.manual_coords = None
                self.update_board_and_avatars_regions(coords=moved_coords)
                print("棋盘定位成功(窗口移动)")
                msg = "已重新计算棋盘位置"
            else:
                # 优先尝试自动定位
                try:
                    self.update_board_and_avatars_regions(coords=None)
                    print("棋盘定位成功(自动)")
                    msg = "棋盘定位完成"
                except LocationError:
                    # 自动定位失败
                    # 1. 尝试使用本次计算的Fallback坐标（通常是基于窗口缩放推算的）
                    if fallback_coords is not None:
                         self.update_board_and_avatars_regions(coords=fallback_coords)
                         print("棋盘定位成功(使用推算的Fallback坐标)")
                         msg = "棋盘定位成功"
                    else:
                        # 2. 检查是否有保存的手动坐标（注意：如果窗口已移动，这可能失效）
                        saved_manual_coords = self.context.manual_coords
                        if saved_manual_coords is not None:
                            # 使用保存的手动坐标
                            self.update_board_and_avatars_regions(coords=saved_manual_coords)
                            print("棋盘定位成功(使用保存的手动坐标)")
                            msg = "棋盘定位成功"
                        else:
                            # 没有手动坐标，重新抛出异常
                            raise
            
            # 发送成功消息
            message_bus.publish_status(msg)
            # 设置定位成功事件（唤醒等待）
            self._located_event.set()
            return True
        finally:
            # 重置定位状态
            with self._relocate_lock:
                self._relocating = False

    def monitor_window_movement(self, stop_event):
        """
        监控窗口移动，检测到移动时调用回调
        Args:
            stop_event: 停止事件
        """
        # 初始化：记录基准窗口边界（最近一次成功定位时的窗口边界）
        first_info = self.find_game_window(self.context.platform)
        baseline_bounds = first_info['region'] if first_info else None
        last_seen_bounds = baseline_bounds
        # 以定位时的棋盘区域为位移参考基准，避免累计漂移
        baseline_board_region = None
        platform_conf = self.context.get_platform(self.context.platform)
        if platform_conf and platform_conf.regions.get('board'):
            br = platform_conf.regions.get('board')
            baseline_board_region = {
                'left': int(br['left']),
                'top': int(br['top']),
                'width': int(br['width']),
                'height': int(br['height'])
            }

        # 阈值与去抖动设置
        move_threshold = 2   # 像素阈值：位移
        size_threshold = 3   # 像素阈值：尺寸
        check_interval = 1   # 检查间隔（秒）
        stable_wait    = 1.0 # 稳定时间（秒）
        
        next_check_time = time.monotonic() 
        last_change_time = None
        pending_move = False
        pending_resize = False
        
        while not stop_event.is_set():
            now = time.monotonic()
            if now >= next_check_time:
                next_check_time = now + check_interval
                win_info = self.find_game_window(self.context.platform)
                if win_info and 'region' in win_info:
                    current_bounds = win_info['region']
                    if last_seen_bounds is None:
                        last_seen_bounds = current_bounds
                    # 与最近一次看到的边界比较，更新"是否变化"和最近变化时间
                    dx_seen = int(current_bounds['left']) - int(last_seen_bounds['left'])
                    dy_seen = int(current_bounds['top']) - int(last_seen_bounds['top'])
                    dw_seen = int(current_bounds['width']) - int(last_seen_bounds['width'])
                    dh_seen = int(current_bounds['height']) - int(last_seen_bounds['height'])
                    win_moved = abs(dx_seen) >= move_threshold or abs(dy_seen) >= move_threshold
                    size_changed = abs(dw_seen) >= size_threshold or abs(dh_seen) >= size_threshold

                    if win_moved or size_changed:
                        pending_move = pending_move or win_moved
                        pending_resize = pending_resize or size_changed
                        last_change_time = now
                        last_seen_bounds = current_bounds
                        
                    else:
                        # 没有新变化，检查是否已稳定超过阈值，若是则执行重定位
                        if last_change_time is not None and (now - last_change_time) >= stable_wait and (pending_move or pending_resize):
                            # 以基准边界为参考计算总位移
                            dx_total = int(last_seen_bounds['left']) - int(baseline_bounds['left']) if baseline_bounds else 0
                            dy_total = int(last_seen_bounds['top']) - int(baseline_bounds['top']) if baseline_bounds else 0
                            
                            # 获取最新基准区域（可能会在手动定位后变化）
                            curr_platform = self.context.get_platform(self.context.platform)
                            curr_board = curr_platform.regions.get('board') if curr_platform else None
                            ref_board_region = baseline_board_region or curr_board

                            try:
                                if pending_resize:
                                    # 尺寸变化：执行完整自动定位
                                    # 计算预测Fallback坐标：基于窗口缩放比例
                                    fallback = None
                                    if baseline_bounds and ref_board_region and int(baseline_bounds['width']) > 0 and int(baseline_bounds['height']) > 0:
                                        scale_w = int(last_seen_bounds['width']) / int(baseline_bounds['width'])
                                        scale_h = int(last_seen_bounds['height']) / int(baseline_bounds['height'])
                                        
                                        # 计算相对于旧窗口左上角的偏移
                                        rel_x = (int(ref_board_region['left']) - int(baseline_bounds['left'])) * scale_w
                                        rel_y = (int(ref_board_region['top']) - int(baseline_bounds['top'])) * scale_h
                                        
                                        new_w = int(ref_board_region['width']) * scale_w
                                        new_h = int(ref_board_region['height']) * scale_h
                                        
                                        new_l = int(last_seen_bounds['left']) + rel_x
                                        new_t = int(last_seen_bounds['top']) + rel_y
                                        
                                        fallback = (int(new_l), int(new_t), int(new_w), int(new_h))
                                        print(f"窗口缩放，计算Fallback坐标: {fallback}")
                                    
                                    self.handle_locating_board_tasks(fallback_coords=fallback)
                                else:
                                    # 仅移动：根据总位移平移棋盘左上角，复用原宽高，传入4元组
                                    if ref_board_region is not None:
                                        new_left = int(ref_board_region['left']) + dx_total
                                        new_top = int(ref_board_region['top']) + dy_total
                                        new_width = int(ref_board_region['width'])
                                        new_height = int(ref_board_region['height'])
                                        move_region = (new_left, new_top, new_width, new_height)
                                        self.handle_locating_board_tasks(moved_coords=move_region)

                                reset_border_cache(self.context.platform)
                                # 重置检查器状态，确保重新定位后能正常分析新局面
                                self.context.reset_checker()
                                # 成功后更新基准为当前稳定的窗口边界，并清空待处理标志
                                baseline_bounds = last_seen_bounds
                                # 成功后刷新基准棋盘区域
                                platform_conf2 = self.context.get_platform(self.context.platform)
                                if platform_conf2 and platform_conf2.regions.get('board'):
                                    br2 = platform_conf2.regions.get('board')
                                    baseline_board_region = {
                                        'left': int(br2['left']),
                                        'top': int(br2['top']),
                                        'width': int(br2['width']),
                                        'height': int(br2['height'])
                                    }
                                    
                                pending_move = False
                                pending_resize = False
                                last_change_time = None
                            except (WindowError, PieceError, CombsError, LocationError) as e:
                                print(f"窗口移动后重新定位失败: {e}")
                                # 立即设置停止事件，避免时间差问题
                                stop_event.set()
                                # 重新抛出异常，让截图模块处理
                                raise
                            except Exception as e:
                                print(f"窗口移动监控异常: {e}")
                                # 其他异常继续监控，不中断循环
                # 若未找到窗口，跳过
            time.sleep(0.1)

    def _draw_grid_on_board_image(self, board_img):
        """
        在棋盘图片上绘制网格线（包含两种y坐标计算方法对比）
        
        Args:
            board_img: 棋盘图片的OpenCV图像（已缩放为800宽度）
        """
        try:
            # 检查context中是否有board_coords
            if not hasattr(self.context, 'board_coords') or not self.context.board_coords:
                print("警告：context中没有board_coords，无法绘制网格线")
                return
            
            board_coords = self.context.board_coords
            # my_x_coords = [45, 134, 223, 311, 400, 489, 578, 667, 756]
            # my_y_coords = [44, 130, 216, 302, 388, 474, 560, 646, 732, 818]
            # x_coords = my_x_coords
            # y_coords_original = my_y_coords

            x_coords = board_coords['x']
            y_coords_original = board_coords['y']
            y_coords_equal = board_coords.get('y_equal', [])
            
            # 保存的坐标已经是标准化为800宽度的，可以直接使用
            # 绘制垂直线（9列）- 绿色
            for i, x in enumerate(x_coords):
                pixel_x = int(x)
                start_y = 0
                end_y = board_img.shape[0] - 1
                
                # 确保x坐标在图片范围内
                if 0 <= pixel_x < board_img.shape[1]:
                    cv2.line(board_img, (pixel_x, start_y), (pixel_x, end_y), (0, 255, 0), 1)  # 绿色线
            
            # 绘制原始方法的水平线（10行）- 绿色
            for i, y in enumerate(y_coords_original):
                pixel_y = int(y)
                start_x = 0
                end_x = board_img.shape[1] - 1
                
                # 确保y坐标在图片范围内
                if 0 <= pixel_y < board_img.shape[0]:
                    cv2.line(board_img, (start_x, pixel_y), (end_x, pixel_y), (0, 255, 0), 1)  # 绿色线
            
            # 绘制等分方法的水平线（10行）- 蓝色
            if y_coords_equal:
                for i, y in enumerate(y_coords_equal):
                    pixel_y = int(y)
                    start_x = 0
                    end_x = board_img.shape[1] - 1
                    
                    # 确保y坐标在图片范围内
                    if 0 <= pixel_y < board_img.shape[0]:
                        cv2.line(board_img, (start_x, pixel_y), (end_x, pixel_y), (255, 0, 0), 1)  # 蓝色线
            
            # 在原始方法交叉点绘制小圆点 - 红色
            for x in x_coords:
                for y in y_coords_original:
                    pixel_x = int(x)
                    pixel_y = int(y)
                    
                    # 确保坐标在图片范围内
                    if (0 <= pixel_x < board_img.shape[1] and 
                        0 <= pixel_y < board_img.shape[0]):
                        cv2.circle(board_img, (pixel_x, pixel_y), 3, (0, 0, 255), -1)  # 红色圆点
            
            # 在等分方法交叉点绘制小圆点 - 黄色
            if y_coords_equal:
                for x in x_coords:
                    for y in y_coords_equal:
                        pixel_x = int(x)
                        pixel_y = int(y)
                        
                        # 确保坐标在图片范围内
                        if (0 <= pixel_x < board_img.shape[1] and 
                            0 <= pixel_y < board_img.shape[0]):
                            cv2.circle(board_img, (pixel_x, pixel_y), 2, (0, 255, 255), -1)  # 黄色圆点
            
            print(f"已在缩放后的棋盘图片上绘制网格线，保存为 board_with_grid.png")
            print(f"  缩放后图片尺寸: {board_img.shape[1]} x {board_img.shape[0]}")
            print(f"  绿色线/红点: 原始方法（基于棋子位置）")
            print(f"  蓝色线/黄点: 等分方法（black_y_avg到red_y_avg等分）")
            
        except Exception as e:
            print(f"在棋盘图片上绘制网格线时出错: {e}")

if __name__ == "__main__":
    # 测试代码
    print("开始检测棋盘位置...")
    start_time = time.time()
    locator = BoardLocator()
    try:
        board_pos = locator._locate_board_from_combs()
    finally:
        locator.stop()
    end_time = time.time()
    print(f"检测完成，耗时: {end_time - start_time:.2f}秒")
    print("棋盘坐标：", board_pos)


