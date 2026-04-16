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
OVERLAY_SCORE_PANEL_BG = "#15110d"
OVERLAY_SCORE_MAIN_BG = "#15110d"
OVERLAY_SCORE_MAIN_BORDER = "#19130f"
OVERLAY_SCORE_ITEM_BG = "#18130f"
OVERLAY_SCORE_ITEM_BORDER = "#221a14"
OVERLAY_SCORE_LABEL_FG = "#9f9688"
OVERLAY_SCORE_SLOT_LABEL_FG = "#8d816c"
OVERLAY_SCORE_VALUE_FG = OVERLAY_SCORE_LABEL_FG
OVERLAY_SCORE_SLOT_FG = OVERLAY_SCORE_SLOT_LABEL_FG
OVERLAY_SCORE_TIME_FG = "#d8c6a0"
OVERLAY_SCORE_FAIL_FG = OVERLAY_SCORE_LABEL_FG
OVERLAY_SCORE_LABEL_FONT = ("Microsoft YaHei", 11, "bold")
OVERLAY_SCORE_VALUE_FONT = OVERLAY_SCORE_LABEL_FONT
OVERLAY_SCORE_TIME_FONT = ("Bahnschrift", 16, "bold")
OVERLAY_SCORE_SLOT_FONT = OVERLAY_SCORE_LABEL_FONT
OVERLAY_SCORE_PANEL_PAD_X = 6
OVERLAY_SCORE_PANEL_PAD_Y = (5, 0)
OVERLAY_SCORE_MAIN_PAD_X = 7
OVERLAY_SCORE_MAIN_PAD_Y = 6
OVERLAY_SCORE_COLUMN_GAP = 4
OVERLAY_SCORE_ROW_GAP = 7
OVERLAY_SCORE_ITEM_PAD_X = 7
OVERLAY_SCORE_ITEM_PAD_Y = 6
OVERLAY_SCORE_ITEM_PAD_Y_FIRST_ROW = 7
OVERLAY_SCORE_TEXT_PAD_Y = 1
OVERLAY_SCORE_TITLE_PAD_X = (4, 0)
OVERLAY_SCORE_VALUE_GAP = (6, 3)
OVERLAY_SCORE_VALUE_GAP_FIRST_ROW = (6, 3)
OVERLAY_LOG_PANEL_BG = "#15110d"
OVERLAY_LOG_PANEL_BORDER = "#241b15"
OVERLAY_LOG_TEXT_FG = "#9ab284"
OVERLAY_LOG_PANEL_PAD_X = 6
OVERLAY_LOG_PANEL_PAD_Y = (8, 10)
OVERLAY_LOG_TEXT_PAD_X = 8
OVERLAY_LOG_TEXT_PAD_Y = 7
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
    if not balance_text:
        balance_text = str(state.current_balance or "").strip()
    if not balance_text:
        return "待确认"

    mode = str(getattr(state, "balance_display_mode", "") or "").strip()
    if mode in ("新", "沿"):
        return f"{mode}{balance_text}"
    return balance_text


def _get_current_inventory():
    return max(0, int(state.baseline_item_count or 0))


def _format_overlay_value(value, fallback="--"):
    text = str(value or "").strip()
    return text or fallback


