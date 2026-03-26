import cv2
import numpy as np
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

# ================= 启动环境硬核校验 =================
def diagnostic_check():
    print("="*60)
    print(" 🛠️  正在执行脚本启动自检...")
    print("="*60)
    
    # 1. 检查 Python 位数
    if sys.maxsize <= 2**32:
        print("❌ 错误：你安装的是 32 位 Python，请更换为 64 位版本！")
        return False
    print(f"✅ Python 架构: 64-bit (版本 {sys.version.split(' ')[0]})")

    # 2. 检查图片路径
    base_dir = os.path.dirname(os.path.abspath(__file__))
    check_list = [
        ("logo/jiage/0.png", "价格数字模板"),
        ("logo/tezhengtu/jiaoyihang.png", "交易行特征图"),
        ("logo/tezhengtu/chenggong.png", "成功弹窗图"),
        ("logo/shangjia/pojiaoshi.png", "上架道具图"),
        ("logo/shangjia/tishi.png", "首次上架提示图")
    ]
    
    missing = []
    for rel_path, desc in check_list:
        if not os.path.exists(os.path.join(base_dir, rel_path)):
            missing.append(f"{desc} -> {rel_path}")
    
    if missing:
        print("❌ 错误：发现关键素材文件缺失！")
        for m in missing:
            print(f"   - {m}")
        return False
    print("✅ 关键图片素材校验通过")
    return True

# ================= 1. 坐标与参数配置 =================
MONITOR_PRICE = {"left": 1473, "top": 181, "width": 79, "height": 22} 
MONITOR_SUCCESS = {"left": 780, "top": 190, "width": 370, "height": 143}
MONITOR_SHOP = {"left": 1600, "top": 100, "width": 66, "height": 55}       
MONITOR_JIAOYIHANG = {"left": 1698, "top": 184, "width": 64, "height": 87} 
MONITOR_GOUMAI = {"left": 883, "top": 367, "width": 80, "height": 33}      
MONITOR_MEIHUO = {"left": 590, "top": 838, "width": 117, "height": 46}
MONITOR_DIYICI = {"left": 780, "top": 673, "width": 107, "height": 43}
MONITOR_BALANCE = {"left": 1690, "top": 10, "width": 150, "height": 36}

REFRESH_POS = (1400, 230)
EXIT_POS = (1893, 34)
BUY_POS = (641, 859)
CONFIRM_POS = (1096, 687)        
SUCCESS_CONFIRM_POS = (960, 830) 
FIX_SHOP_POS1 = (1850, 270)
FIX_SHOP_POS2 = (1850, 355)
DIYICI_CLICK_POS = (833, 694)

MAX_PRICE = 1300001
MIN_PRICE = 325000

# 极限延迟参数 (0.01s 连招)
CONFIRM_DELAY = 0.01
PRE_EXIT_CLICK_DELAY = 0.03 
EXIT_DELAY = 1.88            
MISMATCH_EXIT_DELAY = 1.88  

ACCOUNT_LIMIT_THRESHOLD = 20 
STUCK_PUSH_INTERVAL = 300  
FRAME_MAX_AGE = 0.2  

# ---- 自动上架专用配置 ----
TARGET_PRICE = "3249911"       
CLICK_1 = (1850, 990)
CLICK_2 = (1855, 269)
CLICK_JIAOSHI = (1730, 370)
PRICE_INPUT_POS = (1219, 736)     
CONFIRM_BTN_POS = (1386, 802)
SCROLL_POS = (1400, 520)

MONITOR_TEXT_SHANGJIA = {"left": 70, "top": 80, "width": 110, "height": 50}
MONITOR_TEXT_JIAOSHI = {"left": 1700, "top": 350, "width": 60, "height": 40}
MONITOR_CAPACITY = {"left": 179, "top": 103, "width": 51, "height": 27}
POPUP_REGION = {"left": 300, "top": 200, "width": 188, "height": 63}
SCAN_REGION = {"left": 1212, "top": 94, "width": 468, "height": 956}
MONITOR_TISHI = {"left": 737, "top": 664, "width": 188, "height": 263}

SIMILARITY_THRESHOLD = 0.95
POST_LIST_WAIT = 1.5             
MAX_LISTING_RETRY = 3
ITEM_THRESHOLD = 0.75
POPUP_THRESHOLD = 0.85

LIST_INTERVAL = 55 * 60  
last_list_time = 0.0

