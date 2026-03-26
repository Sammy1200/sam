"""
底层键鼠操作、sleep、剪贴板、GC 工具
"""
import ctypes
import time
import gc
import numpy as np
import cv2
import os
import state
from config import SCROLL_POS, PRE_EXIT_CLICK_DELAY, SCRIPT_DIR


def safe_sleep(seconds):
    remaining = seconds
    while remaining > 0:
        if state.IS_PAUSED:
            time.sleep(0.1)
            continue
        step = min(0.05, remaining)
        time.sleep(step)
        remaining -= step


def safe_get_frame(camera_obj):
    frame = camera_obj.get_latest_frame()
    if frame is not None:
        return frame.copy()
    return None


def gc_checkpoint():
    gc.enable()
    gc.collect()
    gc.disable()


def safe_imread(relative_path_tuple, flags=0):
    filepath = os.path.join(SCRIPT_DIR, *relative_path_tuple)
    if not os.path.exists(filepath):
        return None
    return cv2.imdecode(np.fromfile(filepath, dtype=np.uint8), flags)


def keybd_down(vk):
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)

def keybd_up(vk):
    ctypes.windll.user32.keybd_event(vk, 0, 2, 0)

def press_key(vk):
    keybd_down(vk)
    safe_sleep(0.02)
    keybd_up(vk)
    safe_sleep(0.03)


def hotkey(vk_modifier, vk_key):
    keybd_down(vk_modifier)
    keybd_down(vk_key)
    safe_sleep(0.05)
    keybd_up(vk_key)
    keybd_up(vk_modifier)
    safe_sleep(0.1)


def type_digits(digit_str):
    for ch in digit_str:
        if ch.isdigit():
            press_key(0x30 + int(ch))
    safe_sleep(0.15)


def scroll_down(count=21):
    x, y = int(SCROLL_POS[0]), int(SCROLL_POS[1])
    ctypes.windll.user32.SetCursorPos(x, y)
    safe_sleep(0.1)
    for _ in range(count):
        ctypes.windll.user32.mouse_event(0x0800, 0, 0, ctypes.c_int(-120), 0)
        safe_sleep(0.05)
    safe_sleep(0.3)


def fast_click(pos):
    x, y = int(pos[0]), int(pos[1])
    ctypes.windll.user32.SetCursorPos(x, y)
    ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
    ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)


def get_clipboard_text():
    CF_UNICODETEXT = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_bool
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_bool
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            text = ctypes.wstring_at(ptr)
            return text if text is not None else ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def precise_sleep(seconds, spin_threshold=0.002):
    if seconds <= 0:
        return
    target_time = time.perf_counter() + seconds
    while target_time - time.perf_counter() > spin_threshold:
        if state.IS_PAUSED:
            break
        time.sleep(0.001)
    while time.perf_counter() < target_time:
        if state.IS_PAUSED:
            break


def click_exit():
    precise_sleep(PRE_EXIT_CLICK_DELAY, spin_threshold=0.01)
    press_key(0x1B)


def get_current_elapsed():
    if not state.IS_PAUSED and state.last_resume_time is not None:
        return state.total_running_time + (time.time() - state.last_resume_time)
    return state.total_running_time


def smart_wait(seconds):
    gc_checkpoint()
    start = time.time()
    while time.time() - start < seconds:
        if state.IS_PAUSED:
            return False
        time.sleep(0.01)
    return True
