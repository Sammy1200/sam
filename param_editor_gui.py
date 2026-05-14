"""param_editor_gui.py  F12 暂停态参数修改面板（收起/展开）"""

import tkinter as tk
from datetime import datetime

import listing
import state
from local_switch_account_config import save_listing_target_price
from machine_sync_config import get_machine_sync_runtime_context
from overlay import enqueue_overlay_task, schedule_pause_auto_resume
from round_persistence import persist_minimal_item_balance_sync

# ── 模块级引用 ──
_editor_win = None

# ── 配色（深褐色主题，匹配主悬浮窗风格）──
_BG         = "#1c1714"
_BG_HEADER  = "#251e19"
_FG         = "#e0d8d0"
_FG_DIM     = "#9a918a"
_ACCENT     = "#6b5d50"
_ACCENT_HV  = "#8a7a6a"
_SUCCESS    = "#7acc7a"
_ERROR      = "#e07070"
_ENTRY_BG   = "#2a211a"
_ENTRY_FG   = "#f0ece8"
_BORDER     = "#3a3028"

# ── 字体 ──
_FONT_TITLE = ("Microsoft YaHei UI", 11, "bold")
_FONT_LABEL = ("Microsoft YaHei UI", 9)
_FONT_ENTRY = ("Consolas", 10)
_FONT_BTN   = ("Microsoft YaHei UI", 9, "bold")
_FONT_MSG   = ("Microsoft YaHei UI", 8)


# ═══════════════════════════════════════
#  公开接口（签名不变）
# ═══════════════════════════════════════

def show_param_editor():
    enqueue_overlay_task(_create_editor)


def destroy_param_editor():
    enqueue_overlay_task(_destroy_editor)


# ═══════════════════════════════════════
#  内部实现
# ═══════════════════════════════════════

def _destroy_editor():
    global _editor_win
    if _editor_win is not None:
        try:
            if _editor_win.winfo_exists():
                _editor_win.destroy()
        except Exception:
            pass
    _editor_win = None


def _format_editor_machine_label():
    runtime_context = get_machine_sync_runtime_context()
    machine_id = str(runtime_context.get("machine_id") or "").strip().lower()
    machine_display_name = str(runtime_context.get("machine_display_name") or "").strip()

    machine_id_to_pc = {
        "pc1": "PC1",
        "pc2": "PC2",
        "pc3": "PC3",
        "pc4": "PC4",
    }
    if machine_id in machine_id_to_pc:
        return machine_id_to_pc[machine_id]

    for suffix in ("1", "2", "3", "4"):
        if machine_display_name == f"{suffix}号电脑":
            return f"PC{suffix}"

    fallback_machine_id = str(runtime_context.get("machine_id") or "").strip()
    return machine_display_name or fallback_machine_id or "本机"


def _format_editor_execution_slot():
    raw_slot = state.current_execution_slot
    try:
        normalized_slot = int(raw_slot)
        if normalized_slot > 0:
            return str(normalized_slot)
    except (TypeError, ValueError):
        pass

    slot_text = str(raw_slot or "").strip()
    if slot_text.isdigit() and int(slot_text) > 0:
        return slot_text
    return "--"


def _build_editor_title_text():
    return f" {_format_editor_machine_label()} - {_format_editor_execution_slot()}"


