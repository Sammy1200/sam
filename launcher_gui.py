import sys
import tkinter as tk

from config import EXECUTION_SLOT_COUNT


def show_launcher():
    """
    弹出启动器窗口，阻塞等待用户选择。

    返回:
        ("launcher", None)        — 登录界面启动
        ("2", int)                — 临时抢购模式 + 执行位编号
    """
    result = [None]
    root = tk.Tk()
    root.title("古墓迷途 - 启动器")
    root.configure(bg="#2b2b2b")
    root.resizable(False, False)

    window_width = 400
    window_height = 280
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    pos_x = (screen_width - window_width) // 2
    pos_y = (screen_height - window_height) // 2
    root.geometry(f"{window_width}x{window_height}+{pos_x}+{pos_y}")

    root.protocol("WM_DELETE_WINDOW", lambda: sys.exit(0))

    title_label = tk.Label(
        root,
        text="请选择启动方式",
        fg="white",
        bg="#2b2b2b",
        font=("Microsoft YaHei", 14, "bold"),
    )
    title_label.pack(pady=(25, 20))

    def choose_launcher():
        result[0] = ("launcher", None)
        root.destroy()

    input_frame = tk.Frame(root, bg="#2b2b2b")
    input_visible = [False]

    input_label = tk.Label(
        input_frame,
        text=f"下一个执行位 (1-{int(EXECUTION_SLOT_COUNT)}):",
        fg="white",
        bg="#2b2b2b",
        font=("Microsoft YaHei", 10),
    )
    input_label.pack(pady=(0, 8))

    slot_entry = tk.Entry(
        input_frame,
        width=5,
        justify="center",
        font=("Microsoft YaHei", 12),
    )
    slot_entry.pack()
    slot_entry.bind("<Return>", lambda e: confirm_temporary_mode())
    slot_entry.bind("<KP_Enter>", lambda e: confirm_temporary_mode())
    default_entry_bg = slot_entry.cget("bg")

    error_label = tk.Label(
        input_frame,
        text="",
        fg="#ff6b6b",
        bg="#2b2b2b",
        font=("Microsoft YaHei", 9),
    )
    error_label.pack(pady=(8, 0))

    def confirm_temporary_mode():
        raw_value = slot_entry.get().strip()
        if not raw_value.isdigit():
            slot_entry.configure(bg="#ffcccc")
            error_label.configure(text=f"请输入 1-{int(EXECUTION_SLOT_COUNT)} 的数字")
            return

        slot_value = int(raw_value)
        if slot_value < 1 or slot_value > int(EXECUTION_SLOT_COUNT):
            slot_entry.configure(bg="#ffcccc")
            error_label.configure(text=f"请输入 1-{int(EXECUTION_SLOT_COUNT)} 的数字")
            return

        slot_entry.configure(bg=default_entry_bg)
        error_label.configure(text="")
        result[0] = ("2", slot_value)
        root.destroy()

    confirm_button = tk.Button(
        input_frame,
        text="确认",
        width=10,
        bg="#4a90d9",
        fg="white",
        font=("Microsoft YaHei", 11),
        relief="flat",
        command=confirm_temporary_mode,
    )
    confirm_button.pack(pady=(10, 0))

    def show_temporary_input():
        if not input_visible[0]:
            input_frame.pack(pady=(15, 0))
            input_visible[0] = True
        slot_entry.configure(bg=default_entry_bg)
        error_label.configure(text="")
        slot_entry.focus_set()
        slot_entry.selection_range(0, tk.END)

    launcher_button = tk.Button(
        root,
        text="登录界面启动",
        width=25,
        height=2,
        bg="#4a90d9",
        fg="white",
        font=("Microsoft YaHei", 11),
        relief="flat",
        command=choose_launcher,
    )
    launcher_button.pack()

    temporary_button = tk.Button(
        root,
        text="临时抢购模式",
        width=25,
        height=2,
        bg="#4a90d9",
        fg="white",
        font=("Microsoft YaHei", 11),
        relief="flat",
        command=show_temporary_input,
    )
    temporary_button.pack(pady=(10, 0))

    root.mainloop()

    if result[0] is None:
        sys.exit(0)
    return result[0]


if __name__ == "__main__":
    choice = show_launcher()
    print(f"选择结果: {choice}")
