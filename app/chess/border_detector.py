import cv2
import numpy as np
from typing import Tuple, List, Optional
import time

class BorderDetector:
    """边框检测器类，支持TT平台的矩形边框和JJ平台的圆弧边框检测"""
    
    def __init__(
            self, 
            arc_area_threshold: int = 300, 
            arc_radius_threshold: float = 25.0, 
            arc_border_line_width: int = 5,
            rect_area_threshold: int = 300,
            rect_height_threshold: int = 40,
            rect_border_line_width: int = 5
            ):
        
        self.arc_area_threshold = arc_area_threshold #圆弧面积阈值，默认300
        self.arc_radius_threshold = arc_radius_threshold #圆弧半径阈值，默认25.0
        self.arc_border_line_width = arc_border_line_width #圆弧线宽，默认5
        self.rect_area_threshold = rect_area_threshold #矩形面积阈值，默认300
        self.rect_height_threshold = rect_height_threshold #矩形高度阈值，默认40
        self.rect_border_line_width = rect_border_line_width #矩形线宽，默认5
        
        self.upper_max_rect_border = None
        self.lower_max_rect_border = None
        self.upper_max_arc_border = None
        self.lower_max_arc_border = None
        
    

    
    def has_border(self, screenshot, platform: str, avatar: str) -> bool:
        """
        检测头像是否有边框（倒计时状态）
        根据头像截图尺寸动态调整检测阈值，确保在不同分辨率设备上都能正常工作
        """
        # 计算缩放比例：当前头像截图尺寸 / 标准头像尺寸
        # 标准头像尺寸：72x72（与BoardLocator中的base_sizes['square_size']保持一致）
        base_square_size = 72
        current_size = min(screenshot.width, screenshot.height)
        scale_factor = current_size / base_square_size
        
        # 限制缩放范围，避免极端情况
        scale_factor = max(0.5, min(2.5, scale_factor))
        
        # 动态计算本次检测的阈值参数
        # 长度类阈值：乘以缩放比例
        # 面积类阈值：乘以缩放比例的平方
        # 线宽类阈值：乘以缩放比例，但至少为1
        arc_radius_threshold_s = self.arc_radius_threshold * scale_factor
        arc_border_line_width_s = max(1, int(round(self.arc_border_line_width * scale_factor)))
        rect_height_threshold_s = max(1, int(round(self.rect_height_threshold * scale_factor)))
        rect_border_line_width_s = max(1, int(round(self.rect_border_line_width * scale_factor)))
        
        # 面积阈值需要平方缩放
        arc_area_threshold_s = int(round(self.arc_area_threshold * (scale_factor ** 2)))
        rect_area_threshold_s = int(round(self.rect_area_threshold * (scale_factor ** 2)))
        
        # 调试信息
        # if avatar == "lower":  # 只在下头像打印，避免日志过多
            # print(f"头像{avatar} - 尺寸: {screenshot.width}x{screenshot.height}, 缩放因子: {scale_factor:.3f}")
            # print(f"JJ圆弧 - 半径阈值: {arc_radius_threshold_s:.1f}, 线宽: {arc_border_line_width_s}, 面积阈值: {arc_area_threshold_s}")
            # print(f"TT矩形 - 高度阈值: {rect_height_threshold_s}, 线宽: {rect_border_line_width_s}, 面积阈值: {rect_area_threshold_s}")

        if platform == "TT":
            if avatar == "upper":
                if self.upper_max_rect_border is None:
                    result, border_data = self._detect_rectangle_border(
                        screenshot, 
                        rect_area_threshold_s, 
                        rect_height_threshold_s, 
                        rect_border_line_width_s
                    )
                    if result and border_data is not None:
                        self.upper_max_rect_border = border_data
                    return result
                else:
                    return self._is_color_enough_in_rectangle_border(screenshot, self.upper_max_rect_border, avatar)
            elif avatar == "lower":
                if self.lower_max_rect_border is None:
                    result, border_data = self._detect_rectangle_border(
                        screenshot, 
                        rect_area_threshold_s, 
                        rect_height_threshold_s, 
                        rect_border_line_width_s
                    )
                    if result and border_data is not None:
                        self.lower_max_rect_border = border_data
                    return result
                else:
                    return self._is_color_enough_in_rectangle_border(screenshot, self.lower_max_rect_border, avatar)
                
        elif platform == "JJ":
            if avatar == "upper":
                if self.upper_max_arc_border is None:
                    result, border_data = self._detect_arc_border(
                        screenshot, 
                        arc_area_threshold_s, 
                        arc_radius_threshold_s, 
                        arc_border_line_width_s
                    )
                    if result and border_data is not None:
                        self.upper_max_arc_border = border_data
                    return result
                else:
                    return self._is_color_enough_in_arc_border(screenshot, self.upper_max_arc_border, avatar)
            elif avatar == "lower":
                if self.lower_max_arc_border is None:
                    result, border_data = self._detect_arc_border(
                        screenshot, 
                        arc_area_threshold_s, 
                        arc_radius_threshold_s, 
                        arc_border_line_width_s
                    )
                    if result and border_data is not None:
                        self.lower_max_arc_border = border_data
                    return result
                else:
                    return self._is_color_enough_in_arc_border(screenshot, self.lower_max_arc_border, avatar)
        else:
            raise ValueError(f"不支持的平台: {platform}")
    
    def _is_color_enough_in_rectangle_border(self, screenshot, border_data, avatar) -> bool:
        """
        判断颜色在矩形边框环内的填充比例是否足够
        使用轮廓拟合方案：计算颜色轮廓长度与边框环中心线周长比较
        Args:
            screenshot: 截图对象
            border_data: 矩形边框环数据 (x, y, w, h, inner_x, inner_y, inner_w, inner_h)
        Returns:
            bool: 颜色填充比例是否足够
        """
        try:
            # 将截图转换为OpenCV格式
            img_cv = np.frombuffer(screenshot.bgra, np.uint8).reshape(screenshot.height, screenshot.width, 4)[:, :, :3]
            
            # TT平台：矩形边框环
            x, y, w, h, inner_x, inner_y, inner_w, inner_h = border_data
            
            # 创建边框环掩码
            mask = np.zeros(img_cv.shape[:2], dtype=np.uint8)
            
            # 外矩形
            outer_rect = np.array([
                [x, y], [x + w, y], [x + w, y + h], [x, y + h]
            ], dtype=np.int32)
            
            # 内矩形
            inner_rect = np.array([
                [inner_x, inner_y], [inner_x + inner_w, inner_y],
                [inner_x + inner_w, inner_y + inner_h], [inner_x, inner_y + inner_h]
            ], dtype=np.int32)
            
            # 先填充外矩形
            cv2.fillPoly(mask, [outer_rect], 255)
            # 再挖空内矩形
            cv2.fillPoly(mask, [inner_rect], 0)
            
            # 计算边框环区域面积
            border_area = np.sum(mask == 255)
            if border_area == 0:
                print("TT平台矩形边框环 - 边框环面积为0，返回False")
                return False
            
            # 转换为HSV颜色空间
            hsv = cv2.cvtColor(img_cv, cv2.COLOR_BGR2HSV)
            
            # 提取绿色区域
            green_lower = np.array([35, 80, 80])
            green_upper = np.array([85, 255, 255])
            green_mask = cv2.inRange(hsv, green_lower, green_upper)
            
            # 提取黄色区域
            yellow_lower = np.array([20, 100, 100])
            yellow_upper = np.array([40, 255, 255])
            yellow_mask = cv2.inRange(hsv, yellow_lower, yellow_upper)
            
            # 仅保留边框环内部的颜色掩码
            green_in_ring_mask = ((mask == 255) & (green_mask == 255)).astype(np.uint8) * 255
            yellow_in_ring_mask = ((mask == 255) & (yellow_mask == 255)).astype(np.uint8) * 255
            
            # 计算颜色轮廓拟合长度（边框环内部）
            green_contours, _ = cv2.findContours(green_in_ring_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            yellow_contours, _ = cv2.findContours(yellow_in_ring_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # 对每个轮廓进行多边形拟合，减少噪点影响
            green_length = 0
            for contour in green_contours:
                if len(contour) > 3:  # 至少3个点才能形成多边形
                    # 使用Douglas-Peucker算法简化轮廓
                    epsilon = 0.02 * cv2.arcLength(contour, True)
                    approx = cv2.approxPolyDP(contour, epsilon, True)
                    # 计算拟合后的轮廓长度（不闭合）
                    green_length += cv2.arcLength(approx, False)
            
            yellow_length = 0
            for contour in yellow_contours:
                if len(contour) > 3:
                    epsilon = 0.02 * cv2.arcLength(contour, True)
                    approx = cv2.approxPolyDP(contour, epsilon, True)
                    yellow_length += cv2.arcLength(approx, False)
            
            # 轮廓周长通常比中心线周长大，除以2进行归一化
            green_length = green_length / 2
            yellow_length = yellow_length / 2
            
            # 计算边框环中心线的理论周长
            # 中心线是内外矩形之间的中点连线
            center_width = (w + inner_w) / 2
            center_height = (h + inner_h) / 2
            center_line_perimeter = 2 * (center_width + center_height)
            
            # 计算长度占比
            green_ratio = green_length / center_line_perimeter
            yellow_ratio = yellow_length / center_line_perimeter
            
            if avatar == "lower":
                print(f"头像{avatar} - 绿色长度: {green_length:.1f}, 占比: {green_ratio:.3f} - 黄色长度: {yellow_length:.1f}, 占比: {yellow_ratio:.3f} - 中心线周长: {center_line_perimeter:.1f}")
         
            # print(f"头像{avatar} - 绿色长度占比: {green_ratio:.3f}, 黄色长度占比: {yellow_ratio:.3f}")
            
            # 判断绿色长度占比是否大于0.35
            if green_ratio > 0.35:
                # print(f"TT平台矩形边框环 - 绿色长度占比: {green_ratio:.3f} > 0.35, 检测到边框")
                return True
            
            # 如果绿色长度占比不够，判断黄色长度占比是否大于0.12
            if yellow_ratio > 0.12:
                # print(f"TT平台矩形边框环 - 黄色长度占比: {yellow_ratio:.3f} > 0.12, 检测到边框")
                return True
            
            # print(f"TT平台矩形边框环 - 绿色长度占比: {green_ratio:.3f} ≤ 0.35, 黄色长度占比: {yellow_ratio:.3f} ≤ 0.12, 未检测到边框")
            return False
            
        except Exception as e:
            print(f"矩形边框颜色填充比例检测出错: {e}")
            return False
    
    def _is_color_enough_in_arc_border(self, screenshot, border_data, avatar) -> bool:
        """
        判断颜色在圆弧边框环内的填充是否足够（基于轮廓拟合长度 vs 环中心线周长）
        Args:
            screenshot: 截图对象
            border_data: 圆弧边框环数据 (center_x, center_y, outer_radius, inner_radius)
        Returns:
            bool: 颜色线条长度占比是否足够
        """
        try:
            # 将截图转换为OpenCV格式
            img_cv = np.frombuffer(screenshot.bgra, np.uint8).reshape(screenshot.height, screenshot.width, 4)[:, :, :3]
            
            center_x, center_y, outer_radius, inner_radius = border_data
            
            # 创建边框环掩码（圆环）
            mask = np.zeros(img_cv.shape[:2], dtype=np.uint8)
            cv2.circle(mask, (int(center_x), int(center_y)), int(outer_radius), 255, -1)
            cv2.circle(mask, (int(center_x), int(center_y)), max(0, int(inner_radius)), 0, -1)
            
            border_area = np.sum(mask == 255)
            if border_area == 0:
                print("JJ平台圆弧边框环 - 边框环面积为0，返回False")
                return False
            
            # 转换为HSV颜色空间
            hsv = cv2.cvtColor(img_cv, cv2.COLOR_BGR2HSV)
            
            # 提取黄色与红色区域
            yellow_lower = np.array([20, 100, 100])
            yellow_upper = np.array([40, 255, 255])
            yellow_mask = cv2.inRange(hsv, yellow_lower, yellow_upper)
            
            red_lower1 = np.array([0, 100, 100])
            red_upper1 = np.array([10, 255, 255])
            red_lower2 = np.array([170, 100, 100])
            red_upper2 = np.array([180, 255, 255])
            red_mask1 = cv2.inRange(hsv, red_lower1, red_upper1)
            red_mask2 = cv2.inRange(hsv, red_lower2, red_upper2)
            red_mask = cv2.bitwise_or(red_mask1, red_mask2)
            
            # 仅保留边框环内部的颜色掩码
            yellow_in_ring_mask = ((mask == 255) & (yellow_mask == 255)).astype(np.uint8) * 255
            red_in_ring_mask = ((mask == 255) & (red_mask == 255)).astype(np.uint8) * 255
            
            # 计算颜色轮廓拟合长度（环内）；周长/2 作为“线条长度”
            def fitted_length(mask_bin: np.ndarray) -> float:
                contours, _ = cv2.findContours(mask_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                total = 0.0
                for c in contours:
                    if len(c) > 3:
                        eps = 0.02 * cv2.arcLength(c, True)
                        approx = cv2.approxPolyDP(c, eps, True)
                        total += cv2.arcLength(approx, False)
                return total / 2.0
            
            yellow_length = fitted_length(yellow_in_ring_mask)
            red_length = fitted_length(red_in_ring_mask)
            
            # 计算圆环中心线周长：以中心半径 r_c = (outer + inner) / 2
            center_radius = (float(outer_radius) + float(inner_radius)) / 2.0
            center_circumference = 2.0 * np.pi * center_radius
            
            # 占比
            yellow_ratio = (yellow_length / center_circumference) if center_circumference > 0 else 0.0
            red_ratio = (red_length / center_circumference) if center_circumference > 0 else 0.0
            
            # 调试输出
            if avatar == "lower":
                print(f"JJ平台圆弧边框环 - 黄长度: {yellow_length:.1f}, 红长度: {red_length:.1f}, 中心线周长: {center_circumference:.1f}")
            
            # 判定（与矩形逻辑风格一致，阈值可按需微调）
            if yellow_ratio > 0.13:
                return True
            if red_ratio > 0.05:
                return True
            return False
        except Exception as e:
            print(f"圆弧边框颜色填充比例检测出错: {e}")
            return False
    
    def reset_border_cache(self, platform: str = None):
        """
        重置边框环缓存
        Args:
            platform: 平台名称，如果为None则重置所有平台
        """
        if platform is None or platform == "TT":
            self.upper_max_rect_border = None
            self.lower_max_rect_border = None
        if platform is None or platform == "JJ":
            self.upper_max_arc_border = None
            self.lower_max_arc_border = None
    
    def _detect_rectangle_border(self, screenshot, area_threshold, height_threshold, line_width) -> Tuple[bool, Optional[np.ndarray]]:
        """
        检测TT平台的矩形边框
        Args:
            screenshot: sct.grab()返回的截图对象
            area_threshold: 面积阈值（已根据头像尺寸缩放）
            height_threshold: 高度阈值（已根据头像尺寸缩放）
            line_width: 边框线宽（已根据头像尺寸缩放）
        Returns:
            Tuple[bool, Optional[np.ndarray]]: (是否检测到矩形边框, 边框环轮廓)
        """
        try:
            img_cv = np.frombuffer(screenshot.bgra, np.uint8).reshape(screenshot.height, screenshot.width, 4)[:, :, :3]
            
            # 阈值参数
            # area_threshold = 300  # 面积阈值
            # height_threshold = 40  # 高度阈值
        
            # 转HSV提取绿色区域
            hsv = cv2.cvtColor(img_cv, cv2.COLOR_BGR2HSV)
            lower_green = np.array([35, 80, 80])   # 根据实际绿色调节
            upper_green = np.array([85, 255, 255])
            mask = cv2.inRange(hsv, lower_green, upper_green)

            # 查找轮廓
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                print("TT矩形: 未找到任何绿色轮廓，返回False")
                return False, None

            # 选择外接矩形高度最大的轮廓
            max_height = 0
            cnt = None
            biggest_rect = None  # 保存选中的外接矩形信息
            
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < area_threshold:  # 过滤太小的轮廓
                    continue
                
                # 计算外接矩形高度
                x, y, w, h = cv2.boundingRect(contour)
                if h > max_height:
                    max_height = h 
                    cnt = contour
                    biggest_rect = (x, y, w, h)  # 保存外接矩形信息
            
            if cnt is None:
                print("TT矩形: 轮廓存在但面积均低于阈值，或未选到有效轮廓，返回False")
                return False, None
            
            # 检查最大高度是否满足阈值
            if max_height < height_threshold:
                print(f"TT矩形: 最大高度{max_height} < 阈值{height_threshold}，返回False")
                return False, None
            
            # 最大外接矩形
            x, y, w, h = biggest_rect
            center_x = x + w // 2

            # 多边形拟合
            epsilon = 0.01 * cv2.arcLength(cnt, True)  # 减小epsilon值，保留更多角点
            approx = cv2.approxPolyDP(cnt, epsilon, True)

            # 边框检测：形状、大小、位置三个维度
            result = False
            
            # 1. 形状判断：只在外接矩形左半边查找直角
            right_angle_count = 0
            right_angle_points = []
            
            # 计算外接矩形左半边的x坐标范围
            for i in range(len(approx)):
                p0, p1, p2 = approx[i-1][0], approx[i][0], approx[(i+1)%len(approx)][0]
                
                # 只检查左半边的角点
                if p1[0] <= center_x:
                    d1, d2 = (p0-p1).astype(float), (p2-p1).astype(float)
                    cos_val = abs(np.dot(d1, d2) / (np.linalg.norm(d1)*np.linalg.norm(d2)))
                    if cos_val < 0.15:  # 接近直角
                        # 检查两条边长至少达到高度阈值的一半
                        len1 = np.linalg.norm(d1)
                        len2 = np.linalg.norm(d2)
                        if len1 > 0.6*height_threshold and len2 > 0.6*height_threshold:
                            right_angle_count += 1
                            right_angle_points.append(p1)
            
            # 形状判断：左半边直角数量 >= 2
            if right_angle_count >= 1:
                result = True
                # 2. 大小判断：左半边最高和最低直角顶点的垂直距离 > threshold
                # 找到左半边最高和最低的直角顶点
                leftmost_points = sorted(right_angle_points, key=lambda p: p[1])  # 按y坐标排序
                highest_point = leftmost_points[0]  # y坐标最小的是最高的
                lowest_point = leftmost_points[-1]  # y坐标最大的是最低的
                
                vertical_distance = lowest_point[1] - highest_point[1]
                
                # 大小判断：垂直距离 > threshold
                if vertical_distance > height_threshold:
                    result = True

            if result:
                # 创建边框环：外接矩形 - 内矩形
                x, y, w, h = biggest_rect
                
                # 确保内矩形不会太小
                inner_x = x + line_width
                inner_y = y + line_width
                inner_w = max(1, w - 2 * line_width)  # 至少1像素宽
                inner_h = max(1, h - 2 * line_width)  # 至少1像素高
                
                # 返回边框环数据：外矩形和内矩形的坐标信息
                border_data = (x, y, w, h, inner_x, inner_y, inner_w, inner_h)
                print(f"TT矩形: 形状/大小判定通过，返回True。外矩形=({x},{y},{w},{h})，内矩形=({inner_x},{inner_y},{inner_w},{inner_h})")
                return True, border_data
            else:
                print(f"TT矩形: 形状或大小判定未通过，返回False,垂直距离: {vertical_distance};直角数量: {right_angle_count}")
                return False, None
            
        except Exception as e:
            print(f"TT矩形: 检测过程中出现异常: {e}，返回False")
            return False, None
    
    def _detect_arc_border(self, screenshot, area_threshold, radius_threshold, line_width) -> Tuple[bool, Optional[np.ndarray]]:
        """
        检测JJ平台的圆弧边框
        Args:
            screenshot: sct.grab()返回的截图对象
            area_threshold: 面积阈值（已根据头像尺寸缩放）
            radius_threshold: 半径阈值（已根据头像尺寸缩放）
            line_width: 边框线宽（已根据头像尺寸缩放）
        Returns:
            Tuple[bool, Optional[np.ndarray]]: (是否检测到圆弧边框, 边框环轮廓)
        """
        try:
            img_cv = np.frombuffer(screenshot.bgra, np.uint8).reshape(screenshot.height, screenshot.width, 4)[:, :, :3]
            
            # 转换为HSV颜色空间
            hsv = cv2.cvtColor(img_cv, cv2.COLOR_BGR2HSV)
            
            # 定义黄色和红色的HSV范围
            yellow_lower = np.array([20, 100, 100])
            yellow_upper = np.array([40, 255, 255])
            
            red_lower1 = np.array([0, 100, 100])
            red_upper1 = np.array([10, 255, 255])
            red_lower2 = np.array([170, 100, 100])
            red_upper2 = np.array([180, 255, 255])
            
            # 创建颜色掩码
            yellow_mask = cv2.inRange(hsv, yellow_lower, yellow_upper)
            red_mask1 = cv2.inRange(hsv, red_lower1, red_upper1)
            red_mask2 = cv2.inRange(hsv, red_lower2, red_upper2)
            red_mask = cv2.bitwise_or(red_mask1, red_mask2)
            
            # 合并黄色和红色掩码
            color_mask = cv2.bitwise_or(yellow_mask, red_mask)
            
            # 形态学操作，连接断开的区域
            kernel = np.ones((2, 2), np.uint8)
            color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_CLOSE, kernel)
            
            # 查找轮廓
            contours, _ = cv2.findContours(color_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # 过滤太小的轮廓
            filtered_contours = [c for c in contours if cv2.contourArea(c) > area_threshold]
            
            # 检测是否有圆弧
            for contour in filtered_contours:
                if len(contour) < 5:
                    continue
                
                try:
                    # 将轮廓转换为浮点数组
                    contour_points = contour.reshape(-1, 2).astype(np.float32)
                    
                    # 使用最小二乘法拟合圆
                    # 圆方程: (x-a)² + (y-b)² = r²
                    # 展开: x² + y² = 2ax + 2by + r² - a² - b²
                    
                    # 构建线性方程组 Ax = b
                    A = np.column_stack([
                        2 * contour_points[:, 0],  # 2x
                        2 * contour_points[:, 1],  # 2y
                        np.ones(len(contour_points))  # 1
                    ])
                    b = contour_points[:, 0]**2 + contour_points[:, 1]**2  # x² + y²
                    
                    # 求解最小二乘问题
                    center_params = np.linalg.lstsq(A, b, rcond=None)[0]
                    center_x, center_y = center_params[0], center_params[1]
                    radius = np.sqrt(center_params[2] + center_x**2 + center_y**2)
                    
                    if radius <= 0:
                        continue
                    
                    # 计算拟合误差和最大距离
                    fitted_circle = (contour_points[:, 0] - center_x)**2 + (contour_points[:, 1] - center_y)**2
                    actual_radius = np.sqrt(fitted_circle)
                    error = np.mean(np.abs(actual_radius - radius)) / radius # 拟合误差
                    
                    # 计算轮廓点到圆心的最大距离，用于确定外圆半径
                    max_distance = np.max(actual_radius)
                    min_distance = np.min(actual_radius)
                    
                    # 判断是否为圆弧
                    if error < 0.2 and radius > radius_threshold: 
                        print(f"检测到圆弧 - 圆心: ({center_x:.1f}, {center_y:.1f}), 半径: {radius:.1f}, 拟合误差: {error:.4f}")
                        
                        # 创建圆形边框环：外圆 - 内圆
                        # 使用基于实际轮廓距离的稳定方法
                        # 外圆半径使用最大距离，确保覆盖所有轮廓点
                        outer_radius = max_distance + 1  # 加1像素确保完全覆盖
                        # 内圆半径基于外圆半径和线宽
                        inner_radius = max(0, outer_radius - line_width)
                        
                        # 返回圆形边框环数据：圆心坐标和半径信息
                        border_data = (center_x, center_y, outer_radius, max(0, inner_radius))
                        return True, border_data
                        
                except Exception:
                    continue
            
            return False, None
            
        except Exception:
            return False, None
        
    def _draw_border_ring(self, image, border_data, color, platform_type, line_width=1):
        """
        绘制边框环轮廓
        Args:
            image: 要绘制的图像
            border_data: 边框数据
            color: 颜色 (B, G, R)
            platform_type: 平台类型 ("TT" 或 "JJ")
            line_width: 线宽，默认1
        """
        if platform_type == "TT":
            # 矩形边框环
            x, y, w, h, inner_x, inner_y, inner_w, inner_h = border_data
            
            # 绘制外矩形轮廓
            cv2.rectangle(image, (x, y), (x + w, y + h), color, line_width)
            
            # 绘制内矩形轮廓
            if inner_w > 0 and inner_h > 0:
                cv2.rectangle(image, (inner_x, inner_y), (inner_x + inner_w, inner_y + inner_h), color, line_width)
            
        elif platform_type == "JJ":
            # 圆形边框环
            center_x, center_y, outer_radius, inner_radius = border_data
            
            # 绘制外圆轮廓
            cv2.circle(image, (int(center_x), int(center_y)), int(outer_radius), color, line_width)
            
            # 绘制内圆轮廓
            if inner_radius > 0:
                cv2.circle(image, (int(center_x), int(center_y)), int(inner_radius), color, line_width)


# 直接在模块级别创建BorderDetector实例，确保缓存不被重置
_border_detector = BorderDetector()

# 便捷函数直接使用模块级实例
def has_border(screenshot, platform: str, avatar: str) -> bool:

    return _border_detector.has_border(screenshot, platform, avatar)

# 如果需要重置缓存，提供重置函数
def reset_border_cache(platform: str = None):
    """重置边框环缓存"""
    _border_detector.reset_border_cache(platform)


# 使用示例
if __name__ == "__main__":
    # 测试图片路径
    test_image_path = "app/images/board/temp_avatar_lower4.png"
    
    try:
        # 读取测试图片
        test_image = cv2.imread(test_image_path)
        if test_image is None:
            print(f"无法读取图片: {test_image_path}")
            exit(1)
        
        # 转换为BGRA格式模拟sct.grab()的输出
        test_image_bgra = cv2.cvtColor(test_image, cv2.COLOR_BGR2BGRA)
        
        # 创建模拟的screenshot对象
        class MockScreenshot:
            def __init__(self, img_array):
                self.bgra = img_array
                self.height, self.width = img_array.shape[:2]
                self.size = (self.width, self.height)
        
        mock_screenshot = MockScreenshot(test_image_bgra)
        
        # 创建检测器
        detector = BorderDetector()
        
        # 直接使用原始截图
        raw_shot = mock_screenshot
        raw_bgr = cv2.cvtColor(raw_shot.bgra, cv2.COLOR_BGRA2BGR)
        
        # 创建可视化图片副本（原始尺寸上绘制）
        vis_image = raw_bgr.copy()
        
        # 测试TT平台（矩形检测）
        print("=== TT平台矩形边框检测 ===")
        result_tt, border_ring_tt = detector._detect_rectangle_border(
            raw_shot, 
            detector.rect_area_threshold, 
            detector.rect_height_threshold, 
            detector.rect_border_line_width
        )
        print(f"TT平台检测结果: {'有边框' if result_tt else '无边框'}")
        if result_tt and border_ring_tt is not None:
            # 绘制TT平台边框环
            detector._draw_border_ring(vis_image, border_ring_tt, (0, 255, 0), "TT")
            x, y, w, h, inner_x, inner_y, inner_w, inner_h = border_ring_tt
            print(f"TT平台边框环 - 外矩形: ({x},{y},{w},{h}), 内矩形: ({inner_x},{inner_y},{inner_w},{inner_h})")
        
        # 测试JJ平台（圆弧检测）
        print("=== JJ平台圆弧边框检测 ===")
        result_jj, border_ring_jj = detector._detect_arc_border(
            raw_shot, 
            detector.arc_area_threshold, 
            detector.arc_radius_threshold, 
            detector.arc_border_line_width
        )
        print(f"JJ平台检测结果: {'有边框' if result_jj else '无边框'}")
        
        if result_jj and border_ring_jj is not None:
            # 绘制JJ平台边框环
            detector._draw_border_ring(vis_image, border_ring_jj, (0, 0, 255), "JJ")
            center_x, center_y, outer_radius, inner_radius = border_ring_jj
            print(f"JJ平台边框环 - 圆心: ({center_x:.1f},{center_y:.1f}), 外半径: {outer_radius:.1f}, 内半径: {inner_radius:.1f}")
        
        # 显示结果
        print("\n=== 可视化结果 ===")
        print("绿色: TT平台矩形边框环")
        print("红色: JJ平台圆弧边框环")
        
        # 保存可视化结果（标准尺寸）
        output_path = "app/images/board/border_detection_result.png"
        cv2.imwrite(output_path, vis_image)
        print(f"可视化结果已保存到: {output_path}")
        
        # 创建单独的边框环可视化图
        border_only_image = np.zeros_like(vis_image)
        
        if result_tt and border_ring_tt is not None:
            # 绘制TT平台边框环
            detector._draw_border_ring(border_only_image, border_ring_tt, (0, 255, 0), "TT")
            print(f"TT平台边框环已绘制")
        
        if result_jj and border_ring_jj is not None:
            # 绘制JJ平台边框环
            detector._draw_border_ring(border_only_image, border_ring_jj, (0, 0, 255), "JJ")
            print(f"JJ平台边框环已绘制")
        
        # 保存边框环专用图
        border_output_path = "app/images/board/border_rings_only.png"
        cv2.imwrite(border_output_path, border_only_image)
        print(f"边框环专用图已保存到: {border_output_path}")
        
        # 显示图片（如果有GUI环境）
        try:
            cv2.imshow('Border Detection Result (standardized)', vis_image)
            cv2.imshow('Border Rings Only (standardized)', border_only_image)
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        except:
            print("无法显示图片窗口，请查看保存的结果图片")
        
    except FileNotFoundError:
        print(f"图片文件不存在: {test_image_path}")
    except Exception as e:
        print(f"处理图片时发生错误: {e}")
