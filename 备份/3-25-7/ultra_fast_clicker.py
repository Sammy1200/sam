import cv2
import numpy as np
import pyautogui
import time
import os
import sys
import keyboard 
from datetime import datetime
import ctypes
import tkinter as tk
import threading
import gc
import requests 
import dxcam    
import re

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    print("❌ 缺少 rapidocr_onnxruntime 库，请执行: pip install rapidocr-onnxruntime")
    os.system('pause')
    sys.exit()

# ================= 1. 坐标与核心参数配置 =================
# ---- 极速抢购坐标 ----
MONITOR_PRICE = {"left": 1473, "top": 181, "width": 79, "height": 22} 
MONITOR_SUCCESS = {"left": 780, "top": 190, "width": 370, "height": 143}
MONITOR_SHOP = {"left": 1600, "top": 100, "width": 66, "height": 55}       
MONITOR_JIAOYIHANG = {"left": 1698, "top": 184, "width": 64, "height": 87} 
MONITOR_GOUMAI = {"left": 883, "top": 367, "width": 80, "height": 33}      
MONITOR_MEIHUO = {"left": 590, "top": 838, "width": 117, "height": 46}
MONITOR_DIYICI = {"left": 780, "top": 673, "width": 107, "height": 43}
MONITOR_BALANCE = {"left": 1690, "top": 10, "width": 150, "height": 36}

REFRESH_POS = (1400, 230)
BUY_POS = (641, 859)
CONFIRM_POS = (1096, 687)        
SUCCESS_CONFIRM_POS = (960, 830) 
FIX_SHOP_POS1 = (1850, 270)
FIX_SHOP_POS2 = (1850, 355)
DIYICI_CLICK_POS = (833, 694)
EXIT_POS = (1893, 34)

MAX_PRICE = 1300001
MIN_PRICE = 325000

# ---- 抢购延迟与风控配置 ----
CONFIRM_DELAY = 0.01
PRE_EXIT_CLICK_DELAY = 0.03 
EXIT_DELAY = 1.88            
MISMATCH_EXIT_DELAY = 1.88  
ACCOUNT_LIMIT_THRESHOLD = 20 
IDLE_PUSH_INTERVAL = 1800  
STUCK_PUSH_INTERVAL = 300  
FRAME_MAX_AGE = 0.2  

# ---- 自动上架专用坐标与配置 ----
TARGET_PRICE = "3249911"       # 【需求修改】上架价格修改为 3249911
CLICK_1 = (1850, 990)
CLICK_2 = (1855, 269)
CLICK_JIAOSHI = (1730, 370)
PRICE_INPUT_POS = (1219, 736)     
CONFIRM_BTN_POS = (1466, 800)
SCROLL_POS = (1400, 520)

MONITOR_TEXT_SHANGJIA = {"left": 70, "top": 80, "width": 110, "height": 50}
MONITOR_TEXT_JIAOSHI = {"left": 1700, "top": 350, "width": 60, "height": 40}
MONITOR_CAPACITY = {"left": 179, "top": 103, "width": 51, "height": 27}
POPUP_REGION = {"left": 300, "top": 200, "width": 188, "height": 63}

# 【需求修改】商品扫描区域修改为 1212,94 到 1680,1050
SCAN_REGION = {"left": 1212, "top": 94, "width": 468, "height": 956}

# 【需求修改】到底判断相似度阈值降低至 0.95
SIMILARITY_THRESHOLD = 0.95
POST_LIST_WAIT = 1.5             
MAX_LISTING_RETRY = 3
ITEM_THRESHOLD = 0.75
POPUP_THRESHOLD = 0.85

# 上架时间周期配置 (秒)
LIST_INTERVAL = 55 * 60  
last_list_time = 0.0

# 容量数字模板参数
UPSCALE = 4
STANDARD_W = 20
STANDARD_H = 28
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "logo", "shangjia")
DIGIT_TEMPLATES = {}

# 全局状态
IS_PAUSED = False
limit_count = 0 
unknown_page_count = 0 
success_count = 0
fail_count = 0
total_running_time = 0.0  
last_resume_time = None   
target_stop_seconds = 0  
start_mode = 0  
current_balance = "获取中..."  
ocr_engine = None 
_last_balance_hash = None 

# 图片模板缓存
TEMP_JIAOYI = None
TEMP_ITEM = None
pyautogui.FAILSAFE = False


# ================= 2. 底层键鼠与工具模块 =================

