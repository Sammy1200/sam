import sys
import tkinter as tk


def show_launcher():
    """
    弹出启动器窗口，阻塞等待用户选择。

    返回:
        ("launcher", None)           — 登录界面启动
        ("listing_launcher", None)    — 启动页上架模式
        ("temporary_launcher", None)  — 启动页临时抢购模式
    """
    result = [None]
    root = tk.Tk()
    root.title("古墓迷途 - 启动器")
    root.configure(bg="#101217")
    root.resizable(False, False)

    window_width = 360
    window_height = 220
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    pos_x = (screen_width - window_width) // 2
    pos_y = (screen_height - window_height) // 2
    root.geometry(f"{window_width}x{window_height}+{pos_x}+{pos_y}")

    root.protocol("WM_DELETE_WINDOW", lambda: sys.exit(0))

    panel = tk.Frame(root, bg="#151922", padx=28, pady=0)
    panel.pack(fill="both", expand=True, padx=1, pady=1)

    button_frame = tk.Frame(panel, bg="#151922")
    button_frame.pack(expand=True, fill="x")

    def choose_launcher():
        result[0] = ("launcher", None)
        root.destroy()

    def choose_listing_launcher():
        result[0] = ("listing_launcher", None)
        root.destroy()

    def choose_temporary_launcher():
        result[0] = ("temporary_launcher", None)
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

    launcher_button = create_mode_button("正常启动", choose_launcher, is_primary=True)
    launcher_button.pack(fill="x")

    listing_button = create_mode_button("上架模式", choose_listing_launcher)
    listing_button.pack(fill="x", pady=(10, 0))

    temporary_button = create_mode_button("临时模式", choose_temporary_launcher)
    temporary_button.pack(fill="x", pady=(10, 0))

    root.mainloop()

    if result[0] is None:
        sys.exit(0)
    return result[0]


if __name__ == "__main__":
    choice = show_launcher()
    print(f"选择结果: {choice}")
