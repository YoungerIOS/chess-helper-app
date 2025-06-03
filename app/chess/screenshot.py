import pyautogui
import mss
import json
import time
import cv2
import subprocess
import queue
import os
import sys
import threading
import numpy as np
from chess import process, engine
from chess.message import Message, MessageType
from chess.context import context

engine_param_lock = threading.Lock()
engine_param = None
manual_trigger = False  # 添加手动触发标志

# 全局变量，用于存储上一次检测到的最大轮廓信息（点集）
last_max_contour = None

def resource_path(relative_path):  
    """ 获取资源文件的绝对路径 """  
    if hasattr(sys, '_MEIPASS'):  
        # 如果是打包后的应用，则使用 sys._MEIPASS  
        return os.path.join(sys._MEIPASS, relative_path)  
    return os.path.join(os.path.abspath("./app/"), relative_path)

def decide_side(avatar_region):
    global manual_trigger
    if manual_trigger:
        manual_trigger = False  # 使用后立即重置
        return True
    
    # 截取头像区域
    with mss.mss() as sct:
        avatar_screenshot = sct.grab(avatar_region)
        avatar_img = np.frombuffer(avatar_screenshot.bgra, np.uint8).reshape(avatar_screenshot.height, avatar_screenshot.width, 4)
        avatar_img = avatar_img[:, :, :3]  # 去掉 alpha 通道
    
    # 从上下文对象获取平台设置
    platform = context.platform
    
    # 根据平台选择对应的检测函数
    if platform == 'TT':
        return detect_avatar_border_tt(avatar_img)
    else:  # JJ平台
        return detect_avatar_border_jj(avatar_img)


def get_contour_overlap(contour1, contour2):
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
    
    # 打印调试信息
    print(f"轮廓1总像素数: {total_pixels1}")
    print(f"轮廓2总像素数: {total_pixels2}")
    print(f"重叠像素数: {overlap_pixels}")
    print(f"重叠像素比例: {overlap_ratio:.2%}")
    
    return overlap_ratio


def detect_avatar_border_tt(img):
    """
    检测TT平台头像边框
    Args:
        img: 头像区域的图像
    Returns:
        bool: 是否检测到边框
    """
    global last_max_contour
    
    # 转换为HSV颜色空间
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    # TT平台：绿色(前期) -> 黄色(中期)
    color_ranges = [
        # 绿色范围
        (np.array([35, 50, 50]), np.array([85, 255, 255]), "绿色"),
        # 黄色范围
        (np.array([20, 100, 100]), np.array([40, 255, 255]), "黄色")
    ]
    print("检测TT平台边框: 绿色->黄色")
    
    # 按顺序检测每个颜色
    for lower, upper, color_name in color_ranges:
        # 创建当前颜色的掩码
        mask = cv2.inRange(hsv, lower, upper)
        
        # 形态学操作去除噪点
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        
        # 查找轮廓
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        print(f"检测{color_name}边框，找到 {len(contours)} 个轮廓")
        
        # 遍历所有轮廓
        found_valid = False
        max_perimeter = 0.0
        contour_with_max_perimeter = None
        
        for i, contour in enumerate(contours):
            # 计算轮廓周长
            perimeter = cv2.arcLength(contour, True)
            print(f"轮廓 {i+1} 周长: {perimeter}")
            
            # 找出周长最大的轮廓
            if perimeter > max_perimeter:
                max_perimeter = perimeter
                contour_with_max_perimeter = contour
            
            found_valid = True
        
        # 如果找到有效轮廓，进行判断
        if found_valid:
            # 检查是否有周长大于150的轮廓
            if max_perimeter > 150:
                print(f"找到{color_name}边框且周长大于150，判定为倒计时状态")
                # 只在找到周长大于阈值的轮廓时更新last_max_contour
                last_max_contour = contour_with_max_perimeter
                return True
            else:
                # 检查当前最大轮廓是否在上一帧的轮廓内部
                if last_max_contour is not None:
                    # 计算两个轮廓的重叠程度
                    overlap_ratio = get_contour_overlap(contour_with_max_perimeter, last_max_contour)
                    print(f"当前轮廓与最大轮廓的重叠程度: {overlap_ratio:.2%}")
                    
                    if overlap_ratio > 0.95:  # 如果重叠程度大于95%
                        print(f"当前{color_name}轮廓与最大轮廓重叠程度大于95%，判定为倒计时状态")
                        last_max_contour = contour_with_max_perimeter
                        return True
                    else:
                        print(f"当前{color_name}轮廓与最大轮廓重叠程度不足，继续检测下一个颜色")
                        continue
                else:
                    print(f"没有最大轮廓信息，继续检测下一个颜色")
                    continue
                    
        else:
            print(f"未找到{color_name}边框，继续检测下一个颜色")
            continue
    
    print("所有颜色都未检测到有效轮廓，判定为非倒计时状态")
    return False