# 容量数字模板参数
UPSCALE = 4
STANDARD_W = 20
STANDARD_H = 28
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "logo", "shangjia")
DIGIT_TEMPLATES = {}

IS_PAUSED = False
limit_count = 0 
unknown_page_count = 0 
success_count = 0
fail_count = 0
total_listed_count = 0  
total_running_time = 0.0  
last_resume_time = None   
target_stop_seconds = 0  
start_mode = 0  
current_balance = "获取中..."  
ocr_engine = None 
temp_jiaoyi = None
TEMP_ITEM = None
TEMP_TISHI = None 
_last_balance_hash = None 

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
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    if not user32.OpenClipboard(None): return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle: return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr: return ""
        try:
            text = ctypes.wstring_at(ptr)
            return text if text is not None else ""
        finally: kernel32.GlobalUnlock(handle)
    finally: user32.CloseClipboard()

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
    global overlay_root, score_var, success_count, fail_count, current_balance, total_listed_count
    if overlay_root and score_var:
        elapsed = int(get_current_elapsed())
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        bal_str = str(current_balance)
        msg = (f"⏱️ 运行: {h:02d}:{m:02d}:{s:02d}      |  💰 金额: [ {bal_str} ]\n"
               f" ✔ 抢购: [ {success_count:<2} ] ✖ 漏掉: [ {fail_count:<2} ] |  📦 上架: [ {total_listed_count:<2} ] 件")
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
    overlay_root.geometry("+20+20")          
    overlay_root.attributes("-alpha", 0.75)   
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
        except: pass
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
            with open(os.path.join("logs", f"log_{datetime.now().strftime('%Y-%m-%d')}.txt"), "a", encoding="utf-8") as f:
                f.write(f"[{now}] {msg}\n")
        except: pass
    if overlay_root and log_text_var:
        gui_msg = f"[{now}] {msg}"
        if is_replace and log_lines: log_lines[-1] = gui_msg 
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
        ui_print("⏸️ 脚本已暂停")
        if overlay_root: overlay_root.after(0, overlay_root.withdraw)
    else:
        last_resume_time = time.time()
        if overlay_root: overlay_root.after(0, overlay_root.deiconify)
        ui_print("▶️ 脚本已恢复")

keyboard.add_hotkey('f12', toggle_pause)

def move_overlay(geometry_str):
    global overlay_root
    if overlay_root:
        try: overlay_root.after(0, lambda: overlay_root.geometry(geometry_str))
        except: pass

# ================= 4. 容量识别专属模块 =================

def preprocess_template(img):
    if len(img.shape) == 3: gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.shape[2] == 3 else cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
    else: gray = img.copy()
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    coords = cv2.findNonZero(binary)
    if coords is not None:
        x, y, w, h = cv2.boundingRect(coords)
        binary = binary[y:y + h, x:x + w]
    norm = cv2.resize(binary, (STANDARD_W, STANDARD_H), interpolation=cv2.INTER_CUBIC)
    return norm

