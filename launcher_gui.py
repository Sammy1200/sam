import ctypes
import json
import os
import sys
import time
import tkinter as tk

from live_paths import LIVE_ROOT_DIR


_VK_F9 = 0x78
_last_f9_toggle_at = 0.0
_LAUNCHER_PREFERENCES_PATH = os.path.join(LIVE_ROOT_DIR, "launcher_preferences.json")


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


def _load_listing_enabled_preference():
    try:
        with open(_LAUNCHER_PREFERENCES_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return True
    except Exception as exc:
        print(f"[启动器] 上架勾选记录读取失败：{exc}")
        return True

    value = data.get("listing_enabled")
    if isinstance(value, bool):
        return value
    return True


def _save_listing_enabled_preference(listing_enabled):
    try:
        os.makedirs(os.path.dirname(_LAUNCHER_PREFERENCES_PATH), exist_ok=True)
        payload = {
            "listing_enabled": bool(listing_enabled),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(_LAUNCHER_PREFERENCES_PATH, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"[启动器] 上架勾选记录保存失败：{exc}")


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
    """
    result = [None]
    root = tk.Tk()
    root.title("古墓迷途 - 启动器")
    root.configure(bg="#101217")
    root.resizable(False, False)

    window_width = 360
    window_height = 390
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
    listing_enabled_var = tk.BooleanVar(master=root, value=_load_listing_enabled_preference())

    def _current_listing_enabled():
        return bool(listing_enabled_var.get())

    def choose_launcher():
        current_listing_enabled = _current_listing_enabled()
        _save_listing_enabled_preference(current_listing_enabled)
        cleanup_f9_listener()
        _close_launcher_counter()
        result[0] = ("launcher", current_listing_enabled)
        root.destroy()

    def choose_listing_launcher():
        _save_listing_enabled_preference(True)
        cleanup_f9_listener()
        _close_launcher_counter()
        result[0] = ("listing_launcher", True)
        root.destroy()

    def choose_temporary_launcher():
        current_listing_enabled = _current_listing_enabled()
        _save_listing_enabled_preference(current_listing_enabled)
        cleanup_f9_listener()
        _close_launcher_counter()
        result[0] = ("temporary_launcher", current_listing_enabled)
        root.destroy()

    def choose_brutal_launcher():
        _save_listing_enabled_preference(_current_listing_enabled())
        cleanup_f9_listener()
        _close_launcher_counter()
        result[0] = ("brutal_launcher", False)
        root.destroy()

    def choose_accessory_launcher():
        _save_listing_enabled_preference(_current_listing_enabled())
        cleanup_f9_listener()
        _close_launcher_counter()
        result[0] = ("accessory_launcher", False)
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

    listing_check = tk.Checkbutton(
        panel,
        text="上架",
        variable=listing_enabled_var,
        command=sync_listing_button_state,
        bg="#151922",
        fg="#ffffff",
        activebackground="#151922",
        activeforeground="#ffffff",
        selectcolor="#202635",
        font=("Microsoft YaHei UI", 10, "bold"),
        relief="flat",
        bd=0,
        cursor="hand2",
    )
    listing_check.pack(anchor="w", pady=(12, 0))
    sync_listing_button_state()

    root.mainloop()

    if result[0] is None:
        sys.exit(0)
    return result[0]


if __name__ == "__main__":
    choice = show_launcher()
    print(f"选择结果: {choice}")