def detect_avatar_border_jj(img):
    """
    检测JJ平台头像边框
    Args:
        img: 头像区域的图像
    Returns:
        bool: 是否检测到边框
    """
    global last_max_contour
    
    # 转换为HSV颜色空间
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    # JJ平台：黄色(前期) -> 红色(末期)
    color_ranges = [
        # 黄色范围
        (np.array([20, 100, 100]), np.array([40, 255, 255]), "黄色"),
        # 红色范围
        (np.array([0, 100, 100]), np.array([10, 255, 255]), "红色"),
        (np.array([170, 100, 100]), np.array([180, 255, 255]), "红色")
    ]
    print("检测JJ平台边框: 黄色->红色")
    
    # 按顺序检测每个颜色
    for lower, upper, color_name in color_ranges:
        # 创建当前颜色的掩码
        mask = cv2.inRange(hsv, lower, upper)
        
        # 形态学操作去除噪点
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        
        # 查找轮廓
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        print(f"检测{color_name}边框，找到 {len(contours)} 个轮廓")
        
        # 遍历所有轮廓
        found_valid = False
        max_area = 0.0
        contour_with_max_area = None
        
        for i, contour in enumerate(contours):
            # 计算轮廓面积
            area = cv2.contourArea(contour)
            print(f"轮廓 {i+1} 面积: {area}")
            
            # 找出面积最大的轮廓
            if area > max_area:
                max_area = area
                contour_with_max_area = contour
            
            found_valid = True
        
        # 如果找到有效轮廓，进行判断
        if found_valid:
            # 根据颜色使用不同的判断标准
            if color_name == "黄色":
                # 黄色使用原有的判断流程
                if max_area > 250:
                    print(f"找到{color_name}边框且面积大于250，判定为倒计时状态")
                    print(f"轮廓面积: {max_area:.2f}")
                    last_max_contour = contour_with_max_area
                    return True
                else:
                    # 检查当前最大轮廓是否在上一帧的轮廓内部
                    if last_max_contour is not None:
                        # 计算两个轮廓的重叠程度
                        overlap_ratio = get_contour_overlap(contour_with_max_area, last_max_contour)
                        print(f"当前轮廓与最大轮廓的重叠程度: {overlap_ratio:.2%}")
                        
                        if overlap_ratio > 0.95:  # 如果重叠程度大于95%
                            print(f"当前{color_name}轮廓与最大轮廓重叠程度大于95%，判定为倒计时状态")
                            last_max_contour = contour_with_max_area
                            return True
                        else:
                            print(f"当前{color_name}轮廓与最大轮廓重叠程度不足，继续检测下一个颜色")
                            continue
                    else:
                        print(f"没有最大轮廓信息，继续检测下一个颜色")
                        continue
            else:  # 红色
                # 红色只需要面积大于50
                if max_area > 50:
                    print(f"找到红色边框且面积大于50，返回True")
                    print(f"轮廓面积: {max_area:.2f}")
                    last_max_contour = contour_with_max_area
                    return True
                else:
                    print(f"红色轮廓面积不足50，返回False")
                    continue
                    
        else:
            print(f"未找到黄色边框，继续检测红色边框")
            continue
    
    print("两个颜色都未检测到有效轮廓，返回False")
    return False

