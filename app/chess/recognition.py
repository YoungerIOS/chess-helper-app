import cv2
import numpy as np
import os
from tools import utils
import json

def show_image(name, image):
    # 显示结果  
    cv2.imshow(name, image)  
    cv2.waitKey(0)  
    cv2.destroyAllWindows()

def pre_processing_image(img_origin):
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
    x_array = []
    y_array = []
    error = ''
    try:
        # 尝试读取 JSON 文件
        with open(utils.resource_path("json/board.json"), 'r') as file:
            data = json.load(file)

        # 提取横坐标和纵坐标
        x_array = data["x"]
        y_array = data["y"]

        # print("读取的横坐标：", x_array)
        # print("读取的纵坐标：", y_array)
    except FileNotFoundError:
        error = 'board.json文件未找到'
        print(error)
    return x_array, y_array, error

# 识别棋盘
def board_recognition(img, gray):
    x_arr, y_arr, error = get_board_data()
    if not error: return x_arr, y_arr

    # 高斯模糊  
    gaus = cv2.GaussianBlur(gray, (5, 5), 0)  
    # 边缘检测  
    edges = cv2.Canny(gaus, 20, 120, apertureSize=3)  
    # show_image('Edges', edges)
    
    # 膨胀操作以合并相邻线条  
    # kernel = np.ones((3, 3), np.uint8)  # 定义膨胀核的大小，可以根据需要调整  
    # dilated_edges = cv2.dilate(edges, kernel, iterations=1) 
    
    # 腐蚀操作以恢复线条宽度  
    # eroded_edges = cv2.erode(dilated_edges, kernel, iterations=1) 
    
    # 可选：再次膨胀以调整线条宽度  
    # final_edges = cv2.dilate(eroded_edges, kernel, iterations=1)
    # show_image('Edges', final_edges)

    # 霍夫线变换  
    lines = cv2.HoughLinesP(edges, 0.5, np.pi/180, threshold=80, minLineLength=100, maxLineGap=5)  
    
    # 创建一张新图
    # black_img = np.zeros((img.shape[0], img.shape[1], 3), np.uint8)
    # black_img.fill(0) # 使用黑色填充图片区域

    # 过滤线段并在新图上绘制
    # 竖线 (x1 == x2)
    x_array = []
    vlines, yMin, yMax = utils.filter_vertical_lines(lines, img.shape[1])
    for line in vlines:  
        for x1, y1, x2, y2 in line:
            # cv2.line(black_img, (x1, yMin), (x2, yMax), (0, 255, 0), 1)
            x_array.append(int(x1))

    # 横线 (y1 == y2)
    y_array = []
    hlines, xMin, xMax = utils.filter_horizontal_lines(lines, img.shape[1])
    for line in hlines:  
        for x1, y1, x2, y2 in line:  
            # cv2.line(black_img, (xMin, y1), (xMax, y2), (0, 255, 0), 1)
            y_array.append(int(y1))
    
    
    # 显示结果 
    # show_image('Detected Lines', black_img) 
    # print(f"横坐标:{x_array}\n 纵坐标:{y_array}")
    # 将数组组合成一个字典
    data = {
        "x": x_array,
        "y": y_array
    }

    # 确保json目录存在
    json_dir = os.path.dirname(utils.resource_path("json/board.json"))
    os.makedirs(json_dir, exist_ok=True)
    
    # 保存board.json
    with open(utils.resource_path("json/board.json"), 'w') as file:
        json.dump(data, file)

    return x_array, y_array


