import cv2
import numpy as np
import time
import os
import sys
import ctypes
import keyboard
import re
import dxcam
import threading
import logging
from datetime import datetime
from rapidocr_onnxruntime import RapidOCR


# ================================================================
#  0. 日志系统
# ================================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

log_filename = datetime.now().strftime("run_%Y%m%d_%H%M%S.log")
log_filepath = os.path.join(LOG_DIR, log_filename)

logger = logging.getLogger("ListingBot")
logger.setLevel(logging.DEBUG)

file_handler = logging.FileHandler(log_filepath, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)-7s] %(message)s", datefmt="%H:%M:%S"
))

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("%(message)s"))

logger.addHandler(file_handler)
logger.addHandler(console_handler)


# ================================================================
#  1. 配置常量
# ================================================================

EXPECTED_WIDTH  = 1920
EXPECTED_HEIGHT = 1080

# ---- 跳转点击坐标 ----
CLICK_1         = (1850, 990)
CLICK_2         = (1855, 269)
CLICK_JIAOSHI   = (1730, 370)

# ---- OCR / 模板 监控区域 ----
MONITOR_TEXT_SHANGJIA = {"left": 70,   "top": 80,  "width": 110, "height": 50}
MONITOR_TEXT_JIAOSHI  = {"left": 1700, "top": 350, "width": 60,  "height": 40}
MONITOR_CAPACITY      = {"left": 179,  "top": 103, "width": 51,  "height": 27}
MONITOR_JIAOYIHANG    = {"left": 1698, "top": 184, "width": 64,  "height": 87}

# ---- 基础时间参数 ----
CLICK_PRE_DELAY  = 0.10
CLICK_POST_DELAY = 0.15
OCR_TIMEOUT      = 5.0
MAX_RETRY        = 3
RETRY_INTERVAL   = 0.8
CAMERA_FPS       = 30

# ---- 容量数字模板 ----
UPSCALE    = 4
STANDARD_W = 20
STANDARD_H = 28
TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "logo", "shangjia")

# ---- 道具扫描 ----
ITEM_TEMPLATE_PATH     = os.path.join("logo", "shangjia", "pojiaoshi.png")
ITEM_THRESHOLD         = 0.75
HEIKUANG_TEMPLATE_PATH = os.path.join("logo", "shangjia", "heikuang.png")
HEIKUANG_THRESHOLD     = 0.7

# ---- 背包扫描区域 ----
SCAN_REGION = {"left": 106, "top": 155, "width": 1729, "height": 780}

# ---- 翻页 ----
SIMILARITY_THRESHOLD = 0.98
SCROLL_COUNT         = 21
SCROLL_POS           = (1400, 520)

# ---- 弹窗检测 ----
POPUP_REGION    = {"left": 300, "top": 200, "width": 188, "height": 63}
POPUP_THRESHOLD = 0.85

# ---- 二次验证拖动 ----
DRAG_START        = (1400, 1000)
DRAG_END          = (1400, 350)
DRAG_DURATION     = 0.6
DRAG_CHECK_REGION = {"left": 1240, "top": 900, "width": 440, "height": 140}

# ---- 上架操作 ----
TARGET_PRICE      = "3199111"       # ← 以后改价格只改这里
PRICE_INPUT_POS   = (1219, 736)     # 输入框中心 (区域: 1095,723 ~ 1343,749)
CONFIRM_BTN_POS   = (1466, 800)
MAX_PRICE_RETRY   = 3               # 价格验证最大重试次数
POST_LIST_WAIT    = 1.5             # 上架成功后等补位的秒数

# ---- 防死循环 ----
MAX_LISTING_RETRY = 3


# ================================================================
#  2. 素材读取
# ================================================================

def safe_imread(filename, flags=0):
    filepath = os.path.join(SCRIPT_DIR, filename)
    if not os.path.exists(filepath):
        logger.error(f"素材文件不存在: {filepath}")
        return None
    img = cv2.imdecode(np.fromfile(filepath, dtype=np.uint8), flags)
    if img is None:
        logger.error(f"素材文件损坏: {filepath}")
    return img