def safe_imread(relative_path_tuple, flags=0):
    filepath = os.path.join(SCRIPT_DIR, *relative_path_tuple)
    if not os.path.exists(filepath): return None
    return cv2.imdecode(np.fromfile(filepath, dtype=np.uint8), flags)

def keybd_down(vk): ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
def keybd_up(vk): ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
def press_key(vk):
    keybd_down(vk)
    time.sleep(0.02)
    keybd_up(vk)
    time.sleep(0.03)

def hotkey(vk_modifier, vk_key):
    keybd_down(vk_modifier)
    keybd_down(vk_key)
    time.sleep(0.05)
    keybd_up(vk_key)
    keybd_up(vk_modifier)
    time.sleep(0.1)

def type_digits(digit_str):
    for ch in digit_str:
        if ch.isdigit(): press_key(0x30 + int(ch))
    time.sleep(0.15)

def scroll_down(count=21):
    x, y = int(SCROLL_POS[0]), int(SCROLL_POS[1])
    ctypes.windll.user32.SetCursorPos(x, y)
    time.sleep(0.1)
    for _ in range(count):
        ctypes.windll.user32.mouse_event(0x0800, 0, 0, ctypes.c_int(-120), 0)
        time.sleep(0.05)
    time.sleep(0.3)

def fast_click(pos):
    x, y = int(pos[0]), int(pos[1])
    ctypes.windll.user32.SetCursorPos(x, y)
    ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0) 
    ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0) 

def get_clipboard_text():
    CF_UNICODETEXT = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_bool
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_bool

    if not user32.OpenClipboard(None): return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle: return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr: return ""
        try:
            text = ctypes.wstring_at(ptr)
            return text if text is not None else ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()

def capture_game_hwnd():
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    return hwnd

def precise_sleep(seconds, spin_threshold=0.002):
    if seconds <= 0: return
    target_time = time.perf_counter() + seconds
    while target_time - time.perf_counter() > spin_threshold:
        if IS_PAUSED: break
        time.sleep(0.001) 
    while time.perf_counter() < target_time:
        if IS_PAUSED: break

def click_exit():
    precise_sleep(PRE_EXIT_CLICK_DELAY, spin_threshold=0.01)
    press_key(0x1B) 

def get_current_elapsed():
    global total_running_time, last_resume_time, IS_PAUSED
    is_p = IS_PAUSED
    lrt = last_resume_time
    if not is_p and lrt is not None:
        return total_running_time + (time.time() - lrt)
    return total_running_time

def smart_wait(seconds):
    gc.collect() 
    start = time.time()
    while time.time() - start < seconds:
        if IS_PAUSED: return False 
        time.sleep(0.01)
    return True

# ================= 3. OSD 悬浮窗 =================

overlay_root = None
log_text_var = None
score_var = None  
log_lines = []

def update_score_text():
    global overlay_root, score_var, success_count, fail_count, current_balance
    if overlay_root and score_var:
        elapsed = int(get_current_elapsed())
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        msg = (f"⏱️ 运行: {h:02d}:{m:02d}:{s:02d}      |  💰 金额: [ {current_balance} ]\n"
               f" ✔  成功: [ {success_count:<2} ] 次       |   ✖  失败: [ {fail_count:<2} ] 次")
        try: score_var.set(msg)
        except: pass

def tick_timer():
    update_score_text()
    if overlay_root: overlay_root.after(1000, tick_timer)

def create_overlay():
    global overlay_root, log_text_var, score_var, last_resume_time
    overlay_root = tk.Tk()
    overlay_root.overrideredirect(True)      
    overlay_root.attributes("-topmost", True) 
    
    overlay_root.geometry("+600+0")          
    overlay_root.attributes("-alpha", 0.8)   
    overlay_root.config(bg='black')          

    score_var = tk.StringVar()
    tk.Label(overlay_root, textvariable=score_var, font=("Microsoft YaHei", 11, "bold"), fg="gold", bg="black", justify="left").pack(padx=10, pady=(10, 5), anchor="w")
    log_text_var = tk.StringVar()
    log_text_var.set("🤖 脚本悬浮窗就绪...")
    tk.Label(overlay_root, textvariable=log_text_var, font=("Microsoft YaHei", 10, "bold"), fg="lime", bg="black", justify="left").pack(padx=10, pady=(0, 10), anchor="w")

    if os.name == 'nt':
        try:
            hwnd = ctypes.windll.user32.GetParent(overlay_root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x00080000 | 0x00000020)
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x11)
        except Exception: pass
            
    last_resume_time = time.time()
    tick_timer()
    overlay_root.mainloop()

