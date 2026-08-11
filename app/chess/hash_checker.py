from PIL import Image
import imagehash
import numpy as np
import cv2
from collections import deque
from app.tools.log_config import get_logger


logger = get_logger(__name__)

# 说明：
# 该模块提供一个基于帧哈希波动的"倒计时边框"近似检测方案。
# 判断逻辑：头像倒计时时，边框缩短和数字跳动会产生前后帧哈希波动(30左右)，非倒计时时,哈希几乎无波动(小于1)
# 状态改变时的相邻帧哈希差异较大(60-80左右)

class StableFrameDetector:
    def __init__(self, hash_size=16, stable_count=2, diff_threshold=3):
        """
        :param hash_size: 哈希尺寸（越大越精细，推荐 16）
        :param stable_count: 需要连续多少帧一致才算稳定（推荐 2 或 3）
        :param diff_threshold: 哈希差异阈值，小于等于该值认为相同
        """
        self.hash_size = hash_size
        self.stable_count = stable_count
        self.diff_threshold = diff_threshold
        self.prev_hash = None
        self.buffer = deque(maxlen=stable_count)
        self.last_confirmed_hash = None
        
        self.last_log_hash = None  # 仅用于打印相邻帧哈希差

    def update(self, frame: Image.Image, force_output=False):
        """
        传入一帧图像，返回：
        - None : 还不稳定，不输出新局面
        - frame: 检测到稳定的新局面
        """
        # 计算整图 dHash
        curr_hash = imagehash.dhash(frame, hash_size=self.hash_size)

        # 如果与上一帧差异太小，直接当成重复帧
        if self.prev_hash is not None:
            if (self.prev_hash - curr_hash) <= self.diff_threshold:
                self.buffer.append(curr_hash)
            else:
                self.buffer.clear()
                self.buffer.append(curr_hash)
        else:
            self.buffer.append(curr_hash)

        self.prev_hash = curr_hash

        # 判断是否稳定
        if len(self.buffer) == self.stable_count:
            # 检查 buffer 内是否都相同
            if all((self.buffer[0] - h) <= self.diff_threshold for h in self.buffer):
                # 如果是新局面，或者强制输出，才输出
                if (force_output or 
                    self.last_confirmed_hash is None or
                    (self.last_confirmed_hash - curr_hash) > self.diff_threshold):
                    
                    self.last_confirmed_hash = curr_hash
                    return frame  # 输出稳定帧

        return None

    def process_screenshot(self, board_screenshot, log_prefix="[board]", force_output=False):
        """
        将 MSS 截图转换为 PIL.Image，打印与上一帧的哈希差，并通过稳定帧检测返回稳定帧。
        Returns: (stable_frame: PIL.Image | None, curr_hash)
        """
        try:
            img_cv = np.frombuffer(board_screenshot.bgra, dtype=np.uint8).reshape(
                board_screenshot.height, board_screenshot.width, 4
            )
            img_bgr = img_cv[:, :, :3]
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(img_rgb)

            curr_hash = imagehash.dhash(pil_img, hash_size=self.hash_size)
            if self.last_log_hash is not None:
                diff = (self.last_log_hash - curr_hash)
                # print(f"{log_prefix} board hash diff: {diff}")
            else:
                logger.debug(f"{log_prefix} 首张棋盘帧（无上一帧哈希）")
            self.last_log_hash = curr_hash

            stable_frame = self.update(pil_img, force_output=force_output)
            return stable_frame, curr_hash
        except Exception as e:
            logger.exception(f"{log_prefix} 哈希差异计算失败")
            return None, None


# 全局稳定帧检测器实例
# 参数基于 180ms 采样间隔的视频分析:
# - diff_threshold=5: 静止帧 diff ≤5 (85.8%), 动画帧 diff ≥6
# - stable_count=2: 2帧连续静止即确认 → 响应时间 ~333ms
_stable_detector = StableFrameDetector(hash_size=20, stable_count=2, diff_threshold=5)

def filter_stable_frame(board_screenshot, log_prefix="[board]", force_output=False):
    """便捷函数，使用全局稳定帧检测器实例，处理棋盘截图"""
    return _stable_detector.process_screenshot(board_screenshot, log_prefix, force_output)