TEMP_JIAOYI   = safe_imread("jiaoyihang.png", 0)
TEMP_ITEM     = safe_imread(ITEM_TEMPLATE_PATH, cv2.IMREAD_COLOR)
TEMP_HEIKUANG = safe_imread(HEIKUANG_TEMPLATE_PATH, cv2.IMREAD_COLOR)


# ================================================================
#  3. 全局状态
# ================================================================

ocr_engine      = None
camera          = None
game_hwnd       = None
run_lock        = threading.Lock()
DIGIT_TEMPLATES = {}


# ================================================================
#  4. 底层工具函数
# ================================================================

def check_resolution():
    w = ctypes.windll.user32.GetSystemMetrics(0)
    h = ctypes.windll.user32.GetSystemMetrics(1)
    if w != EXPECTED_WIDTH or h != EXPECTED_HEIGHT:
        logger.warning(f"⚠️ 分辨率 {w}×{h}，坐标基于 {EXPECTED_WIDTH}×{EXPECTED_HEIGHT}")
        return False
    logger.info(f"✅ 分辨率校验通过: {w}×{h}")
    return True


def capture_game_hwnd():
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if hwnd:
        logger.info(f"✅ 游戏窗口句柄: {hwnd}")
    else:
        logger.warning("⚠️ 未能捕获前台窗口句柄")
    return hwnd


def ensure_foreground(hwnd):
    if hwnd:
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)


def fast_click(pos, hwnd=None):
    if hwnd:
        ensure_foreground(hwnd)
    x, y = pos
    ctypes.windll.user32.SetCursorPos(x, y)
    time.sleep(CLICK_PRE_DELAY)
    ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)   # MOUSEEVENTF_LEFTDOWN
    ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)   # MOUSEEVENTF_LEFTUP
    time.sleep(CLICK_POST_DELAY)
    logger.debug(f"点击 ({x}, {y})")


def safe_get_frame(camera_obj, max_attempts=20, interval=0.1):
    for _ in range(max_attempts):
        frame = camera_obj.get_latest_frame()
        if frame is not None:
            return frame
        time.sleep(interval)
    logger.error(f"连续 {max_attempts} 次未获取到画面")
    return None


def crop_frame(frame, monitor):
    t, l = monitor["top"], monitor["left"]
    return frame[t:t + monitor["height"], l:l + monitor["width"]]


def frame_to_bgr(frame):
    """dxcam 输出 BGRA → BGR"""
    if len(frame.shape) == 3 and frame.shape[2] == 4:
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    return frame


def frame_to_gray(frame):
    """dxcam 输出 BGRA → 灰度"""
    if len(frame.shape) == 3:
        if frame.shape[2] == 4:
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return frame


# ---- 滚轮 ----

def scroll_down(count=SCROLL_COUNT, pos=SCROLL_POS):
    x, y = pos
    ctypes.windll.user32.SetCursorPos(x, y)
    time.sleep(0.1)
    for _ in range(count):
        ctypes.windll.user32.mouse_event(0x0800, 0, 0, -120, 0)
        time.sleep(0.05)
    time.sleep(0.3)


# ---- 拖动 ----

def mouse_drag(start, end, duration=0.6):
    sx, sy = start
    ex, ey = end
    ctypes.windll.user32.SetCursorPos(sx, sy)
    time.sleep(0.1)
    ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)   # 按下
    steps = max(int(duration / 0.016), 1)
    for i in range(steps):
        t = (i + 1) / steps
        cx = int(sx + (ex - sx) * t)
        cy = int(sy + (ey - sy) * t)
        ctypes.windll.user32.SetCursorPos(cx, cy)
        time.sleep(0.016)
    time.sleep(0.3)


def mouse_up():
    ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)   # 松开


# ---- 键盘输入 ----

def keybd_down(vk):
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)

def keybd_up(vk):
    ctypes.windll.user32.keybd_event(vk, 0, 2, 0)     # KEYEVENTF_KEYUP

def press_key(vk):
    """按下并松开一个键"""
    keybd_down(vk)
    time.sleep(0.02)
    keybd_up(vk)
    time.sleep(0.03)

