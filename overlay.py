"""
悬浮窗、日志输出、计分板、暂停控制
"""
import atexit
import ctypes
import os
import threading
import time
import tkinter as tk
from datetime import datetime

import state
from round_persistence import (
    get_runtime_window_remaining_seconds,
    persist_pause_snapshot,
    persist_resume_snapshot,
)
from utils import (
    OVERLAY_LOG_LABEL_PACK,
    OVERLAY_LOG_LABEL_STYLE,
    OVERLAY_NORMAL_ALPHA,
    OVERLAY_NORMAL_BG,
    OVERLAY_NORMAL_GEOMETRY,
    OVERLAY_SCORE_LABEL_PACK,
    OVERLAY_SCORE_LABEL_STYLE,
    drain_overlay_tasks,
    enqueue_overlay_task,
)


DEFAULT_OVERLAY_STATUS_TEXT = "状态待更新"
F12_VK = 0x7B
OVERLAY_LEFT_COLUMN_WIDTH = 18
_pause_hotkey_listener_started = False
_overlay_shutdown_requested = False
_overlay_closed_event = threading.Event()


def fit_overlay_to_content(position_override=None):
    """按当前内容重新计算正常模式悬浮窗尺寸，避免恢复后被裁切。"""
    root = state.overlay_root
    if root is None or getattr(root, "_overlay_is_mini", False):
        return

    try:
        position = position_override or getattr(root, "_overlay_normal_position", OVERLAY_NORMAL_GEOMETRY)
        root.update_idletasks()
        root.geometry(f"{root.winfo_reqwidth()}x{root.winfo_reqheight()}{position}")
    except Exception:
        pass


