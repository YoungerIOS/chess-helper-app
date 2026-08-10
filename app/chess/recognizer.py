import cv2
import numpy as np
import os
from app.tools.utils import app_cache_path, resource_path
from app.tools.log_config import get_logger
from app.chess.context import context as global_context
from app.chess.marker_detector import MarkerDetector
from dataclasses import dataclass
from enum import Enum, auto

logger = get_logger(__name__)

class RecognitionErrorType(Enum):
    COVERED = auto()          # 动画遮挡
    LOW_CONFIDENCE = auto()   # 置信度低
    MARKER_MISSING = auto()   # 未检测到标记
    MASSIVE_CHANGE = auto()   # 巨大变化(可能是结算画面)
    UNKNOWN = auto()          # 未知错误

@dataclass
class RecognitionDetail:
    type: RecognitionErrorType
    position: tuple  # (row, col)
    message: str
    confidence: float = 0.0
    piece_type: str = None

class ChessRecognizer:
    def __init__(self, context=None):
        # 支持依赖注入，默认使用全局context
        self.context = context or global_context
        self.marker_detector = MarkerDetector()
        # 缓存上一帧的哈希和棋盘状态，用于增量识别
        self.last_grid_hashes = None
        self.last_board_array = None
        self.last_marker_coords = []  # 缓存标记位置
        self._jj_black_piece_templates = None

    def _load_jj_black_piece_templates(self):
        """加载界面自带的黑方棋子图，供JJ模型漏检时进行轻量模板复核。"""
        if self._jj_black_piece_templates is not None:
            return self._jj_black_piece_templates

        templates = {}
        for piece in ("r", "n", "b", "a", "k", "c", "p"):
            path = resource_path("images", "media", f"black_{piece}.png")
            image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if image is None or image.ndim != 3 or image.shape[2] < 4:
                continue
            bgr = cv2.resize(image[:, :, :3], (80, 80))
            alpha = cv2.resize(image[:, :, 3], (80, 80)) > 128
            templates[piece] = (cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), alpha)
        self._jj_black_piece_templates = templates
        return templates

    @staticmethod
    def _contains_centered_piece_circle(piece_img):
        if piece_img is None or min(piece_img.shape[:2]) < 40:
            return False
        gray = cv2.cvtColor(piece_img[:, :, :3], cv2.COLOR_BGR2GRAY)
        height, width = gray.shape
        circles = cv2.HoughCircles(
            gray,
            cv2.HOUGH_GRADIENT,
            dp=1,
            minDist=max(10, min(width, height) // 3),
            param1=80,
            param2=18,
            minRadius=max(10, int(min(width, height) * 0.34)),
            maxRadius=max(12, int(min(width, height) * 0.51)),
        )
        if circles is None:
            return False
        center_x, center_y = width / 2, height / 2
        tolerance = min(width, height) * 0.18
        return any(
            abs(float(x) - center_x) <= tolerance
            and abs(float(y) - center_y) <= tolerance
            for x, y, _ in circles[0]
        )

    @staticmethod
    def _has_black_ink(piece_img):
        """区分黑色字形与红色字形，避免把红炮补成黑炮。"""
        height, width = piece_img.shape[:2]
        y_margin = max(1, int(height * 0.18))
        x_margin = max(1, int(width * 0.18))
        center = piece_img[y_margin:height-y_margin, x_margin:width-x_margin, :3]
        hsv = cv2.cvtColor(center, cv2.COLOR_BGR2HSV)
        hue, saturation, value = cv2.split(hsv)
        dark_neutral = ((value < 110) & (saturation < 130)).mean()
        red_ink = (
            ((hue < 12) | (hue > 170))
            & (saturation > 100)
            & (value > 80)
        ).mean()
        return dark_neutral >= 0.08 and dark_neutral > red_ink * 1.5

    def _recover_jj_black_cannon(self, piece_img, previous_piece="-"):
        """模型误报空格时，以圆形、字色和模板三重证据恢复黑炮。"""
        if self.context.platform != "JJ":
            return False
        if not self._contains_centered_piece_circle(piece_img):
            return False
        if not self._has_black_ink(piece_img):
            return False
        if previous_piece == "c":
            return True

        templates = self._load_jj_black_piece_templates()
        if "c" not in templates:
            return False
        actual = cv2.cvtColor(
            cv2.resize(piece_img[:, :, :3], (80, 80)),
            cv2.COLOR_BGR2GRAY,
        )
        scores = {}
        for piece, (template, mask) in templates.items():
            actual_values = actual[mask].astype(np.float32)
            template_values = template[mask].astype(np.float32)
            if actual_values.std() < 1e-6 or template_values.std() < 1e-6:
                continue
            scores[piece] = float(np.corrcoef(actual_values, template_values)[0, 1])
        cannon_score = scores.get("c", -1.0)
        other_best = max((v for k, v in scores.items() if k != "c"), default=-1.0)
        return cannon_score >= 0.20 and cannon_score - other_best >= 0.05

    def preprocess_image(self, img_origin):
        # img = cv2.imread(img_path)  
        img_np = np.frombuffer(img_origin.bgra, np.uint8).reshape(img_origin.height, img_origin.width, 4)
        img_np = img_np[:, :, :3]  # 去掉 alpha 通道
        if img_np is None:  
            logger.error("npImage is None.")
            return  None, None 
        new_width = 800  
        scale_factor = new_width / img_np.shape[1]  # 注意使用宽度来计算缩放因子  
        new_height = int(img_np.shape[0] * scale_factor)  
        resized_img = cv2.resize(img_np, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)
        # cv2.imwrite('./chess_assistant/app/uploads/图像.png', resized_img)
        # print(f"图片宽高是:{img.shape[1]} x {img.shape[0]}")
        # 灰度化  
        gray = cv2.cvtColor(resized_img, cv2.COLOR_BGR2GRAY) 
        return resized_img, gray


    # 识别棋子
    def recognize_piece_from_circle(self, img, x_array, y_array):
        """
        识别棋子并确定其位置和类型
        Args:
            img: 原始图像
            x_array: 棋盘横线坐标数组
            y_array: 棋盘纵线坐标数组
        Returns:
            pieceArray: 9x10的二维数组，表示棋盘状态，每个位置存储棋子类型代号或"-"
            is_red: 是否为红方
        """
        # 预处理
        resized_img, gray = self.preprocess_image(img)
        width = resized_img.shape[1]
        maxRadius = int(width/9/2)  # 棋盘宽度除以9（横向最多9个棋子，再除2就是半径）
        minRadius = int(0.8 * width/9/2)
        minDist = int(0.8 * width/9)  # 棋子与棋子间距，最小就是2个半径
        # 检测圆形
        circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1, minDist, 
                                  param1=50, param2=30, 
                                  minRadius=minRadius, maxRadius=maxRadius)
        if circles is not None:
            circles = np.round(circles[0, :]).astype("int")
            # 识别黑将并获取计算好坐标的棋盘数组
            pieceArray, is_red = self.recognize_black_king(circles, resized_img, x_array, y_array)
            logger.info(f"当前方为{'红方' if is_red else '黑方'}")
            # 识别所有棋子
            for i in range(len(pieceArray)):
                for j in range(len(pieceArray[0])):
                    if pieceArray[i][j] == '-':
                        continue
                    x, y, r = pieceArray[i][j]
                    piece_img = self.get_piece_image(resized_img, x, y, r)
                    piece_type, confidence = self.recognize_piece_type(piece_img)
                    # print(f"位置({j}, {i}) 识别为 {piece_type}")
                    if piece_type:
                        pieceArray[i][j] = piece_type
                    else:
                        pieceArray[i][j] = '-'
        else:
            pieceArray = [["-"] * len(x_array) for _ in range(len(y_array))]
        return pieceArray

    def recognize_piece_from_grid(self, img, x_array, y_array):
        """
        切割棋盘格点识别棋子，返回9x10棋盘数组和红黑方
        Args:
            img: 原始图像
            x_array: 棋盘横线坐标数组
            y_array: 棋盘纵线坐标数组
        Returns:
            (pieceArray, marker_coords, current_grid_hashes): 
                pieceArray: 9x10的二维数组
                marker_coords: 标记坐标 (由CNN识别的 '.' 类型)
                current_grid_hashes: 哈希
        """
        from app.tools.utils import compute_image_hash

        # 使用内部缓存
        last_grid_hashes = self.last_grid_hashes
        last_board_array = self.last_board_array
        last_marker_coords = self.last_marker_coords or []

        # 预处理
        resized_img, gray = self.preprocess_image(img)
        
        # 初始化结果数组
        pieceArray = [["-"] * len(x_array) for _ in range(len(y_array))]
        current_grid_hashes = [([None] * len(x_array)) for _ in range(len(y_array))]
        
        # CNN检测到的标记位置 (替代 marker_detector)
        marker_coords = []
        
        # 收集识别过程中的错误/警告
        details = []
        
        # 创建保存目录
        save_dir = app_cache_path("pieces")
        try:
            os.makedirs(save_dir, exist_ok=True)
        except OSError:
            # 如果无法创建目录，跳过保存调试图片
            save_dir = None
        
        # 准备批量识别
        crops = []
        positions = []  # 与 crops 对应，存 (i, j)
        
        # 统计增量识别效果
        cached_count = 0
        predicted_count = 0
        
        for i in range(len(y_array)):
            for j in range(len(x_array)):
                center_x = x_array[j]
                center_y = y_array[i]
                # 计算当前位置的切割半径
                if j == 0:
                    x_radius = (x_array[j+1] - x_array[j]) // 2
                elif j == len(x_array)-1:
                    x_radius = (x_array[j] - x_array[j-1]) // 2
                else:
                    x_radius = min((x_array[j] - x_array[j-1]) // 2, (x_array[j+1] - x_array[j]) // 2)
                if i == 0:
                    y_radius = (y_array[i+1] - y_array[i]) // 2
                elif i == len(y_array)-1:
                    y_radius = (y_array[i] - y_array[i-1]) // 2
                else:
                    y_radius = min((y_array[i] - y_array[i-1]) // 2, (y_array[i+1] - y_array[i]) // 2)
                # JJ 新版棋子外圈和阴影更宽。沿用 0.95 会把过多背景缩进
                # 80x80 模型输入，黑炮等字形会被误判；稍微收紧后模型能
                # 聚焦棋子文字。TT 保持原比例，避免改变已有识别效果。
                crop_scale = 0.85 if self.context.platform == "JJ" else 0.95
                cut_radius = int((x_radius + y_radius) // 2 * crop_scale)
                adjusted_center_x = max(cut_radius, min(resized_img.shape[1] - 1 - cut_radius, center_x))
                adjusted_center_y = max(cut_radius, min(resized_img.shape[0] - 1 - cut_radius, center_y))
                x1 = adjusted_center_x - cut_radius
                y1 = adjusted_center_y - cut_radius
                x2 = adjusted_center_x + cut_radius
                y2 = adjusted_center_y + cut_radius
                piece_img = resized_img[y1:y2, x1:x2]
                
                # 计算当前格子的哈希
                curr_hash = compute_image_hash(piece_img)
                current_grid_hashes[i][j] = curr_hash
                
                # 检查缓存命中
                is_hit = False
                if last_grid_hashes and last_board_array and curr_hash:
                    last_h = last_grid_hashes[i][j]
                    if last_h == curr_hash:
                        pieceArray[i][j] = last_board_array[i][j]
                        # 如果上一帧该位置是标记，继续保留标记状态
                        if (i, j) in last_marker_coords:
                            marker_coords.append((i, j))
                        is_hit = True
                        cached_count += 1
                
                # 未命中缓存，加入待识别队列
                if not is_hit:
                    crops.append(piece_img)
                    positions.append((i, j))
                    predicted_count += 1
        
        if crops:
            logger.debug(f"增量识别: 缓存命中 {cached_count} 格, 哈希变动(重算) {predicted_count} 格")
            batch_results = self.context.piece_recognizer.recognize_batch(crops)
            for idx, res in enumerate(batch_results):
                i, j = positions[idx]
                piece_img = crops[idx]
                if res is None:
                    details.append(RecognitionDetail(
                        type=RecognitionErrorType.UNKNOWN,
                        position=(i, j),
                        message=f"批量识别失败: 结果为None at ({i},{j})",
                        confidence=0.0
                    ))
                    continue
                    
                piece_type = res['class_name']
                confidence = res['confidence']
                previous_piece = (
                    last_board_array[i][j]
                    if last_board_array is not None
                    else '-'
                )
                # JJ 新棋盘上的黑炮有两种常见漏检：一枚会被模型判成
                # 空格/其他棋子，另一枚虽然判为 c，但置信度会略低于
                # 通用的 0.60 写入门槛。两种情况都用同一组视觉证据复核。
                if (
                    (
                        previous_piece == 'c'
                        or piece_type == '-'
                        or confidence <= 0.6
                    )
                    and self._recover_jj_black_cannon(piece_img, previous_piece)
                ):
                    piece_type = 'c'
                    confidence = max(float(confidence), 0.75)
                    logger.warning(
                        f"JJ黑炮视觉兜底: position=({i}, {j}), "
                        f"model_class={res['class_name']!r}, previous={previous_piece!r}"
                    )
                
                if piece_type and confidence > 0.6:
                    if piece_type == 'covered':
                        details.append(RecognitionDetail(
                            type=RecognitionErrorType.COVERED,
                            position=(i, j),
                            message=f"动画遮挡 at ({i},{j})",
                            confidence=confidence,
                            piece_type=piece_type
                        ))
                        # 动画遮挡时不更新棋盘状态,保留'-'
                        continue
                    
                    # 检测标记：模型识别为 '.' 的位置
                    if piece_type == '.':
                        marker_coords.append((i, j))
                        logger.debug(f"CNN检测到标记 at ({i+1}, {j+1}) conf={confidence:.2f}")  # 1-indexed for readability
                        pieceArray[i][j] = '-'  # 标记位置的棋子标记为空
                    else:
                        pieceArray[i][j] = piece_type
                        # 调试：显示非标记的识别结果，帮助排查漏检
                        # print(f"Debug - CNN识别 ({i+1}, {j+1}): {piece_type} conf={confidence:.2f}")
                else:
                    # 低置信度：记录错误，但不要把不可靠的猜测写入棋盘。
                    # 有上一帧时保留该格状态；首次识别则维持为空，等待后续
                    # 稳定帧重新识别。这样可避免一个误判造成非法棋子数量。
                    details.append(RecognitionDetail(
                        type=RecognitionErrorType.LOW_CONFIDENCE,
                        position=(i, j),
                        message=f"低置信度 at ({i},{j}): {piece_type} - {confidence:.2f}",
                        confidence=confidence,
                        piece_type=piece_type
                    ))
                    if last_board_array:
                        pieceArray[i][j] = last_board_array[i][j]
                    # 不缓存本次不可靠结果，确保下一稳定帧会重新推理该格。
                    current_grid_hashes[i][j] = None
        else:
            # 全部命中缓存
            # print("Debug - 全局缓存命中，跳过CNN识别")
            pass

        # 检查是否无标记 (新增 MARKER_MISSING 检测)
        if not marker_coords:
            details.append(RecognitionDetail(
                type=RecognitionErrorType.MARKER_MISSING,
                position=(-1, -1),
                message=f"未检测到标记 (Hash变动: {predicted_count}格)",
                confidence=1.0
            ))
        
        # 检查是否巨大变化 (可能是结算画面)
        if predicted_count > 45:
            details.append(RecognitionDetail(
                type=RecognitionErrorType.MASSIVE_CHANGE,
                position=(-1, -1),
                message=f"巨大变化 ({predicted_count}格)",
                confidence=1.0
            ))

        # 打印时转换为 1-indexed 方便阅读
        display_coords = [(r+1, c+1) for r, c in marker_coords]
        logger.info(f"检测到 {len(marker_coords)} 个标记--------------------------------------{display_coords}")
        
        # 更新内部缓存
        self.last_grid_hashes = current_grid_hashes
        self.last_board_array = pieceArray
        self.last_marker_coords = marker_coords  # 缓存标记位置
        
        return pieceArray, marker_coords, current_grid_hashes, details

    # 计算棋子坐标
    def get_piece_position(self, point, x_array, y_array):
        """
        根据像素坐标计算棋盘格点坐标
        Args:
            point: 棋子中心坐标
            x_array: 棋盘横线坐标数组
            y_array: 棋盘纵线坐标数组
        Returns:
            (board_x, board_y): 棋盘格点坐标
        """
        distances = [abs(point[0] - x) for x in x_array]
        board_x = distances.index(min(distances))
        distances = [abs(point[1] - y) for y in y_array]
        board_y = distances.index(min(distances))
        return board_x, board_y

    # 圆形轮廓转棋子图片
    def get_piece_image(self, img, x, y, r):
        """
        根据圆心和半径获取棋子图像
        Args:
            img: 原始图像
            x: 圆心x坐标
            y: 圆心y坐标
            r: 半径
        Returns:
            piece_img: 棋子图像
        """
        x1, y1, x2, y2 = x - r, y - r, x + r, y + r
        if x1 < 0: x1 = 0
        if y1 < 0: y1 = 0
        if x2 >= img.shape[1]: x2 = img.shape[1] - 1
        if y2 >= img.shape[0]: y2 = img.shape[0] - 1
        return img[y1:y2+1, x1:x2+1]

    # 计算棋子9x10坐标,单独识别将
    def recognize_black_king(self, circles, img, x_array, y_array):
        # 初始化棋盘数组和is_red
        pieceArray = [["-"] * len(x_array) for _ in range(len(y_array))]
        is_red = False  # 默认值设为False
        # 计算所有棋子的棋盘坐标
        for x, y, r in circles:
            board_x, board_y = self.get_piece_position((x, y), x_array, y_array)
            # 存储棋子的原始信息到对应位置
            pieceArray[board_y][board_x] = (x, y, r)
        # 在上下两个九宫格内寻找黑将
        upper_palace_king = None  # 上方九宫格黑将位置
        lower_palace_king = None  # 下方九宫格黑将位置
        # 检查上方九宫格
        for i in range(3):  # 上方九宫格是前3行
            for j in range(3, 6):  # 上方九宫格是中间3列
                if pieceArray[i][j] == '-':
                    continue
                x, y, r = pieceArray[i][j]
                piece_img = self.get_piece_image(img, x, y, r)
                # 使用recognize_piece_type识别棋子类型
                piece_type = self.recognize_piece_type(piece_img)
                if piece_type is None:
                    logger.warning(f"无法识别棋子: {piece_img}")
                    continue
                if piece_type == 'k':  # 如果是黑将
                    upper_palace_king = (j, i)
                    break
            if upper_palace_king:
                break
        # 检查下方九宫格
        for i in range(7, 10):  # 下方九宫格是后3行
            for j in range(3, 6):  # 下方九宫格是中间3列
                if pieceArray[i][j] == '-':
                    continue
                x, y, r = pieceArray[i][j]
                piece_img = self.get_piece_image(img, x, y, r)
                # 使用recognize_piece_type识别棋子类型
                piece_type = self.recognize_piece_type(piece_img)
                if piece_type is None:
                    logger.warning(f"无法识别棋子: {piece_img}")
                    continue
                if piece_type == 'k':  # 如果是黑将
                    lower_palace_king = (j, i)
                    break
            if lower_palace_king:
                break
        # 根据黑将位置判断红黑方
        # 如果上方九宫格有黑将，说明红方在下方
        # 如果下方九宫格有黑将，说明红方在上方
        if upper_palace_king:
            is_red = True  # 红方在下方
            # print(f"检测到黑将在上方九宫格，位置: {upper_palace_king}")
        elif lower_palace_king:
            is_red = False  # 红方在上方
            # print(f"检测到黑将在下方九宫格，位置: {lower_palace_king}")
        else:
            is_red = False  # 设置默认值
        return pieceArray, is_red

    def recognize_piece_type(self, piece_img):
        """
        识别棋子类型
        :param piece_img: 棋子图片
        :return: 棋子类型, 置信度或None
        """
        try:
            result = self.context.piece_recognizer.recognize_from_array(piece_img)
            if result is None:
                return None
            return result['class_name'], result['confidence']
        except Exception as e:
            logger.error(f"棋子识别过程中出错: {e}")
            return None