def hotkey(vk_modifier, vk_key):
    """按下组合键，如 Ctrl+A, Ctrl+C"""
    keybd_down(vk_modifier)
    keybd_down(vk_key)
    time.sleep(0.05)
    keybd_up(vk_key)
    keybd_up(vk_modifier)
    time.sleep(0.1)

def type_digits(digit_str):
    """逐字输入 0-9 数字"""
    for ch in digit_str:
        if ch.isdigit():
            vk = 0x30 + int(ch)
            press_key(vk)
    time.sleep(0.15)


# ---- 剪贴板（纯 Win32 API，无额外依赖，线程安全） ----

def get_clipboard_text():
    """
    用 Win32 API 读取剪贴板 Unicode 文本。
    复制出来的是纯文本，光标不会混入。
    """
    CF_UNICODETEXT = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # 关键：补类型声明，避免 64 位 Python 下句柄/指针出错
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool

    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_bool

    user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
    user32.IsClipboardFormatAvailable.restype = ctypes.c_bool

    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p

    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p

    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_bool

    if not user32.OpenClipboard(None):
        logger.debug("剪贴板打开失败")
        return ""

    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            logger.debug("剪贴板里没有 Unicode 文本")
            return ""

        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            logger.debug("GetClipboardData 失败")
            return ""

        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            logger.debug("GlobalLock 失败")
            return ""

        try:
            text = ctypes.wstring_at(ptr)
            return text if text is not None else ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


# ================================================================
#  4.5 价格输入 + 验证
# ================================================================

def input_price_with_verify(target_price, hwnd=None):
    """
    在已弹出的上架弹窗中输入价格，并通过剪贴板验证。

    流程（每次重试）:
      1. 点击输入框获取焦点
      2. Ctrl+A 全选 → 输入数字（自动替换旧内容）
      3. Ctrl+A 全选 → Ctrl+C 复制 → 读剪贴板对比
      4. 通过 → 按 End 取消选中 → return True
      5. 不通过 → 下一次重试

    全部失败 → 按 ESC 关闭弹窗 → return False
    """
    VK_CTRL = 0x11
    VK_A    = 0x41
    VK_C    = 0x43
    VK_ESC  = 0x1B
    VK_END  = 0x23

    for attempt in range(1, MAX_PRICE_RETRY + 1):
        # ---- 点击输入框确保焦点 ----
        fast_click(PRICE_INPUT_POS, hwnd)
        time.sleep(0.15)

        # ---- Ctrl+A 全选 → 输入数字 ----
        hotkey(VK_CTRL, VK_A)
        type_digits(str(target_price))
        time.sleep(0.2)

        # ---- 验证: Ctrl+A → Ctrl+C → 读剪贴板 ----
        hotkey(VK_CTRL, VK_A)
        time.sleep(0.1)
        hotkey(VK_CTRL, VK_C)
        time.sleep(0.15)

        clipboard_raw = get_clipboard_text()
        # 只保留数字，去掉一切干扰（空格、逗号等）
        actual = ''.join(c for c in clipboard_raw if c.isdigit())

        if actual == str(target_price):
            # ---- 验证通过，取消全选 ----
            press_key(VK_END)
            logger.info(f"  ✅ 价格验证通过（第{attempt}次）: {actual}")
            return True
        else:
            logger.warning(
                f"  ❌ 价格验证失败（第{attempt}/{MAX_PRICE_RETRY}次）: "
                f"期望={target_price}, 剪贴板原文='{clipboard_raw}', 清洗后='{actual}'"
            )

    # ---- 全部失败 → ESC 安全关闭弹窗 ----
    logger.error(f"  ⛔ 价格 {MAX_PRICE_RETRY} 次验证均失败，ESC 关闭弹窗")
    press_key(VK_ESC)
    time.sleep(0.5)
    return False


# ================================================================
#  5. 数字模板系统（容量识别，原样保留）
# ================================================================

