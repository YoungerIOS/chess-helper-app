import cv2
import numpy as np
import os
from tools import utils
from chess.context import context
from .piece_recognizer import ChessPieceRecognizer

def show_image(name, image):
    # 显示结果  
    cv2.imshow(name, image)  
    cv2.waitKey(0)  
    cv2.destroyAllWindows()

def preprocess_image(img_origin):
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

# 获取本地棋盘数据
def get_board_data():
    """从上下文获取当前平台的棋盘坐标"""
    # 获取当前平台的坐标
    platform = context.get_platform(context.platform)
    x_array = platform.board_coords["x"]
    y_array = platform.board_coords["y"]
    error = ""
    
    # 检查坐标数组是否为空
    if not x_array or not y_array:
        error = "No board coordinates found"
    
    return x_array, y_array, error

# 识别棋盘
def recognize_board(img):
    """识别棋盘并保存坐标到上下文"""
    x_arr, y_arr, error = get_board_data()
    if not error: 
        return x_arr, y_arr
    
    # 预处理
    resized_img, gray = preprocess_image(img)
    
    # 高斯模糊  
    gaus = cv2.GaussianBlur(gray, (5, 5), 0)  
    # 边缘检测  
    edges = cv2.Canny(gaus, 20, 120, apertureSize=3)  
    
    # 霍夫线变换  
    lines = cv2.HoughLinesP(edges, 0.5, np.pi/180, threshold=80, minLineLength=100, maxLineGap=5)  
    
    # 创建一张新图用于绘制检测到的线条
    board_vis = resized_img.copy()
    
    # 过滤线段并在新图上绘制
    # 竖线 (x1 == x2)
    x_array = []
    vlines, yMin, yMax = utils.filter_vertical_lines(lines, resized_img.shape[1])
    for line in vlines:  
        for x1, y1, x2, y2 in line:
            cv2.line(board_vis, (x1, yMin), (x2, yMax), (0, 255, 0), 2)  # 绿色，加粗线条
            x_array.append(int(x1))

    # 横线 (y1 == y2)
    y_array = []
    hlines, xMin, xMax = utils.filter_horizontal_lines(lines, resized_img.shape[1])
    for line in hlines:  
        for x1, y1, x2, y2 in line:  
            cv2.line(board_vis, (xMin, y1), (xMax, y2), (0, 0, 255), 2)  # 红色，加粗线条
            y_array.append(int(y1))
    
    # 对坐标进行排序
    x_array.sort()
    y_array.sort()
    
    # 使用IQR方法修复缺失的线条
    def fix_missing_lines(coords, expected_count):
        if len(coords) >= expected_count:
            return coords
            
        # 计算相邻坐标的间距
        spacings = [coords[i+1] - coords[i] for i in range(len(coords)-1)]
        
        # 计算四分位数
        Q1 = np.percentile(spacings, 25)
        Q3 = np.percentile(spacings, 75)
        IQR = Q3 - Q1
        
        # 计算上界
        upper_bound = Q3 + 1.5 * IQR
        
        # 找出异常大的间距
        missing_positions = []
        for i, spacing in enumerate(spacings):
            if spacing > upper_bound:
                missing_positions.append(i)
        
        # 在缺失位置插入新的坐标
        new_coords = coords.copy()
        for pos in sorted(missing_positions, reverse=True):
            # 计算缺失坐标的值（使用相邻坐标的平均值）
            missing_value = int((new_coords[pos] + new_coords[pos+1]) / 2)
            new_coords.insert(pos+1, missing_value)
            
        return new_coords
    
    # 修复竖线（应该有9条）
    x_array = fix_missing_lines(x_array, 9)
    
    # 修复横线（应该有10条）
    y_array = fix_missing_lines(y_array, 10)
    
    # 在可视化图像上绘制修复后的线条
    # 绘制修复后的竖线（使用蓝色）
    for x in x_array:
        if x not in [int(line[0][0]) for line in vlines]:  # 只绘制新修复的线条
            cv2.line(board_vis, (x, yMin), (x, yMax), (255, 0, 0), 2)  # 蓝色，加粗线条
    
    # 绘制修复后的横线（使用黄色）
    for y in y_array:
        if y not in [int(line[0][1]) for line in hlines]:  # 只绘制新修复的线条
            cv2.line(board_vis, (xMin, y), (xMax, y), (0, 255, 255), 2)  # 黄色，加粗线条
    
    # 保存可视化结果
    output_dir = os.path.dirname(utils.resource_path("images/board/board_visual.jpg"))
    os.makedirs(output_dir, exist_ok=True)
    cv2.imwrite(utils.resource_path("images/board/board_visual.jpg"), board_vis)

    # 更新当前平台的棋盘坐标
    platform = context.get_platform(context.platform)
    platform.board_coords = {
        "x": x_array,
        "y": y_array
    }
    
    # 保存到文件
    context.save_board_coords()
    
    return x_array, y_array

