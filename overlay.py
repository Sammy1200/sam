"""
悬浮窗、ui_print、计分板、暂停控制
"""
import tkinter as tk
import threading
import ctypes
import os
import time
from datetime import datetime
import keyboard
import state
from account_db import compute_new_baseline_item_count
from utils import (
    get_current_elapsed,
    OVERLAY_NORMAL_GEOMETRY,
    OVERLAY_NORMAL_BG,
    OVERLAY_NORMAL_ALPHA,
    OVERLAY_SCORE_LABEL_STYLE,
    OVERLAY_LOG_LABEL_STYLE,
    OVERLAY_SCORE_LABEL_PACK,
    OVERLAY_LOG_LABEL_PACK,
)


DEFAULT_OVERLAY_STATUS_TEXT = "状态待更新"


def fit_overlay_to_content(position_override=None):
    """按当前内容重新计算正常模式悬浮窗尺寸，避免恢复后被裁切。"""
    root = state.overlay_root
    if root is None or getattr(root, "_overlay_is_mini", False):
        return

    try:
        position = position_override or getattr(root, "_overlay_normal_position", OVERLAY_NORMAL_GEOMETRY)
        root.update_idletasks()
        root.geometry(f"{root.winfo_reqwidth()}x{root.winfo_reqheight()}{position}")
    except:
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
    if status_text:
        return status_text
    return DEFAULT_OVERLAY_STATUS_TEXT


def _get_balance_display_text():
    balance_text = str(state.round_current_balance or "").strip()
    if balance_text:
        return balance_text
    fallback_text = str(state.current_balance or "").strip()
    return fallback_text or "获取中..."


def _get_runtime_item_estimate():
    return compute_new_baseline_item_count(
        state.baseline_item_count,
        state.round_purchase_success_count,
        state.round_listing_success_count,
    )


def update_score_text():
    if state.overlay_root and state.score_var:
        elapsed_text = _format_duration(get_current_elapsed())
        status_text = _get_overlay_status_text()
        nickname_text = str(state.current_nickname or "").strip() or "未设置"
        slot_text = str(state.current_execution_slot or "--")
        wait_flag_text = "是" if state.account_is_waiting else "否"
        allow_start_text = _format_account_time(state.account_allow_start_time)
        remaining_text = _format_remaining_time(state.account_allow_start_time) if state.account_is_waiting else "无需等待"
        balance_text = _get_balance_display_text()
        runtime_item_estimate = _get_runtime_item_estimate()
        msg = (
            f"🧭 执行位: {slot_text} | 昵称: {nickname_text} | 状态: {status_text}\n"
            f"⏳ 冷却中: {wait_flag_text} | 可开抢: {allow_start_text} | 剩余: {remaining_text}\n"
            f"⏱️ 抢购运行: {elapsed_text} | 💰 当前余额: [ {balance_text} ]\n"
            f"✔ 本轮抢购成功: [ {state.round_purchase_success_count:<2} ] | ✖ 本轮抢购失败: [ {state.round_purchase_fail_count:<2} ] | 📦 本轮上架成功: [ {state.round_listing_success_count:<2} ]\n"
            f"📚 已加载基线数量: [ {state.baseline_item_count:<2} ] | 🧮 运行中道具推算值: [ {runtime_item_estimate:<2} ]"
        )
        try:
            state.score_var.set(msg)
            fit_overlay_to_content()
        except:
            pass


def tick_timer():
    update_score_text()
    if state.overlay_root:
        state.overlay_root.after(1000, tick_timer)


def create_overlay():
    state.overlay_root = tk.Tk()
    root = state.overlay_root
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry(OVERLAY_NORMAL_GEOMETRY)
    root.attributes("-alpha", OVERLAY_NORMAL_ALPHA)
    root.config(bg=OVERLAY_NORMAL_BG)
    root._overlay_is_mini = False
    root._overlay_normal_position = OVERLAY_NORMAL_GEOMETRY

    state.score_var = tk.StringVar()
    root._overlay_score_label = tk.Label(
        root,
        textvariable=state.score_var,
        **OVERLAY_SCORE_LABEL_STYLE,
    )
    root._overlay_score_label.pack(**OVERLAY_SCORE_LABEL_PACK)

    state.log_text_var = tk.StringVar()
    state.log_text_var.set("🤖 脚本悬浮窗就绪...")
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
        except:
            pass

    state.last_resume_time = time.time()
    tick_timer()
    fit_overlay_to_content()
    root.mainloop()


def start_overlay():
    t = threading.Thread(target=create_overlay, daemon=True)
    t.start()


def ui_print(msg, is_replace=False, save_log=False, show_console=True):
    now = datetime.now().strftime("%H:%M:%S")
    if show_console:
        print(f"\r[{now}] {msg}" if is_replace else f"[{now}] {msg}",
              end="\n" if not is_replace else "")
    if save_log:
        try:
            if not os.path.exists("logs"):
                os.makedirs("logs")
            with open(
                os.path.join("logs", f"result_log_{datetime.now().strftime('%Y-%m-%d')}.txt"),
                "a",
                encoding="utf-8",
            ) as f:
                f.write(f"[{now}] {msg}\n")
        except:
            pass
    if state.overlay_root and state.log_text_var:
        gui_msg = f"[{now}] {msg}"
        if is_replace and state.log_lines and any(
                icon in state.log_lines[-1] for icon in ["✔", "✖", "⏭️"]):
            state.log_lines.append(gui_msg)
        elif is_replace and state.log_lines:
            state.log_lines[-1] = gui_msg
        else:
            state.log_lines.append(gui_msg)
        if len(state.log_lines) > 20:
            state.log_lines.pop(0)
        try:
            def _apply_log_text(log_text):
                if not state.overlay_root or not state.log_text_var:
                    return
                state.log_text_var.set(log_text)
                fit_overlay_to_content()

            state.overlay_root.after(0, _apply_log_text, "\n".join(state.log_lines))
        except:
            pass


def toggle_pause():
    state.IS_PAUSED = not state.IS_PAUSED
    if state.IS_PAUSED:
        if state.last_resume_time is not None:
            state.total_running_time += (time.time() - state.last_resume_time)
            state.last_resume_time = None
        ui_print("⏸️ 脚本已暂停（按 F12 恢复）")
        if state.overlay_root:
            try:
                state.overlay_root.after(0, state.overlay_root.withdraw)
            except:
                pass
    else:
        state.last_resume_time = time.time()
        if state.overlay_root:
            try:
                state.overlay_root.after(0, state.overlay_root.deiconify)
            except:
                pass
        ui_print("▶️ 脚本已恢复！（按 F12 暂停）")


keyboard.add_hotkey("f12", toggle_pause)


def move_overlay(geometry_str):
    if state.overlay_root:
        try:
            def _apply_move():
                if not state.overlay_root:
                    return
                if not getattr(state.overlay_root, "_overlay_is_mini", False):
                    state.overlay_root._overlay_normal_position = geometry_str
                    fit_overlay_to_content(geometry_str)
                else:
                    state.overlay_root.geometry(geometry_str)

            state.overlay_root.after(0, _apply_move)
        except:
            pass
