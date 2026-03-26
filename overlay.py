"""
OSD 悬浮窗、ui_print、计分板、暂停控制
"""
import tkinter as tk
import threading
import ctypes
import os
import time
from datetime import datetime
import keyboard
import state
from utils import get_current_elapsed


def update_score_text():
    if state.overlay_root and state.score_var:
        elapsed = int(get_current_elapsed())
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        bal_str = str(state.current_balance)
        msg = (f"⏱️ 运行: {h:02d}:{m:02d}:{s:02d}      |  💰 金额: [ {bal_str} ]\n"
               f" ✔ 抢购: [ {state.success_count:<2} ] ✖ 漏掉: [ {state.fail_count:<2} ] |  📦 上架: [ {state.total_listed_count:<2} ] 件")
        try:
            state.score_var.set(msg)
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
    root.geometry("+20+20")
    root.attributes("-alpha", 0.75)
    root.config(bg='black')

    state.score_var = tk.StringVar()
    tk.Label(root, textvariable=state.score_var,
             font=("Microsoft YaHei", 11, "bold"),
             fg="gold", bg="black", justify="left").pack(padx=10, pady=(10, 5), anchor="w")

    state.log_text_var = tk.StringVar()
    state.log_text_var.set("🤖 脚本悬浮窗就绪...")
    tk.Label(root, textvariable=state.log_text_var,
             font=("Microsoft YaHei", 10, "bold"),
             fg="lime", bg="black", justify="left").pack(padx=10, pady=(0, 10), anchor="w")

    if os.name == 'nt':
        try:
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x00080000 | 0x00000020)
        except:
            pass

    state.last_resume_time = time.time()
    tick_timer()
    root.mainloop()


def start_overlay():
    t = threading.Thread(target=create_overlay, daemon=True)
    t.start()


def ui_print(msg, is_replace=False, save_log=False, show_console=True):
    now = datetime.now().strftime('%H:%M:%S')
    if show_console:
        print(f"\r[{now}] {msg}" if is_replace else f"[{now}] {msg}",
              end="\n" if not is_replace else "")
    if save_log:
        try:
            if not os.path.exists("logs"):
                os.makedirs("logs")
            with open(os.path.join("logs", f"result_log_{datetime.now().strftime('%Y-%m-%d')}.txt"),
                       "a", encoding="utf-8") as f:
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
            state.overlay_root.after(0, state.log_text_var.set, "\n".join(state.log_lines))
        except:
            pass


def toggle_pause():
    state.IS_PAUSED = not state.IS_PAUSED
    if state.IS_PAUSED:
        if state.last_resume_time is not None:
            state.total_running_time += (time.time() - state.last_resume_time)
            state.last_resume_time = None
        ui_print("⏸️ 脚本已暂停 (按F12恢复)")
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
        ui_print("▶️ 脚本已恢复！ (按F12暂停)")


keyboard.add_hotkey('f12', toggle_pause)


def move_overlay(geometry_str):
    if state.overlay_root:
        try:
            state.overlay_root.after(0, lambda: state.overlay_root.geometry(geometry_str))
        except:
            pass
