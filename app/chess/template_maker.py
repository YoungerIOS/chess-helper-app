import os
import json
import cv2
import numpy as np
import mss
from .recognition import (
    pre_processing_image,
    board_recognition,
    recognize_piece_color,
    find_nearest_index
)

def get_piece_type_by_position(x, y, x_array, y_array):
    """
    根据棋子的位置确定其类型
    :param x: 棋子x坐标
    :param y: 棋子y坐标
    :param x_array: 棋盘x坐标数组
    :param y_array: 棋盘y坐标数组
    :return: 棋子类型代号
    """
    # 找到最近的横线和竖线索引
    x_idx = find_nearest_index(x, x_array)
    y_idx = find_nearest_index(y, y_array)
    
    # 开局时红方棋子的位置映射（从下到上，从左到右）
    red_pieces = {
        (0, 0): 'R',  # 车
        (1, 0): 'N',  # 马
        (2, 0): 'B',  # 相
        (3, 0): 'A',  # 仕
        (4, 0): 'K',  # 帅
        (5, 0): 'A',  # 仕
        (6, 0): 'B',  # 相
        (7, 0): 'N',  # 马
        (8, 0): 'R',  # 车
        (1, 2): 'C',  # 炮
        (7, 2): 'C',  # 炮
        (0, 3): 'P',  # 兵
        (2, 3): 'P',  # 兵
        (4, 3): 'P',  # 兵
        (6, 3): 'P',  # 兵
        (8, 3): 'P',  # 兵
    }
    
    # 开局时黑方棋子的位置映射（从上到下，从左到右）
    black_pieces = {
        (0, 9): 'r',  # 车
        (1, 9): 'n',  # 马
        (2, 9): 'b',  # 相
        (3, 9): 'a',  # 仕
        (4, 9): 'k',  # 将
        (5, 9): 'a',  # 仕
        (6, 9): 'b',  # 相
        (7, 9): 'n',  # 马
        (8, 9): 'r',  # 车
        (1, 7): 'c',  # 炮
        (7, 7): 'c',  # 炮
        (0, 6): 'p',  # 卒
        (2, 6): 'p',  # 卒
        (4, 6): 'p',  # 卒
        (6, 6): 'p',  # 卒
        (8, 6): 'p',  # 卒
    }
    
    # 根据y坐标判断是红方还是黑方
    if y_idx <= 4:  # 红方区域
        piece_type = red_pieces.get((x_idx, y_idx))
    else:  # 黑方区域
        piece_type = black_pieces.get((x_idx, y_idx))
    
    return piece_type

def save_chess_pieces(img, gray, x_array, y_array, output_dir="chess_pieces"):
    """
    保存切割的棋子图片
    :param img: 原始图片
    :param gray: 灰度图
    :param x_array: 棋盘x坐标数组
    :param y_array: 棋盘y坐标数组
    :param output_dir: 输出目录
    """
    # 计算棋子半径
    # 使用相邻x坐标的间距作为参考
    x_distances = [x_array[i+1] - x_array[i] for i in range(len(x_array)-1)]
    avg_x_distance = sum(x_distances) / len(x_distances)
    
    # 设置半径范围
    maxRadius = int(avg_x_distance * 0.46)  # 使用间距的46%作为最大半径
    minRadius = int(avg_x_distance * 0.36)  # 使用间距的36%作为最小半径
    minDist = int(avg_x_distance * 0.8)     # 使用间距的80%作为最小距离
    
    print(f"计算得到的棋子半径范围: {minRadius} - {maxRadius}")
    
    # 使用霍夫圆检测
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1, minDist, 
                             param1=50, param2=30, 
                             minRadius=minRadius, maxRadius=maxRadius)
    
    if circles is None:
        print("未检测到棋子")
        return False
        
    circles = np.round(circles[0, :]).astype("int")
    
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    # 遍历所有检测到的棋子
    for idx, (x, y, r) in enumerate(circles):
        # 增加安全边距，确保不会切掉棋子
        padding = int(r * 0.1)  # 增加10%的边距
        
        # 计算切割区域
        x1, y1 = max(0, x-r-padding), max(0, y-r-padding)
        x2, y2 = min(img.shape[1]-1, x+r+padding), min(img.shape[0]-1, y+r+padding)
        
        # 切割棋子图片
        piece_img = img[y1:y2, x1:x2]
        
        # 判断棋子颜色
        color = recognize_piece_color(piece_img)
        
        if color:
            # 获取棋子类型
            piece_type = get_piece_type_by_position(x, y, x_array, y_array)
            
            if piece_type:
                # 根据颜色调整棋子类型的大小写
                if color == "red":
                    piece_type = piece_type.upper()  # 红方用大写
                else:
                    piece_type = piece_type.lower()  # 黑方用小写
                
                # 直接保存在平台目录下，命名格式为 color_piece_type.jpg
                output_path = os.path.join(output_dir, f"{color}_{piece_type}.jpg")
                cv2.imwrite(output_path, piece_img)
                
                print(f"Saved {color} piece {piece_type} to {output_path}")
    
    return True

def save_templates():
    """保存棋盘上的棋子模板"""
    try:
        # 读取棋盘位置
        with open('app/json/coordinates.json', 'r') as f:
            data = json.load(f)
            region = data['region1']
        
        # 读取游戏平台设置
        with open('app/json/params.json', 'r') as f:
            params = json.load(f)
            platform = params.get('platform', 'TT')  # 默认为天天象棋
        
        # 根据平台选择保存目录
        if platform == 'JJ':
            template_dir = 'app/images/jj'
        else:
            template_dir = 'app/images/tiantian'
        
        # 截取棋盘区域
        with mss.mss() as sct:
            board_img = sct.grab(region)
        
        if board_img is None:
            return False
        
        # 预处理图像
        image, gray = pre_processing_image(board_img)
        if image is None or gray is None:
            return False
        
        # 识别棋盘并生成坐标
        x_array, y_array = board_recognition(image, gray)
        if not x_array or not y_array:
            print("棋盘识别失败")
            return False
        
        # 保存模板
        if not save_chess_pieces(image, gray, x_array, y_array, template_dir):
            print("保存模板失败")
            return False
        
        return True
        
    except Exception as e:
        print(f"保存模板时出错: {str(e)}")
        return False 