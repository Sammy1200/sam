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

# ================= 1. 坐标与参数配置 =================
MONITOR_PRICE = {"left": 1473, "top": 181, "width": 79, "height": 22} 
MONITOR_SUCCESS = {"left": 780, "top": 190, "width": 370, "height": 143}
MONITOR_SHOP = {"left": 1600, "top": 100, "width": 66, "height": 55}       
MONITOR_JIAOYIHANG = {"left": 1698, "top": 184, "width": 64, "height": 87} 
MONITOR_GOUMAI = {"left": 883, "top": 367, "width": 80, "height": 33}      
MONITOR_MEIHUO = {"left": 590, "top": 838, "width": 117, "height": 46}
MONITOR_DIYICI = {"left": 780, "top": 673, "width": 107, "height": 43}

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

# 【极限压缩】购买与确定之间的延迟为 0.01 秒
CONFIRM_DELAY = 0.01
PRE_EXIT_CLICK_DELAY = 0.03 
EXIT_DELAY = 1.88            
MISMATCH_EXIT_DELAY = 1.88  

ACCOUNT_LIMIT_THRESHOLD = 20 

# 推送阈值 (单位: 秒)
IDLE_PUSH_INTERVAL = 1800  # 30分钟未抢到商品汇报一次存活
STUCK_PUSH_INTERVAL = 300  # 5分钟未执行任何刷新判定为卡死/掉线

IS_PAUSED = False
limit_count = 0 

success_count = 0
fail_count = 0
total_running_time = 0.0  
last_resume_time = None   
target_stop_seconds = 0  # 定时暂停目标秒数

pyautogui.FAILSAFE = False

# ================= 2. 悬浮窗控制系统 (OSD) =================
overlay_root = None
log_text_var = None
score_var = None  
log_lines = []

def update_score_text():
    global overlay_root, score_var, success_count, fail_count
    global total_running_time, last_resume_time, IS_PAUSED

    if overlay_root and score_var:
        if not IS_PAUSED and last_resume_time is not None:
            elapsed = int(total_running_time + (time.time() - last_resume_time))
        else:
            elapsed = int(total_running_time)
            
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        s = elapsed % 60
        msg = f"🖥️ ⏱️ 运行: {h:02d}:{m:02d}:{s:02d}  |  ✔ 成功: [ {success_count} ] 次  |  ✖ 失败: [ {fail_count} ] 次"
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

def ui_print(msg, is_replace=False, save_log=False):
    global overlay_root, log_text_var, log_lines
    now = datetime.now().strftime('%H:%M:%S')
    
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
    """Win32 API 底层鼠标点击"""
    x, y = pos
    ctypes.windll.user32.SetCursorPos(x, y)
    ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0) 
    ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0) 

def precise_sleep(seconds):
    """混合休眠，微秒级精度阻塞"""
    if seconds <= 0: return
    target_time = time.perf_counter() + seconds
    while target_time - time.perf_counter() > 0.003:
        time.sleep(0.001) 
    while time.perf_counter() < target_time:
        pass

def async_push_msg(title, content):
    """微信异步推送子线程"""
    def send():
        token = "59653da98d3049adb1deb19660767621"  # 你的 PushPlus Token
        url = "http://www.pushplus.plus/send"
        data = {"token": token, "title": title, "content": content}
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
    """矩阵切片工具：从全屏画面提取所需区域"""
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
        # ==================== 单点像素极速预检 ====================
        # 使用全屏绝对坐标 (Y=207, X=1320)，防错规避局部裁剪越界
        pixel_color = frame[207, 1320] 
        
        # 目标 RGB(255, 237, 110) 转为 BGRA: B=110, G=237, R=255
        target_bgr = [110, 237, 255] 
        
        # 计算颜色绝对通道误差
        color_diff = abs(int(pixel_color[0]) - target_bgr[0]) + \
                     abs(int(pixel_color[1]) - target_bgr[1]) + \
                     abs(int(pixel_color[2]) - target_bgr[2])
                     
        # 宽容度设为 30。如果不符，0毫秒瞬间跳过整帧
        if color_diff > 30:
            return None 
        # ========================================================

        # 预检通过，才执行极耗 CPU 的裁剪、灰度与 10 次矩阵匹配
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
    except: return None

def click_exit():
    precise_sleep(PRE_EXIT_CLICK_DELAY)
    fast_click(EXIT_POS)

def setup_schedule():
    """配置启动模式与定时任务"""
    global target_stop_seconds
    while True:
        print("\n" + "="*40)
        print(" ⚙️  请选择启动模式：")
        print(" [1] 设置定时暂停任务")
        print(" [2] 立即启动脚本 (无定时)")
        print("="*40)
        choice = input("👉 请输入选项 (1或2) 并回车: ").strip()

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
                    if target_stop_seconds <= 0:
                        print("❌ 时间必须大于0！")
                        continue
                    print(f"✅ 设置成功！脚本将在悬浮窗计时达到 {hours} 小时 {minutes} 分钟后自动暂停。")
                    return
                except ValueError:
                    print("❌ 格式错误，请重新输入！(仅支持数字和小数点)")
        elif choice == '2':
            target_stop_seconds = 0
            print("✅ 已选择立即启动！")
            return
        else:
            print("❌ 无效选项，请输入 1 或 2！")

