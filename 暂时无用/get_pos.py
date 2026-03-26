import pydirectinput
import time

print("请将鼠标移动到游戏按钮的【左上角】，5秒后记录...")
time.sleep(5)
pos1 = pydirectinput.position()
print(f"起点坐标: {pos1}")

print("请将鼠标移动到游戏按钮的【右下角】，5秒后记录...")
time.sleep(5)
pos2 = pydirectinput.position()
print(f"终点坐标: {pos2}")

print(f"最终配置建议: left={pos1.x}, top={pos1.y}, width={pos2.x-pos1.x}, height={pos2.y-pos1.y}")