def display_notification(title, subtitle, message):  
    script = f'''  
    display notification "{message}" with title "{title}" subtitle "{subtitle}"  
    '''  
    subprocess.run(['osascript', '-e', script])  
  

def update_params(new_value):
    global engine_param
    with engine_param_lock:
        engine_param = new_value

def capture_region(result_queue, stop_event): 
    """截图和分析函数"""
    # 启动象棋引擎
    global engine_param
    engine.init_engine()

    # 读取存在本地的坐标 
    file_path = resource_path("json/coordinates.json")
    with open(file_path, 'r') as file:
        data = json.load(file)
        board_region = data['region1']
        avatar_region = data['region2']

    got_move = False
    while not stop_event.is_set():
        if decide_side(avatar_region): # 我方进入计时状态
            # 还没有获得着法
            if not got_move:
                time.sleep(1) # 由于对方棋子落下的前一瞬间我方倒计时已经出现,可能会截到半途中的图,所以等片刻
                with mss.mss() as sct:  
                    # 截屏
                    screenshot = sct.grab(board_region) 
                    result_queue.put(Message(MessageType.STATUS, "轮到我方走棋..."))
                    
                    # 识别图片
                    with engine_param_lock:
                        print(f"Engine param is: {engine_param}")
                        # 定义显示回调函数
                        def display_callback(msg):
                            result_queue.put(msg)
                            
                        move_text_msg, move_code_msg = process.main_process(screenshot, engine_param, display_callback)
                        print(f"------>>{move_text_msg.content}, {move_code_msg.content}")
                        if move_code_msg.content:  # 如果有着法代码
                            result_queue.put(move_code_msg)  # 先发送着法代码用于显示箭头
                            result_queue.put(move_text_msg)  # 再发送中文着法用于显示文本
                        else:  # 如果发生错误
                            result_queue.put(move_text_msg)  # 发送错误消息
                            result_queue.put(move_code_msg)  # 发送空的棋盘显示消息

                    got_move = True
        else:
            got_move = False
        time.sleep(0.5)

def get_position(x, y):  
    # 确定截图区域  
    width = 375  
    height = 415  
    region1 = {'left': x, 'top': y, 'width': width, 'height': height}  
    region2 = {'left': (x + width*0.75), 'top': y + height, 'width': width*0.25, 'height': height*0.3} 

    # 保存本地
    save_path = resource_path("json/coordinates.json")  
    data = {
        'region1': region1,
        'region2': region2
    }
    with open(save_path, 'w') as file:
        json.dump(data, file)

    # 截取两个区域的图片
    with mss.mss() as sct:
        # 截取棋盘区域
        board_screenshot = sct.grab(region1)
        board_img = np.frombuffer(board_screenshot.bgra, np.uint8).reshape(board_screenshot.height, board_screenshot.width, 4)
        board_img = board_img[:, :, :3]  # 去掉 alpha 通道
        cv2.imwrite(resource_path('images/board/board.png'), board_img)

        # 截取头像区域
        avatar_screenshot = sct.grab(region2)
        avatar_img = np.frombuffer(avatar_screenshot.bgra, np.uint8).reshape(avatar_screenshot.height, avatar_screenshot.width, 4)
        avatar_img = avatar_img[:, :, :3]  # 去掉 alpha 通道
        cv2.imwrite(resource_path('images/board/avatar.png'), avatar_img)

    return region1

def trigger_manual_recognition():
    """触发一次手动识别"""
    global manual_trigger
    manual_trigger = True
    