# 识别棋子
def pieces_recognition(img, gray, param, x_array, y_array):
    """
    识别棋子并确定其位置和类型
    Args:
        img: 原始图像
        gray: 灰度图像
        param: 参数配置
        x_array: 棋盘横线坐标数组
        y_array: 棋盘纵线坐标数组
    Returns:
        pieceArray: 9x10的二维数组，表示棋盘状态，每个位置存储棋子类型代号或"-"
        is_red: 是否为红方
    """
    width = img.shape[1]
    maxRadius = int(width/9/2)  # 棋盘宽度除以9（横向最多9个棋子，再除2就是半径）
    minRadius = int(0.8 * width/9/2)
    minDist = int(0.8 * width/9)  # 棋子与棋子间距，最小就是2个半径
    
    # 检测圆形
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1, minDist, 
                              param1=50, param2=30, 
                              minRadius=minRadius, maxRadius=maxRadius)
    if circles is not None:
        circles = np.round(circles[0, :]).astype("int")
        
        # 根据游戏平台选择模板目录
        platform = param['platform']
        template_path = utils.resource_path("images/jj" if platform == 'JJ' else "images/tiantian")
        
        # 识别黑将并获取计算好坐标的棋盘数组
        pieceArray, is_red = recognize_black_king(circles, img, x_array, y_array, template_path)
        print(f"\n当前方为{'红方' if is_red else '黑方'}")
        
        # 识别所有棋子
        for i in range(len(pieceArray)):
            for j in range(len(pieceArray[0])):
                if pieceArray[i][j] == '-':
                    continue
                x, y, r = pieceArray[i][j]
                x1, y1, x2, y2 = x - r, y - r, x + r, y + r
                if x1 < 0: x1 = 0
                if y1 < 0: y1 = 0
                if x2 >= img.shape[1]: x2 = img.shape[1] - 1
                if y2 >= img.shape[0]: y2 = img.shape[0] - 1
                piece_img = img[y1:y2+1, x1:x2+1]
                color = recognize_piece_color(piece_img)
                if color is None:
                    print(f"位置({j}, {i}) 无法确定棋子颜色，跳过")
                    continue
                piece_type, score = recognize_piece_type(piece_img, template_path, j, i, is_red)
                print(f"位置({j}, {i}) 识别为 {piece_type}，颜色: {color}，得分: {score}")
                if piece_type:
                    pieceArray[i][j] = piece_type
                else:
                    pieceArray[i][j] = '-'

    else:
        pieceArray = [["-"] * len(x_array) for _ in range(len(y_array))]
        is_red = False
    return pieceArray, is_red

#比较两张图片的特征点,返回相似度
def compare_feature(img1, img2):
    """
    比较两张图片的特征点，返回相似度
    Args:
        img1: 第一张图片
        img2: 第二张图片
    Returns:
        int: 相似度分数
    """
    # 确保图片大小一致
    img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))
    
    # 创建SIFT对象
    sift = cv2.SIFT_create()
    
    # 检测关键点和描述符
    kp1, des1 = sift.detectAndCompute(img1, None)
    kp2, des2 = sift.detectAndCompute(img2, None)
    
    if des1 is None or des2 is None or len(kp1) == 0 or len(kp2) == 0:
        return 0
    
    # 创建BFMatcher对象
    bf = cv2.BFMatcher()
    
    # 使用knnMatch进行特征匹配
    matches = bf.knnMatch(des1, des2, k=2)
    
    # 应用比率测试
    good_matches = []
    for m, n in matches:
        if m.distance < 0.75 * n.distance:
            good_matches.append(m)
    
    # 计算匹配点数量
    match_count = len(good_matches)
    
    # 计算特征点分布相似度
    if len(kp1) > 0 and len(kp2) > 0:
        # 计算关键点的分布
        kp1_centers = np.array([kp.pt for kp in kp1])
        kp2_centers = np.array([kp.pt for kp in kp2])
        
        # 计算质心
        center1 = np.mean(kp1_centers, axis=0)
        center2 = np.mean(kp2_centers, axis=0)
        
        # 计算质心距离
        center_dist = np.linalg.norm(center1 - center2)
        
        # 计算特征点分布的方差
        var1 = np.var(kp1_centers, axis=0)
        var2 = np.var(kp2_centers, axis=0)
        
        # 计算方差差异
        var_diff = np.linalg.norm(var1 - var2)
        
        # 根据图像大小动态调整阈值
        img_size = max(img1.shape[0], img1.shape[1])
        center_threshold = img_size * 0.1  # 质心距离阈值为图像尺寸的10%
        var_threshold = img_size * 0.05    # 方差差异阈值为图像尺寸的5%
        
        # 根据质心距离和方差差异调整得分
        if center_dist > center_threshold:
            match_count = int(match_count * 0.8)  # 质心距离太大，降低得分
        if var_diff > var_threshold:
            match_count = int(match_count * 0.9)  # 方差差异太大，降低得分
    
    return match_count

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

