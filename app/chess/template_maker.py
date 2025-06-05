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
from . import recognition
from .context import context


def iter_pieces_by_grid(img, x_array, y_array, template_path=None, is_red=True):
    """
    网格交点切割棋子生成器，yield (piece_img, piece_type, color, (center_x, center_y))
    """
    if template_path is None:
        template_path = os.path.join("app", "images", "jj")
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
            cut_radius = int(min(x_radius, y_radius) * 0.9)
            vertical_offset = int(cut_radius * 0.06)
            x1 = max(0, center_x - cut_radius)
            y1 = max(0, center_y - cut_radius - vertical_offset)
            x2 = min(img.shape[1]-1, center_x + cut_radius)
            y2 = min(img.shape[0]-1, center_y + cut_radius - vertical_offset)
            piece_img = img[y1:y2, x1:x2]
            color = recognition.recognize_piece_color(piece_img)
            piece_type = None
            if color:
                piece_type, _ = recognition.recognize_piece_type(piece_img, template_path, j, i, is_red)
            yield piece_img, piece_type, color, (center_x, center_y)

def iter_pieces_by_hough(img, gray, x_array, y_array, template_path=None, is_red=True):
    """
    霍夫圆检测切割棋子生成器，yield (piece_img, piece_type, color, (x, y))
    """
    if template_path is None:
        template_path = os.path.join("app", "images", "jj")
    x_distances = [x_array[i+1] - x_array[i] for i in range(len(x_array)-1)]
    avg_x_distance = sum(x_distances) / len(x_distances)
    maxRadius = int(avg_x_distance * 0.46)
    minRadius = int(avg_x_distance * 0.36)
    minDist = int(avg_x_distance * 0.8)
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1, minDist, 
                             param1=50, param2=30, 
                             minRadius=minRadius, maxRadius=maxRadius)
    if circles is None:
        return
    circles = np.round(circles[0, :]).astype("int")
    for idx, (x, y, r) in enumerate(circles):
        padding = int(r * 0.1)
        x1, y1 = max(0, x-r-padding), max(0, y-r-padding)
        x2, y2 = min(img.shape[1]-1, x+r+padding), min(img.shape[0]-1, y+r+padding)
        piece_img = img[y1:y2, x1:x2]
        color = recognition.recognize_piece_color(piece_img)
        piece_type = None
        if color:
            board_x = min(range(len(x_array)), key=lambda j: abs(x_array[j] - x))
            board_y = min(range(len(y_array)), key=lambda i: abs(y_array[i] - y))
            piece_type, _ = recognition.recognize_piece_type(piece_img, template_path, board_x, board_y, is_red)
        yield piece_img, piece_type, color, (x, y)

def save_chess_samples(img, gray, x_array, y_array, method='grid', output_dir='app/images/jj_sample', is_red=True, template_path=None):
    """
    收集棋子样本，method为'grid'或'hough'，每种类型分文件夹保存，不去重
    """
    os.makedirs(output_dir, exist_ok=True)
    sample_count = {}
    if method == 'grid':
        piece_iter = iter_pieces_by_grid(img, x_array, y_array, template_path, is_red)
    else:
        piece_iter = iter_pieces_by_hough(img, gray, x_array, y_array, template_path, is_red)
    for piece_img, piece_type, color, _ in piece_iter:
        # 如果是空格，跳过不保存
        if not piece_type:
            continue
        # 等比例缩放为80x80
        piece_img = cv2.resize(piece_img, (80, 80), interpolation=cv2.INTER_AREA)
        prefix = f'{color}_' if color else ''
        type_dir = os.path.join(output_dir, f'{prefix}{piece_type}')
        key = f'{prefix}{piece_type}'
        os.makedirs(type_dir, exist_ok=True)
        # 获取目录下已有文件的最大序号
        existing_files = [f for f in os.listdir(type_dir) if f.endswith('.jpg')]
        max_num = 0
        for f in existing_files:
            try:
                num = int(f.split('_')[-1].split('.')[0])
                max_num = max(max_num, num)
            except:
                continue
        # 从最大序号+1开始保存
        sample_count[key] = max_num + 1
        filename = f"{key}_{sample_count[key]}.jpg"
        output_path = os.path.join(type_dir, filename)
        cv2.imwrite(output_path, piece_img)
        print(f"Saved sample {output_path}")
        sample_count[key] += 1
    return True

