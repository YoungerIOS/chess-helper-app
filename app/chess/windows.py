"""Windows window enumeration helpers.

This module intentionally uses only the standard library.  Window discovery is
needed before the optional ``pywin32`` package can be diagnosed, and DWM's
extended frame bounds are expressed in the same physical-pixel coordinate
space used by MSS.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from typing import Dict, List, Optional, Tuple


DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
GA_ROOT = 2
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = (("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD))


def _dwm_value(hwnd: int, attribute: int, value) -> bool:
    try:
        dwmapi = ctypes.windll.dwmapi
        return dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(attribute),
            ctypes.byref(value),
            ctypes.sizeof(value),
        ) == 0
    except (AttributeError, OSError):
        return False


def _physical_window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """Return a visible window's physical-pixel ``(x, y, width, height)``."""
    rect = wintypes.RECT()
    if not _dwm_value(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, rect):
        if not ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return None

    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width <= 1 or height <= 1:
        return None
    return int(rect.left), int(rect.top), width, height


def enumerate_windows() -> List[Dict]:
    """Enumerate usable top-level windows using built-in Windows APIs."""
    if os.name != "nt":
        return []

    user32 = ctypes.windll.user32
    windows: List[Dict] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True

            cloaked = wintypes.DWORD(0)
            if _dwm_value(hwnd, DWMWA_CLOAKED, cloaked) and cloaked.value:
                return True

            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, len(buffer))
            title = buffer.value.strip()
            bounds = _physical_window_rect(int(hwnd))
            if not title or bounds is None:
                return True

            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            windows.append({
                "title": title,
                "pid": int(pid.value),
                "window_id": int(hwnd),
                "bounds": bounds,
            })
        except Exception:
            # One unusual system window must not abort the entire enumeration.
            pass
        return True

    user32.EnumWindows(callback_type(callback), 0)
    return windows


def user_idle_seconds() -> float:
    """Return seconds since the last keyboard/mouse input on Windows."""
    if os.name != "nt":
        return 0.0
    info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    # Both values are DWORD ticks; masking preserves correct wraparound math.
    elapsed_ms = (int(ctypes.windll.kernel32.GetTickCount()) - int(info.dwTime)) & 0xFFFFFFFF
    return elapsed_ms / 1000.0


def is_foreground_window(window_id: int) -> bool:
    """Check whether ``window_id`` (or one of its children) owns the foreground."""
    if os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetAncestor.restype = wintypes.HWND
    target = wintypes.HWND(int(window_id))
    foreground = user32.GetForegroundWindow()
    if not foreground:
        return False
    return int(user32.GetAncestor(foreground, GA_ROOT) or foreground) == int(
        user32.GetAncestor(target, GA_ROOT) or target.value
    )


def click_window_point(window_id: int, point: Tuple[int, int]) -> None:
    """Send a click to the target's child window at a physical screen point."""
    if os.name != "nt":
        raise OSError("Windows API is unavailable")
    user32 = ctypes.windll.user32
    user32.WindowFromPoint.argtypes = (wintypes.POINT,)
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetAncestor.restype = wintypes.HWND
    user32.ScreenToClient.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
    user32.ScreenToClient.restype = wintypes.BOOL
    user32.SendMessageW.argtypes = (
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    )
    user32.SendMessageW.restype = wintypes.LPARAM

    target = wintypes.HWND(int(window_id))
    screen_point = wintypes.POINT(int(point[0]), int(point[1]))
    recipient = user32.WindowFromPoint(screen_point) or target.value
    target_root = int(user32.GetAncestor(target, GA_ROOT) or target.value)
    recipient_root = int(user32.GetAncestor(recipient, GA_ROOT) or recipient)
    if recipient_root != target_root:
        recipient = target.value

    client_point = wintypes.POINT(screen_point.x, screen_point.y)
    if not user32.ScreenToClient(wintypes.HWND(recipient), ctypes.byref(client_point)):
        raise OSError("无法转换游戏窗口点击坐标")
    packed_point = (client_point.x & 0xFFFF) | ((client_point.y & 0xFFFF) << 16)
    user32.SendMessageW(wintypes.HWND(recipient), WM_MOUSEMOVE, 0, packed_point)
    user32.SendMessageW(wintypes.HWND(recipient), WM_LBUTTONDOWN, MK_LBUTTON, packed_point)
    time.sleep(0.07)
    user32.SendMessageW(wintypes.HWND(recipient), WM_LBUTTONUP, 0, packed_point)
