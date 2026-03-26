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
    print("❌ 缺少 rapidocr_onnxruntime 库，请在 cmd 中执行: pip install rapidocr-onnxruntime")
    os.system('pause')
    sys.exit()

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

# 延迟配置
CONFIRM_DELAY = 0.01
PRE_EXIT_CLICK_DELAY = 0.03 
EXIT_DELAY = 1.88            
MISMATCH_EXIT_DELAY = 1.88  

ACCOUNT_LIMIT_THRESHOLD = 20 
IDLE_PUSH_INTERVAL = 1800  
STUCK_PUSH_INTERVAL = 300  

# 【新增安全防护】旧帧最大允许存活时间(秒)
FRAME_MAX_AGE = 0.2  

IS_PAUSED = False
limit_count = 0 
unknown_page_count = 0 

success_count = 0
fail_count = 0
total_running_time = 0.0  
last_resume_time = None   
target_stop_seconds = 0  
current_balance = "获取中..."  
ocr_engine = None 
temp_jiaoyi = None
_last_balance_hash = None # 【新增】余额图像哈希缓存

pyautogui.FAILSAFE = False

# ================= 2. 悬浮窗控制系统 (OSD) =================
overlay_root = None
log_text_var = None
score_var = None  
log_lines = []

def update_score_text():
    global overlay_root, score_var, success_count, fail_count
    global total_running_time, last_resume_time, IS_PAUSED, current_balance

    if overlay_root and score_var:
        # 使用本地快照减缓竞态条件影响
        is_p = IS_PAUSED
        lrt = last_resume_time
        
        if not is_p and lrt is not None:
            elapsed = int(total_running_time + (time.time() - lrt))
        else:
            elapsed = int(total_running_time)
            
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        s = elapsed % 60
        
        bal_str = str(current_balance)
        msg = (f"⏱️ 运行: {h:02d}:{m:02d}:{s:02d}      |  💰 金额: [ {bal_str} ]\n"
               f" ✔  成功: [ {success_count:<2} ] 次       |   ✖  失败: [ {fail_count:<2} ] 次")
        try:
            score_var.set(msg)
        except:
            pass

def tick_timer():
    update_score_text()
    if overlay_root:
        overlay_root.after(1000, tick_timer)

def create_overlay():
    global overlay_root, log_text_var, score_var, last_resume_time
    overlay_root = tk.Tk()
    overlay_root.overrideredirect(True)      
    overlay_root.attributes("-topmost", True) 
    overlay_root.geometry("+20+20")          
    overlay_root.attributes("-alpha", 0.75)   
    overlay_root.config(bg='black')          

    score_var = tk.StringVar()
    score_label = tk.Label(overlay_root, textvariable=score_var, font=("Microsoft YaHei", 11, "bold"), 
                           fg="gold", bg="black", justify="left")
    score_label.pack(padx=10, pady=(10, 5), anchor="w")

    log_text_var = tk.StringVar()
    log_text_var.set("🤖 脚本悬浮窗就绪...")
    log_label = tk.Label(overlay_root, textvariable=log_text_var, font=("Microsoft YaHei", 10, "bold"), 
                         fg="lime", bg="black", justify="left")
    log_label.pack(padx=10, pady=(0, 10), anchor="w")

    if os.name == 'nt':
        try:
            hwnd = ctypes.windll.user32.GetParent(overlay_root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x00080000 | 0x00000020)
        except:
            pass

    last_resume_time = time.time()
    tick_timer()
    overlay_root.mainloop()

def start_overlay():
    t = threading.Thread(target=create_overlay, daemon=True)
    t.start()

def ui_print(msg, is_replace=False, save_log=False, show_console=True):
    global overlay_root, log_text_var, log_lines
    now = datetime.now().strftime('%H:%M:%S')
    
    if show_console:
        if is_replace:
            print(f"\r[{now}] {msg}", end="")
        else:
            print(f"[{now}] {msg}")
        
    if save_log:
        try:
            if not os.path.exists("logs"): os.makedirs("logs")
            date_str = datetime.now().strftime("%Y-%m-%d")
            with open(os.path.join("logs", f"result_log_{date_str}.txt"), "a", encoding="utf-8") as f:
                f.write(f"[{now}] {msg}\n")
        except: pass

    if overlay_root and log_text_var:
        gui_msg = f"[{now}] {msg}"
        if is_replace and log_lines:
            if any(icon in log_lines[-1] for icon in ["✔", "✖", "⏭️"]):
                log_lines.append(gui_msg)
            else:
                log_lines[-1] = gui_msg 
        else:
            log_lines.append(gui_msg)
            
        if len(log_lines) > 20:
            log_lines.pop(0)
            
        try:
            overlay_root.after(0, log_text_var.set, "\n".join(log_lines))
        except:
            pass

