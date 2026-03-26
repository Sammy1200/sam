import mss
import cv2
import numpy as np
import time

# 你提供的新坐标：左上角 (1698, 184)，右下角 (1762, 271)
# 计算宽度: 1762 - 1698 = 64
# 计算高度: 271 - 184 = 87
MONITOR_TEST_AREA = {"left": 1698, "top": 184, "width": 64, "height": 87}

def test_recognition():
    # 这里默认测试 jiaoyihang.png，如果你要测 dianpu.png，直接改名字就行
    target_image_name = "jiaoyihang.png" 
    
    temp_img = cv2.imread(target_image_name, 0)
    if temp_img is None:
        print(f"❌ 错误：在当前文件夹找不到 {target_image_name}！")
        return

    print("=========================================")
    print(f"🔍 启动专属测试，监测区域: {MONITOR_TEST_AREA}")
    print(f"🎯 正在测试匹配目标: {target_image_name}")
    print("💡 请切入游戏，并停留在对应页面。")
    print("⏳ 每秒打印一次匹配度，按 Ctrl+C 停止测试")
    print("=========================================\n")

    with mss.mss() as sct:
        try:
            while True:
                # 抓取屏幕特定区域
                sct_img = sct.grab(MONITOR_TEST_AREA)
                img = np.array(sct_img)
                gray = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
                
                # 【关键】把脚本截到的图保存下来，让你能亲眼看到它到底看到了啥
                cv2.imwrite("debug_capture.png", gray)

                # 计算相似度
                res = cv2.matchTemplate(gray, temp_img, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(res)

                # 打印结果
                if max_val >= 0.8:
                    print(f"🟢 [成功] 找到标志！当前匹配度: {max_val:.4f} (及格线 0.8)")
                else:
                    print(f"🔴 [失败] 未达标。当前匹配度: {max_val:.4f} (及格线 0.8)")
                
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n测试结束。请检查文件夹内的 debug_capture.png 看看截图是否准确。")

if __name__ == "__main__":
    test_recognition()
