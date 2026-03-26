import mss
import cv2
import numpy as np
import pydirectinput
import time

# --- 1. 核心准备工作 ---
# 你需要提前截好数字 0-9 的图片，放在文件夹里
# 比如 '0.png', '1.png' ... '9.png'
DIGITS = {str(i): cv2.imread(f'{i}.png', 0) for i in range(10)}

def get_number_from_screen(monitor_area):
    with mss.mss() as sct:
        # 截图并转灰度
        img = np.array(sct.grab(monitor_area))
        gray_screen = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
        
        detected_results = []
        
        # 用 0-9 的模板去撞库
        for num, template in DIGITS.items():
            if template is None: continue
            res = cv2.matchTemplate(gray_screen, template, cv2.TM_CCOEFF_NORMED)
            threshold = 0.9  # 匹配度要求 90%
            loc = np.where(res >= threshold)
            
            for pt in zip(*loc[::-1]):
                # 记录找到的数字及其 X 坐标（用来排序）
                detected_results.append((pt[0], num))
        
        # 按 X 坐标排序，把数字拼起来 (比如 [ (10, '9'), (25, '8') ] -> '98')
        detected_results.sort()
        final_number = "".join([item[1] for item in detected_results])
        return int(final_number) if final_number else None

# --- 2. 抢购主循环 ---
MONITOR = {"top": 400, "left": 800, "width": 150, "height": 50} # 极其精准的小区域
PRICE_LIMIT = 500  # 你的预算

print("极速模式启动...")
while True:
    current_price = get_number_from_screen(MONITOR)
    
    if current_price is not None:
        print(f"当前价格: {current_price}")
        if current_price <= PRICE_LIMIT:
            # 瞬间点击
            pydirectinput.click(MONITOR["left"] + 75, MONITOR["top"] + 25)
            print("!!! 抢到了 !!!")
            break
    
    # 极短延迟，甚至可以不加，取决于你 CPU 够不够强
    time.sleep(0.01)