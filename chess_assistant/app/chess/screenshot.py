import pyautogui
import mss
import json
import time
import os
import cv2
import subprocess
import queue
import threading
import numpy as np
from chess import process, engine

engine_param_lock = threading.Lock()
engine_param = None

def check_color(region, ranges, threshold):  
    # 截取屏幕区域  
        with mss.mss() as sct:  
            # mss.grab()返回的是 BGRA 格式的原始数据 
            screenshot = sct.grab(region) 
            # 转成大小确定的图片对象
            img_np = np.frombuffer(screenshot.bgra, np.uint8).reshape(screenshot.height, screenshot.width, 4)  
            img_np = img_np[:, :, :3]  # 去掉 alpha 通道  
  
            # 保存截图（可选）  
            # cv2.imwrite('./chess_assistant/app/uploads/rect_region.png', img_np)  
  
            # 转换到 HSV 颜色空间  
            hsv_img = cv2.cvtColor(img_np, cv2.COLOR_BGR2HSV)  
  
            # 初始化黄色掩码  
            color_mask = np.zeros_like(hsv_img[:, :, 0])  
  
            # 遍历每个黄色范围并更新掩码  
            for lower, upper in ranges:  
                lower = np.array(lower, dtype=np.uint8)  
                upper = np.array(upper, dtype=np.uint8)  
                color_mask_temp = cv2.inRange(hsv_img, lower, upper)  
                color_mask = cv2.bitwise_or(color_mask, color_mask_temp)  
  
            # 形态学操作去除噪点  
            kernel = np.ones((5, 5), np.uint8)  
            color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_OPEN, kernel)  
  
            # 计算黄色区域的像素总数  
            total = cv2.countNonZero(color_mask)  
            # print(f"目标颜色面积为{total}")  
  
            if total > threshold:  
                return True
            else:    
                return False 
    
def decide_side(rect_region):
    # 绿色、黄色和红色的 HSV 值范围
    green_ranges = [  
        ([35, 50, 50], [75, 255, 255]),  # 浅绿色  
        ([70, 50, 50], [100, 255, 255]),  # 中等绿色  
        ([120, 50, 50], [179, 255, 255])  # 深绿色（注意HSV中色相是循环的，所以179之后是0）  
    ] 
    yellow_ranges = [  
        ([20, 100, 100], [40, 255, 255]),  # 浅黄色  
        ([40, 100, 100], [60, 255, 255]),  # 中等黄色  
        # ([55, 100, 100], [75, 255, 255])   # 深黄色  
    ] 
    
    my_side = False
    my_side = check_color(rect_region, green_ranges, 600)
    if not my_side:
        my_side = check_color(rect_region, yellow_ranges, 500)
    if my_side:
        # print("检测到目标颜色，我方正在倒计时")
        return True
    else:
        # print("未检测到目标颜色")
        return False
     
def display_notification(title, subtitle, message):  
    script = f'''  
    display notification "{message}" with title "{title}" subtitle "{subtitle}"  
    '''  
    subprocess.run(['osascript', '-e', script])  
  
def on_press(key):  
    try:  
        if key.char == 's':  # 如果按下的是s键
            print('按下了S键')
            return False  # 停止监听  
    except AttributeError:  
        pass  # 忽略非字符按键（如功能键） 

def update_params(new_value):
    global engine_param
    with engine_param_lock:
        engine_param = new_value

def capture_region(result_queue, stop_event): 
    # 启动象棋引擎
    global engine_param
    engine.init_engine()

    # 读取存在本地的坐标 
    with open('./chess_assistant/app/json/coordinates.json', 'r') as file:
        data = json.load(file)
        board_region = data['region1']
        timer_region = data['region2']

    got_move = False
    while not stop_event.is_set():
        if decide_side(timer_region): # 我方进入计时状态
            # 还没有获得着法
            if not got_move:
                time.sleep(1) # 由于对方棋子落下的前一瞬间我方倒计时已经出现,可能会截到半途中的图,所以等片刻
                with mss.mss() as sct:  
                    # 截屏
                    screenshot = sct.grab(board_region) 
                    result_queue.put("引擎正在计算...")
                    # 识别图片
                    with engine_param_lock:
                        print(f"Engine param is: {engine_param}")
                        result = process.main_process(screenshot, engine_param)
                        print(f"------>>{result}")
                        if len(result) == 4:
                            result_queue.put(result)
                            # display_notification(result, "", "")
                            got_move = True
                        else:
                            got_move = False
        else:
            got_move = False
        time.sleep(0.5)

def get_position():  
    print(f"工作路径:{os.getcwd()}") # 如果相对路径出问题,就看看cwd的打印,以这里为基点配置相对路径
    
    # 等待用户将鼠标移动到截图区域的左上角位置  
    # print("等待中...") 

    # 捕获当前鼠标位置
    click_pos = pyautogui.position() 
    width = 375  
    height = 415  
    # 确定截图区域  
    region1 = {'left': click_pos[0], 'top': click_pos[1], 'width': width, 'height': height}  
    region2 = {'left': (click_pos[0]+305), 'top': (click_pos[1]+430), 'width': 70, 'height': 70} 

    # 保存本地
    save_path = './chess_assistant/app/json/coordinates.json'  
    data = {
        'region1': region1,
        'region2': region2
    }
    with open(save_path, 'w') as file:
        json.dump(data, file)

    # 通知
    # display_notification("棋盘定位完毕!", "切勿移动游戏界面!", "请开始你的游戏...")

    return region1
    

