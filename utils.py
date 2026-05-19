"""
底层输入、等待、日志、推送和悬浮窗控制工具函数。
"""
import ctypes
import time
import gc
import logging
import queue
import re
from datetime import datetime
import tkinter as tk
import numpy as np
import cv2
import os
import threading
import requests
import sys
import config
import state
from machine_sync_config import get_machine_sync_runtime_context
from config import SCROLL_POS, PRE_EXIT_CLICK_DELAY, SCRIPT_DIR

OVERLAY_NORMAL_GEOMETRY = "+20+20"
OVERLAY_NORMAL_BG = "black"
OVERLAY_NORMAL_ALPHA = 0.9
OVERLAY_SCORE_LABEL_STYLE = {
    "font": ("NSimSun", 12, "bold"),
    "fg": "gold",
    "bg": OVERLAY_NORMAL_BG,
    "justify": "left",
}
OVERLAY_LOG_LABEL_STYLE = {
    "font": ("Microsoft YaHei", 10, "bold"),
    "fg": "lime",
    "bg": OVERLAY_NORMAL_BG,
    "justify": "left",
}
OVERLAY_SCORE_LABEL_PACK = {"padx": 10, "pady": (10, 5), "anchor": "w"}
OVERLAY_LOG_LABEL_PACK = {"padx": 10, "pady": (0, 10), "anchor": "w"}
OVERLAY_MINI_LABEL_STYLE = {
    "font": ("Microsoft YaHei", 14, "bold"),
    "fg": "white",
    "bg": OVERLAY_NORMAL_BG,
    "justify": "left",
}
OVERLAY_MINI_LABEL_PACK = {"padx": 10, "pady": 8, "anchor": "w"}


class ChineseLevelFormatter(logging.Formatter):
    """将日志级别名映射为中文，避免用户看到英文级别。"""

    _LEVEL_NAMES = {
        logging.DEBUG: "调试",
        logging.INFO: "信息",
        logging.WARNING: "警告",
        logging.ERROR: "错误",
        logging.CRITICAL: "严重",
    }

    def format(self, record):
        original_levelname = record.levelname
        record.levelname = self._LEVEL_NAMES.get(record.levelno, original_levelname)
        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname


class ConsoleVisibilityFilter(logging.Filter):
    """允许按日志记录粒度控制是否输出到 PowerShell 窗口。"""

    def filter(self, record):
        return bool(getattr(record, "show_console", True))