# 计算棋子9x10坐标,单独识别将
def recognize_black_king(circles, img, x_array, y_array, template_path):
    """
    识别九宫格内的黑将'k',并计算所有棋子的9x10棋盘坐标
    Args:
        circles: 棋子圆心和半径列表
        img: 原始图像
        x_array: 棋盘横线坐标数组
        y_array: 棋盘纵线坐标数组
        template_path: 模板图片目录
    Returns:
        pieceArray: 9x10的二维数组,表示棋盘状态,已计算好所有棋子的坐标
    """
    # 初始化棋盘数组
    pieceArray = [["-"] * len(x_array) for _ in range(len(y_array))]

    # 黑将是否在上方九宫
    black_king_in_upper_palace = False
    best_score = 0
    best_match = None

    # 计算所有棋子的棋盘坐标
    for x, y, r in circles:
        board_x, board_y = get_piece_position((x, y), x_array, y_array)
        # 存储棋子的原始信息到对应位置
        pieceArray[board_y][board_x] = (x, y, r)

    # 在九宫格内寻找黑将
    for i in range(3):  # 上方九宫格是前3行
        for j in range(3, 6):  # 上方九宫格是中间3列
            if pieceArray[i][j] == '-':
                continue
            x, y, r = pieceArray[i][j]
            x1, y1, x2, y2 = x - r, y - r, x + r, y + r
            if x1 < 0: x1 = 0
            if y1 < 0: y1 = 0
            if x2 >= img.shape[1]: x2 = img.shape[1] - 1
            if y2 >= img.shape[0]: y2 = img.shape[0] - 1
            piece_img = img[y1:y2+1, x1:x2+1]
            color = recognize_piece_color(piece_img)
            if color is None or color != 'black':
                continue
            template_name = "black_k.jpg"
            template_img = cv2.imread(os.path.join(template_path, template_name))
            if template_img is not None:
                score = compare_feature(piece_img, template_img)
                print(f"位置({j}, {i}) 黑将匹配得分: {score}")
                if score > best_score:
                    best_score = score
                    best_match = (j, i)

    # 如果找到最佳匹配且相似度超过阈值，则标记为找到黑将
    if best_match and best_score > 40:
        black_king_in_upper_palace = True

    return pieceArray, black_king_in_upper_palace

# 判断棋子红色与黑色 
def recognize_piece_color(img):
    """
    判断棋子颜色（红/黑）
    Args:
        img: 棋子图像
    Returns:
        str: 'red' 或 'black'，如果无法判断则返回 None
    """
    if img is None or img.size == 0:  
        print(f"Error: img is None or empty (shape: {img.shape if img is not None else 'None'})")  
        return None

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)  
    if hsv is None or hsv.size == 0:  
        print(f"Error: Failed to convert image to HSV (shape before: {img.shape})")  
        return None
    
    # 定义多个红色的HSV阈值范围  
    red_ranges = [  
        ([0, 50, 50], [10, 255, 255]),  # 浅红色  
        ([160, 50, 50], [180, 255, 255]),  # 深红色（跨越了180度的边界）  
        ([0, 100, 100], [10, 255, 255])  # 中等红色  
    ]  
  
    # 初始化红色掩码  
    red_mask = np.zeros_like(hsv[:, :, 0])  
  
    # 遍历每个红色范围并更新掩码  
    for lower, upper in red_ranges:  
        lower = np.array(lower, dtype=np.uint8)  
        upper = np.array(upper, dtype=np.uint8)  
        red_mask_temp = cv2.inRange(hsv, lower, upper)  
        red_mask = cv2.bitwise_or(red_mask, red_mask_temp)  
  
    # 假设黑色通过亮度检测（在灰度图中）  
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)  
    _, black_mask = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY_INV)  # 假设亮度低于50的为黑色  
  
    # 形态学操作去除噪点  
    kernel = np.ones((5, 5), np.uint8)  
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, kernel)  
    black_mask = cv2.morphologyEx(black_mask, cv2.MORPH_OPEN, kernel)  
  
    # 计算红色和黑色区域的面积  
    red_area = cv2.countNonZero(red_mask)  
    black_area = cv2.countNonZero(black_mask)  
  
    # 返回颜色判断结果  
    return "red" if red_area > black_area else 'black' 

def recognize_piece_type(piece_img, template_path, board_x, board_y, is_red):
    """
    识别棋子类型
    Args:
        piece_img: 棋子图像
        template_path: 模板图片目录
        board_x: 棋盘横坐标
        board_y: 棋盘纵坐标
        is_red: 本方是否为红方
    Returns:
        piece_type: 棋子类型，如果无法识别则返回None
        score: 相似度得分
    """
    best_score = 0  
    best_match = None  
      
    # 判断棋子颜色
    color = recognize_piece_color(piece_img)
    if color is None:
        return None, 0
    
    # 遍历模板图片
    for filename in os.listdir(template_path):
        if filename.endswith('.jpg'): 
            # 检查颜色匹配
            if (color == 'red' and filename.startswith('red_')) or (color == 'black' and filename.startswith('black_')):  
                # 获取棋子类型，保持原有大小写
                piece_type = utils.cut_substring(filename)
                
                # 先验证该类型的棋子是否可以出现在当前位置
                if not is_valid_position(piece_type, board_x, board_y, is_red):
                    continue  # 如果位置不合法，直接跳过这个模板
                
                # 读取模板图片
                template_img = cv2.imread(os.path.join(template_path, filename))
                if template_img is not None:
                    # 计算相似度
                    score = compare_feature(piece_img, template_img)
                    
                    # 更新最佳匹配
                    if score > best_score:  
                        best_score = score  
                        best_match = piece_type
    
    # 如果找到匹配，返回棋子类型和得分
    return best_match, best_score

