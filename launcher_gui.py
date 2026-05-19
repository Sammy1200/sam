import ctypes
import sys
import time
import tkinter as tk
from tkinter import messagebox

from local_switch_account_config import (
    STONE_PRICE_MODE_FIXED_RANGE,
    STONE_PRICE_MODE_PREFIX,
    load_launcher_settings,
    save_launcher_settings,
)


_VK_F9 = 0x78
_last_f9_toggle_at = 0.0


def _close_launcher_counter():
    try:
        from jishujiaoben.floating_counter import destroy_counter

        destroy_counter()
    except Exception:
        pass


def _toggle_launcher_counter(root):
    global _last_f9_toggle_at
    now = time.monotonic()
    if now - _last_f9_toggle_at < 0.25:
        return
    _last_f9_toggle_at = now
    try:
        from jishujiaoben.floating_counter import toggle_counter

        toggle_counter(root)
    except Exception as exc:
        print(f"[启动器] F9计数窗失败：{exc}")


def _load_launcher_settings_for_ui():
    try:
        return load_launcher_settings()
    except Exception as exc:
        print(f"[启动器] 参数设置读取失败：{exc}")
        return {
            "listing_enabled": True,
            "stone_purchase_price_mode": STONE_PRICE_MODE_PREFIX,
            "stone_fixed_price_min_inclusive": 325000,
            "stone_fixed_price_max_inclusive": 2099999,
            "equipment_price_min_exclusive": 50000,
            "equipment_price_max_exclusive": 4200000,
            "source_path": "",
        }


def _install_launcher_f9_listener(root):
    if sys.platform != "win32":
        return lambda: None, False

    try:
        user32 = ctypes.windll.user32
        user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        user32.GetAsyncKeyState.restype = ctypes.c_short
    except Exception as exc:
        print(f"[启动器] F9监听初始化失败：{exc}")
        return lambda: None, False

    active = [True]
    after_id = [None]
    last_f9_down = [False]

    def poll_f9():
        if not active[0]:
            return
        try:
            if not root.winfo_exists():
                return
            is_f9_down = bool(user32.GetAsyncKeyState(_VK_F9) & 0x8000)
            if is_f9_down and not last_f9_down[0]:
                _toggle_launcher_counter(root)
            last_f9_down[0] = is_f9_down
            after_id[0] = root.after(50, poll_f9)
        except Exception as exc:
            print(f"[启动器] F9监听失败：{exc}")

    after_id[0] = root.after(50, poll_f9)

    def cleanup():
        if not active[0]:
            return
        active[0] = False
        if after_id[0] is not None:
            try:
                root.after_cancel(after_id[0])
            except Exception:
                pass

    return cleanup, True


