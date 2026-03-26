import ctypes
from ctypes import wintypes
import sys
import platform
import time
import os
from datetime import datetime

# ========== Win32 DLL ==========
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ========== 常量 ==========
WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000
VK_F1 = 0x70
VK_ESC = 0x1B

CF_UNICODETEXT = 13

# 常见剪贴板格式
CLIPBOARD_FORMATS = {
    1: "CF_TEXT",
    2: "CF_BITMAP",
    3: "CF_METAFILEPICT",
    4: "CF_SYLK",
    5: "CF_DIF",
    6: "CF_TIFF",
    7: "CF_OEMTEXT",
    8: "CF_DIB",
    9: "CF_PALETTE",
    10: "CF_PENDATA",
    11: "CF_RIFF",
    12: "CF_WAVE",
    13: "CF_UNICODETEXT",
    14: "CF_ENHMETAFILE",
    15: "CF_HDROP",
    16: "CF_LOCALE",
    17: "CF_DIBV5",
}

# ========== 设置函数签名（很重要） ==========
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL

user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wintypes.BOOL

user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
user32.IsClipboardFormatAvailable.restype = wintypes.BOOL

user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE

user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
user32.EnumClipboardFormats.restype = wintypes.UINT

user32.GetClipboardFormatNameW.argtypes = [wintypes.UINT, wintypes.LPWSTR, ctypes.c_int]
user32.GetClipboardFormatNameW.restype = ctypes.c_int

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL

user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL

user32.GetMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = wintypes.LPVOID

kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL

kernel32.GetLastError.argtypes = []
kernel32.GetLastError.restype = wintypes.DWORD

kernel32.FormatMessageW.argtypes = [
    wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
    wintypes.LPWSTR, wintypes.DWORD, wintypes.LPVOID
]
kernel32.FormatMessageW.restype = wintypes.DWORD


# ========== 结构体 ==========
class POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


# ========== 日志 ==========
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clipboard_debug_log.txt")


def log(msg):
    text = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(text)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def get_error_message(err_code=None):
    if err_code is None:
        err_code = ctypes.get_last_error()

    if err_code == 0:
        return "错误码 0（没有可用错误信息）"

    FORMAT_MESSAGE_FROM_SYSTEM = 0x00001000
    FORMAT_MESSAGE_IGNORE_INSERTS = 0x00000200
    buf = ctypes.create_unicode_buffer(1024)

    kernel32.FormatMessageW(
        FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        None,
        err_code,
        0,
        buf,
        len(buf),
        None
    )
    msg = buf.value.strip()
    if not msg:
        msg = "系统没有返回文字说明"
    return f"错误码 {err_code}: {msg}"


def reset_log():
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("=== 剪贴板排查日志 ===\n")


def list_clipboard_formats():
    """列出当前剪贴板里所有格式"""
    formats = []
    fmt = 0
    while True:
        ctypes.set_last_error(0)
        fmt = user32.EnumClipboardFormats(fmt)
        if fmt == 0:
            err = ctypes.get_last_error()
            if err != 0:
                formats.append(f"EnumClipboardFormats 结束时异常：{get_error_message(err)}")
            break

        if fmt in CLIPBOARD_FORMATS:
            formats.append(f"{fmt} ({CLIPBOARD_FORMATS[fmt]})")
        else:
            # 尝试读取注册格式名
            name_buf = ctypes.create_unicode_buffer(256)
            length = user32.GetClipboardFormatNameW(fmt, name_buf, 256)
            if length > 0:
                formats.append(f"{fmt} (自定义格式: {name_buf.value})")
            else:
                formats.append(f"{fmt} (未知/无名称格式)")
    return formats