def start_overlay():
    t = threading.Thread(target=create_overlay, daemon=True)
    t.start()

def ui_print(msg, is_replace=False, save_log=False, show_console=True):
    global overlay_root, log_text_var, log_lines
    now = datetime.now().strftime('%H:%M:%S')
    if show_console: print(f"\r[{now}] {msg}" if is_replace else f"[{now}] {msg}", end="\n" if not is_replace else "")
    if save_log:
        try:
            if not os.path.exists("logs"): os.makedirs("logs")
            with open(os.path.join("logs", f"result_log_{datetime.now().strftime('%Y-%m-%d')}.txt"), "a", encoding="utf-8") as f:
                f.write(f"[{now}] {msg}\n")
        except: pass
    if overlay_root and log_text_var:
        gui_msg = f"[{now}] {msg}"
        if is_replace and log_lines and any(icon in log_lines[-1] for icon in ["✔", "✖", "⏭️"]):
            log_lines.append(gui_msg)
        elif is_replace and log_lines: log_lines[-1] = gui_msg 
        else: log_lines.append(gui_msg)
        if len(log_lines) > 15: log_lines.pop(0)
        try: overlay_root.after(0, log_text_var.set, "\n".join(log_lines))
        except: pass

def toggle_pause():
    global IS_PAUSED, total_running_time, last_resume_time, overlay_root
    IS_PAUSED = not IS_PAUSED
    if IS_PAUSED:
        if last_resume_time is not None:
            total_running_time += (time.time() - last_resume_time)
            last_resume_time = None
        ui_print("⏸️ 脚本已暂停 (按F12恢复)")
        if overlay_root:
            try: overlay_root.after(0, overlay_root.withdraw)
            except: pass
    else:
        last_resume_time = time.time()
        if overlay_root:
            try: overlay_root.after(0, overlay_root.deiconify)
            except: pass
        ui_print("▶️ 脚本已恢复！ (按F12暂停)")

keyboard.add_hotkey('f12', toggle_pause)


# ================= 4. 容量识别专属：数字模板匹配 =================