def _build_score_item(
    parent,
    *,
    title,
    value_key,
    value_width,
    value_font,
    value_fg,
    score_vars,
    title_fg=None,
    value_padx=(10, 0),
    value_anchor="e",
    value_sticky="e",
):
    item = tk.Frame(
        parent,
        bg=OVERLAY_SCORE_ITEM_BG,
        bd=0,
        highlightthickness=1,
        highlightbackground=OVERLAY_SCORE_ITEM_BORDER,
    )
    item.grid_columnconfigure(0, weight=1)
    item.grid_columnconfigure(1, weight=1)
    item.grid_rowconfigure(0, weight=1)

    if title:
        title_label = tk.Label(
            item,
            text=title,
            font=OVERLAY_SCORE_LABEL_FONT,
            fg=title_fg or OVERLAY_SCORE_LABEL_FG,
            bg=OVERLAY_SCORE_ITEM_BG,
            anchor="w",
        )
        title_label.grid(
            row=0,
            column=0,
            sticky="w",
            padx=OVERLAY_SCORE_TITLE_PAD_X,
            pady=OVERLAY_SCORE_TEXT_PAD_Y,
        )

    value_var = tk.StringVar(master=parent, value="--")
    value_label = tk.Label(
        item,
        textvariable=value_var,
        font=value_font,
        fg=value_fg,
        bg=OVERLAY_SCORE_ITEM_BG,
        anchor=value_anchor,
        width=value_width,
    )
    if title:
        value_label.grid(row=0, column=1, sticky=value_sticky, padx=value_padx, pady=OVERLAY_SCORE_TEXT_PAD_Y)
    else:
        value_label.grid(
            row=0,
            column=0,
            columnspan=2,
            sticky=value_sticky,
            padx=value_padx,
            pady=OVERLAY_SCORE_TEXT_PAD_Y,
        )

    score_vars[value_key] = value_var
    return item


def _create_score_panel(root):
    panel = tk.Frame(root, bg=OVERLAY_SCORE_PANEL_BG, bd=0, highlightthickness=0)
    panel._overlay_score_value_vars = {}

    main_shell = tk.Frame(
        panel,
        bg=OVERLAY_SCORE_MAIN_BORDER,
        bd=0,
        highlightthickness=0,
    )
    main_shell.pack(fill="x")

    body = tk.Frame(
        main_shell,
        bg=OVERLAY_SCORE_MAIN_BG,
        bd=0,
        highlightthickness=0,
    )
    body.pack(fill="x", padx=1, pady=1)

    row_specs = [
        (
            {"title": "", "value_key": "remaining", "value_width": 8, "value_font": OVERLAY_SCORE_TIME_FONT, "value_fg": OVERLAY_SCORE_TIME_FG, "value_padx": 0, "value_anchor": "center", "value_sticky": "ew"},
            {"title": "执行位", "value_key": "slot", "value_width": 3, "value_font": OVERLAY_SCORE_SLOT_FONT, "value_fg": OVERLAY_SCORE_SLOT_FG, "title_fg": OVERLAY_SCORE_SLOT_LABEL_FG, "value_padx": OVERLAY_SCORE_VALUE_GAP_FIRST_ROW},
        ),
        (
            {"title": "上架成功", "value_key": "listing_success", "value_width": 4, "value_font": OVERLAY_SCORE_VALUE_FONT, "value_fg": OVERLAY_SCORE_VALUE_FG, "value_padx": OVERLAY_SCORE_VALUE_GAP},
            {"title": "道具库存", "value_key": "inventory", "value_width": 4, "value_font": OVERLAY_SCORE_VALUE_FONT, "value_fg": OVERLAY_SCORE_VALUE_FG, "value_padx": OVERLAY_SCORE_VALUE_GAP},
        ),
        (
            {"title": "抢购成功", "value_key": "purchase_success", "value_width": 4, "value_font": OVERLAY_SCORE_VALUE_FONT, "value_fg": OVERLAY_SCORE_VALUE_FG, "value_padx": OVERLAY_SCORE_VALUE_GAP},
            {"title": "抢购失败", "value_key": "purchase_fail", "value_width": 4, "value_font": OVERLAY_SCORE_VALUE_FONT, "value_fg": OVERLAY_SCORE_FAIL_FG, "value_padx": OVERLAY_SCORE_VALUE_GAP},
        ),
    ]

    for row_index, row_spec in enumerate(row_specs):
        row = tk.Frame(body, bg=OVERLAY_SCORE_MAIN_BG, bd=0, highlightthickness=0)
        row.grid(
            row=row_index,
            column=0,
            sticky="ew",
            padx=OVERLAY_SCORE_MAIN_PAD_X,
            pady=(OVERLAY_SCORE_MAIN_PAD_Y, OVERLAY_SCORE_ROW_GAP)
            if row_index == 0
            else (0, OVERLAY_SCORE_ROW_GAP)
            if row_index < len(row_specs) - 1
            else (0, OVERLAY_SCORE_MAIN_PAD_Y),
        )
        row.grid_columnconfigure(0, weight=1, uniform="overlay_score")
        row.grid_columnconfigure(1, weight=1, uniform="overlay_score")

        left_item = _build_score_item(row, score_vars=panel._overlay_score_value_vars, **row_spec[0])
        right_item = _build_score_item(row, score_vars=panel._overlay_score_value_vars, **row_spec[1])
        left_item.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=(0, OVERLAY_SCORE_COLUMN_GAP),
            ipadx=OVERLAY_SCORE_ITEM_PAD_X,
            ipady=OVERLAY_SCORE_ITEM_PAD_Y_FIRST_ROW if row_index == 0 else OVERLAY_SCORE_ITEM_PAD_Y,
        )
        right_item.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(OVERLAY_SCORE_COLUMN_GAP, 0),
            ipadx=OVERLAY_SCORE_ITEM_PAD_X,
            ipady=OVERLAY_SCORE_ITEM_PAD_Y_FIRST_ROW if row_index == 0 else OVERLAY_SCORE_ITEM_PAD_Y,
        )

    balance_row = tk.Frame(body, bg=OVERLAY_SCORE_MAIN_BG, bd=0, highlightthickness=0)
    balance_row.grid(
        row=len(row_specs),
        column=0,
        sticky="ew",
        padx=OVERLAY_SCORE_MAIN_PAD_X,
        pady=(0, OVERLAY_SCORE_MAIN_PAD_Y),
    )
    balance_row.grid_columnconfigure(0, weight=1)

    balance_item = _build_score_item(
        balance_row,
        title="余额",
        value_key="balance",
        value_width=10,
        value_font=OVERLAY_SCORE_VALUE_FONT,
        value_fg=OVERLAY_SCORE_VALUE_FG,
        value_padx=OVERLAY_SCORE_VALUE_GAP,
        score_vars=panel._overlay_score_value_vars,
    )
    balance_item.grid(
        row=0,
        column=0,
        sticky="ew",
        ipadx=OVERLAY_SCORE_ITEM_PAD_X,
        ipady=OVERLAY_SCORE_ITEM_PAD_Y,
    )

    root._overlay_score_value_vars = panel._overlay_score_value_vars
    return panel