# ================= 4. 主程序逻辑 =================

def run_automation():
    global limit_count, success_count, fail_count 
    global target_stop_seconds
    
    # 启动前让用户选择定时设置
    setup_schedule()
    
    start_overlay()
    
    if os.name == 'nt':
        try:
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(handle, 0x00000100)
            ctypes.windll.kernel32.SetProcessAffinityMask(handle, 0x0055)
        except Exception as e: pass
            
    gc.disable()

    templates = {str(i): cv2.imread(f"{i}.png", 0) for i in range(10)}
    temp_success = cv2.imread("chenggong.png", 0)
    temp_shop = cv2.imread("dianpu.png", 0)     
    temp_jiaoyi = cv2.imread("jiaoyihang.png", 0)
    temp_goumai = cv2.imread("goumai.png", 0)
    temp_meihuo = cv2.imread("meihuo.png", 0)
    temp_diyici = cv2.imread("diyici.png", 0)
    
    if any(v is None for v in [temp_success, temp_shop, temp_jiaoyi, temp_goumai, temp_meihuo, temp_diyici]):
        ui_print("❌ 核心素材读取失败，请检查图片！")
        time.sleep(5)
        return

    ui_print("🚀 正在启动显卡 DirectX 捕获通道...")
    try:
        camera = dxcam.create(output_color="BGRA")
        camera.start(target_fps=144) 
        ui_print("✅ 显卡通道接管成功！视觉并发流水线全开。")
    except Exception as e:
        ui_print(f"❌ DXCAM 启动失败: {e}。请确保游戏为无边框窗口化模式。")
        time.sleep(5)
        return

    pyautogui.PAUSE = 0 
    
    last_refresh = time.time()
    last_success_time = time.time()
    last_idle_push_time = time.time()
    last_stuck_push_time = time.time()
    
    try:
        while True:
            # ---------------- 定时暂停校验模块 ----------------
            if target_stop_seconds > 0:
                if not IS_PAUSED and last_resume_time is not None:
                    current_elapsed = int(total_running_time + (time.time() - last_resume_time))
                else:
                    current_elapsed = int(total_running_time)
                    
                if current_elapsed >= target_stop_seconds:
                    ui_print("⏰ 设定的运行时间已到，准备暂停脚本...", save_log=True)
                    
                    # 格式化运行时间用于推送
                    h = current_elapsed // 3600
                    m = (current_elapsed % 3600) // 60
                    s = current_elapsed % 60
                    
                    push_content = (
                        f"脚本已按计划运行了设定的时间，现已自动暂停挂机。\n"
                        f"--------------------\n"
                        f"✔ 成功抢购: {success_count} 次\n"
                        f"✖ 失败抢购: {fail_count} 次\n"
                        f"⏱️ 运行时间: {h}小时{m}分{s}秒"
                    )
                    async_push_msg("⏸️ [1号电脑] 定时暂停任务完成", push_content)
                    
                    target_stop_seconds = 0  # 重置定时目标，防止恢复脚本后被无限重复暂停
                    
                    if not IS_PAUSED:
                        toggle_pause() # 调用现有函数自动隐去悬浮窗并暂停脚本
                        
                    continue # 跳出本次循环，下次进来时会在上方的暂停判定处休息
            # --------------------------------------------------

            if IS_PAUSED:
                time.sleep(0.5)
                last_refresh = time.time()
                last_success_time = time.time()
                last_idle_push_time = time.time()
                last_stuck_push_time = time.time()
                continue

            try:
                # ---------------- 推送监控模块 ----------------
                current_time = time.time()
                
                # 监控 1: 长时间(30分钟)无收获汇报 (已取消推送)
                if current_time - last_success_time > IDLE_PUSH_INTERVAL and current_time - last_idle_push_time > IDLE_PUSH_INTERVAL:
                    # async_push_msg("⏳ 运行状态存活汇报", f"脚本已连续监控 {IDLE_PUSH_INTERVAL // 60} 分钟未抢购到新商品，当前循环机制正常。")
                    last_idle_push_time = current_time
                    
                # 监控 2: 长时间(5分钟)未执行任何刷新判定为卡死/掉线
                if current_time - last_refresh > STUCK_PUSH_INTERVAL and current_time - last_stuck_push_time > STUCK_PUSH_INTERVAL:
                    async_push_msg("🚨 [1号电脑] 脚本异常/卡死警告", f"超过 {STUCK_PUSH_INTERVAL // 60} 分钟未执行任何刷新动作，页面可能卡死或掉线，请远程查看！")
                    last_stuck_push_time = current_time
                # ----------------------------------------------

                frame = camera.get_latest_frame()
                if frame is None:
                    continue 
                    
                price = get_number(frame, templates)
                
                if price is not None:
                    limit_count = 0 
                    last_refresh = time.time() 
                    
                    if MIN_PRICE < price < MAX_PRICE:
                        
                        fast_click(BUY_POS)
                        precise_sleep(CONFIRM_DELAY) 
                        fast_click(CONFIRM_POS)
                        
                        time.sleep(0.8)
                        frame_after = camera.get_latest_frame()
                        
                        if frame_after is not None and is_image_present(frame_after, MONITOR_SUCCESS, temp_success):
                            success_count += 1
                            last_success_time = time.time() 
                            last_idle_push_time = time.time() 
                            
                            if overlay_root: overlay_root.after(0, update_score_text)
                            ui_print(f"✔ 抢购成功! 识别价格: {price}", save_log=True)
                            
                            precise_sleep(0.2)
                            fast_click(SUCCESS_CONFIRM_POS)
                            precise_sleep(0.2)
                            fast_click(SUCCESS_CONFIRM_POS)
                            # 挂载推送 (已取消成功提醒推送)
                            # async_push_msg("🎉 抢购成功提醒", f"已成功抢购商品，识别价格: {price}")
                        else:
                            fail_count += 1
                            if overlay_root: overlay_root.after(0, update_score_text)
                            ui_print(f"✖ 抢购失败! 识别价格: {price}", save_log=True)
                            
                            click_exit() 
                            
                        # 原版连招：盲等完毕后直接刷新
                        if smart_wait(EXIT_DELAY): 
                            fast_click(REFRESH_POS) 
                            last_refresh = time.time()
                    else:
                        ui_print(f"⏭️ 价格不符！识别价格: {price}", is_replace=True)
                        click_exit() 
                        
                        # 原版连招：退出后直接刷新
                        if smart_wait(MISMATCH_EXIT_DELAY):
                            fast_click(REFRESH_POS) 
                            last_refresh = time.time()
                
                else:
                    if is_image_present(frame, MONITOR_MEIHUO, temp_meihuo):
                        ui_print("⚡ 识别到售空！极速退出...", is_replace=True)
                        click_exit()
                        
                        # 原版连招：退出后直接刷新
                        if smart_wait(EXIT_DELAY):
                            fast_click(REFRESH_POS)
                            last_refresh = time.time()
                        continue 
                    
                    if time.time() - last_refresh > 5.0:
                        
                        if is_image_present(frame, MONITOR_DIYICI, temp_diyici):
                            ui_print("🚨 识别到异常弹窗(diyici)，执行自动消除...", is_replace=True)
                            fast_click(DIYICI_CLICK_POS)
                            last_refresh = time.time()
                            
                        elif is_image_present(frame, MONITOR_GOUMAI, temp_goumai):
                            ui_print("🚨 卡在详情页。强制退出...")
                            click_exit()
                            if smart_wait(EXIT_DELAY):
                                last_refresh = time.time()
                            
                        elif is_image_present(frame, MONITOR_JIAOYIHANG, temp_jiaoyi):
                            if not is_image_present(frame, MONITOR_SHOP, temp_shop):
                                ui_print("🚨 店铺图丢失。强制修复...")
                                fast_click(FIX_SHOP_POS1)
                                if smart_wait(1.0):
                                    fast_click(FIX_SHOP_POS2)
                                    last_refresh = time.time()
                            else:
                                limit_count += 1
                                ui_print(f"🔄 正常空置店铺... (未见价格 {limit_count}/{ACCOUNT_LIMIT_THRESHOLD})", is_replace=True)
                                
                                if limit_count >= ACCOUNT_LIMIT_THRESHOLD:
                                    ui_print("🛑 警告：疑似被限！脚本休眠并发送微信。", save_log=True)
                                    
                                    async_push_msg("🛑 [1号电脑] 账号被限休眠警告", f"连续 {ACCOUNT_LIMIT_THRESHOLD} 次空置，脚本已自动休眠，请尽快手动处理。")
                                    
                                    limit_count = 0  
                                    if not IS_PAUSED:
                                        toggle_pause() 
                                    continue 
                                        
                                # 原版连招：店铺为空时直接点击刷新
                                fast_click(REFRESH_POS)
                                last_refresh = time.time()
                                
                        else:
                            ui_print("❓ 未知页面。5秒后重试...", is_replace=True)
                            last_refresh = time.time()

                time.sleep(0.002) 
            except Exception as e:
                time.sleep(0.5); continue
    finally:
        camera.stop() 

if __name__ == "__main__":
    try:
        run_automation()
    except SystemExit:
        pass 
    except KeyboardInterrupt:
        sys.exit()