def preprocess_template(img):
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.shape[2] == 3 else cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
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
    if not os.path.exists(TEMPLATE_DIR): return False
    all_files = os.listdir(TEMPLATE_DIR)
    png_files = [f for f in all_files if f.lower().endswith('.png')]
    name_map = {f"{d}.png": str(d) for d in range(10)}
    for sn in ["slash.png", "斜杠.png", "xiegang.png", "_.png"]:
        name_map[sn] = '/'
    for fname in png_files:
        label = name_map.get(fname)
        if label is None: continue
        fpath = os.path.join(TEMPLATE_DIR, fname)
        raw = cv2.imdecode(np.fromfile(fpath, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if raw is None: continue
        DIGIT_TEMPLATES[label] = preprocess_template(raw)
    return len(DIGIT_TEMPLATES) > 0

def binarize_capacity_region(frame):
    cropped = crop_frame(frame, MONITOR_CAPACITY)
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY) if frame.shape[2] == 4 else cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    big = cv2.resize(gray, (w * UPSCALE, h * UPSCALE), interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    border = np.concatenate([binary[0], binary[-1], binary[:, 0], binary[:, -1]])
    if np.mean(border) > 127: binary = cv2.bitwise_not(binary)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    return binary

def segment_characters(binary):
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w >= 4 and h >= 10: boxes.append((x, y, w, h))
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
        if len(chars) == 0: return None
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
                score = cv2.matchTemplate(norm, template, cv2.TM_CCOEFF_NORMED)[0][0]
                if score > best_score:
                    best_score = score
                    best_char = label
            min_confidence = min(min_confidence, best_score)
            recognized.append(best_char)
        text = ''.join(recognized)
        if min_confidence < 0.5: return None
        if '/' in text:
            parts = text.split('/')
            if len(parts) == 2:
                try:
                    c, t = int(parts[0]), int(parts[1])
                    if 0 <= c <= t <= 99: return (c, t)
                except ValueError: pass
        return None
    except Exception: return None

def read_capacity(frame):
    if DIGIT_TEMPLATES:
        result = recognize_capacity_by_template(frame)
        if result is not None: return result
        
    raw = read_text_from_area(frame, MONITOR_CAPACITY, is_number_mode=True)
    if raw and "/" in raw:
        parts = raw.split("/")
        try:
            c = int(parts[0]) if parts[0].isdigit() else -1
            t = int(parts[1]) if parts[1].isdigit() else 10
            if c != -1: return (c, t)
        except: pass
    return None


# ================= 5. 视觉与 OCR 模块 =================

def crop_frame(frame, monitor):
    t, l = monitor["top"], monitor["left"]
    return frame[t:t + monitor["height"], l:l + monitor["width"]]

def is_image_present(frame, monitor, template, threshold=0.8):
    try:
        cropped = crop_frame(frame, monitor)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        return cv2.minMaxLoc(res)[1] > threshold
    except: return False

def get_number(frame, templates):
    try:
        pixel_color = frame[207, 1320] 
        if sum([abs(int(pixel_color[i]) - [110, 237, 255][i]) for i in range(3)]) > 45: return None 
        cropped = crop_frame(frame, MONITOR_PRICE)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        detected = []
        for num, temp in templates.items():
            loc = np.where(cv2.matchTemplate(gray, temp, cv2.TM_CCOEFF_NORMED) >= 0.75) 
            for pt in zip(*loc[::-1]): detected.append({'x': pt[0], 'num': num, 'score': cv2.matchTemplate(gray, temp, cv2.TM_CCOEFF_NORMED)[pt[1], pt[0]]})
        if not detected: return None
        detected.sort(key=lambda x: x['x'])
        final_list = []
        last = detected[0]
        for i in range(1, len(detected)):
            if detected[i]['x'] - last['x'] < 5:
                if detected[i]['score'] > last['score']: last = detected[i]
            else: final_list.append(last); last = detected[i]
        final_list.append(last)
        res_str = "".join([i['num'] for i in final_list])
        return int(res_str) if len(res_str) >= 6 else None
    except: return None

def read_text_from_area(frame, monitor, is_number_mode=False):
    try:
        cropped = crop_frame(frame, monitor)
        gray_img = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        if is_number_mode:
            padded = cv2.copyMakeBorder(gray_img, 20, 20, 20, 20, cv2.BORDER_REPLICATE)
            final_img = cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)
            result, _ = ocr_engine(final_img)
            if result:
                text = "".join([item[1] for item in result]).replace(" ", "")
                text = text.replace("O", "0").replace("o", "0").replace("Q", "0").replace("D", "0")
                text = re.sub(r'[lI|\\i]+', '/', text) 
                return text
            return ""
        else:
            resized = cv2.resize(gray_img, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
            padded = cv2.copyMakeBorder(resized, 20, 20, 20, 20, cv2.BORDER_REPLICATE)
            final_img = cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)
            result, _ = ocr_engine(final_img)
            return "".join([item[1] for item in result]) if result else ""
    except: return ""

def wait_for_ocr_text(camera_obj, monitor, keywords, timeout=3.0):
    start = time.time()
    while time.time() - start < timeout:
        frame = camera_obj.get_latest_frame()
        if frame is None:
            time.sleep(0.05); continue
        text = read_text_from_area(frame, monitor, is_number_mode=False)
        if text and any(kw in text for kw in keywords): return True
        time.sleep(0.05)
    return False

def get_balance(frame):
    global ocr_engine, _last_balance_hash, current_balance
    try:
        if not ocr_engine: return None
        cropped = crop_frame(frame, MONITOR_BALANCE)
        tiny = cv2.resize(cropped, (8, 8))
        current_hash = tiny.tobytes()
        if _last_balance_hash is not None and current_hash == _last_balance_hash:
            return current_balance 
        
        gray_img = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        resized = cv2.resize(gray_img, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        sharpened = cv2.filter2D(resized, -1, kernel)
        padded = cv2.copyMakeBorder(sharpened, 30, 30, 30, 30, cv2.BORDER_REPLICATE)
        final_img = cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)
        
        result, _ = ocr_engine(final_img)
        if result and len(result) > 0:
            res_str = "".join([item[1] for item in result])
            if res_str:
                if any(u in res_str for u in ['万', '亿']): res_str = res_str.replace("。", ".").replace(",", ".")
                else: res_str = res_str.replace("。", "").replace(",", "").replace(".", "")
                res_str = re.sub(r'[^\d\.万亿]', '', res_str.replace(" ", "").replace("·", ".").replace("'", ".").replace("`", "."))
                if res_str: _last_balance_hash = current_hash 
            return res_str if res_str else None
        return None
    except: return None

def check_balance_limit(frame):
    global current_balance, IS_PAUSED
    bal_str = get_balance(frame)
    if bal_str:
        current_balance = bal_str 
        if overlay_root: overlay_root.after(0, update_score_text)
        try:
            match = re.search(r'[\d\.]+', bal_str)
            if match:
                num_val = float(match.group())
                real_val = int(round(num_val * 100000000)) if '亿' in bal_str else (int(round(num_val * 10000)) if '万' in bal_str else int(num_val))
                if real_val < 1300001:
                    ui_print(f"🛑 余额不足！金额 {bal_str}，自动暂停。", save_log=True)
                    if not IS_PAUSED: toggle_pause()
                    return False
        except: pass
    return True 


# ================= 6. 自动上架子系统 =================

def input_price_with_verify():
    for attempt in range(1, 4):
        fast_click(PRICE_INPUT_POS)
        time.sleep(0.15)
        hotkey(0x11, 0x41) 
        type_digits(TARGET_PRICE)
        time.sleep(0.2)
        hotkey(0x11, 0x41)
        time.sleep(0.1)
        hotkey(0x11, 0x43) 
        time.sleep(0.15)
        
        clipboard_raw = get_clipboard_text()
        actual = ''.join(c for c in clipboard_raw if c.isdigit())
        if actual == TARGET_PRICE:
            press_key(0x23) 
            return True
        ui_print(f"  ❌ 价格验证失败({attempt}/3)，重试...")
    press_key(0x1B) 
    time.sleep(0.5)
    return False

def compare_region_similarity(frame1, frame2, monitor):
    g1 = cv2.cvtColor(crop_frame(frame1, monitor), cv2.COLOR_BGRA2GRAY)
    g2 = cv2.cvtColor(crop_frame(frame2, monitor), cv2.COLOR_BGRA2GRAY)
    result = cv2.matchTemplate(g1, g2, cv2.TM_CCOEFF_NORMED)
    return float(result[0][0])

def match_item_in_scan(frame):
    global TEMP_ITEM
    if TEMP_ITEM is None: return False, 0, 0
    cropped = crop_frame(frame, SCAN_REGION)
    cropped_bgr = cv2.cvtColor(cropped, cv2.COLOR_BGRA2BGR)
    th, tw = TEMP_ITEM.shape[:2]
    if th > cropped_bgr.shape[0] or tw > cropped_bgr.shape[1]: return False, 0, 0
    res = cv2.matchTemplate(cropped_bgr, TEMP_ITEM, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val >= ITEM_THRESHOLD:
        abs_x = SCAN_REGION["left"] + max_loc[0] + tw // 2
        abs_y = SCAN_REGION["top"]  + max_loc[1] + th // 2
        return True, abs_x, abs_y
    return False, 0, 0

def execute_listing_routine(camera_obj, hwnd):
    """上架功能全家桶集成"""
    global total_running_time, last_resume_time, IS_PAUSED, last_list_time
    
    if not IS_PAUSED and last_resume_time is not None:
        total_running_time += (time.time() - last_resume_time)
        last_resume_time = None
    ui_print("⏸️ [系统] 抢购计时已冻结，正在执行自动化上架...")
    
    try:
        ui_print("👉 [步骤] 开始寻路进入背包...")
        fast_click(CLICK_1)
        if not wait_for_ocr_text(camera_obj, MONITOR_TEXT_SHANGJIA, ["上架", "数量"]): return
        fast_click(CLICK_2)
        if not wait_for_ocr_text(camera_obj, MONITOR_TEXT_JIAOSHI, ["角石"]): return
        fast_click(CLICK_JIAOSHI)
        time.sleep(0.5)
        
        capacity_result = None
        for _ in range(5):
            frame = camera_obj.get_latest_frame()
            if frame is not None:
                capacity_result = read_capacity(frame)
                if capacity_result is not None: break
            time.sleep(0.1)
            
        if not capacity_result:
            ui_print("❌ 额度解析失败，退出上架。")
            return
            
        current, total = capacity_result
        if total - current <= 0:
            ui_print(f"⛔ 容量已满 ({current}/{total})，无需上架。")
            return
            
        remaining = total - current
        ui_print(f"📊 额度充足: 已上架 {current}，还可以上架 {remaining} 个。")
        
        listed = 0
        fail_strike = 0
        while listed < remaining:
            frame = camera_obj.get_latest_frame()
            if frame is None: continue
            
            found, abs_x, abs_y = match_item_in_scan(frame)
            
            if found:
                fast_click((abs_x, abs_y))
                time.sleep(0.5)
                
                popup_found = False
                for _ in range(10):
                    f2 = camera_obj.get_latest_frame()
                    if f2 is not None:
                        g1 = cv2.cvtColor(crop_frame(frame, POPUP_REGION), cv2.COLOR_BGRA2GRAY)
                        g2 = cv2.cvtColor(crop_frame(f2, POPUP_REGION), cv2.COLOR_BGRA2GRAY)
                        if cv2.matchTemplate(g1, g2, cv2.TM_CCOEFF_NORMED)[0][0] < POPUP_THRESHOLD:
                            popup_found = True; break
                    time.sleep(0.2)
                    
                if popup_found and input_price_with_verify():
                    fast_click(CONFIRM_BTN_POS)
                    listed += 1
                    fail_strike = 0
                    ui_print(f"📦 成功上架 {listed}/{remaining} 个")
                    time.sleep(POST_LIST_WAIT) 
                else:
                    fail_strike += 1
                    if fail_strike >= MAX_LISTING_RETRY:
                        ui_print("🔄 连续失败达上限，翻页跳过")
                        before_frame = camera_obj.get_latest_frame()
                        scroll_down()
                        time.sleep(0.5)
                        after_frame = camera_obj.get_latest_frame()
                        
                        if before_frame is not None and after_frame is not None:
                            sim = compare_region_similarity(before_frame, after_frame, SCAN_REGION)
                            if sim >= SIMILARITY_THRESHOLD:
                                ui_print("[翻页] 截图对比相似度极高，确认已到底，结束上架！")
                                break
                        fail_strike = 0
            else:
                fail_strike = 0
                ui_print("[扫描] 未找到道具，翻页...")
                before_frame = frame
                scroll_down()
                time.sleep(0.5)
                after_frame = camera_obj.get_latest_frame()
                
                if after_frame is not None:
                    sim = compare_region_similarity(before_frame, after_frame, SCAN_REGION)
                    if sim < SIMILARITY_THRESHOLD:
                        ui_print("[翻页] 翻页成功，继续扫描")
                        continue
                    else:
                        ui_print("[翻页] 截图对比相似度极高，确认已到底，结束上架！")
                        break
                
        ui_print(f"✅ 上架流水线执行完毕，共上架 {listed} 个。")
    except Exception as e:
        ui_print(f"❌ 上架过程出现意外报错: {e}")
    finally:
        time.sleep(1.0)
        ui_print("🔙 退出背包，按 ESC 返回交易行开启抢购！")
        press_key(0x1B) 
        time.sleep(1.0) 
        
        if not IS_PAUSED: last_resume_time = time.time()
        last_list_time = get_current_elapsed() 
        ui_print("▶️ [系统] 抢购计时已恢复！")

def check_trigger_listing(camera, hwnd):
    global last_list_time
    elapsed = get_current_elapsed()
    if elapsed - last_list_time >= LIST_INTERVAL:
        execute_listing_routine(camera, hwnd)


# ================= 7. 极速主框架 =================

def setup_schedule():
    global target_stop_seconds, start_mode
    while True:
        print("\n" + "="*40)
        print(" ⚙️  请选择启动模式：")
        print(" [1] 设置定时暂停任务")
        print(" [2] 从【自动上架】开始执行，完成后无缝转入抢购")
        print(" [回车] 直接开启无限极速抢购")
        print("="*40)
        choice = input("👉 请输入序号，或直接按【回车】键: ").strip()

        if choice == '1':
            time_str = input("⏳ 请输入运行时间 (例如 1.30 代表1小时30分): ").strip()
            try:
                if '.' in time_str:
                    h, m = time_str.split('.')
                    target_stop_seconds = int(h)*3600 + int(m)*60
                else:
                    target_stop_seconds = int(time_str)*3600
                print("✅ 定时设置成功！")
                start_mode = 1; return
            except: pass
        elif choice == '2':
            print("✅ 确认：将先进行一轮全自动上架！")
            start_mode = 2; return
        else:
            start_mode = 0; return

def run_automation():
    global limit_count, success_count, fail_count, unknown_page_count 
    global target_stop_seconds, start_mode, ocr_engine, TEMP_JIAOYI, TEMP_ITEM
    
    setup_schedule()
    start_overlay()
    
    if os.name == 'nt':
        try:
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(handle, 0x00000100)
            ctypes.windll.kernel32.SetProcessAffinityMask(handle, 0x0055)
        except: pass
            
    gc.disable()

    try:
        ocr_engine = RapidOCR()
        ui_print("✅ 本地 RapidOCR 引擎就绪！")
    except Exception as e:
        ui_print(f"❌ OCR加载失败: {e}"); time.sleep(5); return

    templates = {str(i): safe_imread(("logo", "jiage", f"{i}.png"), 0) for i in range(10)}
    temp_success = safe_imread(("logo", "tezhengtu", "chenggong.png"), 0)
    temp_shop = safe_imread(("logo", "tezhengtu", "dianpu.png"), 0)     
    TEMP_JIAOYI = safe_imread(("logo", "tezhengtu", "jiaoyihang.png"), 0)
    temp_goumai = safe_imread(("logo", "tezhengtu", "goumai.png"), 0)
    temp_meihuo = safe_imread(("logo", "tezhengtu", "meihuo.png"), 0)
    temp_diyici = safe_imread(("logo", "tezhengtu", "diyici.png"), 0)
    TEMP_ITEM = safe_imread(("logo", "shangjia", "pojiaoshi.png"), cv2.IMREAD_COLOR)

    missing_files = []
    if any(v is None for v in templates.values()): missing_files.append("logo/jiage/ 的数字0-9.png")
    if temp_success is None: missing_files.append("logo/tezhengtu/chenggong.png")
    if temp_shop is None: missing_files.append("logo/tezhengtu/dianpu.png")
    if TEMP_JIAOYI is None: missing_files.append("logo/tezhengtu/jiaoyihang.png")
    if temp_goumai is None: missing_files.append("logo/tezhengtu/goumai.png")
    if temp_meihuo is None: missing_files.append("logo/tezhengtu/meihuo.png")
    if temp_diyici is None: missing_files.append("logo/tezhengtu/diyici.png")
    if TEMP_ITEM is None: missing_files.append("logo/shangjia/pojiaoshi.png")

    if missing_files:
        ui_print(f"❌ 启动中断！由于以下素材缺失: {', '.join(missing_files)}", save_log=True)
        time.sleep(10)
        return

    if load_digit_templates():
        ui_print("✅ 容量识别引擎: 【模板匹配】模式加载成功！")
    else:
        ui_print("⚠️ 未发现数字模板，容量识别降级为 OCR 模式。")

    try:
        camera = dxcam.create(output_color="BGRA")
        camera.start(target_fps=144) 
    except Exception as e:
        ui_print(f"❌ DXCAM 启动失败: {e}"); time.sleep(5); return

    if start_mode == 2:
        time.sleep(2.0)
        hwnd = capture_game_hwnd()
        ui_print("🚀 启动选项[2]已触发，前置上架系统启动！")
        execute_listing_routine(camera, hwnd)

    last_refresh = time.time()
    last_frame = None               
    last_frame_time = time.time()
    last_abnormal_print_sec = 0     
    
    try:
        while True:
            if target_stop_seconds > 0 and get_current_elapsed() >= target_stop_seconds:
                target_stop_seconds = 0
                if not IS_PAUSED: toggle_pause()
                continue 

            if IS_PAUSED:
                time.sleep(0.5)
                last_refresh = time.time()
                last_frame = None 
                continue

            try:
                raw_frame = camera.get_latest_frame()
                if raw_frame is None:
                    if last_frame is not None and (time.time() - last_frame_time) < FRAME_MAX_AGE: frame = last_frame
                    else: continue 
                else: 
                    frame = raw_frame
                    last_frame = frame
                    last_frame_time = time.time()
                    
                price = get_number(frame, templates)
                
                if price is not None:
                    limit_count = unknown_page_count = 0 
                    last_refresh = time.time() 
                    
                    if MIN_PRICE < price < MAX_PRICE:
                        fast_click(BUY_POS)
                        precise_sleep(CONFIRM_DELAY) 
                        fast_click(CONFIRM_POS)
                        
                        buy_result = "failed"
                        deadline = time.time() + 1.0 
                        while time.time() < deadline:
                            f = camera.get_latest_frame()
                            if f is not None:
                                if is_image_present(f, MONITOR_SUCCESS, temp_success):
                                    buy_result = "success"; break
                                elif is_image_present(f, MONITOR_MEIHUO, temp_meihuo):
                                    buy_result = "sold_out"; break
                            time.sleep(0.01)
                        
                        if buy_result == "success":
                            success_count += 1
                            ui_print(f"✔ 抢到! 价格: {price}", save_log=True, show_console=False)
                            precise_sleep(0.05)
                            fast_click(SUCCESS_CONFIRM_POS)
                            precise_sleep(0.1)
                            fast_click(SUCCESS_CONFIRM_POS)
                        elif buy_result == "sold_out":
                            ui_print(f"⚡ 晚了一步，已售空! 价格: {price}", is_replace=True)
                        else:
                            fail_count += 1
                            ui_print(f"✖ 错过! 价格: {price}", save_log=True, show_console=False)
                            click_exit() 
                        
                        if is_image_present(camera.get_latest_frame(), MONITOR_JIAOYIHANG, TEMP_JIAOYI):
                            check_trigger_listing(camera, capture_game_hwnd())

                        fast_click(REFRESH_POS) 
                        last_refresh = time.time()
                    else:
                        ui_print(f"⏭️ 价格不符: {price}", is_replace=True)
                        click_exit() 
                        
                        precise_sleep(MISMATCH_EXIT_DELAY)
                        if is_image_present(camera.get_latest_frame(), MONITOR_JIAOYIHANG, TEMP_JIAOYI):
                            check_trigger_listing(camera, capture_game_hwnd())

                        fast_click(REFRESH_POS) 
                        last_refresh = time.time()
                else:
                    if is_image_present(frame, MONITOR_MEIHUO, temp_meihuo):
                        unknown_page_count = 0
                        ui_print("⚡ 识别到空店！", is_replace=True)
                        click_exit() 
                        
                        precise_sleep(EXIT_DELAY)
                        if is_image_present(camera.get_latest_frame(), MONITOR_JIAOYIHANG, TEMP_JIAOYI):
                            check_trigger_listing(camera, capture_game_hwnd())

                        fast_click(REFRESH_POS)
                        last_refresh = time.time()
                        continue 
                    
                    time_since_last_action = time.time() - last_refresh
                    if time_since_last_action > 3.0:
                        is_normal_empty = is_image_present(frame, MONITOR_JIAOYIHANG, TEMP_JIAOYI) and is_image_present(frame, MONITOR_SHOP, temp_shop)
                        if is_normal_empty:
                            limit_count += 1; unknown_page_count = 0
                            ui_print(f"🔄 店铺空置 ({limit_count}/{ACCOUNT_LIMIT_THRESHOLD})", is_replace=True)
                            if limit_count >= ACCOUNT_LIMIT_THRESHOLD:
                                limit_count = 0
                                if not IS_PAUSED: toggle_pause() 
                                continue 
                            if not check_balance_limit(frame): continue 
                            
                            check_trigger_listing(camera, capture_game_hwnd())
                            
                            fast_click(REFRESH_POS)
                            gc.collect()
                            last_refresh = time.time()
                        else:
                            if unknown_page_count == 0 or time_since_last_action > 10.0:
                                ui_print("\n⚠️ 画面异常！全场景识别自愈...", save_log=True)
                                is_unknown_page = False
                                if is_image_present(frame, MONITOR_DIYICI, temp_diyici, threshold=0.6):
                                    fast_click(DIYICI_CLICK_POS)
                                elif is_image_present(frame, MONITOR_GOUMAI, temp_goumai, threshold=0.6):
                                    click_exit() 
                                elif is_image_present(frame, MONITOR_JIAOYIHANG, TEMP_JIAOYI, threshold=0.6) and not is_image_present(frame, MONITOR_SHOP, temp_shop, threshold=0.6):
                                    fast_click(FIX_SHOP_POS1)
                                    precise_sleep(1.0)
                                    fast_click(FIX_SHOP_POS2)
                                else:
                                    is_unknown_page = True; unknown_page_count += 1
                                    if unknown_page_count >= 20:
                                        unknown_page_count = 0
                                        if not IS_PAUSED: toggle_pause()
                                    else: last_refresh = time.time(); last_abnormal_print_sec = 0
                                
                                if not is_unknown_page:
                                    unknown_page_count = 0
                                    time.sleep(1.0)
                                    check_trigger_listing(camera, capture_game_hwnd()) 
                                    fast_click(REFRESH_POS)
                                    last_refresh = time.time()
                            else:
                                current_sec = int(time_since_last_action)
                                if current_sec != last_abnormal_print_sec:
                                    ui_print(f"⏳ 等待场景自愈介入 ({current_sec}s/10s)", is_replace=True)
                                    last_abnormal_print_sec = current_sec

                time.sleep(0.002) 
            except Exception: time.sleep(0.5)
    finally: camera.stop() 

if __name__ == "__main__":
    try: run_automation()
    except SystemExit: pass 
    except KeyboardInterrupt: sys.exit()