def is_valid_position(piece_type, x, y, is_red):
    """
    根据中国象棋规则验证棋子位置是否合法
    Args:
        piece_type: 棋子类型
        x: 棋盘横坐标
        y: 棋盘纵坐标
        is_red: 是否为红方
    Returns:
        bool: 位置是否合法
    """
    # 注意：当红棋在下方时，is_red为True，这时坐标系是反的
    # 红棋在上方时，黑方的棋子应该在下方九宫格
    
    # 士/仕的合法位置（九宫格内的5个位置）
    if piece_type in ['a', 'A']:  # 士/仕
        if piece_type.isupper():  # 红方士
            if is_red:  # 红方在下方
                return (x, y) in [(3, 7), (5, 7), (4, 8), (3, 9), (5, 9)]  # 红方在下方时，士在下方九宫格
            else:  # 红方在上方
                return (x, y) in [(3, 0), (5, 0), (4, 1), (3, 2), (5, 2)]  # 红方在上方时，士在上方九宫格
        else:  # 黑方仕
            if is_red:  # 红方在下方，黑方在上方
                return (x, y) in [(3, 0), (5, 0), (4, 1), (3, 2), (5, 2)]  # 黑方在上方九宫格
            else:  # 红方在上方，黑方在下方
                return (x, y) in [(3, 7), (5, 7), (4, 8), (3, 9), (5, 9)]  # 黑方在下方九宫格
    
    # 相/象的合法位置（己方区域的7个位置）
    elif piece_type in ['b', 'B']:  # 相/象
        if piece_type.isupper():  # 红方相
            if is_red:  # 红方在下方
                return (x, y) in [(2, 5), (6, 5), (0, 7), (4, 7), (8, 7), (2, 9), (6, 9)]  # 红方在下方时，相在下方区域
            else:  # 红方在上方
                return (x, y) in [(2, 0), (6, 0), (0, 2), (4, 2), (8, 2), (2, 4), (6, 4)]  # 红方在上方时，相在上方区域
        else:  # 黑方象
            if is_red:  # 红方在下方，黑方在上方
                return (x, y) in [(2, 0), (6, 0), (0, 2), (4, 2), (8, 2), (2, 4), (6, 4)]  # 黑方在上方区域
            else:  # 红方在上方，黑方在下方
                return (x, y) in [(2, 5), (6, 5), (0, 7), (4, 7), (8, 7), (2, 9), (6, 9)]  # 黑方在下方区域
    
    # 将/帅的合法位置（九宫格内的9个位置）
    elif piece_type in ['k', 'K']:  # 将/帅
        if piece_type.isupper():  # 红方帅
            if is_red:  # 红方在下方
                return (x, y) in [(3, 7), (4, 7), (5, 7), (3, 8), (4, 8), (5, 8), (3, 9), (4, 9), (5, 9)]  # 红方在下方时，帅在下方九宫格
            else:  # 红方在上方
                return (x, y) in [(3, 0), (4, 0), (5, 0), (3, 1), (4, 1), (5, 1), (3, 2), (4, 2), (5, 2)]  # 红方在上方时，帅在上方九宫格
        else:  # 黑方将
            if is_red:  # 红方在下方，黑方在上方
                return (x, y) in [(3, 0), (4, 0), (5, 0), (3, 1), (4, 1), (5, 1), (3, 2), (4, 2), (5, 2)]  # 黑方在上方九宫格
            else:  # 红方在上方，黑方在下方
                return (x, y) in [(3, 7), (4, 7), (5, 7), (3, 8), (4, 8), (5, 8), (3, 9), (4, 9), (5, 9)]  # 黑方在下方九宫格
    
    # 兵/卒的合法位置
    elif piece_type in ['p', 'P']:  # 兵/卒
        if piece_type.isupper():  # 红方兵
            if is_red:  # 红方在下方
                if y >= 5:  # 在己方区域
                    return (x, y) in [(0, 6), (2, 6), (4, 6), (6, 6), (8, 6), (0, 5), (2, 5), (4, 5), (6, 5), (8, 5)]  # 红方在下方时，兵在下方区域
                return True  # 过河后可以在任何位置
            else:  # 红方在上方
                if y <= 4:  # 在己方区域
                    return (x, y) in [(0, 3), (2, 3), (4, 3), (6, 3), (8, 3)]  # 红方在上方时，兵在上方区域，只允许在第3行
                return True  # 过河后可以在任何位置
        else:  # 黑方卒
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
  