def _set_score_panel_values(root, values):
    value_vars = getattr(root, "_overlay_score_value_vars", None)
    if not value_vars:
        return
    for key, value in values.items():
        value_var = value_vars.get(key)
        if value_var is not None:
            value_var.set(_format_overlay_value(value))


def _apply_log_panel_style(root):
    log_label = getattr(root, "_overlay_log_label", None)
    if log_label is None:
        return

    try:
        log_label.configure(
            bg=OVERLAY_LOG_PANEL_BG,
            fg=OVERLAY_LOG_TEXT_FG,
            bd=0,
            highlightthickness=1,
            highlightbackground=OVERLAY_LOG_PANEL_BORDER,
            highlightcolor=OVERLAY_LOG_PANEL_BORDER,
            justify="left",
            anchor="w",
            padx=OVERLAY_LOG_TEXT_PAD_X,
            pady=OVERLAY_LOG_TEXT_PAD_Y,
        )
        if log_label.winfo_manager() == "pack":
            log_label.pack_configure(padx=OVERLAY_LOG_PANEL_PAD_X, pady=OVERLAY_LOG_PANEL_PAD_Y, fill="x")
    except Exception:
        pass


def apply_overlay_normal_layout(root):
    """按启动时的正常模式样式重新挂载计分板和日志区。"""
    if root is None:
        return

    score_label = getattr(root, "_overlay_score_label", None)
    log_label = getattr(root, "_overlay_log_label", None)

    if score_label is not None:
        if isinstance(score_label, tk.Label):
            score_label.configure(**OVERLAY_SCORE_LABEL_STYLE)
            score_label.pack(**OVERLAY_SCORE_LABEL_PACK)
        else:
            try:
                score_label.configure(bg=OVERLAY_SCORE_PANEL_BG)
            except Exception:
                pass
            score_label.pack(
                **{**OVERLAY_SCORE_LABEL_PACK, "padx": OVERLAY_SCORE_PANEL_PAD_X, "pady": OVERLAY_SCORE_PANEL_PAD_Y},
                fill="x",
            )

    if log_label is not None:
        log_label.configure(**OVERLAY_LOG_LABEL_STYLE)
        if isinstance(score_label, tk.Label):
            log_label.pack(**OVERLAY_LOG_LABEL_PACK)
        else:
            log_label.pack(
                **{**OVERLAY_LOG_LABEL_PACK, "padx": OVERLAY_LOG_PANEL_PAD_X, "pady": OVERLAY_LOG_PANEL_PAD_Y},
                fill="x",
            )
            _apply_log_panel_style(root)