def load_digit_templates():
    if not os.path.exists(TEMPLATE_DIR): return False
    all_files = os.listdir(TEMPLATE_DIR)
    name_map = {f"{d}.png": str(d) for d in range(10)}
    name_map.update({"slash.png": "/", "xiegang.png": "/", "_.png": "/"})
    for fname in all_files:
        label = name_map.get(fname)
        if label:
            fpath = os.path.join(TEMPLATE_DIR, fname)
            raw = cv2.imdecode(np.fromfile(fpath, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if raw is not None: DIGIT_TEMPLATES[label] = preprocess_template(raw)
    return len(DIGIT_TEMPLATES) > 0

def read_capacity(frame):
    raw = read_text_from_area(frame, MONITOR_CAPACITY, is_number_mode=True)
    if raw and "/" in raw:
        parts = raw.split("/")
        try: return (int(parts[0]), int(parts[1]))
        except: pass
    return None

# ================= 5. 核心视觉与引擎 =================

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
        if abs(int(pixel_color[0]) - 110) + abs(int(pixel_color[1]) - 237) + abs(int(pixel_color[2]) - 255) > 45: return None 
        cropped = crop_frame(frame, MONITOR_PRICE)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        detected = []
        for num, temp in templates.items():
            res = cv2.matchTemplate(gray, temp, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= 0.75) 
            for pt in zip(*loc[::-1]): detected.append({'x': pt[0], 'num': num, 'score': res[pt[1], pt[0]]})
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
        padded = cv2.copyMakeBorder(gray_img, 20, 20, 20, 20, cv2.BORDER_REPLICATE)
        final_img = cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)
        result, _ = ocr_engine(final_img)
        if result:
            text = "".join([item[1] for item in result]).replace(" ", "")
            return text
        return ""
    except: return ""

def wait_for_ocr_text(camera_obj, monitor, keywords, timeout=3.0):
    start = time.time()
    while time.time() - start < timeout:
        frame = camera_obj.get_latest_frame()
        if frame is None: continue
        text = read_text_from_area(frame, monitor)
        if text and any(kw in text for kw in keywords): return True
        time.sleep(0.05)
    return False

def get_balance(frame):
    global ocr_engine, _last_balance_hash, current_balance
    try:
        if not ocr_engine: return None
        cropped = crop_frame(frame, MONITOR_BALANCE)
        current_hash = cv2.resize(cropped, (8, 8)).tobytes()
        if _last_balance_hash == current_hash: return current_balance 
        
        gray_img = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        resized = cv2.resize(gray_img, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        padded = cv2.copyMakeBorder(resized, 30, 30, 30, 30, cv2.BORDER_REPLICATE)
        final_img = cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)
        result, _ = ocr_engine(final_img)
        if result:
            res_str = "".join([item[1] for item in result])
            res_str = re.sub(r'[^\d\.万亿]', '', res_str.replace(" ", "").replace("·", "."))
            _last_balance_hash = current_hash
            return res_str
        return None
    except: return None

def check_balance_limit(frame):
    global current_balance, IS_PAUSED
    bal_str = get_balance(frame)
    if bal_str:
        current_balance = bal_str 
        if overlay_root: overlay_root.after(0, update_score_text)
        try:
            num_val = float(re.search(r'[\d\.]+', bal_str).group())
            real_val = num_val * 100000000 if '亿' in bal_str else (num_val * 10000 if '万' in bal_str else num_val)
            if real_val < 1300001:
                ui_print(f"🛑 余额不足：{bal_str}，自动暂停。", save_log=True)
                if not IS_PAUSED: toggle_pause()
                return False
        except: pass
    return True 

def async_push_msg(title, content):
    def send():
        token = "59653da98d3049adb1deb19660767621"  
        url = "http://www.pushplus.plus/send"
        data = {"token": token, "title": title, "content": content, "template": "txt"}
        try: requests.post(url, json=data, timeout=3)
        except: pass 
    threading.Thread(target=send, daemon=True).start()

def wait_and_recognize_balance(wait_time, camera):
    global temp_jiaoyi
    start_total = time.time()
    while time.time() - start_total < 1.4:
        if IS_PAUSED: return False
        frame = camera.get_latest_frame()
        if frame is not None and is_image_present(frame, MONITOR_JIAOYIHANG, temp_jiaoyi, 0.7):
            check_balance_limit(frame)
            break
        time.sleep(0.05)
    remaining = wait_time - (time.time() - start_total)
    if remaining > 0: smart_wait(remaining)
    return True

# ================= 6. 自动上架子系统 =================

def check_and_click_tishi(camera_obj):
    global TEMP_TISHI
    time.sleep(0.6)
    frame = camera_obj.get_latest_frame()
    if frame is None: return
    cropped = crop_frame(frame, MONITOR_TISHI)
    res = cv2.matchTemplate(cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY), TEMP_TISHI, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val > 0.7:
        abs_x = MONITOR_TISHI["left"] + max_loc[0] + TEMP_TISHI.shape[1] // 2
        abs_y = MONITOR_TISHI["top"] + max_loc[1] + TEMP_TISHI.shape[0] // 2
        ui_print("🚨 消除首次上架提示弹窗")
        time.sleep(0.08)
        fast_click((abs_x, abs_y))

def input_price_with_verify():
    time.sleep(0.08)
    for _ in range(3):
        fast_click(PRICE_INPUT_POS); time.sleep(0.15)
        hotkey(0x11, 0x41); type_digits(TARGET_PRICE); time.sleep(0.2)
        hotkey(0x11, 0x41); time.sleep(0.1); hotkey(0x11, 0x43); time.sleep(0.15)
        if ''.join(c for c in get_clipboard_text() if c.isdigit()) == TARGET_PRICE:
            press_key(0x23); return True
    press_key(0x1B); return False

def execute_listing_routine(camera_obj):
    global total_running_time, last_resume_time, IS_PAUSED, last_list_time, total_listed_count, _last_balance_hash
    if not IS_PAUSED and last_resume_time: total_running_time += (time.time() - last_resume_time); last_resume_time = None
    ui_print("⏸️ 抢购计时冻结，执行自动上架...")
    move_overlay("+600+0"); first_popup_checked = False
    try:
        ui_print("👉 进入背包...")
        time.sleep(0.08); fast_click(CLICK_1)
        if not wait_for_ocr_text(camera_obj, MONITOR_TEXT_SHANGJIA, ["上架", "数量"]): return
        time.sleep(0.08); fast_click(CLICK_2)
        if not wait_for_ocr_text(camera_obj, MONITOR_TEXT_JIAOSHI, ["角石"]): return
        time.sleep(0.08); fast_click(CLICK_JIAOSHI); time.sleep(0.5)
        cap = read_capacity(camera_obj.get_latest_frame())
        if not cap: ui_print("❌ 额度解析失败"); return
        current, total = cap
        if total - current <= 0: ui_print(f"⛔ 容量已满 ({current}/{total})"); return
        listed = 0
        while listed < (total - current):
            frame = camera_obj.get_latest_frame()
            if frame is None: continue
            cropped_bgr = cv2.cvtColor(crop_frame(frame, SCAN_REGION), cv2.COLOR_BGRA2BGR)
            res = cv2.matchTemplate(cropped_bgr, TEMP_ITEM, cv2.TM_CCOEFF_NORMED)
            if cv2.minMaxLoc(res)[1] >= ITEM_THRESHOLD:
                max_loc = cv2.minMaxLoc(res)[3]
                abs_pos = (SCAN_REGION["left"] + max_loc[0] + TEMP_ITEM.shape[1]//2, SCAN_REGION["top"] + max_loc[1] + TEMP_ITEM.shape[0]//2)
                time.sleep(0.08); fast_click(abs_pos); time.sleep(0.5)
                if input_price_with_verify():
                    time.sleep(0.08); fast_click(CONFIRM_BTN_POS)
                    if not first_popup_checked: check_and_click_tishi(camera_obj); first_popup_checked = True
                    listed += 1; total_listed_count += 1; ui_print(f"📦 成功上架 {listed} 个"); time.sleep(POST_LIST_WAIT)
            else:
                ui_print("[扫描] 翻页..."); before = frame; time.sleep(0.08); scroll_down(); time.sleep(0.5)
                after = camera_obj.get_latest_frame()
                if after is not None and cv2.matchTemplate(cv2.cvtColor(crop_frame(before, SCAN_REGION), cv2.COLOR_BGRA2GRAY), cv2.cvtColor(crop_frame(after, SCAN_REGION), cv2.COLOR_BGRA2GRAY), cv2.TM_CCOEFF_NORMED)[0][0] >= SIMILARITY_THRESHOLD: break
        ui_print(f"✅ 上架结束，共 {listed} 个")
    except Exception as e: ui_print(f"❌ 上架报错: {e}")
    finally:
        time.sleep(1.0); ui_print("🔙 返回交易行"); press_key(0x1B); time.sleep(1.0); _last_balance_hash = None; move_overlay("+20+20")
        if not IS_PAUSED: last_resume_time = time.time()
        last_list_time = get_current_elapsed(); ui_print("▶️ 抢购计时恢复")

# ================= 7. 主程序 =================

def run_automation():
    global target_stop_seconds, ocr_engine, temp_jiaoyi, TEMP_ITEM, TEMP_TISHI, last_list_time, last_refresh, start_mode
    
    if not diagnostic_check():
        os.system('pause'); sys.exit()

    print("\n" + "="*40)
    print(" ⚙️  请选择启动模式：")
    print(" [1] 定时暂停任务")
    print(" [回车] 自动上架 + 无限抢购")
    print("="*40)
    choice = input("👉 请输入: ").strip()
    if choice == '1':
        t_str = input("⏳ 运行多久 (如 1.30): ").strip()
        h, m = t_str.split('.') if '.' in t_str else (t_str, 0)
        target_stop_seconds = int(h)*3600 + int(m)*60
        start_mode = 1
    else:
        start_mode = 2
    
    start_overlay()
    gc.disable()
    ocr_engine = RapidOCR()
    
    templates = {str(i): safe_imread(("logo", "jiage", f"{i}.png"), 0) for i in range(10)}
    temp_success = safe_imread(("logo", "tezhengtu", "chenggong.png"), 0)
    temp_shop = safe_imread(("logo", "tezhengtu", "dianpu.png"), 0)     
    temp_jiaoyi = safe_imread(("logo", "tezhengtu", "jiaoyihang.png"), 0)
    temp_meihuo = safe_imread(("logo", "tezhengtu", "meihuo.png"), 0)
    TEMP_ITEM = safe_imread(("logo", "shangjia", "pojiaoshi.png"), cv2.IMREAD_COLOR)
    TEMP_TISHI = safe_imread(("logo", "shangjia", "tishi.png"), 0)
    load_digit_templates()

    camera = dxcam.create(output_color="BGRA")
    camera.start(target_fps=144) 
    
    ui_print("🚀 校验初始场景...")
    time.sleep(1.0)
    f_start = camera.get_latest_frame()
    if f_start is not None and not (is_image_present(f_start, MONITOR_JIAOYIHANG, temp_jiaoyi, 0.7) and is_image_present(f_start, MONITOR_SHOP, temp_shop, 0.7)):
        ui_print("🚨 尝试修复回到交易行..."); fast_click(FIX_SHOP_POS1); time.sleep(1.0); fast_click(FIX_SHOP_POS2); time.sleep(1.0)

    execute_listing_routine(camera)

    last_refresh = time.time()
    last_frame = None

    try:
        while True:
            curr_run_time = get_current_elapsed()
            if curr_run_time - last_list_time >= LIST_INTERVAL:
                execute_listing_routine(camera)

            if target_stop_seconds > 0 and curr_run_time >= target_stop_seconds:
                async_push_msg("⏸️ 定时结束", "脚本已暂停。"); target_stop_seconds = 0
                if not IS_PAUSED: toggle_pause()
                continue 

            if IS_PAUSED: time.sleep(0.5); last_refresh = time.time(); continue

            try:
                frame = camera.get_latest_frame()
                if frame is None:
                    if last_frame is not None: frame = last_frame
                    else: continue 
                else: last_frame = frame
                    
                price = get_number(frame, templates)
                if price:
                    if MIN_PRICE < price < MAX_PRICE:
                        fast_click(BUY_POS); precise_sleep(CONFIRM_DELAY); fast_click(CONFIRM_POS); time.sleep(0.8)
                        f_res = camera.get_latest_frame()
                        if f_res is not None and is_image_present(f_res, MONITOR_SUCCESS, temp_success):
                            global success_count; success_count += 1; ui_print(f"✔ 抢到: {price}", save_log=True)
                            precise_sleep(0.05); fast_click(SUCCESS_CONFIRM_POS); precise_sleep(0.1); fast_click(SUCCESS_CONFIRM_POS)
                        else:
                            global fail_count; fail_count += 1; ui_print(f"✖ 错过: {price}"); click_exit() 
                        if wait_and_recognize_balance(EXIT_DELAY, camera): fast_click(REFRESH_POS); last_refresh = time.time()
                    else:
                        ui_print(f"⏭️ 价格不符: {price}", is_replace=True); click_exit() 
                        if wait_and_recognize_balance(MISMATCH_EXIT_DELAY, camera): fast_click(REFRESH_POS); last_refresh = time.time()
                else:
                    if is_image_present(frame, MONITOR_MEIHUO, temp_meihuo):
                        ui_print("⚡ 售空秒退", is_replace=True); click_exit()
                        if wait_and_recognize_balance(EXIT_DELAY, camera): fast_click(REFRESH_POS); last_refresh = time.time()
                    elif time.time() - last_refresh > 3.0:
                        if is_image_present(frame, MONITOR_JIAOYIHANG, temp_jiaoyi, 0.7) and is_image_present(frame, MONITOR_SHOP, temp_shop, 0.7):
                            if not check_balance_limit(frame): continue
                            fast_click(REFRESH_POS); last_refresh = time.time(); gc.collect()
                        else:
                            if time.time() - last_refresh > 10.0:
                                ui_print("🚨 异常自愈..."); fast_click(FIX_SHOP_POS1); time.sleep(1.0); fast_click(FIX_SHOP_POS2); last_refresh = time.time()
                time.sleep(0.002) 
            except Exception: time.sleep(0.1)
    finally: camera.stop() 

if __name__ == "__main__":
    try: run_automation()
    except Exception as e:
        import traceback; traceback.print_exc()
        os.system('pause')