# 识别棋子
def recognize_pieces(img, param, x_array, y_array):
    """
    识别棋子并确定其位置和类型
    Args:
        img: 原始图像
        param: 引擎参数配置
        x_array: 棋盘横线坐标数组
        y_array: 棋盘纵线坐标数组
    Returns:
        pieceArray: 9x10的二维数组，表示棋盘状态，每个位置存储棋子类型代号或"-"
        is_red: 是否为红方
    """
    # 预处理
    resized_img, gray = preprocess_image(img)
    
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
        pieceArray, is_red = recognize_black_king(circles, resized_img, x_array, y_array)
        print(f"\n当前方为{'红方' if is_red else '黑方'}")
        
        # 识别所有棋子
        for i in range(len(pieceArray)):
            for j in range(len(pieceArray[0])):
                if pieceArray[i][j] == '-':
                    continue
                x, y, r = pieceArray[i][j]
                piece_img = get_piece_image(resized_img, x, y, r)

                piece_type = recognize_piece_type(piece_img)
                print(f"位置({j}, {i}) 识别为 {piece_type}")
                if piece_type:
                    pieceArray[i][j] = piece_type
                else:
                    pieceArray[i][j] = '-'

    else:
        pieceArray = [["-"] * len(x_array) for _ in range(len(y_array))]
        is_red = False
    return pieceArray, is_red

# 计算棋子坐标
def get_piece_position(point, x_array, y_array):
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
def get_piece_image(img, x, y, r):
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
def recognize_black_king(circles, img, x_array, y_array):
    """
    识别九宫格内的黑将'k',并计算所有棋子的9x10棋盘坐标
    Returns:
        pieceArray: 9x10的二维数组,表示棋盘状态,已计算好所有棋子的坐标
        is_red: 是否红方在下方
    """
    # 初始化棋盘数组
    pieceArray = [["-"] * len(x_array) for _ in range(len(y_array))]

    # 计算所有棋子的棋盘坐标
    for x, y, r in circles:
        board_x, board_y = get_piece_position((x, y), x_array, y_array)
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
            piece_img = get_piece_image(img, x, y, r)
            
            # 保存临时图片
            temp_path = "temp_piece.jpg"
            cv2.imwrite(temp_path, piece_img)
            
            # 使用模型识别
            piece_type = context.piece_recognizer.recognize(temp_path)
            
            # 删除临时文件
            os.remove(temp_path)
            
            if piece_type == 'k':  # 如果是黑将
                print(f"位置({j}, {i}) 识别为黑将")
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
            piece_img = get_piece_image(img, x, y, r)
            
            # 保存临时图片
            temp_path = "temp_piece.jpg"
            cv2.imwrite(temp_path, piece_img)
            
            # 使用模型识别
            piece_type = context.piece_recognizer.recognize(temp_path)
            
            # 删除临时文件
            os.remove(temp_path)
            
            if piece_type == 'k':  # 如果是黑将
                print(f"位置({j}, {i}) 识别为黑将")
                lower_palace_king = (j, i)
                break
        if lower_palace_king:
            break

    # 根据黑将位置判断红黑方
    # 如果上方九宫格有黑将，说明红方在下方
    # 如果下方九宫格有黑将，说明红方在上方
    if upper_palace_king:
        is_red = True  # 红方在下方
        print(f"检测到黑将在上方九宫格，位置: {upper_palace_king}")
    elif lower_palace_king:
        is_red = False  # 红方在上方
        print(f"检测到黑将在下方九宫格，位置: {lower_palace_king}")
    else:
        # 如果两个九宫格都没有找到黑将，默认红方在下方
        is_red = True
        print("未检测到黑将位置，默认红方在下方")

    return pieceArray, is_red


