import cv2
import numpy as np
import time
import os
import sys
import ctypes
import keyboard
import re
import dxcam
from rapidocr_onnxruntime import RapidOCR

# ================= 1. 绝对路径装甲与素材读取 =================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def safe_imread(filename, flags=0):
    filepath = os.path.join(SCRIPT_DIR, filename)
    if not os.path.exists(filepath): return None
    return cv2.imdecode(np.fromfile(filepath, dtype=np.uint8), flags)

TEMP_JIAOYI = safe_imread("jiaoyihang.png", 0)

# ================= 2. 坐标与区域定义 =================
CLICK_1 = (1850, 990)
CLICK_2 = (1855, 269)
CLICK_JIAOSHI = (1730, 370) 

MONITOR_TEXT_SHANGJIA = {"left": 70, "top": 80, "width": 110, "height": 50}
MONITOR_TEXT_JIAOSHI = {"left": 1700, "top": 350, "width": 60, "height": 40}
MONITOR_CAPACITY = {"left": 179, "top": 103, "width": 51, "height": 27}

ocr_engine = None
camera = None
is_running = False

# ================= 3. 底层驱动函数 =================
def fast_click(pos):
    x, y = pos
    ctypes.windll.user32.SetCursorPos(x, y)
    time.sleep(0.05) 
    ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0) 
    ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0) 
    time.sleep(0.05)

def crop_frame(frame, monitor):
    top = monitor["top"]
    bottom = top + monitor["height"]
    left = monitor["left"]
    right = left + monitor["width"]
    return frame[top:bottom, left:right]

def read_text_from_area(frame, monitor, is_number_mode=False):
    """通用高精度 OCR 读取模块（取消放大，直接用原图识别）"""
    try:
        cropped = crop_frame(frame, monitor)
        
        if is_number_mode:
            # ================== 灰度 + 锐化（不放大，保留原始清晰度） ==================
            gray_img = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
            
            # 拉普拉斯边缘锐化，让数字边缘更清晰，防止 5 和 6 粘连
            kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
            sharpened = cv2.filter2D(gray_img, -1, kernel)
            
            # 补边防裁剪（图片没放大了，边框也相应缩小）
            padded = cv2.copyMakeBorder(sharpened, 8, 8, 8, 8, cv2.BORDER_REPLICATE)
            final_img = cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)
            
            # 送入 OCR
            result, _ = ocr_engine(final_img)
            if result and len(result) > 0:
                text = "".join([item[1] for item in result])
                
                # 暴力清洗干扰项
                text = text.replace(" ", "")
                text = text.replace("O", "0").replace("o", "0").replace("Q", "0").replace("D", "0")
                text = re.sub(r'[lI|\\i]+', '/', text) 
                
                numbers = re.findall(r'\d+', text)
                if numbers:
                    current_str = numbers[0] 
                    try:
                        current_num = int(current_str)
                        if 0 <= current_num <= 10:
                            return f"{current_num}/10"
                        elif current_str.endswith("10") and len(current_str) >= 3:
                            real_current = int(current_str[:-2])
                            if 0 <= real_current <= 10:
                                return f"{real_current}/10"
                    except ValueError:
                        pass
            return ""
            
        else:
            # ================== 常规汉字提取模式（不放大，直接识别原图） ==================
            gray_img = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
            padded = cv2.copyMakeBorder(gray_img, 8, 8, 8, 8, cv2.BORDER_REPLICATE)
            final_img = cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)
            
            result, _ = ocr_engine(final_img)
            if result and len(result) > 0:
                text = "".join([item[1] for item in result])
                return text
            return ""
            
    except Exception as e:
        return ""

def wait_for_ocr_text(camera_obj, monitor, keywords, timeout=3.0):
    start_time = time.time()
    print(f"   ⏳ 正在死盯屏幕等待文字 {keywords} ...")
    
    while time.time() - start_time < timeout:
        frame = camera_obj.get_latest_frame()
        if frame is None:
            time.sleep(0.05)
            continue
            
        text = read_text_from_area(frame, monitor, is_number_mode=False)
        if text:
            for kw in keywords:
                if kw in text:
                    print(f"   [✔] 识别成功！提取到文本: '{text}' (耗时: {time.time()-start_time:.2f}s)")
                    return True
        time.sleep(0.05)
        
    print(f"   [❌] 等待超时({timeout}s)，未能在指定区域发现目标文字！")
    return False