# ================= 3. 核心功能与高级重构模块 =================

def fast_click(pos):
    x, y = pos
    ctypes.windll.user32.SetCursorPos(x, y)
    ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0) 
    ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0) 

def precise_sleep(seconds, spin_threshold=0.002):
    """
    混合休眠优化版：
    对于超过 spin_threshold 的等待，让出 CPU；最后几毫秒进行自旋锁等待。
    减小长等待的无意义 CPU 空转。
    """
    if seconds <= 0: return
    target_time = time.perf_counter() + seconds
    while target_time - time.perf_counter() > spin_threshold:
        if IS_PAUSED: break
        time.sleep(0.001) 
    while time.perf_counter() < target_time:
        if IS_PAUSED: break

def get_battle_report():
    global total_running_time, last_resume_time, IS_PAUSED, success_count, fail_count, current_balance
    
    is_p = IS_PAUSED
    lrt = last_resume_time
    
    if not is_p and lrt is not None:
        current_elapsed = int(total_running_time + (time.time() - lrt))
    else:
        current_elapsed = int(total_running_time)
        
    h = current_elapsed // 3600
    m = (current_elapsed % 3600) // 60
    s = current_elapsed % 60
    
    bal_str = str(current_balance)
    
    return (
        f"--------------------\n"
        f"💰 当前余额: {bal_str}\n"
        f"✔ 成功抢购: {success_count} 次\n"
        f"✖ 失败抢购: {fail_count} 次\n"
        f"⏱️ 运行时间: {h}小时{m}分{s}秒"
    )

def async_push_msg(title, content):
    report = get_battle_report()
    full_content = f"{content}\n\n{report}"
    
    def send():
        token = "59653da98d3049adb1deb19660767621"  
        url = "http://www.pushplus.plus/send"
        data = {
            "token": token, 
            "title": title, 
            "content": full_content,
            "template": "txt" 
        }
        try: requests.post(url, json=data, timeout=3)
        except: pass 
    threading.Thread(target=send, daemon=True).start()

def toggle_pause():
    global IS_PAUSED, total_running_time, last_resume_time, overlay_root
    
    IS_PAUSED = not IS_PAUSED
    
    if IS_PAUSED:
        if last_resume_time is not None:
            total_running_time += (time.time() - last_resume_time)
            last_resume_time = None
        ui_print("⏸️ 脚本已暂停，悬浮窗已隐藏 (按F12恢复)")
        if overlay_root:
            try: overlay_root.after(0, overlay_root.withdraw)
            except: pass
    else:
        last_resume_time = time.time()
        if overlay_root:
            try: overlay_root.after(0, overlay_root.deiconify)
            except: pass
        ui_print("▶️ 脚本已恢复，继续抢购！ (按F12暂停)")

keyboard.add_hotkey('f12', toggle_pause)

def smart_wait(seconds):
    gc.collect() 
    start = time.time()
    while time.time() - start < seconds:
        if IS_PAUSED: return False 
        time.sleep(0.01)
    return True

def crop_frame(frame, monitor):
    top = monitor["top"]
    bottom = top + monitor["height"]
    left = monitor["left"]
    right = left + monitor["width"]
    return frame[top:bottom, left:right]

def is_image_present(frame, monitor, template, threshold=0.8):
    try:
        cropped = crop_frame(frame, monitor)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        return max_val > threshold
    except: return False

def get_number(frame, templates):
    try:
        pixel_color = frame[207, 1320] 
        target_bgr = [110, 237, 255] 
        
        color_diff = abs(int(pixel_color[0]) - target_bgr[0]) + \
                     abs(int(pixel_color[1]) - target_bgr[1]) + \
                     abs(int(pixel_color[2]) - target_bgr[2])
                     
        if color_diff > 45:
            return None 

        cropped = crop_frame(frame, MONITOR_PRICE)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
            
        detected = []
        for num, temp in templates.items():
            res = cv2.matchTemplate(gray, temp, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= 0.75) 
            for pt in zip(*loc[::-1]):
                detected.append({'x': pt[0], 'num': num, 'score': res[pt[1], pt[0]]})
        if not detected: return None
        detected.sort(key=lambda x: x['x'])
        final_list = []
        if detected:
            last = detected[0]
            for i in range(1, len(detected)):
                if detected[i]['x'] - last['x'] < 5:
                    if detected[i]['score'] > last['score']: last = detected[i]
                else:
                    final_list.append(last); last = detected[i]
            final_list.append(last)
        res_str = "".join([i['num'] for i in final_list])
        return int(res_str) if len(res_str) >= 6 else None
    except Exception as e:
        # 消灭裸 except，记录真实错误但不中断
        # print(f"Number parsing error: {e}") 
        return None

