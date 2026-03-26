import mss
import cv2
import numpy as np
import time

# --- 1. 你的精准坐标 ---
MONITOR = {
    "left": 1472, 
    "top": 288, 
    "width": 99,   
    "height": 23   
}

def generate_debug_image():
    with mss.mss() as sct:
        print(f"正在截取区域: {MONITOR['left']}, {MONITOR['top']}...")
        
        # 1. 抓取原始屏幕画面
        sct_img = np.array(sct.grab(MONITOR))
        # 转换成 BGR 格式（OpenCV 标准）
        frame = cv2.cvtColor(sct_img, cv2.COLOR_BGRA2BGR)
        
        # 2. 转为灰度图
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # 3. 使用自适应阈值（OTSU）进行黑白二值化
        # 这会让数字变白，背景变黑（或者反过来）
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # 4. 确保是“黑底白字”（符合 OpenCV 匹配习惯）
        if np.sum(binary == 255) > np.sum(binary == 0):
            binary = cv2.bitwise_not(binary)
        
        # 5. 保存图片到本地
        filename = "debug_check.png"
        cv2.imwrite(filename, binary)
        
        print(f"---")
        print(f"✅ 图片已生成: {filename}")
        print(f"请打开文件夹查看这张图。")
        print(f"如果图里能清晰看到白色的数字，就说明坐标和图像处理都对准了！")
        print(f"---")

if __name__ == "__main__":
    # 给自己 2 秒钟切换到游戏窗口的时间
    print("脚本将在 2 秒后截图，请确保游戏窗口没被遮挡...")
    time.sleep(2)
    generate_debug_image()