def setup_logger():
    """初始化日志，同时输出到控制台和文件。"""
    logs_dir = os.path.join(SCRIPT_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = os.path.join(logs_dir, f"switch_{timestamp}.log")

    logger_obj = logging.getLogger("gameclicker")
    logger_obj.setLevel(logging.INFO)
    logger_obj.propagate = False

    for handler in list(logger_obj.handlers):
        logger_obj.removeHandler(handler)
        try:
            handler.close()
        except:
            pass

    formatter = ChineseLevelFormatter(
        "[%(asctime)s] %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(ConsoleVisibilityFilter())

    logger_obj.addHandler(file_handler)
    logger_obj.addHandler(stream_handler)
    return logger_obj


logger = setup_logger()
_OVERLAY_TASK_QUEUE = queue.Queue()
_PUSH_MACHINE_LABEL_CACHE = None
_PUSH_MACHINE_PREFIX_PATTERN = re.compile(r"^(?:【(?:1号电脑|2号电脑|3号电脑|本机)】)+")


def flush_logger_handlers():
    """强制刷新日志处理器，尽量确保日志已落盘。"""
    for handler in list(logger.handlers):
        try:
            handler.flush()
        except:
            pass
        try:
            stream = getattr(handler, "stream", None)
            if stream is not None and hasattr(stream, "flush"):
                stream.flush()
            if stream is not None and hasattr(stream, "fileno"):
                os.fsync(stream.fileno())
        except:
            pass
    try:
        sys.stdout.flush()
    except:
        pass
    try:
        sys.stderr.flush()
    except:
        pass


def enqueue_overlay_task(callback, *args, **kwargs):
    """将悬浮窗操作投递到 Tk 线程执行。"""
    if callback is None:
        return
    _OVERLAY_TASK_QUEUE.put((callback, args, kwargs))


def drain_overlay_tasks(max_tasks=100):
    """在 Tk 线程中批量执行待处理的悬浮窗操作。"""
    processed = 0
    while processed < max_tasks:
        try:
            callback, args, kwargs = _OVERLAY_TASK_QUEUE.get_nowait()
        except queue.Empty:
            break
        try:
            callback(*args, **kwargs)
        except Exception:
            logger.exception("执行悬浮窗队列任务失败")
        processed += 1


def _wait_overlay_root(timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if state.overlay_root is not None:
            return state.overlay_root
        time.sleep(0.05)
    return state.overlay_root


def _forget_packed_widget(widget):
    if widget is None:
        return
    try:
        if widget.winfo_manager() == "pack":
            widget.pack_forget()
    except:
        pass


def _ensure_overlay_label_refs(root):
    score_label = getattr(root, "_overlay_score_label", None)
    log_label = getattr(root, "_overlay_log_label", None)

    for child in root.winfo_children():
        if not isinstance(child, tk.Label):
            continue
        textvariable = str(child.cget("textvariable"))
        if score_label is None and state.score_var is not None and textvariable == str(state.score_var):
            score_label = child
        elif log_label is None and state.log_text_var is not None and textvariable == str(state.log_text_var):
            log_label = child

    if score_label is not None:
        root._overlay_score_label = score_label
    if log_label is not None:
        root._overlay_log_label = log_label

    return score_label, log_label


def _ensure_overlay_labels(root):
    """恢复正常模式前，确保计分板和日志标签对象都存在。"""
    score_label, log_label = _ensure_overlay_label_refs(root)

    if score_label is None and state.score_var is not None:
        score_label = tk.Label(
            root,
            textvariable=state.score_var,
            **OVERLAY_SCORE_LABEL_STYLE,
        )
        root._overlay_score_label = score_label

    if log_label is None and state.log_text_var is not None:
        log_label = tk.Label(
            root,
            textvariable=state.log_text_var,
            **OVERLAY_LOG_LABEL_STYLE,
        )
        root._overlay_log_label = log_label

    return score_label, log_label


def set_overlay_mini(text):
    """将悬浮窗切换为左上角精简模式。"""
    root = _wait_overlay_root()
    if root is None:
        logger.info("悬浮窗未创建，无法切换为精简模式")
        return

    def _apply():
        score_label, log_label = _ensure_overlay_label_refs(root)
        if not getattr(root, "_overlay_is_mini", False):
            root._overlay_normal_position = f"+{root.winfo_x()}+{root.winfo_y()}"

        if not hasattr(root, "_overlay_mini_var"):
            root._overlay_mini_var = tk.StringVar(master=root)
        if not hasattr(root, "_overlay_mini_label"):
            root._overlay_mini_label = tk.Label(
                root,
                textvariable=root._overlay_mini_var,
                **OVERLAY_MINI_LABEL_STYLE,
            )

        _forget_packed_widget(score_label)
        _forget_packed_widget(log_label)

        root._overlay_mini_var.set(text)
        _forget_packed_widget(root._overlay_mini_label)
        root._overlay_mini_label.configure(**OVERLAY_MINI_LABEL_STYLE)
        root._overlay_mini_label.pack(**OVERLAY_MINI_LABEL_PACK)

        root.config(bg=OVERLAY_NORMAL_BG)
        root.attributes("-alpha", OVERLAY_NORMAL_ALPHA)
        root.attributes("-topmost", True)
        root.deiconify()
        root.update_idletasks()
        root.geometry(f"{root.winfo_reqwidth()}x{root.winfo_reqheight()}+0+0")
        root.update()
        root._overlay_is_mini = True

    try:
        enqueue_overlay_task(_apply)
        logger.info(f"悬浮窗已切换为精简模式：{text}")
    except Exception:
        logger.exception("切换悬浮窗精简模式失败")


def update_overlay_mini(text):
    """更新精简模式下显示的文字。"""
    root = state.overlay_root
    if root is None:
        return

    def _apply():
        if not getattr(root, "_overlay_is_mini", False):
            return

        mini_var = getattr(root, "_overlay_mini_var", None)
        if mini_var is None:
            return

        mini_var.set(text)
        root.update_idletasks()
        root.geometry(f"{root.winfo_reqwidth()}x{root.winfo_reqheight()}+0+0")
        root.update()

    try:
        enqueue_overlay_task(_apply)
    except Exception:
        logger.exception("更新精简悬浮窗文字失败")


def restore_overlay():
    """恢复悬浮窗为正常模式。"""
    root = state.overlay_root
    if root is None:
        logger.info("悬浮窗未创建，无法恢复")
        return

    def _apply():
        if not getattr(root, "_overlay_is_mini", False):
            return

        score_label, log_label = _ensure_overlay_labels(root)

        mini_label = getattr(root, "_overlay_mini_label", None)
        _forget_packed_widget(mini_label)
        _forget_packed_widget(score_label)
        _forget_packed_widget(log_label)

        try:
            from overlay import OVERLAY_SCORE_PANEL_BG
            root.config(bg=OVERLAY_SCORE_PANEL_BG)
        except Exception:
            root.config(bg=OVERLAY_NORMAL_BG)
        root.attributes("-alpha", OVERLAY_NORMAL_ALPHA)
        root.attributes("-topmost", True)
        root.deiconify()
        root.update_idletasks()
        root._overlay_is_mini = False

        try:
            from overlay import apply_overlay_normal_layout, fit_overlay_to_content, update_score_text

            apply_overlay_normal_layout(root)
            update_score_text()
            fit_overlay_to_content(getattr(root, "_overlay_normal_position", OVERLAY_NORMAL_GEOMETRY))
        except Exception:
            logger.exception("刷新悬浮窗正常模式内容失败")

        root.update_idletasks()
        root.update()

    try:
        enqueue_overlay_task(_apply)
        logger.info("悬浮窗已恢复为正常模式")
    except Exception:
        logger.exception("恢复悬浮窗正常模式失败")


def safe_sleep(seconds):
    remaining = seconds
    while remaining > 0:
        if state.IS_PAUSED:
            time.sleep(0.1)
            continue
        step = min(0.05, remaining)
        time.sleep(step)
        remaining -= step


class RecoverableDXCamera:
    """dxcam 截图封装：截图线程因远程连接等显示切换中断时自动重建。"""

    def __init__(self, **create_kwargs):
        self._create_kwargs = dict(create_kwargs)
        self._camera = None
        self._lock = threading.RLock()
        self._start_kwargs = {}
        self._started = False
        self._recovering = False
        self._recovery_attempts = 3
        self._recovery_delay = 1.0
        self._stale_frame_seconds = 2.0
        self._last_recovery_log_at = 0.0

    def _create_camera_locked(self):
        import dxcam

        self._camera = dxcam.create(**self._create_kwargs)

    def _stop_camera_locked(self):
        camera = self._camera
        self._camera = None
        if camera is None:
            return
        try:
            camera.stop()
        except Exception:
            logger.exception("停止旧截图引擎失败")

    def _start_camera_locked(self):
        if self._camera is None:
            self._create_camera_locked()
        self._camera.start(**self._start_kwargs)
        self._started = True

    def _capture_thread_dead_locked(self):
        camera = self._camera
        if camera is None:
            return True
        if not bool(getattr(camera, "is_capturing", False)):
            return True
        thread = getattr(camera, "_DXCamera__thread", None)
        return thread is not None and not thread.is_alive()

    def _recover_locked(self, reason):
        if self._recovering:
            return
        self._recovering = True
        try:
            now = time.monotonic()
            if now - self._last_recovery_log_at >= 5.0:
                logger.warning("截图恢复中：%s", reason)
                self._last_recovery_log_at = now
            self._stop_camera_locked()
            last_error = None
            for attempt in range(1, self._recovery_attempts + 1):
                try:
                    time.sleep(self._recovery_delay)
                    self._create_camera_locked()
                    self._camera.start(**self._start_kwargs)
                    logger.info("截图已恢复")
                    return
                except Exception as exc:
                    last_error = exc
                    logger.warning("截图恢复失败 %s/%s：%s", attempt, self._recovery_attempts, exc)
                    self._stop_camera_locked()
            if last_error is not None:
                logger.error("截图恢复失败：%s", last_error)
        finally:
            self._recovering = False

    def start(self, **start_kwargs):
        with self._lock:
            self._start_kwargs = dict(start_kwargs)
            self._start_camera_locked()

    def stop(self):
        with self._lock:
            self._started = False
            self._stop_camera_locked()

    def get_latest_frame(self, copy=True, with_timestamp=False):
        for _ in range(self._recovery_attempts + 1):
            with self._lock:
                if not self._started:
                    return None
                if self._capture_thread_dead_locked():
                    self._recover_locked("线程已停止")
                    continue
                camera = self._camera
                try:
                    latest = camera.get_latest_frame(copy=copy, with_timestamp=True)
                except Exception as exc:
                    logger.warning("截图读取失败：%s", exc)
                    self._recover_locked("读取异常")
                    continue

                if latest is None:
                    self._recover_locked("无画面")
                    continue

                frame, frame_time = latest
                if frame_time is not None and time.perf_counter() - frame_time > self._stale_frame_seconds:
                    self._recover_locked("画面停滞")
                    continue

                if with_timestamp:
                    return frame, frame_time
                return frame
        return None


def create_recoverable_camera(**create_kwargs):
    return RecoverableDXCamera(**create_kwargs)


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


def _normalize_machine_display_name(machine_display_name, machine_id):
    normalized_display_name = str(machine_display_name or "").strip()
    normalized_machine_id = str(machine_id or "").strip().lower()

    if normalized_display_name in ("1号电脑", "2号电脑", "3号电脑"):
        return normalized_display_name

    machine_id_mapping = {
        "pc1": "1号电脑",
        "pc2": "2号电脑",
        "pc3": "3号电脑",
    }
    if normalized_machine_id in machine_id_mapping:
        return machine_id_mapping[normalized_machine_id]

    display_name_match = re.search(r"([123])号电脑", normalized_display_name)
    if display_name_match:
        return f"{display_name_match.group(1)}号电脑"

    return "本机"


def get_push_machine_label():
    global _PUSH_MACHINE_LABEL_CACHE
    if _PUSH_MACHINE_LABEL_CACHE:
        return _PUSH_MACHINE_LABEL_CACHE

    runtime_context = get_machine_sync_runtime_context()
    _PUSH_MACHINE_LABEL_CACHE = _normalize_machine_display_name(
        runtime_context.get("machine_display_name"),
        runtime_context.get("machine_id"),
    )
    return _PUSH_MACHINE_LABEL_CACHE


def _build_push_execution_slot_line():
    raw_slot = state.current_execution_slot
    try:
        normalized_slot = int(raw_slot)
        if normalized_slot > 0:
            return f"执行位：{normalized_slot}"
    except (TypeError, ValueError):
        pass

    slot_text = str(raw_slot or "").strip()
    if slot_text.isdigit() and int(slot_text) > 0:
        return f"执行位：{slot_text}"
    return "执行位：未识别"


def format_push_payload(title, content=""):
    normalized_title = str(title or "").strip()
    normalized_title = _PUSH_MACHINE_PREFIX_PATTERN.sub("", normalized_title)
    normalized_title = f"【{get_push_machine_label()}】{normalized_title}" if normalized_title else f"【{get_push_machine_label()}】"

    normalized_content = str(content or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    content_lines = normalized_content.split("\n") if normalized_content else []
    execution_line_index = next(
        (index for index, line in enumerate(content_lines) if str(line).strip().startswith("执行位：")),
        None,
    )

    if execution_line_index is None:
        content_lines.insert(0, _build_push_execution_slot_line())
    else:
        execution_line = content_lines.pop(execution_line_index)
        content_lines.insert(0, execution_line)

    return normalized_title, "\n".join(content_lines).strip("\n")


def push_msg_sync(title, content=""):
    normalized_title, normalized_content = format_push_payload(title, content)
    token = "59653da98d3049adb1deb19660767621"
    url = "http://www.pushplus.plus/send"
    data = {"token": token, "title": normalized_title, "content": normalized_content, "template": "txt"}
    requests.post(url, json=data, timeout=3)


def async_push_msg(title, content=""):
    def send():
        try:
            push_msg_sync(title, content)
        except:
            pass

    threading.Thread(target=send, daemon=True).start()


def smart_wait(seconds):
    gc_checkpoint()
    start = time.time()
    while time.time() - start < seconds:
        if state.IS_PAUSED:
            return False
        time.sleep(0.01)
    return True