def show_launcher():
    """
    弹出启动器窗口，阻塞等待用户选择。

    返回:
        ("launcher", True/False)           — 登录界面启动，第二项表示是否启用上架
        ("listing_launcher", True)          — 启动页上架模式
        ("temporary_launcher", True/False)  — 启动页临时抢购模式，第二项表示是否启用上架
        ("brutal_launcher", False)          — 暴力模式
        ("accessory_launcher", False)       — 饰品抢购模式
        ("equipment_launcher", False)       — 装备抢购模式
    """
    result = [None]
    root = tk.Tk()
    root.title("古墓迷途 - 启动器")
    root.configure(bg="#101217")
    root.resizable(False, False)

    window_width = 360
    window_height = 450
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    pos_x = (screen_width - window_width) // 2
    pos_y = (screen_height - window_height) // 2
    root.geometry(f"{window_width}x{window_height}+{pos_x}+{pos_y}")

    cleanup_f9_listener, _ = _install_launcher_f9_listener(root)
    root.bind_all("<F9>", lambda _event: _toggle_launcher_counter(root))
    root.bind_all("<KeyPress-F9>", lambda _event: _toggle_launcher_counter(root))

    def close_launcher():
        cleanup_f9_listener()
        _close_launcher_counter()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close_launcher)

    panel = tk.Frame(root, bg="#151922", padx=28, pady=0)
    panel.pack(fill="both", expand=True, padx=1, pady=1)

    button_frame = tk.Frame(panel, bg="#151922")
    button_frame.pack(expand=True, fill="x")
    settings = [_load_launcher_settings_for_ui()]
    listing_enabled_var = tk.BooleanVar(master=root, value=bool(settings[0]["listing_enabled"]))

    def _current_listing_enabled():
        return bool(listing_enabled_var.get())

    def choose_launcher():
        current_listing_enabled = _current_listing_enabled()
        cleanup_f9_listener()
        _close_launcher_counter()
        result[0] = ("launcher", current_listing_enabled)
        root.destroy()

    def choose_listing_launcher():
        if not _current_listing_enabled():
            return
        cleanup_f9_listener()
        _close_launcher_counter()
        result[0] = ("listing_launcher", True)
        root.destroy()

    def choose_temporary_launcher():
        current_listing_enabled = _current_listing_enabled()
        cleanup_f9_listener()
        _close_launcher_counter()
        result[0] = ("temporary_launcher", current_listing_enabled)
        root.destroy()

    def choose_brutal_launcher():
        cleanup_f9_listener()
        _close_launcher_counter()
        result[0] = ("brutal_launcher", False)
        root.destroy()

    def choose_accessory_launcher():
        cleanup_f9_listener()
        _close_launcher_counter()
        result[0] = ("accessory_launcher", False)
        root.destroy()

    def choose_equipment_launcher():
        cleanup_f9_listener()
        _close_launcher_counter()
        result[0] = ("equipment_launcher", False)
        root.destroy()

    def create_mode_button(text, command, is_primary=False):
        bg = "#2563eb" if is_primary else "#202635"
        hover_bg = "#1d4ed8" if is_primary else "#293145"
        button = tk.Button(
            button_frame,
            text=text,
            width=22,
            height=2,
            bg=bg,
            fg="#ffffff",
            activebackground=hover_bg,
            activeforeground="#ffffff",
            font=("Microsoft YaHei UI", 11, "bold"),
            relief="flat",
            bd=0,
            cursor="hand2",
            command=command,
        )
        button.bind("<Enter>", lambda _event: button.configure(bg=hover_bg))
        button.bind("<Leave>", lambda _event: button.configure(bg=bg))
        return button

    def sync_listing_button_state():
        if _current_listing_enabled():
            listing_button.configure(state="normal", cursor="hand2")
        else:
            listing_button.configure(state="disabled", cursor="arrow")

    def open_settings_window():
        settings_window = tk.Toplevel(root)
        settings_window.title("参数设置")
        settings_window.configure(bg="#101217")
        settings_window.resizable(False, False)
        settings_window.transient(root)
        settings_window.grab_set()
        settings_window.protocol(
            "WM_DELETE_WINDOW",
            lambda: (settings_window.grab_release(), settings_window.destroy()),
        )

        window_width = 560
        window_height = 560
        root.update_idletasks()
        pos_x = root.winfo_rootx() + (root.winfo_width() - window_width) // 2
        pos_y = root.winfo_rooty() + (root.winfo_height() - window_height) // 2
        settings_window.geometry(f"{window_width}x{window_height}+{pos_x}+{pos_y}")

        outer = tk.Frame(settings_window, bg="#151922", padx=24, pady=20)
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        listing_var = tk.BooleanVar(master=settings_window, value=_current_listing_enabled())
        mode_var = tk.StringVar(
            master=settings_window,
            value=str(settings[0].get("stone_purchase_price_mode") or STONE_PRICE_MODE_PREFIX),
        )
        fixed_min_var = tk.StringVar(
            master=settings_window,
            value=str(settings[0].get("stone_fixed_price_min_inclusive") or ""),
        )
        fixed_max_var = tk.StringVar(
            master=settings_window,
            value=str(settings[0].get("stone_fixed_price_max_inclusive") or ""),
        )
        equipment_min_var = tk.StringVar(
            master=settings_window,
            value=str(settings[0].get("equipment_price_min_exclusive") or ""),
        )
        equipment_max_var = tk.StringVar(
            master=settings_window,
            value=str(settings[0].get("equipment_price_max_exclusive") or ""),
        )

        def create_section(parent, title):
            section = tk.Frame(
                parent,
                bg="#1b2130",
                highlightthickness=1,
                highlightbackground="#2d3548",
                padx=16,
                pady=14,
            )
            title_label = tk.Label(
                section,
                text=title,
                bg="#1b2130",
                fg="#ffffff",
                font=("Microsoft YaHei UI", 11, "bold"),
                anchor="w",
            )
            title_label.pack(anchor="w")
            return section

        global_section = create_section(outer, "全局设置")
        global_section.pack(fill="x")
        listing_check = tk.Checkbutton(
            global_section,
            text="启用上架",
            variable=listing_var,
            bg="#1b2130",
            fg="#ffffff",
            activebackground="#1b2130",
            activeforeground="#ffffff",
            selectcolor="#202635",
            font=("Microsoft YaHei UI", 10, "bold"),
            relief="flat",
            bd=0,
            cursor="hand2",
        )
        listing_check.pack(anchor="w", pady=(12, 0))

        stone_section = create_section(outer, "石头设置")
        stone_section.pack(fill="x", pady=(16, 0))

        radio_frame = tk.Frame(stone_section, bg="#1b2130")
        radio_frame.pack(fill="x", pady=(12, 0))
        prefix_radio = tk.Radiobutton(
            radio_frame,
            text="前缀抢购",
            variable=mode_var,
            value=STONE_PRICE_MODE_PREFIX,
            bg="#1b2130",
            fg="#ffffff",
            activebackground="#1b2130",
            activeforeground="#ffffff",
            selectcolor="#202635",
            font=("Microsoft YaHei UI", 10, "bold"),
            relief="flat",
            bd=0,
            cursor="hand2",
        )
        prefix_radio.pack(side="left")
        fixed_radio = tk.Radiobutton(
            radio_frame,
            text="固定上下限抢购",
            variable=mode_var,
            value=STONE_PRICE_MODE_FIXED_RANGE,
            bg="#1b2130",
            fg="#ffffff",
            activebackground="#1b2130",
            activeforeground="#ffffff",
            selectcolor="#202635",
            font=("Microsoft YaHei UI", 10, "bold"),
            relief="flat",
            bd=0,
            cursor="hand2",
        )
        fixed_radio.pack(side="left", padx=(26, 0))

        price_frame = tk.Frame(stone_section, bg="#1b2130")
        price_frame.pack(fill="x", pady=(16, 0))
        price_label = tk.Label(
            price_frame,
            text="石头价格",
            bg="#1b2130",
            fg="#d8dee9",
            font=("Microsoft YaHei UI", 10, "bold"),
            anchor="w",
        )
        price_label.grid(row=0, column=0, sticky="w", padx=(0, 12))
        min_entry = tk.Entry(
            price_frame,
            textvariable=fixed_min_var,
            width=14,
            bg="#101217",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            font=("Microsoft YaHei UI", 10),
        )
        min_entry.grid(row=0, column=1, sticky="w")
        range_label = tk.Label(
            price_frame,
            text="到",
            bg="#1b2130",
            fg="#d8dee9",
            font=("Microsoft YaHei UI", 10),
        )
        range_label.grid(row=0, column=2, padx=10)
        max_entry = tk.Entry(
            price_frame,
            textvariable=fixed_max_var,
            width=14,
            bg="#101217",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            font=("Microsoft YaHei UI", 10),
        )
        max_entry.grid(row=0, column=3, sticky="w")

        def sync_price_entry_state(*_args):
            entry_state = "normal" if mode_var.get() == STONE_PRICE_MODE_FIXED_RANGE else "disabled"
            min_entry.configure(state=entry_state)
            max_entry.configure(state=entry_state)

        mode_var.trace_add("write", sync_price_entry_state)
        sync_price_entry_state()

        equipment_section = create_section(outer, "装备设置")
        equipment_section.pack(fill="x", pady=(16, 0))
        equipment_price_frame = tk.Frame(equipment_section, bg="#1b2130")
        equipment_price_frame.pack(fill="x", pady=(12, 0))
        equipment_price_label = tk.Label(
            equipment_price_frame,
            text="装备价格",
            bg="#1b2130",
            fg="#d8dee9",
            font=("Microsoft YaHei UI", 10, "bold"),
            anchor="w",
        )
        equipment_price_label.grid(row=0, column=0, sticky="w", padx=(0, 12))
        equipment_min_entry = tk.Entry(
            equipment_price_frame,
            textvariable=equipment_min_var,
            width=14,
            bg="#101217",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            font=("Microsoft YaHei UI", 10),
        )
        equipment_min_entry.grid(row=0, column=1, sticky="w")
        equipment_range_label = tk.Label(
            equipment_price_frame,
            text="到",
            bg="#1b2130",
            fg="#d8dee9",
            font=("Microsoft YaHei UI", 10),
        )
        equipment_range_label.grid(row=0, column=2, padx=10)
        equipment_max_entry = tk.Entry(
            equipment_price_frame,
            textvariable=equipment_max_var,
            width=14,
            bg="#101217",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            font=("Microsoft YaHei UI", 10),
        )
        equipment_max_entry.grid(row=0, column=3, sticky="w")

        footer = tk.Frame(outer, bg="#151922")
        footer.pack(side="bottom", fill="x", pady=(20, 0))

        def save_settings():
            payload = {
                "listing_enabled": bool(listing_var.get()),
                "stone_purchase_price_mode": mode_var.get(),
                "stone_fixed_price_min_inclusive": fixed_min_var.get(),
                "stone_fixed_price_max_inclusive": fixed_max_var.get(),
                "equipment_price_min_exclusive": equipment_min_var.get(),
                "equipment_price_max_exclusive": equipment_max_var.get(),
            }
            try:
                saved_settings = save_launcher_settings(payload)
            except Exception as exc:
                messagebox.showerror("保存失败", str(exc), parent=settings_window)
                return

            settings[0] = saved_settings
            listing_enabled_var.set(bool(saved_settings["listing_enabled"]))
            sync_listing_button_state()
            settings_window.grab_release()
            settings_window.destroy()

        save_button = tk.Button(
            footer,
            text="保存",
            width=10,
            height=2,
            bg="#2563eb",
            fg="#ffffff",
            activebackground="#1d4ed8",
            activeforeground="#ffffff",
            font=("Microsoft YaHei UI", 10, "bold"),
            relief="flat",
            bd=0,
            cursor="hand2",
            command=save_settings,
        )
        save_button.pack(side="right")

    launcher_button = create_mode_button("正常启动", choose_launcher, is_primary=True)
    launcher_button.pack(fill="x")

    listing_button = create_mode_button("上架模式", choose_listing_launcher)
    listing_button.pack(fill="x", pady=(10, 0))

    temporary_button = create_mode_button("临时模式", choose_temporary_launcher)
    temporary_button.pack(fill="x", pady=(10, 0))

    brutal_button = create_mode_button("暴力模式", choose_brutal_launcher)
    brutal_button.pack(fill="x", pady=(10, 0))

    accessory_button = create_mode_button("饰品抢购", choose_accessory_launcher)
    accessory_button.pack(fill="x", pady=(10, 0))

    equipment_button = create_mode_button("装备抢购", choose_equipment_launcher)
    equipment_button.pack(fill="x", pady=(10, 0))

    settings_button = create_mode_button("功能设置", open_settings_window)
    settings_button.pack(fill="x", pady=(10, 0))
    sync_listing_button_state()

    root.mainloop()

    if result[0] is None:
        sys.exit(0)
    return result[0]


if __name__ == "__main__":
    choice = show_launcher()
    print(f"选择结果: {choice}")
