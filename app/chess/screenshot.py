import mss
import time
import cv2
import os
import sys
import threading
import numpy as np
from chess import process, engine
from chess.message import Message, MessageType
from chess.context import context

manual_trigger = False  # 添加手动触发标志

# 全局变量，用于存储倒计时区域检测到的最大轮廓
max_contour = None


def resource_path(relative_path):  
    """ 获取资源文件的绝对路径 """  
    if hasattr(sys, '_MEIPASS'):  
        # 如果是打包后的应用，则使用 sys._MEIPASS  
        return os.path.join(sys._MEIPASS, relative_path)  
    return os.path.join(os.path.abspath("./app/"), relative_path)

def detect_avatar_border(img, platform):
    """
    检测头像边框
    Args:
        img: 头像区域的图像
        platform: 平台名称 ('TT' 或 'JJ')
    Returns:
        bool: 是否检测到边框
    """
    global max_contour
    
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
                max_contour = max_contour_area
            return True
            
        # 检查当前最大轮廓是否在上一帧的轮廓内部
        if color_name == "黄色" and max_contour is not None:
            overlap_ratio = get_contour_overlap(max_contour_area, max_contour)
            if overlap_ratio > 0.95:
                return True
    
    return False

def check_turn_order(avatar_region):
    global manual_trigger
    if manual_trigger:
        manual_trigger = False  # 使用后立即重置
        print("手动触发识别")
        return True
    
    # 截取头像区域
    with mss.mss() as sct:
        avatar_screenshot = sct.grab(avatar_region)
        avatar_img = np.frombuffer(avatar_screenshot.bgra, np.uint8).reshape(avatar_screenshot.height, avatar_screenshot.width, 4)
        avatar_img = avatar_img[:, :, :3]  # 去掉 alpha 通道
        
        # 保存临时图片用于预测
        temp_path = "app/images/board/temp_avatar.png"
        cv2.imwrite(temp_path, avatar_img)
        
        # 使用模型预测
        try:
            result = context.countdown_predictor.predict(temp_path)
            # print(f"倒计时预测结果: {result}")  
            return result['class_name'] == 'countdown' and result['confidence'] > 0.9
        except Exception as e:
            print(f"预测出错: {e}, 使用颜色检测")
            return detect_avatar_border(avatar_img, context.platform)


def capture_region(result_queue, stop_event): 
    """截图和分析函数"""
    # 启动象棋引擎
    engine.init_engine()    

    # 从上下文获取区域配置
    platform = context.get_platform(context.platform)
    board_region = platform.regions["board"]
    avatar_region = platform.regions["avatar"]

    got_move = False
    while not stop_event.is_set():
        if check_turn_order(avatar_region): # 我方进入计时状态
            # 还没有获得着法
            if not got_move:
                time.sleep(0.3) # 倒计时出现时,吃子,将军等动画还未完全结束,所以等片刻
                with mss.mss() as sct:  
                    # 截屏
                    screenshot = sct.grab(board_region) 
                    result_queue.put(Message(MessageType.STATUS, "轮到我方走棋..."))
                    
                    # 定义显示回调函数
                    def display_callback(msg):
                        result_queue.put(msg)
                        
                    move_text_msg, move_code_msg = process.main_process(screenshot, display_callback)
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
    board_region = {'left': x, 'top': y, 'width': width, 'height': height}  
    avatar_region = {'left': (x + width*0.75), 'top': y + height, 'width': width*0.25, 'height': height*0.3} 

    # 更新当前平台的区域配置
    platform = context.get_platform(context.platform)
    platform.regions = {
        "board": board_region,
        "avatar": avatar_region
    }
    
    # 保存配置
    context.save_config()

    # 截取两个区域的图片
    with mss.mss() as sct:
        # 截取棋盘区域
        board_screenshot = sct.grab(board_region)
        board_img = np.frombuffer(board_screenshot.bgra, np.uint8).reshape(board_screenshot.height, board_screenshot.width, 4)
        board_img = board_img[:, :, :3]  # 去掉 alpha 通道
        cv2.imwrite(resource_path('images/board/board.png'), board_img)

        # 截取头像区域
        avatar_screenshot = sct.grab(avatar_region)
        avatar_img = np.frombuffer(avatar_screenshot.bgra, np.uint8).reshape(avatar_screenshot.height, avatar_screenshot.width, 4)
        avatar_img = avatar_img[:, :, :3]  # 去掉 alpha 通道
        cv2.imwrite(resource_path('images/board/avatar.png'), avatar_img)

    return board_region

def trigger_manual_recognition():
    """触发一次手动识别"""
    global manual_trigger
    manual_trigger = True
    

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
    # print(f"轮廓1总像素数: {total_pixels1}")
    # print(f"轮廓2总像素数: {total_pixels2}")
    # print(f"重叠像素数: {overlap_pixels}")
    # print(f"重叠像素比例: {overlap_ratio:.2%}")
    
    return overlap_ratio


#================= 头像截图 , 用于训练模型 =================
capture_avatar_thread = None
stop_capture = threading.Event()

def capture_avatar():
    """捕获头像区域"""
    global capture_avatar_thread, stop_capture
    
    # 如果线程已经在运行，则停止它
    if capture_avatar_thread and capture_avatar_thread.is_alive():
        stop_capture.set()
        capture_avatar_thread.join()
        stop_capture.clear()
        print("停止截图")
        return
    
    # 创建新线程执行截图
    capture_avatar_thread = threading.Thread(target=_capture_avatar_loop)
    capture_avatar_thread.start()
    print("开始截图")

def _capture_avatar_loop():
    """截图循环"""
    # 获取当前平台的区域配置
    platform = context.get_platform(context.platform)
    avatar_region = platform.regions["avatar"]
    
    # 创建样本目录
    sample_dir = "app/images/jj_sample_timer"
    if not os.path.exists(sample_dir):
        os.makedirs(sample_dir)
    
    # 使用mss进行截图
    with mss.mss() as sct:
        while not stop_capture.is_set():
            try:
                avatar_screenshot = sct.grab(avatar_region)
                
                # 使用时间戳作为文件名
                timestamp = int(time.time() * 1000)
                filename = f"{sample_dir}/timer_{timestamp}.png"
                
                # 保存图片
                mss.tools.to_png(avatar_screenshot.rgb, avatar_screenshot.size, output=filename)
                print(f"保存倒计时截图: {filename}")
                
                # 等待0.5秒
                time.sleep(0.5)
            except Exception as e:
                print(f"截图出错: {e}")
                break

    