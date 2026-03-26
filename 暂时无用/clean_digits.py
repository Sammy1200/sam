import cv2
import numpy as np
import os

# --- 配置 ---
INPUT_FILE = 'all_digits.png'  # 包含 0-9 所有的原始截图
OUTPUT_DIR = 'digits'          # 保存切片后的文件夹

# --- 主逻辑 ---
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# 1. 读取图片并转灰度
img = cv2.imread(INPUT_FILE)
if img is None:
    print(f"错误：找不到文件 {INPUT_FILE}")
    exit()
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

# 2. 关键：二值化（将背景变纯黑，数字变纯白）
# 根据你的游戏画面，可能需要调整 150 这个阈值
_, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

# 3. 查找数字轮廓
contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

# 4. 对轮廓按从左到右排序
contours = sorted(contours, key=lambda ctr: cv2.boundingRect(ctr)[0])

if len(contours) < 10:
    print(f"警告：只找到了 {len(contours)} 个数字，请检查阈值或截图！")

# 5. 切片并保存
for i, ctr in enumerate(contours):
    if i >= 10: break # 只取前10个
    
    # 获取每个数字的包裹矩形
    x, y, w, h = cv2.boundingRect(ctr)
    
    # 根据轮廓切片（只留纯黑白抠图）
    roi = thresh[y:y+h, x:x+w]
    
    # 或者如果你想要带颜色的数字，但背景是黑色的：
    # roi = img[y:y+h, x:x+w]
    # _, mask = cv2.threshold(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), 150, 255, cv2.THRESH_BINARY)
    # roi = cv2.bitwise_and(roi, roi, mask=mask)

    # 保存为 0.png, 1.png...
    file_name = os.path.join(OUTPUT_DIR, f"{i}.png")
    cv2.imwrite(file_name, roi)
    print(f"已生成: {file_name}")

print(f"\n✅ 0-9 干净素材已生成在 '{OUTPUT_DIR}' 文件夹中。")
print("请将它们复制到你抢购脚本的文件夹下。")