def preprocess_template(img):
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    border = np.concatenate([binary[0], binary[-1], binary[:, 0], binary[:, -1]])
    if np.mean(border) > 127:
        binary = cv2.bitwise_not(binary)
    coords = cv2.findNonZero(binary)
    if coords is not None:
        x, y, w, h = cv2.boundingRect(coords)
        binary = binary[y:y + h, x:x + w]
    norm = cv2.resize(binary, (STANDARD_W, STANDARD_H), interpolation=cv2.INTER_CUBIC)
    _, norm = cv2.threshold(norm, 127, 255, cv2.THRESH_BINARY)
    return norm


def load_digit_templates():
    if not os.path.exists(TEMPLATE_DIR):
        logger.error(f"⛔ 模板目录不存在: {TEMPLATE_DIR}")
        return False

    all_files = os.listdir(TEMPLATE_DIR)
    png_files = [f for f in all_files if f.lower().endswith('.png')]
    logger.info(f"📁 模板目录: {TEMPLATE_DIR}")
    logger.info(f"   找到 {len(png_files)} 个 png: {sorted(png_files)}")

    name_map = {}
    for d in range(10):
        name_map[f"{d}.png"] = str(d)
    for sn in ["slash.png", "斜杠.png", "xiegang.png", "_.png"]:
        name_map[sn] = '/'

    for fname in png_files:
        label = name_map.get(fname)
        if label is None:
            continue
        fpath = os.path.join(TEMPLATE_DIR, fname)
        raw = cv2.imdecode(np.fromfile(fpath, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if raw is None:
            logger.warning(f"   ⚠️ 无法读取: {fpath}")
            continue
        template = preprocess_template(raw)
        DIGIT_TEMPLATES[label] = template
        logger.info(f"   ✅ '{label}' ← {fname}  "
                     f"(原始 {raw.shape[1]}×{raw.shape[0]} → 标准 {STANDARD_W}×{STANDARD_H})")

    loaded  = set(DIGIT_TEMPLATES.keys())
    missing = set('0123456789/') - loaded
    logger.info(f"\n   已加载 {len(loaded)} 个: {sorted(loaded)}")
    if missing:
        logger.error(f"   ⛔ 缺少模板: {sorted(missing)}")
        return False
    logger.info("   ✅ 0-9 和 / 全部就绪！")
    return True


def binarize_capacity_region(frame):
    cropped = crop_frame(frame, MONITOR_CAPACITY)
    gray = frame_to_gray(cropped)
    h, w = gray.shape
    big = cv2.resize(gray, (w * UPSCALE, h * UPSCALE), interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    border = np.concatenate([binary[0], binary[-1], binary[:, 0], binary[:, -1]])
    if np.mean(border) > 127:
        binary = cv2.bitwise_not(binary)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    return binary


def segment_characters(binary):
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w >= 4 and h >= 10:
            boxes.append((x, y, w, h))
    boxes.sort(key=lambda b: b[0])

    if len(boxes) >= 2:
        widths = [w for (_, _, w, _) in boxes]
        median_w = sorted(widths)[len(widths) // 2]
        new_boxes = []
        for (x, y, w, h) in boxes:
            if w > median_w * 1.8 and w > 15:
                mid = w // 2
                new_boxes.append((x, y, mid, h))
                new_boxes.append((x + mid, y, w - mid, h))
            else:
                new_boxes.append((x, y, w, h))
        boxes = new_boxes
        boxes.sort(key=lambda b: b[0])

    chars = [binary[y:y + h, x:x + w] for (x, y, w, h) in boxes]
    return chars, boxes


def recognize_capacity_by_template(frame):
    try:
        binary = binarize_capacity_region(frame)
        chars, boxes = segment_characters(binary)
        if len(chars) == 0:
            return None

        recognized = []
        min_confidence = 1.0

        for i, char_img in enumerate(chars):
            coords = cv2.findNonZero(char_img)
            if coords is not None:
                cx, cy, cw, ch = cv2.boundingRect(coords)
                char_img = char_img[cy:cy + ch, cx:cx + cw]
            norm = cv2.resize(char_img, (STANDARD_W, STANDARD_H), interpolation=cv2.INTER_CUBIC)
            _, norm = cv2.threshold(norm, 127, 255, cv2.THRESH_BINARY)

            best_char, best_score = '?', -1
            for label, template in DIGIT_TEMPLATES.items():
                result = cv2.matchTemplate(norm, template, cv2.TM_CCOEFF_NORMED)
                score = result[0][0]
                if score > best_score:
                    best_score = score
                    best_char  = label

            logger.debug(f"  字符[{i}]: '{best_char}' ({best_score:.3f})")
            min_confidence = min(min_confidence, best_score)
            recognized.append(best_char)

        text = ''.join(recognized)
        logger.info(f"📐 模板识别: '{text}'  最低置信度: {min_confidence:.3f}")

        if min_confidence < 0.5:
            return None

        if '/' in text:
            parts = text.split('/')
            if len(parts) == 2:
                try:
                    current, total = int(parts[0]), int(parts[1])
                    if 0 <= current <= total <= 99:
                        return (current, total)
                except ValueError:
                    pass
        return None

    except Exception as e:
        logger.error(f"模板识别异常: {e}", exc_info=True)
        return None


# ================================================================
#  6. OCR 系统
# ================================================================

def read_text_from_area(frame, monitor):
    try:
        cropped = crop_frame(frame, monitor)
        gray = frame_to_gray(cropped)
        padded = cv2.copyMakeBorder(gray, 8, 8, 8, 8, cv2.BORDER_REPLICATE)
        bgr = cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)
        result, _ = ocr_engine(bgr)
        if not result:
            return ""
        text = "".join([item[1] for item in result])
        logger.debug(f"OCR: '{text}'")
        return text
    except Exception as e:
        logger.error(f"OCR 异常: {e}", exc_info=True)
        return ""


def parse_capacity_ocr(raw_text):
    if not raw_text:
        return None
    text = raw_text.replace(" ", "")
    text = text.replace("O", "0").replace("o", "0")
    text = text.replace("Q", "0").replace("D", "0")
    text = re.sub(r'[lI|\\i]+', '/', text)

    match = re.match(r'^(\d{1,2})/(\d{1,2})$', text)
    if match:
        c, t = int(match.group(1)), int(match.group(2))
        if 0 <= c <= t <= 10:
            return (c, t)

    digits = re.findall(r'\d+', text)
    if digits:
        num_str = digits[0]
        if num_str.endswith("10") and len(num_str) >= 3:
            try:
                c = int(num_str[:-2])
                if 0 <= c <= 10:
                    return (c, 10)
            except ValueError:
                pass
    return None


def wait_for_ocr_text(camera_obj, monitor, keywords, timeout=OCR_TIMEOUT):
    start = time.time()
    logger.info(f"   ⏳ 等待 {keywords} (超时 {timeout}s)...")
    while time.time() - start < timeout:
        frame = camera_obj.get_latest_frame()
        if frame is None:
            time.sleep(0.05)
            continue
        text = read_text_from_area(frame, monitor)
        if text:
            for kw in keywords:
                if kw in text:
                    logger.info(f"   ✅ 识别到 '{kw}'  耗时 {time.time() - start:.2f}s")
                    return True
        time.sleep(0.05)
    logger.warning(f"   ❌ 超时 ({timeout}s)")
    return False


def check_jiaoyihang(frame):
    if TEMP_JIAOYI is None:
        return False
    try:
        cropped = crop_frame(frame, MONITOR_JIAOYIHANG)
        gray = frame_to_gray(cropped)
        res = cv2.matchTemplate(gray, TEMP_JIAOYI, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        logger.debug(f"交易行置信度: {max_val:.3f}")
        return max_val > 0.7
    except Exception as e:
        logger.error(f"模板匹配异常: {e}", exc_info=True)
        return False


# ================================================================
#  7. 统一容量读取
# ================================================================

def read_capacity(frame):
    if DIGIT_TEMPLATES:
        result = recognize_capacity_by_template(frame)
        if result is not None:
            return result
        logger.warning("模板匹配失败，尝试 OCR 兜底...")
    raw = read_text_from_area(frame, MONITOR_CAPACITY)
    return parse_capacity_ocr(raw)


# ================================================================
#  8. 点击-验证-重试
# ================================================================

def step_click_and_verify(step_name, click_pos, ocr_monitor, ocr_keywords,
                          camera_obj, hwnd=None,
                          max_retry=MAX_RETRY, ocr_timeout=OCR_TIMEOUT):
    for attempt in range(1, max_retry + 1):
        logger.info(f"\n👉 {step_name}  (第 {attempt}/{max_retry} 次)")
        fast_click(click_pos, hwnd)
        if wait_for_ocr_text(camera_obj, ocr_monitor, ocr_keywords, timeout=ocr_timeout):
            return True
        if attempt < max_retry:
            logger.warning(f"   ⚠️ 失败，{RETRY_INTERVAL}s 后重试...")
            time.sleep(RETRY_INTERVAL)
        else:
            logger.error(f"   ❌ {step_name} 重试 {max_retry} 次仍失败")
    return False


# ================================================================
#  9. 上架扫描系统
# ================================================================

def match_item_in_scan(frame):
    """在扫描区域查找道具，返回 (found, abs_x, abs_y)"""
    if TEMP_ITEM is None:
        logger.error("道具模板未加载")
        return False, 0, 0

    cropped = crop_frame(frame, SCAN_REGION)
    cropped_bgr = frame_to_bgr(cropped)

    th, tw = TEMP_ITEM.shape[:2]
    if th > cropped_bgr.shape[0] or tw > cropped_bgr.shape[1]:
        return False, 0, 0

    result = cv2.matchTemplate(cropped_bgr, TEMP_ITEM, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    logger.debug(f"道具匹配置信度: {max_val:.3f}")

    if max_val >= ITEM_THRESHOLD:
        abs_x = SCAN_REGION["left"] + max_loc[0] + tw // 2
        abs_y = SCAN_REGION["top"]  + max_loc[1] + th // 2
        return True, abs_x, abs_y

    return False, 0, 0


def compare_region_similarity(frame1, frame2, monitor):
    """比较两帧指定区域的相似度 (0~1)"""
    g1 = frame_to_gray(crop_frame(frame1, monitor))
    g2 = frame_to_gray(crop_frame(frame2, monitor))
    result = cv2.matchTemplate(g1, g2, cv2.TM_CCOEFF_NORMED)
    return float(result[0][0])


def handle_listing(abs_x, abs_y, camera_obj, hwnd):
    """
    上架单个道具：点击 → 等弹窗 → 输价格(带验证) → 确定

    返回:
      True  = 上架成功
      False = 失败（弹窗未出现 / 价格验证失败已 ESC）
    """

    # 1. 基准帧
    before_frame = safe_get_frame(camera_obj)
    if before_frame is None:
        return False

    # 2. 点击道具
    fast_click((abs_x, abs_y), hwnd)
    logger.info(f"  点击道具 ({abs_x}, {abs_y})")
    time.sleep(0.5)

    # 3. 等弹窗出现（区域变化 → 弹窗弹出）
    popup_found = False
    for i in range(10):
        after_frame = safe_get_frame(camera_obj, max_attempts=5)
        if after_frame is None:
            time.sleep(0.3)
            continue
        sim = compare_region_similarity(before_frame, after_frame, POPUP_REGION)
        logger.debug(f"  弹窗检测 #{i+1}: 相似度 {sim:.4f}")
        if sim < POPUP_THRESHOLD:
            popup_found = True
            logger.info(f"  ✅ 弹窗已出现 (相似度 {sim:.4f})")
            break
        time.sleep(0.3)

    if not popup_found:
        logger.warning("  ⚠️ 未检测到弹窗，跳过")
        return False

    # 4-5. 输入价格 + 剪贴板验证（失败会自动 ESC 关闭弹窗）
    if not input_price_with_verify(TARGET_PRICE, hwnd):
        return False

    # 6. 价格正确，点击确定
    fast_click(CONFIRM_BTN_POS, hwnd)
    logger.info("  ✅ 点击确定，上架完成")
    time.sleep(0.8)

    return True


def verify_bottom(camera_obj):
    """二次到底验证：拖动 + 黑框检测"""
    logger.info("[验证] 二次到底验证...")

    mouse_drag(DRAG_START, DRAG_END, DRAG_DURATION)

    found = False
    if TEMP_HEIKUANG is not None:
        frame = safe_get_frame(camera_obj, max_attempts=5)
        if frame is not None:
            cropped = crop_frame(frame, DRAG_CHECK_REGION)
            cropped_bgr = frame_to_bgr(cropped)
            th, tw = TEMP_HEIKUANG.shape[:2]
            if th <= cropped_bgr.shape[0] and tw <= cropped_bgr.shape[1]:
                result = cv2.matchTemplate(cropped_bgr, TEMP_HEIKUANG, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(result)
                logger.debug(f"黑框匹配置信度: {max_val:.3f}")
                found = max_val >= HEIKUANG_THRESHOLD

    mouse_up()

    if found:
        logger.info("[验证] ✅ 确认已到底")
    else:
        logger.info("[验证] ❌ 非真到底")
    return found


def listing_loop(camera_obj, hwnd, remaining):
    """上架扫描主循环，最多上架 remaining 个"""
    listed_count = 0
    fail_count   = 0

    while listed_count < remaining:

        # ---- 扫描（每次都重新截图，确保能捕获补位道具） ----
        frame = safe_get_frame(camera_obj)
        if frame is None:
            logger.error("截屏失败，中止")
            break

        found, abs_x, abs_y = match_item_in_scan(frame)

        if found:
            logger.info(f"[扫描] ✅ 找到道具 ({abs_x}, {abs_y})")

            success = handle_listing(abs_x, abs_y, camera_obj, hwnd)

            if success:
                listed_count += 1
                fail_count = 0
                logger.info(f"  📦 累计上架: {listed_count}/{remaining}")

                # ★ 等待补位动画完成，然后回到循环顶部重新截图扫描
                #   如果补位上来的道具也是目标道具，会被自然匹配到
                logger.info(f"  ⏳ 等待 {POST_LIST_WAIT}s 补位...")
                time.sleep(POST_LIST_WAIT)
            else:
                fail_count += 1
                logger.warning(f"  ⚠️ 连续失败 {fail_count}/{MAX_LISTING_RETRY}")
                if fail_count >= MAX_LISTING_RETRY:
                    logger.info("  🔄 连续失败达上限，翻页跳过")
                    scroll_down()
                    fail_count = 0
            continue

        # ---- 没找到 → 翻页 ----
        fail_count = 0
        logger.info("[扫描] 未找到道具，翻页...")

        before_frame = frame
        scroll_down()
        after_frame = safe_get_frame(camera_obj)

        if after_frame is not None:
            sim = compare_region_similarity(before_frame, after_frame, SCAN_REGION)
            logger.info(f"[翻页] 前后相似度: {sim:.4f}")

            if sim < SIMILARITY_THRESHOLD:
                logger.info("[翻页] 翻页成功")
                continue

            # 疑似到底
            logger.info("[翻页] 疑似到底...")
            if verify_bottom(camera_obj):
                break
            else:
                time.sleep(0.3)
                continue

    return listed_count


# ================================================================
#  10. 业务主流程
# ================================================================

def run_full_sequence():
    """F12 触发：跳转 → 读额度 → 上架循环"""
    global game_hwnd

    if not run_lock.acquire(blocking=False):
        logger.warning("⚠️ 上一轮还在执行，忽略")
        return

    try:
        logger.info("\n" + "=" * 50)
        logger.info("⏳ 2 秒后开始，请切回游戏...")
        time.sleep(2.0)

        game_hwnd = capture_game_hwnd()

        # ---- 前置检查 ----
        frame = safe_get_frame(camera)
        if frame is None:
            logger.error("⛔ 无法截屏，中止")
            return
        if not check_jiaoyihang(frame):
            logger.error("⛔ 不在交易行界面，中止")
            return

        logger.info("🚀 确认在交易行，开始跳转...\n")

        # ========== 一级跳转 ==========
        if not step_click_and_verify(
            "[一级] 功能键 → 等'上架数量'",
            CLICK_1, MONITOR_TEXT_SHANGJIA, ["上架", "数量"],
            camera, game_hwnd
        ):
            raise Exception("一级跳转失败")

        # ========== 二级跳转 ==========
        if not step_click_and_verify(
            "[二级] 入口 → 等'角石'",
            CLICK_2, MONITOR_TEXT_JIAOSHI, ["角石"],
            camera, game_hwnd
        ):
            raise Exception("二级跳转失败")

        # ========== 三级跳转 ==========
        logger.info(f"\n👉 [三级] 点击角石 {CLICK_JIAOSHI}")
        fast_click(CLICK_JIAOSHI, game_hwnd)
        time.sleep(0.5)

        # ========== 读取上架额度 ==========
        logger.info("👉 [读取] 上架额度...")
        capacity_result = None
        for _ in range(5):
            frame = safe_get_frame(camera, max_attempts=5)
            if frame is None:
                continue
            capacity_result = read_capacity(frame)
            if capacity_result is not None:
                break
            time.sleep(0.3)

        if not capacity_result:
            logger.error("❌ 额度解析失败，请检查坐标或模板")
            return

        current, total = capacity_result
        remaining = total - current
        logger.info(f"\n📊 额度: {current}/{total}，剩余 {remaining}")

        if remaining <= 0:
            logger.info("⛔ 上限已满！无需上架")
            return

        logger.info(f"✅ 开始上架（最多 {remaining} 个）...\n")
        logger.info(f"💰 目标价格: {TARGET_PRICE}\n")

        # ========== 上架循环 ==========
        listed = listing_loop(camera, game_hwnd, remaining)

        logger.info(f"\n{'=' * 50}")
        logger.info(f"🏁 完成！本次上架 {listed} 个")

    except Exception as e:
        logger.error(f"💥 执行中断: {e}", exc_info=True)

    finally:
        logger.info("=" * 50)
        logger.info(f"📄 日志: {log_filepath}")
        logger.info("👉 F12 再次执行，ESC 退出\n")
        run_lock.release()


# ================================================================
#  11. 启动入口
# ================================================================

def startup_checks():
    passed = True
    check_resolution()
    if TEMP_JIAOYI is None:
        logger.error("⛔ jiaoyihang.png 缺失")
        passed = False
    if TEMP_ITEM is None:
        logger.error("⛔ 道具模板缺失: " + ITEM_TEMPLATE_PATH)
        passed = False
    if TEMP_HEIKUANG is None:
        logger.warning("⚠️ 黑框模板缺失（到底验证不可用）: " + HEIKUANG_TEMPLATE_PATH)
    return passed


def main():
    global ocr_engine, camera

    logger.info("=" * 50)
    logger.info("📦 上架脚本启动（合并版）")
    logger.info(f"📄 日志: {log_filepath}")
    logger.info(f"💰 当前目标价格: {TARGET_PRICE}")

    if not startup_checks():
        logger.error("⛔ 启动检查未通过")
        return

    # 数字模板
    templates_ok = load_digit_templates()
    if templates_ok:
        logger.info("🔢 容量识别: 模板匹配\n")
    else:
        logger.warning("🔢 容量识别: OCR 兜底\n")

    # OCR
    logger.info("🔧 初始化 OCR...")
    ocr_engine = RapidOCR()

    # DXCam
    logger.info(f"🔧 初始化 DXCam ({CAMERA_FPS} fps)...")
    camera = dxcam.create(output_color="BGRA")
    camera.start(target_fps=CAMERA_FPS)

    test_frame = safe_get_frame(camera, max_attempts=30)
    if test_frame is None:
        logger.error("⛔ DXCam 无法截屏")
        camera.stop()
        return
    logger.info(f"✅ 截屏: {test_frame.shape[1]}×{test_frame.shape[0]}")

    logger.info("\n✅ 就绪！按 F12 开始，ESC 退出\n")

    keyboard.add_hotkey('f12', run_full_sequence)
    keyboard.wait('esc')

    camera.stop()
    logger.info("👋 正常退出")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"💥 致命错误: {e}", exc_info=True)
    finally:
        input("\n按回车关闭窗口...")