def save_chess_pieces_by_grid(img, x_array, y_array, output_dir="chess_pieces"):
    """
    基于网格坐标切割并保存棋子模板（去重）
    """
    os.makedirs(output_dir, exist_ok=True)
    saved_types = set()
    for piece_img, piece_type, _ in iter_pieces_by_grid(img, x_array, y_array):
        if piece_type in saved_types:
            continue
        saved_types.add(piece_type)
        output_path = os.path.join(output_dir, f"{piece_type}.jpg")
        cv2.imwrite(output_path, piece_img)
        print(f"Saved {piece_type} to {output_path}")
    return True

def save_chess_pieces(img, gray, x_array, y_array, output_dir="chess_pieces"):
    """
    霍夫圆检测切割并保存棋子模板（去重）
    """
    os.makedirs(output_dir, exist_ok=True)
    saved_types = set()
    for piece_img, piece_type, _ in iter_pieces_by_hough(img, gray, x_array, y_array):
        if piece_type in saved_types:
            continue
        saved_types.add(piece_type)
        output_path = os.path.join(output_dir, f"{piece_type}.jpg")
        cv2.imwrite(output_path, piece_img)
        print(f"Saved {piece_type} to {output_path}")
    return True



def save_chess_samples_by_grid(img, x_array, y_array, output_dir="app/images/jj_sample", template_path=None, is_red=True):
    """
    基于网格坐标切割并保存棋子样本图片（用于模型训练，不去重，每种类型单独文件夹）
    :param img: 原始图片
    :param x_array: 棋盘x坐标数组
    :param y_array: 棋盘y坐标数组
    :param output_dir: 输出目录（默认app/images/jj_sample）
    :param template_path: 模板路径
    :param is_red: 是否红方在下
    """
    if template_path is None:
        template_path = os.path.join("app", "images", "jj")
    os.makedirs(output_dir, exist_ok=True)
    sample_count = {}
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
            cut_radius = int(min(x_radius, y_radius) * 0.9)
            vertical_offset = int(cut_radius * 0.06)
            x1 = max(0, center_x - cut_radius)
            y1 = max(0, center_y - cut_radius - vertical_offset)
            x2 = min(img.shape[1]-1, center_x + cut_radius)
            y2 = min(img.shape[0]-1, center_y + cut_radius - vertical_offset)
            piece_img = img[y1:y2, x1:x2]
            # 等比例缩放为80x80
            piece_img = cv2.resize(piece_img, (80, 80), interpolation=cv2.INTER_AREA)
            color = recognition.recognize_piece_color(piece_img)
            piece_type = None
            if color:
                piece_type, _ = recognition.recognize_piece_type(piece_img, template_path, j, i, is_red)
            # 如果是空格，跳过不保存
            if not piece_type:
                continue
            prefix = f'{color}_' if color else ''
            type_dir = os.path.join(output_dir, f'{prefix}{piece_type}')
            os.makedirs(type_dir, exist_ok=True)
            key = f'{prefix}{piece_type}'
            # 获取目录下已有文件的最大序号
            existing_files = [f for f in os.listdir(type_dir) if f.endswith('.jpg')]
            max_num = 0
            for f in existing_files:
                try:
                    num = int(f.split('_')[-1].split('.')[0])
                    max_num = max(max_num, num)
                except:
                    continue
            # 从最大序号+1开始保存
            sample_count[key] = max_num + 1
            filename = f"{key}_{sample_count[key]}.jpg"
            output_path = os.path.join(type_dir, filename)
            cv2.imwrite(output_path, piece_img)
            print(f"Saved sample {output_path}")
            sample_count[key] += 1
    return True 

def save_templates(use_grid_cut=True):
    """
    保存棋盘上的棋子模板
    :param use_grid_cut: 是否使用网格切割方式，默认为True
    """
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
        if use_grid_cut:
            print("使用网格切割方式保存模板...")
            if not save_chess_pieces_by_grid(image, x_array, y_array, template_dir):
                print("保存模板失败")
                return False
        else:
            print("使用霍夫圆检测方式保存模板...")
            if not save_chess_pieces(image, gray, x_array, y_array, template_dir):
                print("保存模板失败")
                return False
        
        return True
        
    except Exception as e:
        print(f"保存模板时出错: {str(e)}")
        return False