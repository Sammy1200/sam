import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# ===== Win32 常量 =====
WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000
VK_F1 = 0x70
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# ===== Win32 结构体 =====
class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG),
                ("y", wintypes.LONG)]

class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


def get_clipboard_text():
    """纯 Win32 API 读取剪贴板文本，失败返回 None"""
    if not user32.OpenClipboard(None):
        return None

    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None

        h_data = user32.GetClipboardData(CF_UNICODETEXT)
        if not h_data:
            return None

        p_text = kernel32.GlobalLock(h_data)
        if not p_text:
            return None

        try:
            text = ctypes.wstring_at(p_text)
            return text
        finally:
            kernel32.GlobalUnlock(h_data)
    finally:
        user32.CloseClipboard()


def main():
    hotkey_id = 1

    # 注册全局热键 F1
    if not user32.RegisterHotKey(None, hotkey_id, MOD_NOREPEAT, VK_F1):
        print("注册 F1 热键失败。")
        print("常见原因：F1 已被别的软件占用，或者脚本权限不够。")
        input("按回车退出...")
        return

    print("脚本已启动。")
    print("按 F1 读取剪贴板文本。")
    print("按 Esc 退出。")

    msg = MSG()

    try:
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0:
                break
            if ret == -1:
                print("消息循环出错。")
                break

            if msg.message == WM_HOTKEY and msg.wParam == hotkey_id:
                text = get_clipboard_text()
                print("\n===== 剪贴板内容开始 =====")
                if text is None:
                    print("读取失败，或者剪贴板里不是文本。")
                elif text == "":
                    print("(空文本)")
                else:
                    print(text)
                print("===== 剪贴板内容结束 =====\n")

            # 检测 Esc 键退出
            if user32.GetAsyncKeyState(0x1B) & 0x8000:  # 0x1B = Esc
                print("检测到 Esc，脚本退出。")
                break

    finally:
        user32.UnregisterHotKey(None, hotkey_id)


if __name__ == "__main__":
    main()