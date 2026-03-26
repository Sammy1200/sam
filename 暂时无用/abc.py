import cv2
import numpy as np
import os

def auto_extract_from_gray():
    # 1. 读取你刚才生成的那张灰度图
    img = cv2.imread("RAW_GRAY.png", 0)
    if img is None:
        print("❌ 错误：找不到 RAW_GRAY.png")
        return

    # 2. 简单的二值化，把灰色数字变成纯白，方便切割
    _, binary = cv2.threshold(img, 100, 255, cv2.THRESH_BINARY)
    
    # 3. 寻找轮廓（每个数字块）
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # 按从左到右排序
    contours = sorted(contours, key=lambda c: cv2.boundingRect(c)[0])
    
    print(f"🔍 发现 {len(contours)} 个潜在数字块，开始提取...")
    
    if not os.path.exists("temp_images"):
        os.makedirs("temp_images")

    idx = 0
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        
        # 过滤掉太小的杂质（比如逗号）
        if h < 10 or w < 2:
            continue
            
        # 从【原始灰度图】上切下这个数字，保持原汁原味的灰色
        digit_crop = img[y:y+h, x:x+w]
        
        save_path = f"temp_images/crop_{idx}.png"
        cv2.imwrite(save_path, digit_crop)
        print(f"💾 已保存: {save_path}")
        idx += 1

    print("\n✅ 提取完成！请打开 'temp_images' 文件夹。")
    print("⚠️  你需要做的是：看图识字，把它们重命名为 0.png, 1.png... 覆盖到主目录。")

if __name__ == "__main__":
    auto_extract_from_gray()