def get_balance(frame):
    """优化版：通过图像 Hash 预判，如果画面没变，彻底跳过耗时的 OCR 计算"""
    global ocr_engine, _last_balance_hash, current_balance
    try:
        if ocr_engine is None:
            return None
        
        cropped = crop_frame(frame, MONITOR_BALANCE)
        
        # 【哈希提速引擎】将裁剪区缩小为 8x8 计算字节哈希
        tiny = cv2.resize(cropped, (8, 8))
        current_hash = tiny.tobytes()
        
        if _last_balance_hash is not None and current_hash == _last_balance_hash:
            return current_balance # 直接返回缓存的字符串，连正则也不用跑
            
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
                has_unit = any(u in res_str for u in ['万', '亿'])
                if has_unit:
                    res_str = res_str.replace("。", ".").replace(",", ".")
                else:
                    res_str = res_str.replace("。", "").replace(",", "").replace(".", "")
                
                res_str = res_str.replace(" ", "").replace("·", ".").replace("'", ".").replace("`", ".")
                res_str = re.sub(r'[^\d\.万亿]', '', res_str)
                
                if res_str:
                    _last_balance_hash = current_hash # 只有成功识别出有效字符才更新缓存
                
            return res_str if res_str else None
        return None
    except: 
        return None

def parse_balance(bal_str):
    if not bal_str: return None
    try:
        match = re.search(r'[\d\.]+', bal_str)
        if not match: return None
        num_val = float(match.group())
        
        if '亿' in bal_str:
            return int(round(num_val * 100000000)) 
        elif '万' in bal_str:
            return int(round(num_val * 10000))
        else:
            return int(num_val)
    except:
        return None

def check_balance_limit(frame):
    global current_balance, IS_PAUSED
    bal_str = get_balance(frame)
    if bal_str is not None and bal_str != "":
        current_balance = bal_str 
        if overlay_root: overlay_root.after(0, update_score_text)
        
        real_val = parse_balance(bal_str)
        if real_val is not None and real_val < 1300001:
            ui_print(f"🛑 余额不足！当前金额 {bal_str} 低于安全线，自动暂停。", save_log=True)
            async_push_msg("🛑 [2号电脑] 余额不足报警", f"识别金额 {bal_str} ({real_val})，已自动休眠防拉闸。")
            if not IS_PAUSED:
                toggle_pause()
            return False 
    return True 

def wait_and_recognize_balance(wait_time, camera):
    global temp_jiaoyi
    start_total = time.time()
    
    while time.time() - start_total < 1.4:
        if IS_PAUSED: return False
        frame = camera.get_latest_frame()
        if frame is not None:
            if is_image_present(frame, MONITOR_JIAOYIHANG, temp_jiaoyi, threshold=0.7):
                check_balance_limit(frame)
                break
        time.sleep(0.05)

    elapsed = time.time() - start_total
    remaining = wait_time - elapsed
    if remaining > 0:
        return smart_wait(remaining)
    return True

def click_exit():
    # 退出点击容忍度高，放大自旋阈值减少 CPU 空转
    precise_sleep(PRE_EXIT_CLICK_DELAY, spin_threshold=0.01)
    fast_click(EXIT_POS)

def setup_schedule():
    global target_stop_seconds
    while True:
        print("\n" + "="*40)
        print(" ⚙️  请选择启动模式：")
        print(" [1] 设置定时暂停任务")
        print(" [回车] 立即启动脚本 (无限制永久挂机)")
        print("="*40)
        choice = input("👉 请输入 1 设置定时，或直接按【回车】键启动: ").strip()

        if choice == '1':
            while True:
                time_str = input("⏳ 请输入运行时间 (例如 1.30 代表1小时30分, 3 代表3小时): ").strip()
                try:
                    if '.' in time_str:
                        h, m = time_str.split('.')
                        hours = int(h) if h else 0
                        minutes = int(m) if m else 0
                    else:
                        hours = int(time_str)
                        minutes = 0
                    target_stop_seconds = hours * 3600 + minutes * 60
                    if target_stop_seconds <= 0: continue
                    print(f"✅ 设置成功！脚本将在 {hours} 小时 {minutes} 分钟后暂停。")
                    return
                except ValueError: pass
        elif choice == '' or choice == '2':
            target_stop_seconds = 0
            return
        else: pass

# ================= 4. 主程序逻辑 =================