def update_score_text():
    root = state.overlay_root
    if not root:
        return

    remaining_text = _format_duration(get_runtime_window_remaining_seconds())
    slot_text = str(state.current_execution_slot or "--")
    current_inventory = _get_current_inventory()
    balance_text = _get_balance_display_text()
    values = {
        "slot": slot_text,
        "remaining": remaining_text,
        "listing_success": state.round_listing_success_count,
        "inventory": current_inventory,
        "purchase_success": state.round_purchase_success_count,
        "purchase_fail": state.round_purchase_fail_count,
        "balance": balance_text,
    }
    try:
        if state.score_var is not None:
            state.score_var.set(
                "\n".join(
                    [
                        f"执行位 {slot_text}  时间剩余 {remaining_text}",
                        f"上架成功 {state.round_listing_success_count}  道具库存 {current_inventory}",
                        f"抢购成功 {state.round_purchase_success_count}  抢购失败 {state.round_purchase_fail_count}",
                        f"余额 {balance_text}",
                    ]
                )
            )
        _set_score_panel_values(root, values)
        _apply_log_panel_style(root)
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
    root.config(bg=OVERLAY_SCORE_PANEL_BG)
    root._overlay_is_mini = False
    root._overlay_normal_position = OVERLAY_NORMAL_GEOMETRY
    state.log_lines = []
    state.overlay_last_log_replaceable = False

    state.score_var = tk.StringVar()
    root._overlay_score_label = _create_score_panel(root)

    state.log_text_var = tk.StringVar()
    state.log_text_var.set("悬浮窗已就绪。")
    root._overlay_log_label = tk.Label(
        root,
        textvariable=state.log_text_var,
        **OVERLAY_LOG_LABEL_STYLE,
    )
    apply_overlay_normal_layout(root)

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
    if state.log_lines and state.overlay_last_log_replaceable:
        if is_replace:
            state.log_lines[-1] = gui_msg
        else:
            # 正式日志到来时，收掉尾部临时 replace 行，避免结果日志和旧临时日志同时残留。
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
        ui_print("脚本暂停（F12 恢复）")
        pause_persist_result = persist_pause_snapshot()
        if pause_persist_result.status == "success":
            ui_print("暂停后已写入库", save_log=True)
        elif pause_persist_result.status != "skipped":
            ui_print(f"暂停写库失败：{pause_persist_result.reason}", save_log=True)
        if state.overlay_root:
            try:
                enqueue_overlay_task(state.overlay_root.withdraw)
            except Exception:
                pass
        try:
            from param_editor_gui import show_param_editor
            show_param_editor()
        except Exception:
            pass
    else:
        try:
            from param_editor_gui import destroy_param_editor
            destroy_param_editor()
        except Exception:
            pass
        state.last_resume_time = time.time()
        if state.overlay_root:
            try:
                enqueue_overlay_task(state.overlay_root.deiconify)
            except Exception:
                pass
        resume_persist_result = persist_resume_snapshot()
        if resume_persist_result.status == "success":
            ui_print("脚本恢复（F12 暂停）")
        elif resume_persist_result.status == "skipped":
            ui_print("脚本恢复（F12 暂停）")
        else:
            ui_print(f"脚本恢复，回写失败：{resume_persist_result.reason}", save_log=True)


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
