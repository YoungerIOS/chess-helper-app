"""跨平台截图协调与macOS可靠截图后端。"""

import platform
import threading


class ScreenCaptureBusy(RuntimeError):
    """另一个截图仍在进行，本次实时截图应直接跳过。"""


_capture_lock = threading.Lock()


def _grab_macos(region):
    """绕过macOS 26上可能永久阻塞的MSS CoreGraphics截图实现。"""
    from PIL import ImageGrab
    from mss.models import Size
    from mss.screenshot import ScreenShot

    left = int(region["left"])
    top = int(region["top"])
    width = int(region["width"])
    height = int(region["height"])
    image = ImageGrab.grab(
        bbox=(left, top, left + width, top + height),
        include_layered_windows=False,
    ).convert("RGBA")

    # 保持与MSS ScreenShot完全相同的BGRA内存布局及接口，调用方无需分支。
    raw = bytearray(image.tobytes("raw", "BGRA"))
    return ScreenShot(raw, region, size=Size(image.width, image.height))


def locked_grab(capture, region, *, timeout=1.0):
    """串行执行一次 MSS grab；超时后不继续堆积截图请求。"""
    if not _capture_lock.acquire(timeout=max(0.0, float(timeout))):
        raise ScreenCaptureBusy("截图服务正忙")
    try:
        capture_module = type(capture).__module__
        if platform.system() == "Darwin" and capture_module.startswith("mss."):
            return _grab_macos(region)
        return capture.grab(region)
    finally:
        _capture_lock.release()
