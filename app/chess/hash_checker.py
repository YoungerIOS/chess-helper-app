from PIL import Image
import imagehash
import numpy as np
import cv2
from collections import deque, defaultdict

# 说明：
# 该模块提供一个基于帧哈希波动的"倒计时边框"近似检测方案。
# 判断逻辑：头像倒计时时，边框缩短和数字跳动会产生前后帧哈希波动(30左右)，非倒计时时,哈希几乎无波动(小于1)
# 状态改变时的相邻帧哈希差异较大(60-80左右)

class AvatarHashDetector:
    """头像哈希检测器类，用于判断头像是否处于倒计时状态"""
    
    def __init__(self, 
            buffers_count=20, 
            diff_threshold=50, 
            same_threshold=0.2, 
            bounds_threshold=30):
        """
        初始化哈希检测器
        Args:
            diff_threshold: 状态变化时单帧差异阈值（dHash 差值）
            buffers_count: 缓冲区帧数
            same_threshold: 状态稳定期的平均差异阈值
            bounds_threshold: 状态稳定期的平均差异阈值
        """
        self.buffers_count = buffers_count
        self.diff_threshold = diff_threshold
        self.same_threshold = same_threshold
        self.bounds_threshold = bounds_threshold
        
        # 每个头像的数据
        self.hash_buffers = defaultdict(lambda: deque(maxlen=buffers_count))  # 最近10帧哈希
        self.last_frame_cv = {}  # 上一帧原始图像（CV 格式）
        self.last_state = {}  # 上一帧判定结果: True=COUNTDOWN, False=NORMAL
    
    def analyse_hashs(self, screenshot, platform: str, avatar: str) -> tuple[bool, str]:
        """
        - 维护10帧缓冲
        返回: (是否倒计时, 判断说明)
        """
        # 将 mss 的 BGRA ndarray screenshot 转换为 PIL.Image（RGB）
        img_cv = np.frombuffer(screenshot.bgra, dtype=np.uint8).reshape(screenshot.height, screenshot.width, 4)
        img_bgr = img_cv[:, :, :3]
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)
        curr_hash = imagehash.dhash(pil_img, hash_size=16)

        buf = self.hash_buffers[avatar]
        buf.append(curr_hash)

        # 相邻帧哈希差
        instant_diff = 0
        if len(buf) >= 2:
            instant_diff = (buf[-2] - buf[-1])

        # 优先：每帧先检查相邻哈希差是否达到阈值（达到时再计算颜色占比差并判定）
        if len(buf) >= 2 and instant_diff >= self.diff_threshold:
            # 仅在需要时计算颜色占比：分别计算"当前帧"和"上一帧"的颜色占比
            prev_img_cv = self.last_frame_cv.get(avatar, img_cv)
            curr_color_ratio = self._calculate_color_ratio(img_cv, platform, avatar)
            prev_color_ratio = self._calculate_color_ratio(prev_img_cv, platform, avatar)
            color_delta = curr_color_ratio - prev_color_ratio
            curr_state = None
            reason = ""
            if color_delta > 0.05:
                curr_state = True
                reason = f"帧差大({instant_diff})+颜色增({color_delta:.2f})→倒计时"
            elif color_delta < -0.05:
                curr_state = False
                reason = f"帧差大({instant_diff})+颜色减({color_delta:.2f})→空闲"
            else:
                curr_state = False
                reason = f"帧差大({instant_diff})+色差小({color_delta:.2f})→空闲"

            # 更新上一帧缓存
            self.last_frame_cv[avatar] = img_cv
            self.last_state[avatar] = curr_state
            buf.clear()
            return curr_state, reason

        # 其次：若累计已满10帧但一直未出现大差异，再按平均波动判断
        if len(buf) >= self.buffers_count:
            recent = list(buf)[-self.buffers_count:]
            diffs = []
            for i in range(1, len(recent)):
                diffs.append(recent[i-1] - recent[i])
            avg_diff = sum(diffs) / len(diffs) if diffs else 0

            if avg_diff <= self.same_threshold:
                self.last_frame_cv[avatar] = img_cv
                self.last_state[avatar] = False
                reason = f"平均差小({avg_diff:.1f}≤{self.same_threshold})→空闲"
                return False, reason
            elif avg_diff <= self.bounds_threshold:
                self.last_frame_cv[avatar] = img_cv
                self.last_state[avatar] = True
                reason = f"平均差中({avg_diff:.1f}≤{self.bounds_threshold})→倒计时"
                return True, reason
            # avg_diff 不会大于 diff_threshold (因为大差异会返回并清空缓冲区)

        # 缓冲未满且未出现大差异，返回上一帧状态（默认 NORMAL）
        prev_state = self.last_state.get(avatar, False)
        reason = f"缓冲未满({len(buf)}/{self.buffers_count})→{'倒计时' if prev_state else '空闲'}"
        return prev_state, reason
    
    def _calculate_color_ratio(self, img_cv, platform: str, avatar: str) -> float:
        """计算头像区域的颜色占比（黄色/红色等高饱和颜色）"""
        try:
            hsv = cv2.cvtColor(img_cv, cv2.COLOR_BGR2HSV)
            
            # 定义高饱和颜色范围（黄色、红色等）
            yellow_lower = np.array([20, 100, 100])
            yellow_upper = np.array([40, 255, 255])
            red_lower1 = np.array([0, 100, 100])
            red_upper1 = np.array([10, 255, 255])
            red_lower2 = np.array([170, 100, 100])
            red_upper2 = np.array([180, 255, 255])
            
            yellow_mask = cv2.inRange(hsv, yellow_lower, yellow_upper)
            red_mask1 = cv2.inRange(hsv, red_lower1, red_upper1)
            red_mask2 = cv2.inRange(hsv, red_lower2, red_upper2)
            red_mask = cv2.bitwise_or(red_mask1, red_mask2)
            
            color_mask = cv2.bitwise_or(yellow_mask, red_mask)
            color_pixels = np.sum(color_mask > 0)
            total_pixels = img_cv.shape[0] * img_cv.shape[1]
            
            return color_pixels / total_pixels if total_pixels > 0 else 0.0
        except Exception:
            return 0.0


# 全局检测器实例
_detector = AvatarHashDetector()


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

    def update(self, frame: Image.Image):
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
                # 如果是新局面，才输出
                if (self.last_confirmed_hash is None or
                        (self.last_confirmed_hash - curr_hash) > self.diff_threshold):
                    self.last_confirmed_hash = curr_hash
                    return frame  # 输出稳定帧

        return None

    def process_screenshot(self, board_screenshot, log_prefix="[board]"):
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
                print(f"{log_prefix} board hash diff: {diff}")
            else:
                print(f"{log_prefix} first board frame (no previous hash)")
            self.last_log_hash = curr_hash

            stable_frame = self.update(pil_img)
            return stable_frame, curr_hash
        except Exception as e:
            print(f"{log_prefix} hash diff calc failed: {e}")
            return None, None


# 全局稳定帧检测器实例
_stable_detector = StableFrameDetector(hash_size=20, stable_count=2, diff_threshold=2)

# 便捷函数，保持向后兼容
def has_border(screenshot, platform: str, avatar: str) -> tuple[bool, str]:
    """便捷函数，使用全局检测器实例，返回(结果, 说明)"""
    return _detector.analyse_hashs(screenshot, platform, avatar)

def filter_stable_frame(board_screenshot, log_prefix="[board]"):
    """便捷函数，使用全局稳定帧检测器实例，处理棋盘截图"""
    return _stable_detector.process_screenshot(board_screenshot, log_prefix)