def recognize_piece_type(piece_img):
    """
    识别棋子类型
    :param piece_img: 棋子图片
    :return: 棋子类型或None
    """
    # 从上下文中获取棋子识别器
    piece_recognizer = context.piece_recognizer
    if piece_recognizer is None:
        # 如果识别器不存在，初始化并保存到上下文
        piece_recognizer = ChessPieceRecognizer(
            model_path="app/models/model.pth",
            class_map_path="app/models/class_map.json"
        )
        context.piece_recognizer = piece_recognizer
    
    # 保存临时图片
    temp_path = "temp_piece.jpg"
    cv2.imwrite(temp_path, piece_img)
    
    # 使用模型识别
    piece_type = piece_recognizer.recognize(temp_path)
    
    # 删除临时文件
    os.remove(temp_path)
    
    return piece_type

def is_valid_position(piece_type, x, y, is_red):
    """
    根据中国象棋规则验证(x,y)是否为 "兵卒 象相 士仕 将帅" 的合法位置
    Args:
        piece_type: 棋子类型
        x: 棋盘横坐标
        y: 棋盘纵坐标
        is_red: 红方在棋盘下方
    Returns:
        bool: 位置是否合法
    """
    
    # 士/仕的合法位置（九宫格内的5个位置）
    if piece_type in ['a', 'A']:  # 士/仕
        if piece_type.isupper():  # 红士
            if is_red:  # 红方在下方
                return (x, y) in [(3, 7), (5, 7), (4, 8), (3, 9), (5, 9)]  # 红方在下方时，士在下方九宫格
            else:  # 红方在上方
                return (x, y) in [(3, 0), (5, 0), (4, 1), (3, 2), (5, 2)]  # 红方在上方时，士在上方九宫格
        else:  # 黑仕
            if is_red:  # 红方在下方，黑方在上方
                return (x, y) in [(3, 0), (5, 0), (4, 1), (3, 2), (5, 2)]  # 黑方在上方九宫格
            else:  # 红方在上方，黑方在下方
                return (x, y) in [(3, 7), (5, 7), (4, 8), (3, 9), (5, 9)]  # 黑方在下方九宫格
    
    # 相/象的合法位置（己方区域的7个位置）
    elif piece_type in ['b', 'B']:  # 相/象
        if piece_type.isupper():  # 红相
            if is_red:  # 红方在下方
                return (x, y) in [(2, 5), (6, 5), (0, 7), (4, 7), (8, 7), (2, 9), (6, 9)]  # 红方在下方时，相在下方区域
            else:  # 红方在上方
                return (x, y) in [(2, 0), (6, 0), (0, 2), (4, 2), (8, 2), (2, 4), (6, 4)]  # 红方在上方时，相在上方区域
        else:  # 黑象
            if is_red:  # 红方在下方，黑方在上方
                return (x, y) in [(2, 0), (6, 0), (0, 2), (4, 2), (8, 2), (2, 4), (6, 4)]  # 黑方在上方区域
            else:  # 红方在上方，黑方在下方
                return (x, y) in [(2, 5), (6, 5), (0, 7), (4, 7), (8, 7), (2, 9), (6, 9)]  # 黑方在下方区域
    
    # 将/帅的合法位置（九宫格内的9个位置）
    elif piece_type in ['k', 'K']:  # 将/帅
        if piece_type.isupper():  # 红帅
            if is_red:  # 红方在下方
                return (x, y) in [(3, 7), (4, 7), (5, 7), (3, 8), (4, 8), (5, 8), (3, 9), (4, 9), (5, 9)]  # 红方在下方时，帅在下方九宫格
            else:  # 红方在上方
                return (x, y) in [(3, 0), (4, 0), (5, 0), (3, 1), (4, 1), (5, 1), (3, 2), (4, 2), (5, 2)]  # 红方在上方时，帅在上方九宫格
        else:  # 黑将
            if is_red:  # 红方在下方，黑方在上方
                return (x, y) in [(3, 0), (4, 0), (5, 0), (3, 1), (4, 1), (5, 1), (3, 2), (4, 2), (5, 2)]  # 黑方在上方九宫格
            else:  # 红方在上方，黑方在下方
                return (x, y) in [(3, 7), (4, 7), (5, 7), (3, 8), (4, 8), (5, 8), (3, 9), (4, 9), (5, 9)]  # 黑方在下方九宫格
    
    # 兵/卒的合法位置
    elif piece_type in ['p', 'P']:  # 兵/卒
        if piece_type.isupper():  # 红兵
            if is_red:  # 红方在下方
                if y >= 5:  # 在己方区域
                    return (x, y) in [(0, 6), (2, 6), (4, 6), (6, 6), (8, 6), (0, 5), (2, 5), (4, 5), (6, 5), (8, 5)]  # 红方在下方时，兵在下方第5行和第6行
                return True  # 过河后可以在任何位置
            else:  # 红方在上方
                if y <= 4:  # 在己方区域
                    return (x, y) in [(0, 3), (2, 3), (4, 3), (6, 3), (8, 3), (0, 4), (2, 4), (4, 4), (6, 4), (8, 4)]  # 红方在上方时，兵在上方第3行和第4行
                return True  # 过河后可以在任何位置
        else:  # 黑卒
            if is_red:  # 红方在下方，黑方在上方
                if y <= 4:  # 在己方区域
                    return (x, y) in [(0, 3), (2, 3), (4, 3), (6, 3), (8, 3), (0, 4), (2, 4), (4, 4), (6, 4), (8, 4)]  # 黑方在上方区域
                return True  # 过河后可以在任何位置
            else:  # 红方在上方，黑方在下方
                if y >= 5:  # 在己方区域
                    return (x, y) in [(0, 6), (2, 6), (4, 6), (6, 6), (8, 6), (0, 5), (2, 5), (4, 5), (6, 5), (8, 5)]  # 黑方在下方区域
                return True  # 过河后可以在任何位置
    
    # 车、马、炮可以在任何位置
    return True

