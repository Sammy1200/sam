import cv2
import numpy as np
import os

def start_slicing():
    # 1. 设置文件名和路径
    input_file = 'debug_check.png'
    output_dir = 'digits_new'

    print(f"--- 自动切片工具启动 ---")

    # 2. 检查图片是否存在
    if not os.path.exists(input_file):
        print(f"❌ 错误：在当前文件夹下没找到 '{input_file}'！")
        print(f"请先运行 generate_debug.py 生成这张图。")
        return

    # 3. 读取图片
    img = cv2.imread(input_file, 0) # 以灰度模式读取
    if img is None:
        print(f"❌ 错误：无法读取图片，文件可能损坏。")
        return

    # 4. 寻找数字轮廓
    # 查找所有的白色色块
    contours, _ = cv2.findContours(img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # 5. 提取并排序
    digit_boxes = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        # 过滤掉太小的杂点（宽>2且高>5才算数字）
        if w > 2 and h > 5:
            digit_boxes.append((x, y, w, h))

    # 按从左到右的位置排序
    digit_boxes.sort()

    print(f"🔍 识别到 {len(digit_boxes)} 个候选数字。")

    # 6. 保存切好的图片
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    for i, (x, y, w, h) in enumerate(digit_boxes):
        # 切下数字区域
        digit_roi = img[y:y+h, x:x+w]
        
        # 命名并保存（暂时以 0, 1, 2... 命名，稍后需手动对号入座）
        save_path = os.path.join(output_dir, f"{i}.png")
        cv2.imwrite(save_path, digit_roi)
        print(f"✅ 已保存: {save_path}")

    print(f"---")
    print(f"🚀 处理完毕！请打开 '{output_dir}' 文件夹查看结果。")
    print(f"注意：你需要手动确认哪个图是数字几，并重命名为 0.png, 1.png 等。")

if __name__ == "__main__":
    try:
        start_slicing()
    except Exception as e:
        print(f"⚠️ 运行出错: {e}")
    
    print("\n[为了防止闪退，请按回车键退出...]")
    input()