def run_automation():
    global limit_count, success_count, fail_count, unknown_page_count 
    global target_stop_seconds, ocr_engine, temp_jiaoyi
    
    setup_schedule()
    start_overlay()
    
    if os.name == 'nt':
        try:
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(handle, 0x00000100)
            ctypes.windll.kernel32.SetProcessAffinityMask(handle, 0x0055)
        except Exception: pass
            
    gc.disable()

    try:
        ocr_engine = RapidOCR()
        ui_print("✅ 本地 RapidOCR 引擎就绪！")
    except Exception as e:
        ui_print(f"❌ OCR加载失败: {e}")
        time.sleep(5); return

    templates = {str(i): cv2.imread(f"{i}.png", 0) for i in range(10)}
    temp_success = cv2.imread("chenggong.png", 0)
    temp_shop = cv2.imread("dianpu.png", 0)     
    temp_jiaoyi = cv2.imread("jiaoyihang.png", 0)
    temp_goumai = cv2.imread("goumai.png", 0)
    temp_meihuo = cv2.imread("meihuo.png", 0)
    temp_diyici = cv2.imread("diyici.png", 0)
    
    # 尺寸合法性校验，防止 cv2.matchTemplate 崩溃
    for num, temp in templates.items():
        if temp is None:
            ui_print(f"❌ 素材读取失败: 找不到 {num}.png！")
            time.sleep(5); return
        th, tw = temp.shape[:2]
        if th > MONITOR_PRICE["height"] or tw > MONITOR_PRICE["width"]:
            ui_print(f"❌ 素材越界: {num}.png 尺寸({tw}x{th})超过了识别区。")
            time.sleep(5); return
            
    if any(v is None for v in [temp_success, temp_shop, temp_jiaoyi, temp_goumai, temp_meihuo, temp_diyici]):
        ui_print("❌ 核心状态素材读取失败，请检查图片！")
        time.sleep(5); return

    try:
        camera = dxcam.create(output_color="BGRA")
        camera.start(target_fps=144) 
        ui_print("✅ 显卡 DXGI 通道全速运行。")
    except Exception as e:
        ui_print(f"❌ DXCAM 启动失败: {e}")
        time.sleep(5); return

    pyautogui.PAUSE = 0 
    last_refresh = time.time()
    last_success_time = time.time()
    last_idle_push_time = time.time()
    last_stuck_push_time = time.time()
    
    last_frame = None               
    last_frame_time = time.time()
    last_abnormal_print_sec = 0     
    
    try:
        while True:
            # 定时暂停校验
            if target_stop_seconds > 0:
                is_p = IS_PAUSED
                lrt = last_resume_time
                curr_elapsed = int(total_running_time + (time.time() - lrt)) if not is_p and lrt else int(total_running_time)
                
                if curr_elapsed >= target_stop_seconds:
                    async_push_msg("⏸️ [2号电脑] 定时暂停任务完成", "脚本已按计划运行结束。")
                    target_stop_seconds = 0
                    if not IS_PAUSED: toggle_pause()
                    continue 

            if IS_PAUSED:
                time.sleep(0.5)
                last_refresh = time.time()
                last_success_time = last_idle_push_time = last_stuck_push_time = time.time()
                # 暂停期间确保不保留旧帧缓存
                last_frame = None 
                continue

            try:
                current_time = time.time()
                
                # 监控：5分钟刷新卡死
                if current_time - last_refresh > STUCK_PUSH_INTERVAL and current_time - last_stuck_push_time > STUCK_PUSH_INTERVAL:
                    async_push_msg("🚨 [2号电脑] 脚本卡死警告", "超 5 分钟未执行刷新。")
                    last_stuck_push_time = current_time

                # 获取帧与【旧帧防灵异保护】
                raw_frame = camera.get_latest_frame()
                if raw_frame is None:
                    if last_frame is not None and (time.time() - last_frame_time) < FRAME_MAX_AGE:
                        frame = last_frame
                    else:
                        continue 
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
                        
                        # 【终极轮询优化】废弃死等 0.8 秒，改为高频动态探测
                        buy_result = "failed"
                        deadline = time.time() + 1.0 # 最多等 1.0 秒
                        while time.time() < deadline:
                            f = camera.get_latest_frame()
                            if f is not None:
                                if is_image_present(f, MONITOR_SUCCESS, temp_success):
                                    buy_result = "success"
                                    break
                                elif is_image_present(f, MONITOR_MEIHUO, temp_meihuo):
                                    buy_result = "sold_out"
                                    break
                            time.sleep(0.01) # 极高频检测
                        
                        if buy_result == "success":
                            success_count += 1
                            last_success_time = last_idle_push_time = time.time() 
                            if overlay_root: overlay_root.after(0, update_score_text)
                            ui_print(f"✔ 抢到! 识别价格: {price}", save_log=True, show_console=False)
                            precise_sleep(0.05)
                            fast_click(SUCCESS_CONFIRM_POS)
                            precise_sleep(0.1)
                            fast_click(SUCCESS_CONFIRM_POS)
                        elif buy_result == "sold_out":
                            # 被别人捷足先登售空，直接走极速通道，不计入失败，也无需点击退出
                            ui_print(f"⚡ 晚了一步，已售空! 识别价格: {price}", is_replace=True)
                            pass
                        else:
                            fail_count += 1
                            if overlay_root: overlay_root.after(0, update_score_text)
                            ui_print(f"✖ 错过! 识别价格: {price}", save_log=True, show_console=False)
                            click_exit() 
                        
                        if wait_and_recognize_balance(EXIT_DELAY, camera): 
                            fast_click(REFRESH_POS) 
                            last_refresh = time.time()
                    else:
                        ui_print(f"⏭️ 价格不符: {price}", is_replace=True)
                        click_exit() 
                        if wait_and_recognize_balance(MISMATCH_EXIT_DELAY, camera):
                            fast_click(REFRESH_POS) 
                            last_refresh = time.time()
                else:
                    if is_image_present(frame, MONITOR_MEIHUO, temp_meihuo):
                        unknown_page_count = 0
                        ui_print("⚡ 识别到售空！", is_replace=True)
                        click_exit()
                        if wait_and_recognize_balance(EXIT_DELAY, camera):
                            fast_click(REFRESH_POS)
                            last_refresh = time.time()
                        continue 
                    
                    time_since_last_action = time.time() - last_refresh
                    if time_since_last_action > 3.0:
                        is_normal_empty = is_image_present(frame, MONITOR_JIAOYIHANG, temp_jiaoyi) and is_image_present(frame, MONITOR_SHOP, temp_shop)
                        if is_normal_empty:
                            limit_count += 1; unknown_page_count = 0
                            ui_print(f"🔄 店铺空置 ({limit_count}/{ACCOUNT_LIMIT_THRESHOLD})", is_replace=True)
                            if limit_count >= ACCOUNT_LIMIT_THRESHOLD:
                                async_push_msg("🛑 [2号电脑] 账号被限", "连续多次店铺为空，自动休眠。")
                                limit_count = 0
                                if not IS_PAUSED: toggle_pause() 
                                continue 
                            if not check_balance_limit(frame): continue 
                            fast_click(REFRESH_POS)
                            gc.collect()
                            last_refresh = time.time()
                        else:
                            if unknown_page_count == 0 or time_since_last_action > 10.0:
                                ui_print("\n⚠️ 画面异常！全场景识别...", save_log=True)
                                is_unknown_page = False
                                if is_image_present(frame, MONITOR_DIYICI, temp_diyici, threshold=0.6):
                                    fast_click(DIYICI_CLICK_POS)
                                elif is_image_present(frame, MONITOR_GOUMAI, temp_goumai, threshold=0.6):
                                    click_exit()
                                elif is_image_present(frame, MONITOR_JIAOYIHANG, temp_jiaoyi, threshold=0.6) and not is_image_present(frame, MONITOR_SHOP, temp_shop, threshold=0.6):
                                    fast_click(FIX_SHOP_POS1)
                                    precise_sleep(1.0)
                                    fast_click(FIX_SHOP_POS2)
                                else:
                                    is_unknown_page = True; unknown_page_count += 1
                                    if unknown_page_count >= 20:
                                        async_push_msg("🚨 [2号电脑] 未知死锁", "长时卡在未知页面。")
                                        unknown_page_count = 0
                                        if not IS_PAUSED: toggle_pause()
                                    else:
                                        last_refresh = time.time(); last_abnormal_print_sec = 0
                                
                                if not is_unknown_page:
                                    unknown_page_count = 0
                                    if smart_wait(1.0):
                                        fast_click(REFRESH_POS)
                                        last_refresh = time.time()
                            else:
                                current_sec = int(time_since_last_action)
                                if current_sec != last_abnormal_print_sec:
                                    ui_print(f"⏳ 等待场景识别介入 ({current_sec}s/10s)", is_replace=True)
                                    last_abnormal_print_sec = current_sec

                time.sleep(0.002) 
            except Exception: time.sleep(0.5)
    finally: camera.stop() 

if __name__ == "__main__":
    try: run_automation()
    except SystemExit: pass 
    except KeyboardInterrupt: sys.exit()