def _format_duration(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _format_account_time(value):
    if value is None:
        return "--"
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M:%S")
    return str(value)


def _format_remaining_time(target_time):
    if target_time is None:
        return "--"
    remaining_seconds = int((target_time - datetime.now()).total_seconds())
    if remaining_seconds <= 0:
        return "00:00:00"
    return _format_duration(remaining_seconds)


def _get_overlay_status_text():
    status_text = str(state.overlay_status or "").strip()
    return status_text or DEFAULT_OVERLAY_STATUS_TEXT


def _get_balance_display_text():
    balance_text = str(state.round_current_balance or "").strip()
    if balance_text:
        return balance_text
    fallback_text = str(state.current_balance or "").strip()
    return fallback_text or "获取中..."


def _get_current_inventory():
    return max(0, int(state.baseline_item_count or 0))


def _format_overlay_value(value, fallback="--"):
    text = str(value or "").strip()
    return text or fallback


def _build_overlay_row(left_label, left_value, right_label, right_value):
    left_text = f"{left_label}{_format_overlay_value(left_value)}"
    right_text = f"{right_label}{_format_overlay_value(right_value)}"
    return f"{left_text:<{OVERLAY_LEFT_COLUMN_WIDTH}}｜ {right_text}"


def update_score_text():
    if not state.overlay_root or not state.score_var:
        return

    remaining_text = _format_duration(get_runtime_window_remaining_seconds())
    slot_text = str(state.current_execution_slot or "--")
    current_inventory = _get_current_inventory()
    msg = (
        _build_overlay_row("执行位：", slot_text, "可运行时：", remaining_text) + "\n"
        + _build_overlay_row("上架成功：", state.round_listing_success_count, "道具库存：", current_inventory) + "\n"
        + _build_overlay_row("抢购成功：", state.round_purchase_success_count, "抢购失败：", state.round_purchase_fail_count)
    )
    try:
        state.score_var.set(msg)
        fit_overlay_to_content()
    except Exception:
        pass


def _get_balance_display_text():
    live_balance_text = str(state.current_balance or "").strip()
    if live_balance_text and not live_balance_text.startswith("获取中"):
        return live_balance_text
    last_valid_balance_text = str(state.last_valid_balance or "").strip()
    if last_valid_balance_text:
        return last_valid_balance_text
    round_balance_text = str(state.round_current_balance or "").strip()
    if round_balance_text:
        return round_balance_text
    return "获取中..."


def update_score_text():
    if not state.overlay_root or not state.score_var:
        return

    remaining_text = _format_duration(get_runtime_window_remaining_seconds())
    slot_text = str(state.current_execution_slot or "--")
    current_inventory = _get_current_inventory()
    balance_text = _get_balance_display_text()
    msg = (
        _build_overlay_row("执行位：", slot_text, "可运行时：", remaining_text) + "\n"
        + _build_overlay_row("上架成功：", state.round_listing_success_count, "道具库存：", current_inventory) + "\n"
        + _build_overlay_row("抢购成功：", state.round_purchase_success_count, "抢购失败：", state.round_purchase_fail_count) + "\n"
        + _build_overlay_row("当前余额：", balance_text, "当前状态：", _get_overlay_status_text())
    )
    try:
        state.score_var.set(msg)
        fit_overlay_to_content()
    except Exception:
        pass


def tick_timer():
    drain_overlay_tasks()
    update_score_text()
    if state.overlay_root:
        state.overlay_root.after(1000, tick_timer)


def create_overlay():
    global _overlay_shutdown_requested
    _overlay_closed_event.clear()
    _overlay_shutdown_requested = False
    state.overlay_root = tk.Tk()
    root = state.overlay_root
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry(OVERLAY_NORMAL_GEOMETRY)
    root.attributes("-alpha", OVERLAY_NORMAL_ALPHA)
    root.config(bg=OVERLAY_NORMAL_BG)
    root._overlay_is_mini = False
    root._overlay_normal_position = OVERLAY_NORMAL_GEOMETRY
    state.log_lines = []
    state.overlay_last_log_replaceable = False

    state.score_var = tk.StringVar()
    root._overlay_score_label = tk.Label(
        root,
        textvariable=state.score_var,
        **OVERLAY_SCORE_LABEL_STYLE,
    )
    root._overlay_score_label.pack(**OVERLAY_SCORE_LABEL_PACK)

    state.log_text_var = tk.StringVar()
    state.log_text_var.set("悬浮窗已就绪。")
    root._overlay_log_label = tk.Label(
        root,
        textvariable=state.log_text_var,
        **OVERLAY_LOG_LABEL_STYLE,
    )
    root._overlay_log_label.pack(**OVERLAY_LOG_LABEL_PACK)

    if os.name == "nt":
        try:
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x00080000 | 0x00000020)
        except Exception:
            pass

    state.last_resume_time = time.time()
    tick_timer()
    fit_overlay_to_content()
    try:
        root.mainloop()
    finally:
        state.overlay_root = None
        state.log_text_var = None
        state.score_var = None
        _overlay_closed_event.set()


def start_overlay():
    global _overlay_shutdown_requested
    _overlay_shutdown_requested = False
    _start_pause_hotkey_listener()
    threading.Thread(target=create_overlay, daemon=True).start()


def ui_print(msg, is_replace=False, save_log=False, show_console=True):
    now = datetime.now().strftime("%H:%M:%S")
    if show_console:
        print(f"\r[{now}] {msg}" if is_replace else f"[{now}] {msg}", end="\n" if not is_replace else "")

    if save_log:
        try:
            if not os.path.exists("logs"):
                os.makedirs("logs")
            with open(
                os.path.join("logs", f"result_log_{datetime.now().strftime('%Y-%m-%d')}.txt"),
                "a",
                encoding="utf-8",
            ) as file_obj:
                file_obj.write(f"[{now}] {msg}\n")
        except Exception:
            pass

    if not state.overlay_root or not state.log_text_var:
        return

    gui_msg = f"[{now}] {msg}"
    if is_replace and state.log_lines and state.overlay_last_log_replaceable:
        state.log_lines[-1] = gui_msg
    else:
        state.log_lines.append(gui_msg)
    state.overlay_last_log_replaceable = bool(is_replace)
    if len(state.log_lines) > 20:
        state.log_lines.pop(0)

    try:
        def _apply_log_text(log_text):
            if not state.overlay_root or not state.log_text_var:
                return
            state.log_text_var.set(log_text)
            fit_overlay_to_content()

        enqueue_overlay_task(_apply_log_text, "\n".join(state.log_lines))
    except Exception:
        pass