# 计算棋子坐标
def find_nearest_index(point, points):  
    distances = [abs(point - p) for p in points]  # 计算点到所有竖线x坐标的绝对值差异  
    return distances.index(min(distances))  # 返回最接近的竖线的索引 
  

def calculate_pieces_position(x_array, y_array, circles):  
    # 处理circles，计算每个圆心到最近的竖线和横线的索引，并更新pieceArray  
    
    # 初始化pieceArray  
    pieceArray = [["-"] * len(x_array) for _ in range(len(y_array))]  
      
    for cx, cy, radius, name in circles:  
        # 找到最接近的竖线和横线的索引  
        nearest_x_index = find_nearest_index(cx, x_array)  
        nearest_y_index = find_nearest_index(cy, y_array)  
          
        # 可选：检查圆心是否"足够接近"某条竖线或横线（使用半径作为阈值）  
        # 这里我们简单地标记最近的竖线和横线，不考虑阈值  
          
        # 在pieceArray中标记圆心位置  
        # 注意：这里我们假设要在一个"单元格"中标记圆心，即一个特定的(x, y)索引  
        pieceArray[nearest_y_index][nearest_x_index] = name  # 或者使用其他标记方式  
          
        # 如果想要表示圆心的范围（例如，使用半径画圆），则需要更复杂的逻辑  
        # 这通常涉及到在pieceArray中设置多个单元格，可能还需要额外的数据结构或算法  
    
    # 判断本方是红棋还是黑棋
    # 寻找 "K" 的位置以判断是红方还是黑方
    is_red = False
    for row in pieceArray[:3]: # 老将只会在9宫,所以只看前3行
        for cell in row:
            if 'k' in cell:
                is_red = True
                break
        if is_red:
            break

    return pieceArray, is_red   
  
# 测试棋子的HVS范围并打印
# def measure_color_range(roi):  
 
#     # 转换到HSV颜色空间  
#     hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)  
        
#     # 计算并显示颜色范围（这里只是简单地显示所有HSV值）  
#     # 在实际应用中，你可能需要分析这些值来确定合适的范围  
#     hsv_values = hsv_roi.reshape((-1, 3))  # 将图像转换为一维数组，每三个元素为一个HSV值  
        
#     # 打印或分析HSV值  
#     # 例如，你可以找到H、S、V通道的最小值和最大值  
#     h_min, h_max = np.min(hsv_values[:, 0]), np.max(hsv_values[:, 0])  
#     s_min, s_max = np.min(hsv_values[:, 1]), np.max(hsv_values[:, 1])  
#     v_min, v_max = np.min(hsv_values[:, 2]), np.max(hsv_values[:, 2])  
        
#     print(f"H range: {h_min} to {h_max}")  
#     print(f"S range: {s_min} to {s_max}")  
#     print(f"V range: {v_min} to {v_max}")  