import cv2
import numpy as np
import os
from app.tools.utils import app_cache_path
from app.chess.context import context as global_context
from app.chess.marker_detector import MarkerDetector

class ChessRecognizer:
    class RecognitionError(Exception):
        pass

    def __init__(self, context=None):
        # 支持依赖注入，默认使用全局context
        self.context = context or global_context
        self.marker_detector = MarkerDetector()

    def preprocess_image(self, img_origin):
        # img = cv2.imread(img_path)  
        img_np = np.frombuffer(img_origin.bgra, np.uint8).reshape(img_origin.height, img_origin.width, 4)
        img_np = img_np[:, :, :3]  # 去掉 alpha 通道
        if img_np is None:  
            print("Error: npImage is None.")  
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
            print(f"\n当前方为{'红方' if is_red else '黑方'}")
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
            (pieceArray, marker_coords): 
                pieceArray: 9x10的二维数组，表示棋盘状态
                marker_coords: 检测到的标记坐标列表
        """
        # 预处理
        resized_img, gray = self.preprocess_image(img)
        
        # 顺便检测走棋标记 (复用预处理后的灰度图)
        marker_coords = self.marker_detector.detect_markers(gray, x_array, y_array)
        
        pieceArray = [["-"] * len(x_array) for _ in range(len(y_array))]
        
        # 创建保存目录
        save_dir = app_cache_path("pieces")
        try:
            os.makedirs(save_dir, exist_ok=True)
        except OSError:
            # 如果无法创建目录，跳过保存调试图片
            save_dir = None
        
        # 批量收集所有待识别格子的裁剪图片
        crops = []
        positions = []  # 与 crops 对应，存 (i, j)
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
                cut_radius = int((x_radius + y_radius) // 2 * 0.95)
                adjusted_center_x = max(cut_radius, min(resized_img.shape[1] - 1 - cut_radius, center_x))
                adjusted_center_y = max(cut_radius, min(resized_img.shape[0] - 1 - cut_radius, center_y))
                x1 = adjusted_center_x - cut_radius
                y1 = adjusted_center_y - cut_radius
                x2 = adjusted_center_x + cut_radius
                y2 = adjusted_center_y + cut_radius
                piece_img = resized_img[y1:y2, x1:x2]
                crops.append(piece_img)
                positions.append((i, j))

        # 一次批量推理
        batch_results = self.context.piece_recognizer.recognize_batch(crops)
        for idx, res in enumerate(batch_results):
            i, j = positions[idx]
            if res is None:
                raise self.RecognitionError("批量识别失败: 结果为None")
            piece_type = res['class_name']
            confidence = res['confidence']
            if piece_type and confidence > 0.6:
                if piece_type == 'covered':
                    raise self.RecognitionError(f"动画遮挡: {piece_type} - {confidence:.2f}")
                pieceArray[i][j] = piece_type
            else:
                raise self.RecognitionError(f"无法识别或置信度低: {piece_type} - {confidence:.2f}")
        return pieceArray, marker_coords

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
                    print(f"无法识别棋子: {piece_img}")
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
                    print(f"无法识别棋子: {piece_img}")
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
            print(f"棋子识别过程中出错: {e}")
            return None