def validate_piece_positions(pieceArray, is_red):
    """
    根据中国象棋规则验证棋子位置是否合法
    pieceArray: 9x10的二维数组，表示棋盘状态
    is_red: 是否为红方
    """
    # 士/仕的合法位置（九宫格内的5个位置）
    advisor_positions = [(3, 0), (5, 0), (4, 1), (3, 2), (5, 2)]  # 黑方
    if is_red:
        advisor_positions = [(3, 7), (5, 7), (4, 8), (3, 9), (5, 9)]  # 红方

    # 相/象的合法位置（己方区域的7个位置）
    elephant_positions = [(2, 0), (6, 0), (0, 2), (4, 2), (8, 2), (2, 4), (6, 4)]  # 黑方
    if is_red:
        elephant_positions = [(2, 5), (6, 5), (0, 7), (4, 7), (8, 7), (2, 9), (6, 9)]  # 红方

    # 将/帅的合法位置（九宫格内的9个位置）
    king_positions = [
        (3, 0), (4, 0), (5, 0),
        (3, 1), (4, 1), (5, 1),
        (3, 2), (4, 2), (5, 2)
    ]  # 黑方
    if is_red:
        king_positions = [
            (3, 7), (4, 7), (5, 7),
            (3, 8), (4, 8), (5, 8),
            (3, 9), (4, 9), (5, 9)
        ]  # 红方

    # 兵/卒的合法位置（己方区域的前三排）
    pawn_positions = [
        (0, 3), (2, 3), (4, 3), (6, 3), (8, 3),  # 第3行
        (0, 4), (2, 4), (4, 4), (6, 4), (8, 4)   # 第4行
    ]  # 黑方
    if is_red:
        pawn_positions = [
            (0, 6), (2, 6), (4, 6), (6, 6), (8, 6),  # 第6行
            (0, 5), (2, 5), (4, 5), (6, 5), (8, 5)   # 第5行
        ]  # 红方

    # 检查每个棋子的位置
    for y in range(len(pieceArray)):
        for x in range(len(pieceArray[0])):
            piece = pieceArray[y][x]
            if piece == '-':
                continue

            # 判断棋子颜色
            piece_is_red = piece.isupper()
            
            # 根据棋子类型和颜色验证位置
            if piece in ['a', 'A']:  # 士/仕
                if piece.isupper():  # 红方士
                    if (x, y) not in advisor_positions:
                        print(f"警告: 红方士在非法位置 ({x}, {y})")
                else:  # 黑方仕
                    if (x, y) not in advisor_positions:
                        print(f"警告: 黑方仕在非法位置 ({x}, {y})")
            elif piece in ['b', 'B']:  # 相/象
                if piece.isupper():  # 红方相
                    if (x, y) not in elephant_positions:
                        print(f"警告: 红方相在非法位置 ({x}, {y})")
                else:  # 黑方象
                    if (x, y) not in elephant_positions:
                        print(f"警告: 黑方象在非法位置 ({x}, {y})")
            elif piece in ['k', 'K']:  # 将/帅
                if piece.isupper():  # 红方帅
                    if (x, y) not in king_positions:
                        print(f"警告: 红方帅在非法位置 ({x}, {y})")
                else:  # 黑方将
                    if (x, y) not in king_positions:
                        print(f"警告: 黑方将在非法位置 ({x}, {y})")
            elif piece in ['p', 'P']:  # 兵/卒
                if piece.isupper():  # 红方兵
                    if y >= 5:  # 在己方区域
                        if (x, y) not in pawn_positions:
                            print(f"警告: 红方兵在非法位置 ({x}, {y})")
                else:  # 黑方卒
                    if y <= 4:  # 在己方区域
                        if (x, y) not in pawn_positions:
                            print(f"警告: 黑方卒在非法位置 ({x}, {y})")

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