def get_clipboard_text_debug():
    """详细排查剪贴板读取过程"""
    log("开始尝试读取剪贴板...")

    ctypes.set_last_error(0)
    ok = user32.OpenClipboard(None)
    if not ok:
        err = ctypes.get_last_error()
        log("OpenClipboard(None) 失败")
        log(get_error_message(err))
        return None

    log("OpenClipboard(None) 成功")

    try:
        # 列出格式
        formats = list_clipboard_formats()
        if formats:
            log("当前剪贴板格式列表：")
            for item in formats:
                log(f"  - {item}")
        else:
            log("当前剪贴板没有枚举到任何格式")

        # 检查 Unicode 文本格式
        ctypes.set_last_error(0)
        has_unicode = user32.IsClipboardFormatAvailable(CF_UNICODETEXT)
        log(f"IsClipboardFormatAvailable(CF_UNICODETEXT) = {bool(has_unicode)}")

        if not has_unicode:
            log("结论：剪贴板当前没有 Unicode 文本格式，所以这个脚本读不到文本。")
            return None

        # 取数据句柄
        ctypes.set_last_error(0)
        h_data = user32.GetClipboardData(CF_UNICODETEXT)
        if not h_data:
            err = ctypes.get_last_error()
            log("GetClipboardData(CF_UNICODETEXT) 返回空")
            log(get_error_message(err))
            return None

        log(f"GetClipboardData 成功，句柄 = {h_data}")

        # 锁定内存
        ctypes.set_last_error(0)
        p_text = kernel32.GlobalLock(h_data)
        if not p_text:
            err = ctypes.get_last_error()
            log("GlobalLock 失败")
            log(get_error_message(err))
            return None

        log(f"GlobalLock 成功，地址 = {p_text}")

        try:
            try:
                text = ctypes.wstring_at(p_text)
                log(f"读取成功，字符长度 = {len(text)}")
                preview = text[:200].replace("\r", "\\r").replace("\n", "\\n")
                log(f"内容预览（前 200 个字符）: {preview}")
                return text
            except Exception as e:
                log(f"ctypes.wstring_at 读取异常: {repr(e)}")
                return None
        finally:
            ctypes.set_last_error(0)
            unlock_ret = kernel32.GlobalUnlock(h_data)
            unlock_err = ctypes.get_last_error()
            log(f"GlobalUnlock 返回值 = {unlock_ret}")

            # GlobalUnlock 返回 0 不一定是错，要配合错误码判断
            if unlock_ret == 0:
                if unlock_err == 0:
                    log("GlobalUnlock 返回 0，但错误码也是 0，通常表示内存锁已正常释放。")
                else:
                    log(f"GlobalUnlock 可能异常：{get_error_message(unlock_err)}")

    finally:
        ctypes.set_last_error(0)
        close_ret = user32.CloseClipboard()
        if close_ret:
            log("CloseClipboard 成功")
        else:
            err = ctypes.get_last_error()
            log("CloseClipboard 失败")
            log(get_error_message(err))


def main():
    reset_log()

    log("脚本启动")
    log(f"Python 版本: {sys.version}")
    log(f"Python 可执行文件: {sys.executable}")
    log(f"系统信息: {platform.platform()}")
    log(f"机器架构: {platform.machine()}")
    log(f"Python 位数: {ctypes.sizeof(ctypes.c_void_p) * 8} 位")
    log(f"日志文件路径: {LOG_FILE}")
    log("")

    # 先直接读一次，方便排查“不是热键问题，而是读取问题”
    log("========== 第一步：启动后立即尝试读取一次 ==========")
    get_clipboard_text_debug()
    log("")

    hotkey_id = 1

    log("========== 第二步：注册 F1 热键 ==========")
    ctypes.set_last_error(0)
    ok = user32.RegisterHotKey(None, hotkey_id, MOD_NOREPEAT, VK_F1)
    if not ok:
        err = ctypes.get_last_error()
        log("RegisterHotKey(F1) 失败")
        log(get_error_message(err))
        log("常见原因：F1 已被别的软件占用，或者当前环境不允许注册全局热键。")
        input("按回车退出...")
        return

    log("RegisterHotKey(F1) 成功")
    log("现在请你：")
    log("1. 先复制一段普通文本")
    log("2. 按一次 F1")
    log("3. 观察控制台和日志")
    log("4. 按 Esc 退出")
    log("")

    msg = MSG()

    try:
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)

            if ret == -1:
                log("GetMessageW 返回 -1，消息循环异常")
                break
            elif ret == 0:
                log("GetMessageW 返回 0，收到退出消息")
                break

            if msg.message == WM_HOTKEY and msg.wParam == hotkey_id:
                log("收到 F1 热键消息，开始读取剪贴板")
                log("---------- 热键触发读取开始 ----------")
                text = get_clipboard_text_debug()
                if text is None:
                    log("本次结果：读取失败，或剪贴板当前不是 Unicode 文本")
                elif text == "":
                    log("本次结果：读到空文本")
                else:
                    log("本次结果：读取成功")
                log("---------- 热键触发读取结束 ----------")
                log("")

            # 这里保留 Esc 检测，但它只有消息循环被唤醒时才会检查到
            if user32.GetAsyncKeyState(VK_ESC) & 0x8000:
                log("检测到 Esc，准备退出")
                break

    finally:
        user32.UnregisterHotKey(None, hotkey_id)
        log("已注销热键")
        log("脚本结束")
        input("按回车退出...")


if __name__ == "__main__":
    main()