def check_jiaoyihang(frame):
    if TEMP_JIAOYI is None:
        print("❌ 找不到 jiaoyihang.png，请确保它与脚本在同一个文件夹下。")
        return False
    cropped = crop_frame(frame, {"left": 1698, "top": 184, "width": 64, "height": 87})
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
    res = cv2.matchTemplate(gray, TEMP_JIAOYI, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(res)
    return max_val > 0.7

# ================= 4. 业务执行逻辑 =================
def run_test_sequence():
    global is_running, camera
    if is_running: return
    is_running = True
    
    print("\n" + "="*50)
    print(" ⏳ 收到 [F12] 指令！延迟 2 秒执行，请点击切回游戏窗口...")
    time.sleep(2.0)
    print(" 🚀 开始执行上架寻路测试...")
    
    frame = camera.get_latest_frame()
    if not check_jiaoyihang(frame):
        print(" ⛔ 警告：当前似乎不在交易行界面！测试中止。")
        is_running = False
        return
        
    try:
        # [步骤 1] 点击 1850, 990
        print(f"\n👉 [步骤 1] 点击起始按钮 {CLICK_1}")
        fast_click(CLICK_1)
        
        # [步骤 2] 等待"上架数量"出现
        print(f"\n👉 [步骤 2] 验证是否进入第一层界面...")
        if not wait_for_ocr_text(camera, MONITOR_TEXT_SHANGJIA, ["上架", "数量"]):
            raise Exception("寻路失败：未找到'上架数量'字样。")
            
        # [步骤 3] 点击 1855, 269
        print(f"\n👉 [步骤 3] 点击第二层入口 {CLICK_2}")
        fast_click(CLICK_2)
        
        # [步骤 4] 等待"角石"出现
        print(f"\n👉 [步骤 4] 验证是否出现目标道具分类...")
        if not wait_for_ocr_text(camera, MONITOR_TEXT_JIAOSHI, ["角石"]):
            raise Exception("寻路失败：未找到'角石'分类。")
            
        # [步骤 5] 点击"角石"进入背包
        print(f"\n👉 [步骤 5] 点击角石字样 {CLICK_JIAOSHI}")
        fast_click(CLICK_JIAOSHI)
        
        # [步骤 6] 等待并解析上架容量
        print(f"\n👉 [步骤 6] 正在进入背包，解析当前上架额度...")
        time.sleep(0.5) 
        
        capacity_str = ""
        for _ in range(5):
            frame = camera.get_latest_frame()
            if frame is not None:
                capacity_str = read_text_from_area(frame, MONITOR_CAPACITY, is_number_mode=True)
                if "/" in capacity_str:
                    break
            time.sleep(0.1)
            
        print(f"   [🔍] 经过业务规则过滤后的额度: '{capacity_str}'")
        
        if "/" in capacity_str:
            parts = capacity_str.split("/")
            try:
                current = int(parts[0]) if parts[0].isdigit() else -1
                total = int(parts[1]) if parts[1].isdigit() else 10
                
                if current != -1:
                    remaining = total - current
                    print(f"\n📊 额度解析结果：已上架 {current} 个，总上限 {total} 个。")
                    
                    if remaining <= 0:
                        print(f"⛔ 上限已满 (剩余 {remaining} 个)！触发退出逻辑。")
                    else:
                        print(f"✅ 额度充足！还可以继续上架 {remaining} 个道具。")
                else:
                    print("❌ 额度解析失败：未能提取出正确的数字分子。")
            except Exception as calc_e:
                print(f"❌ 计算额度时发生内部错误: {calc_e}")
        else:
            print("❌ 额度解析失败：未找到分隔符。")

    except Exception as e:
        print(f"\n💥 测试逻辑执行中断: {e}")
        
    print("="*50)
    print("🏁 测试本轮执行结束。")
    os.system('pause') 
    print("👉 请按 F12 再次触发测试，或按 ESC 退出整个程序。")
    is_running = False

def main():
    global ocr_engine, camera
    print("初始化 AI 引擎与显卡直连...")
    ocr_engine = RapidOCR()
    camera = dxcam.create(output_color="BGRA")
    camera.start(target_fps=60)
    
    print("✅ 初始化完成！请切入游戏交易行界面，按下【F12】开始自动上架寻路测试。")
    keyboard.add_hotkey('f12', run_test_sequence)
    keyboard.wait('esc')
    camera.stop()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("\n💥 脚本发生全局致命错误！")
    finally:
        os.system('pause')