def _format_duration(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _create_editor():
    global _editor_win
    _destroy_editor()

    root = state.overlay_root
    if not root:
        return

    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg=_BG, highlightbackground=_BORDER, highlightthickness=1)
    win.geometry("+30+30")
    _editor_win = win

    # ── 状态 ──
    expanded = [False]
    is_brutal_mode = bool(getattr(state, "brutal_purchase_mode", False))
    msg_var = tk.StringVar(value="")
    title_base_text = _build_editor_title_text()
    title_var = tk.StringVar(value=title_base_text)

    # ══════════════════════════════════
    #  标题行（始终可见，点击切换展开）
    # ══════════════════════════════════
    header = tk.Frame(win, bg=_BG_HEADER, cursor="hand2", padx=10, pady=6)
    header.pack(fill="x")

    arrow_var = tk.StringVar(value="▶")
    lbl_arrow = tk.Label(header, textvariable=arrow_var,
                         font=_FONT_TITLE, fg=_ACCENT, bg=_BG_HEADER)
    lbl_arrow.pack(side="left")

    lbl_title = tk.Label(header, textvariable=title_var,
                         font=_FONT_TITLE, fg=_FG, bg=_BG_HEADER)
    lbl_title.pack(side="left")

    # ══════════════════════════════════
    #  展开区域（初始隐藏）
    # ══════════════════════════════════
    body = tk.Frame(win, bg=_BG, padx=10, pady=6)

    # ── 价格行 ──
    price_row = tk.Frame(body, bg=_BG)
    price_row.pack(fill="x", pady=(0, 4))

    current_price = str(getattr(listing, "LISTING_TARGET_PRICE", "?"))
    price_lbl = tk.Label(price_row, text=f"价格: {current_price}",
                         font=_FONT_LABEL, fg=_FG_DIM, bg=_BG,
                         width=14, anchor="w")
    price_lbl.pack(side="left")

    price_entry = tk.Entry(price_row, font=_FONT_ENTRY, width=10,
                           bg=_ENTRY_BG, fg=_ENTRY_FG,
                           insertbackground=_ENTRY_FG, relief="flat",
                           highlightthickness=1, highlightcolor=_ACCENT,
                           highlightbackground=_BORDER)
    price_entry.insert(0, current_price)
    price_entry.pack(side="left", padx=(4, 6), ipady=3)

    price_btn = tk.Label(price_row, text=" 修改 ", font=_FONT_BTN,
                         fg=_FG, bg=_ACCENT, cursor="hand2",
                         padx=6, pady=1)
    price_btn.pack(side="left")

    # ── 库存行（变量名已修正为 baseline_item_count）──
    stock_row = tk.Frame(body, bg=_BG)
    stock_row.pack(fill="x", pady=(0, 4))

    current_stock = str(getattr(state, "baseline_item_count", "?"))
    stock_lbl = tk.Label(stock_row, text=f"库存: {current_stock}",
                         font=_FONT_LABEL, fg=_FG_DIM, bg=_BG,
                         width=14, anchor="w")
    stock_lbl.pack(side="left")

    stock_entry = tk.Entry(stock_row, font=_FONT_ENTRY, width=10,
                           bg=_ENTRY_BG, fg=_ENTRY_FG,
                           insertbackground=_ENTRY_FG, relief="flat",
                           highlightthickness=1, highlightcolor=_ACCENT,
                           highlightbackground=_BORDER)
    stock_entry.insert(0, current_stock)
    stock_entry.pack(side="left", padx=(4, 6), ipady=3)

    stock_btn = tk.Label(stock_row, text=" 修改 ", font=_FONT_BTN,
                         fg=_FG, bg=_ACCENT, cursor="hand2",
                         padx=6, pady=1)
    stock_btn.pack(side="left")

    if is_brutal_mode:
        price_row.pack_forget()
        stock_row.pack_forget()

    # ── F12 自动恢复倒计时行 ──
    resume_row = tk.Frame(body, bg=_BG)
    resume_row.pack(fill="x", pady=(0, 4))

    resume_lbl = tk.Label(resume_row, text="恢复:",
                          font=_FONT_LABEL, fg=_FG_DIM, bg=_BG,
                          width=14, anchor="w")
    resume_lbl.pack(side="left")

    resume_entry = tk.Entry(resume_row, font=_FONT_ENTRY, width=10,
                            bg=_ENTRY_BG, fg=_ENTRY_FG,
                            insertbackground=_ENTRY_FG, relief="flat",
                            highlightthickness=1, highlightcolor=_ACCENT,
                            highlightbackground=_BORDER)
    resume_entry.pack(side="left", padx=(4, 6), ipady=3)

    resume_btn = tk.Label(resume_row, text=" 应用 ", font=_FONT_BTN,
                          fg=_FG, bg=_ACCENT, cursor="hand2",
                          padx=6, pady=1)
    resume_btn.pack(side="left")

    # ── 暴力模式抢购上限行 ──
    brutal_limit_row = tk.Frame(body, bg=_BG)
    if is_brutal_mode:
        brutal_limit_row.pack(fill="x", pady=(0, 4))

    brutal_limit_lbl = tk.Label(brutal_limit_row, text="抢购上限:",
                                font=_FONT_LABEL, fg=_FG_DIM, bg=_BG,
                                width=14, anchor="w")
    brutal_limit_lbl.pack(side="left")

    brutal_limit_entry = tk.Entry(brutal_limit_row, font=_FONT_ENTRY, width=10,
                                  bg=_ENTRY_BG, fg=_ENTRY_FG,
                                  insertbackground=_ENTRY_FG, relief="flat",
                                  highlightthickness=1, highlightcolor=_ACCENT,
                                  highlightbackground=_BORDER)
    if getattr(state, "brutal_purchase_limit_enabled", False):
        brutal_limit_entry.insert(0, str(int(getattr(state, "brutal_purchase_limit", 0) or 0)))
    brutal_limit_entry.pack(side="left", padx=(4, 6), ipady=3)

    brutal_limit_btn = tk.Label(brutal_limit_row, text=" 应用 ", font=_FONT_BTN,
                                fg=_FG, bg=_ACCENT, cursor="hand2",
                                padx=6, pady=1)
    brutal_limit_btn.pack(side="left")

    # ── 消息行 ──
    msg_label = tk.Label(body, textvariable=msg_var,
                         font=_FONT_MSG, fg=_SUCCESS, bg=_BG, anchor="w")
    msg_label.pack(fill="x", pady=(2, 0))

    # ══════════════════════════════════
    #  展开 / 收起
    # ══════════════════════════════════
    def _toggle(event=None):
        if expanded[0]:
            body.pack_forget()
            arrow_var.set("▶")
            expanded[0] = False
        else:
            body.pack(fill="x", after=header)
            arrow_var.set("▼")
            expanded[0] = True
            win.focus_force()
            if is_brutal_mode:
                brutal_limit_entry.focus_set()
            else:
                price_entry.focus_set()
        win.update_idletasks()

    for w in (header, lbl_arrow, lbl_title):
        w.bind("<Button-1>", _toggle)

    # ══════════════════════════════════
    #  按钮 Hover 效果
    # ══════════════════════════════════
    def _hover_in(e):
        e.widget.configure(bg=_ACCENT_HV)

    def _hover_out(e):
        e.widget.configure(bg=_ACCENT)

    for btn in (price_btn, stock_btn, resume_btn, brutal_limit_btn):
        btn.bind("<Enter>", _hover_in)
        btn.bind("<Leave>", _hover_out)

    # ══════════════════════════════════
    #  消息显示
    # ══════════════════════════════════
    def _show_msg(text, color=_SUCCESS):
        msg_var.set(text)
        msg_label.configure(fg=color)

    def _collapse_body():
        body.pack_forget()
        arrow_var.set("▶")
        expanded[0] = False
        win.update_idletasks()

    def _refresh_resume_countdown():
        try:
            if not win.winfo_exists():
                return
        except Exception:
            return

        deadline = getattr(state, "pause_auto_resume_deadline", None)
        if deadline is None or not state.IS_PAUSED:
            title_var.set(title_base_text)
            return

        remaining_seconds = (deadline - datetime.now()).total_seconds()
        if remaining_seconds <= 0:
            title_var.set(f"{title_base_text}  恢复 00:00:00")
            return

        display_seconds = max(1, int(remaining_seconds + 0.999))
        title_var.set(f"{title_base_text}  恢复 {_format_duration(display_seconds)}")
        win.after(1000, _refresh_resume_countdown)

    # ══════════════════════════════════
    #  价格修改
    # ══════════════════════════════════
    def _do_save_price(event=None):
        raw = price_entry.get().strip()
        if not raw:
            _show_msg("✗ 请输入价格", _ERROR)
            return
        try:
            save_listing_target_price(raw)
            listing.LISTING_TARGET_PRICE = raw
            price_lbl.configure(text=f"价格: {raw}")
            _show_msg("✓ 价格已更新")
        except Exception as ex:
            _show_msg(f"✗ {ex}", _ERROR)

    price_btn.bind("<Button-1>", _do_save_price)
    price_entry.bind("<Return>", _do_save_price)
    price_entry.bind("<KP_Enter>", _do_save_price)

    # ══════════════════════════════════
    #  库存修改（写内存 baseline_item_count + 持久化）
    # ══════════════════════════════════
    def _do_save_stock(event=None):
        raw = stock_entry.get().strip()
        if not raw:
            _show_msg("✗ 请输入库存", _ERROR)
            return
        try:
            new_val = int(raw)
        except ValueError:
            _show_msg("✗ 库存必须是整数", _ERROR)
            return
        try:
            if (
                str(getattr(state, "account_db_mode", "stone") or "stone") == "stone"
                and not bool(getattr(state, "accessory_purchase_mode", False))
                and not bool(getattr(state, "temporary_purchase_mode", False))
            ):
                locked_count = int(getattr(state, "locked_item_count", 0) or 0)
                if new_val < locked_count:
                    _show_msg("✗ 库存小于不可交易", _ERROR)
                    return
                state.tradable_item_count = new_val - locked_count
            state.baseline_item_count = new_val
            result = persist_minimal_item_balance_sync()
            if not result:
                _show_msg("✗ 库存写入失败", _ERROR)
                return
            stock_lbl.configure(text=f"库存: {new_val}")
            _show_msg("✓ 库存已更新")
        except Exception as ex:
            _show_msg(f"✗ {ex}", _ERROR)

    stock_btn.bind("<Button-1>", _do_save_stock)
    stock_entry.bind("<Return>", _do_save_stock)
    stock_entry.bind("<KP_Enter>", _do_save_stock)

    # ══════════════════════════════════
    #  F12 暂停后倒计时恢复
    # ══════════════════════════════════
    def _do_apply_auto_resume(event=None):
        raw = resume_entry.get().strip()
        if not raw:
            _show_msg("✗ 请输入分钟", _ERROR)
            return
        if not raw.isdigit():
            _show_msg("✗ 分钟必须是整数", _ERROR)
            return
        minutes = int(raw)
        if minutes <= 0:
            _show_msg("✗ 分钟必须大于0", _ERROR)
            return

        result = schedule_pause_auto_resume(minutes)
        if result.get("status") != "success":
            _show_msg(f"✗ {result.get('message') or '设置失败'}", _ERROR)
            return

        _show_msg("✓ 已设置恢复")
        _collapse_body()
        _refresh_resume_countdown()

    resume_btn.bind("<Button-1>", _do_apply_auto_resume)
    resume_entry.bind("<Return>", _do_apply_auto_resume)
    resume_entry.bind("<KP_Enter>", _do_apply_auto_resume)

    # ══════════════════════════════════
    #  暴力模式抢购上限
    # ══════════════════════════════════
    def _do_apply_brutal_limit(event=None):
        raw = brutal_limit_entry.get().strip()
        if not raw or raw == "0":
            state.brutal_purchase_limit = 0
            state.brutal_purchase_limit_enabled = False
            _show_msg("✓ 上限不限")
            return
        if not raw.isdigit():
            _show_msg("✗ 上限必须是整数", _ERROR)
            return

        limit = int(raw)
        if limit <= 0:
            state.brutal_purchase_limit = 0
            state.brutal_purchase_limit_enabled = False
            _show_msg("✓ 上限不限")
            return

        state.brutal_purchase_limit = limit
        state.brutal_purchase_limit_enabled = True
        _show_msg("✓ 上限已设置")
        _collapse_body()

    brutal_limit_btn.bind("<Button-1>", _do_apply_brutal_limit)
    brutal_limit_entry.bind("<Return>", _do_apply_brutal_limit)
    brutal_limit_entry.bind("<KP_Enter>", _do_apply_brutal_limit)
