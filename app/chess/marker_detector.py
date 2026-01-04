import cv2
import numpy as np
from app.chess.message import TurnState

class MarkerDetector:
    def __init__(self):
        pass

    def detect_markers(self, img_gray, x_array, y_array):
        """
        检测棋盘上的"最新移动标记"（白点）。
        
        Args:
            img_gray: 棋盘图像 (Gray numpy array, 800宽)
            x_array, y_array: 网格坐标列表 (像素值)
            
        Returns:
            List of tuples [(row, col), ...]: 检测到的标记的网格坐标列表。
        """
        if img_gray is None:
            return []
        if not x_array or not y_array:
            return []
            
        # 高阈值二值化以分离高亮标记（白点）
        # 输入已经是预处理过的 800宽 灰度图
        # 提高阈值以过滤掉亮度较低的干扰点（原200 -> 220）
        _, thresh = cv2.threshold(img_gray, 220, 255, cv2.THRESH_BINARY)
        
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # 2. 过滤
        if len(x_array) < 9 or len(y_array) < 10:
            return []
            
        cell_w = (x_array[-1] - x_array[0]) / 8.0
        
        h, w = img_gray.shape[:2]
        
        # 用户要求的宽度范围 0.01-0.1
        min_diam = w * 0.01
        max_diam = w * 0.1
        
        min_area = np.pi * (min_diam / 2)**2
        max_area = np.pi * (max_diam / 2)**2
        
        detected_grid_coords = []
        
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if min_area < area < max_area:
                perimeter = cv2.arcLength(cnt, True)
                if perimeter == 0: continue
                circularity = 4 * np.pi * (area / (perimeter * perimeter))
                
                # 提高圆度阈值以过滤掉十字形/折线形的棋盘装饰（原0.6 -> 0.75）
                if circularity > 0.75:
                    M = cv2.moments(cnt)
                    if M["m00"] != 0:
                        cx = int(M["m10"] / M["m00"])
                        cy = int(M["m01"] / M["m00"])
                        
                        # 使用用户要求的逻辑：分别查找最近的 x 和最近的 y
                        dist_x = [abs(cx - x) for x in x_array]
                        min_dist_x = min(dist_x)
                        c = dist_x.index(min_dist_x)
                        
                        dist_y = [abs(cy - y) for y in y_array]
                        min_dist_y = min(dist_y)
                        r = dist_y.index(min_dist_y)
                        
                        # 使用 cell_w / 2 * 0.6 作为安全边距判断是否"在网格上"
                        if min_dist_x < cell_w * 0.6 and min_dist_y < (cell_w if 'cell_h' not in locals() else cell_h) * 0.6:
                             detected_grid_coords.append((r, c))
                                    
        return detected_grid_coords

