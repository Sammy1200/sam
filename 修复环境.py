import subprocess
import sys
import os
import time

REQUIRED_PACKAGES = [
    "opencv-python",
    "numpy",
    "keyboard",
    "requests",
    "dxcam",
    "rapidocr-onnxruntime",
    "Pillow"
]

MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"

def main():
    print("="*50)
    print(" 🚀 Win11 极速抢购环境自动铺设器")
    print("="*50)
    
    for pkg in REQUIRED_PACKAGES:
        print(f"🚚 正在安装: {pkg}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-i", MIRROR, "--upgrade"])
            print(f"✅ {pkg} 安装成功")
        except:
            print(f"❌ {pkg} 安装失败，请检查网络。")
    
    print("\n🎉 环境配置完成！请重启电脑以生效显卡硬件加速。")
    os.system('pause')

if __name__ == "__main__":
    main()