def toggle_pause():
    state.IS_PAUSED = not state.IS_PAUSED
    if state.IS_PAUSED:
        if state.last_resume_time is not None:
            state.total_running_time += (time.time() - state.last_resume_time)
            state.last_resume_time = None
        ui_print("脚本已暂停（按 F12 恢复）")
        pause_persist_result = persist_pause_snapshot()
        if pause_persist_result.status == "success":
            ui_print("暂停后已写入当前账号最小必要字段，账号状态已更新为人工暂停。", save_log=True)
        elif pause_persist_result.status != "skipped":
            ui_print(f"暂停后最小写库失败：{pause_persist_result.reason}", save_log=True)
        if state.overlay_root:
            try:
                enqueue_overlay_task(state.overlay_root.withdraw)
            except Exception:
                pass
    else:
        state.last_resume_time = time.time()
        if state.overlay_root:
            try:
                enqueue_overlay_task(state.overlay_root.deiconify)
            except Exception:
                pass
        resume_persist_result = persist_resume_snapshot()
        if resume_persist_result.status == "success":
            ui_print("脚本已恢复（按 F12 暂停），当前账号状态已从人工暂停恢复为运行中。")
        elif resume_persist_result.status == "skipped":
            ui_print("脚本已恢复（按 F12 暂停）")
        else:
            ui_print(f"脚本已恢复（按 F12 暂停），但状态回写失败：{resume_persist_result.reason}", save_log=True)


def _pause_hotkey_loop():
    """使用轮询监听 F12，避免全局键盘钩子影响输入法和文字输入。"""
    last_down = False
    while not _overlay_shutdown_requested:
        try:
            is_down = bool(ctypes.windll.user32.GetAsyncKeyState(F12_VK) & 0x8000)
            if is_down and not last_down:
                toggle_pause()
            last_down = is_down
        except Exception:
            pass
        time.sleep(0.05)


def _start_pause_hotkey_listener():
    global _pause_hotkey_listener_started
    if _pause_hotkey_listener_started:
        return

    listener = threading.Thread(target=_pause_hotkey_loop, daemon=True)
    listener.start()
    _pause_hotkey_listener_started = True


def shutdown_overlay(wait_timeout=1.5):
    """关闭悬浮窗，并尽量等待 Tk 线程退出。"""
    global _overlay_shutdown_requested
    _overlay_shutdown_requested = True

    root = state.overlay_root
    if root is None:
        _overlay_closed_event.set()
        return

    def _close_root():
        current_root = state.overlay_root
        if current_root is None:
            return
        try:
            current_root.quit()
        except Exception:
            pass
        try:
            current_root.destroy()
        except Exception:
            pass

    try:
        enqueue_overlay_task(_close_root)
    except Exception:
        try:
            root.after(0, _close_root)
        except Exception:
            pass

    _overlay_closed_event.wait(wait_timeout)


atexit.register(shutdown_overlay)


def move_overlay(geometry_str):
    if not state.overlay_root:
        return

    try:
        def _apply_move():
            if not state.overlay_root:
                return
            if not getattr(state.overlay_root, "_overlay_is_mini", False):
                state.overlay_root._overlay_normal_position = geometry_str
                fit_overlay_to_content(geometry_str)
            else:
                state.overlay_root.geometry(geometry_str)

        enqueue_overlay_task(_apply_move)
    except Exception:
        pass
