import cv2
import numpy as np
import os
import time
from scipy import spatial

def compare_images(img1, img2, debug_dir=None):
    """
    比较两张图片的相似度，使用多种特征组合
    Args:
        img1: 第一张图片
        img2: 第二张图片
        debug_dir: 调试图片保存目录
    Returns:
        float: 相似度分数 (0-1)
        dict: 调试信息
    """
    if img1 is None or img2 is None:
        return 0, {}
    
    # 确保图片大小一致
    img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))
    
    # 1. SIFT特征匹配
    sift = cv2.SIFT_create()
    kp1, des1 = sift.detectAndCompute(img1, None)
    kp2, des2 = sift.detectAndCompute(img2, None)
    
    sift_score = 0
    if des1 is not None and des2 is not None and len(kp1) > 0 and len(kp2) > 0:
        bf = cv2.BFMatcher()
        matches = bf.knnMatch(des1, des2, k=2)
        good_matches = []
        for m, n in matches:
            if m.distance < 0.75 * n.distance:
                good_matches.append(m)
        sift_score = len(good_matches) / max(len(kp1), len(kp2))
    
    # 2. 模板匹配
    result = cv2.matchTemplate(img1, img2, cv2.TM_CCOEFF_NORMED)
    template_score = np.max(result)
    
    # 3. 直方图比较
    hist1 = cv2.calcHist([img1], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    hist2 = cv2.calcHist([img2], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    cv2.normalize(hist1, hist1)
    cv2.normalize(hist2, hist2)
    hist_score = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
    
    # 4. 边缘特征比较
    edges1 = cv2.Canny(img1, 100, 200)
    edges2 = cv2.Canny(img2, 100, 200)
    edge_score = cv2.matchTemplate(edges1, edges2, cv2.TM_CCOEFF_NORMED).max()
    
    # 5. 形状特征比较
    def get_shape_features(img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        max_contour = max(contours, key=cv2.contourArea)
        return cv2.HuMoments(cv2.moments(max_contour)).flatten()
    
    shape1 = get_shape_features(img1)
    shape2 = get_shape_features(img2)
    shape_score = 0
    if shape1 is not None and shape2 is not None:
        shape_score = 1 - np.linalg.norm(shape1 - shape2)
    
    # 组合所有特征得分
    weights = {
        'sift': 0.3,
        'template': 0.2,
        'hist': 0.2,
        'edge': 0.15,
        'shape': 0.15
    }
    
    final_score = (
        weights['sift'] * sift_score +
        weights['template'] * template_score +
        weights['hist'] * hist_score +
        weights['edge'] * edge_score +
        weights['shape'] * shape_score
    )
    
    # 保存调试图片
    debug_info = {}
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        debug_info = {
            'sift_score': sift_score,
            'template_score': template_score,
            'hist_score': hist_score,
            'edge_score': edge_score,
            'shape_score': shape_score,
            'final_score': final_score
        }
        
        # 保存特征匹配结果
        if len(good_matches) > 0:
            match_img = cv2.drawMatches(img1, kp1, img2, kp2, good_matches, None, 
                                      flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS)
            cv2.imwrite(os.path.join(debug_dir, 'sift_matches.jpg'), match_img)
        
        # 保存边缘检测结果
        cv2.imwrite(os.path.join(debug_dir, 'edges1.jpg'), edges1)
        cv2.imwrite(os.path.join(debug_dir, 'edges2.jpg'), edges2)
    
    return final_score, debug_info

def visualize_hog(hog_features):
    """可视化HOG特征"""
    # 将HOG特征重塑为图像
    hog_image = hog_features.reshape(64, 64)
    # 归一化到0-255
    hog_image = cv2.normalize(hog_image, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return hog_image

def visualize_sift(img, keypoints):
    """可视化SIFT特征点"""
    if keypoints is None:
        return img.copy()
    return cv2.drawKeypoints(img, keypoints, None, flags=cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)

def enhanced_preprocess(img):
    """增强的预处理函数"""
    if img is None:
        return None
        
    # 1. 基于颜色的自适应二值化
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    _, s, v = cv2.split(hsv)
    
    # 红色棋子使用通道分离法
    if np.mean(hsv[:,:,0]) > 150:  # 红色判定
        _, red = cv2.threshold(img[:,:,2], 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        binary = cv2.bitwise_and(red, cv2.bitwise_not(s < 50))
    else:  # 黑色棋子
        binary = cv2.adaptiveThreshold(v, 255, cv2.ADAPTIVE_THRESH_MEAN_C, 
                                     cv2.THRESH_BINARY_INV, 31, 5)
    
    # 2. 笔画修复（闭运算+骨架提取）
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3,3))
    morphed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    skeleton = cv2.ximgproc.thinning(morphed)
    
    return skeleton

def extract_hybrid_features(img):
    """提取混合特征"""
    if img is None:
        return None
        
    # 1. 方向梯度直方图（HOG）
    hog = cv2.HOGDescriptor((64,64), (16,16), (8,8), (8,8), 9)
    hog_feat = hog.compute(cv2.resize(img, (64,64))).flatten()
    
    # 2. 改进版SIFT（增强文字区域响应）
    sift = cv2.SIFT_create(contrastThreshold=0.02, edgeThreshold=5)
    kp, des = sift.detectAndCompute(img, None)
    
    # 3. 拓扑特征（专用解决形近字）
    skeleton = cv2.ximgproc.thinning(img)
    endpoints = len(find_line_endpoints(skeleton))  # 端点数量
    crossings = len(find_line_crossings(skeleton))  # 交叉点数量
    
    return {
        'hog': hog_feat,
        'sift_kp': kp,
        'sift_des': des,
        'topology': [endpoints, crossings]
    }

def hierarchical_match(target, template):
    """分级匹配"""
    if target is None or template is None:
        return 0
        
    # 第一级：HOG快速筛选
    hog_sim = 1 - spatial.distance.cosine(target['hog'], template['hog'])
    if hog_sim < 0.7:
        return 0
    
    # 第二级：拓扑特征校验
    if abs(target['topology'][0] - template['topology'][0]) > 2:  # 端点差异
        return 0
    if abs(target['topology'][1] - template['topology'][1]) > 1:  # 交叉点差异
        return 0
    
    # 第三级：SIFT精细匹配（添加空间约束）
    if target['sift_des'] is not None and template['sift_des'] is not None:
        matcher = cv2.BFMatcher(cv2.NORM_L2)
        matches = matcher.knnMatch(target['sift_des'], template['sift_des'], k=2)
        
        # 改进的比率测试 + 空间一致性检查
        good = []
        for m,n in matches:
            pt1 = target['sift_kp'][m.queryIdx].pt
            pt2 = template['sift_kp'][m.trainIdx].pt
            if (m.distance < 0.7*n.distance) and (abs(pt1[0]-pt2[0]) < 15):
                good.append(m)
        
        return len(good) / min(len(target['sift_des']), len(template['sift_des']))
    return 0

def find_line_endpoints(skeleton):
    """查找骨架的端点"""
    kernel = np.array([[1, 1, 1],
                      [1, 10, 1],
                      [1, 1, 1]])
    conv = cv2.filter2D(skeleton.astype(np.uint8), -1, kernel)
    return np.where(conv == 11)

def find_line_crossings(skeleton):
    """查找骨架的交叉点"""
    kernel1 = np.array([[1,1,1],
                        [1,10,1],
                        [1,1,1]], dtype=np.uint8)
    kernel2 = np.array([[0,1,0],
                        [1,10,1],
                        [0,1,0]], dtype=np.uint8)
    
    conv1 = cv2.filter2D(skeleton//255, -1, kernel1)
    conv2 = cv2.filter2D(skeleton//255, -1, kernel2)
    
    # 排除直线穿透的情况（邻域和=13但实际是直线）
    y, x = np.where((skeleton == 255) & (conv1 >= 13) & (conv2 < 12))
    return list(zip(x, y))

if __name__ == "__main__":
    # 测试代码
    import argparse
    
    parser = argparse.ArgumentParser(description='比较两张图片的相似度')
    parser.add_argument('piece_img', help='棋子图片路径')
    parser.add_argument('template_img', help='模板图片路径')
    parser.add_argument('--debug', help='调试图片保存目录')
    
    args = parser.parse_args()
    
    # 读取图片
    piece_img = cv2.imread(args.piece_img)
    template_img = cv2.imread(args.template_img)
    
    if piece_img is None or template_img is None:
        print("无法读取图片")
        exit(1)
    
    # 比较图片
    score, debug_info = compare_images(piece_img, template_img, args.debug)
    
    # 打印结果
    print(f"相似度分数: {score:.2f}")
    if debug_info:
        print("\n调试信息:")
        for key, value in debug_info.items():
            print(f"{key}: {value}")