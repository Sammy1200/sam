import sys
import subprocess
import os
import traceback
import time

# 日志记录器，将控制台输出同步保存到本地文件
class Logger(object):
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, "w", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)

    def flush(self):
        self.terminal.flush()
        self.log.flush()

def run_comprehensive_diagnostics():
    # 获取当前脚本所在目录，设置日志文件路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_file_path = os.path.join(script_dir, "env_diagnostics_report.txt")
    
    # 将标准输出和错误输出都重定向到日志记录器
    sys.stdout = Logger(log_file_path)
    sys.stderr = sys.stdout 

    print("="*65)
    print(" 🕵️ 终极深度环境诊断工具 V3.2 (暴力重装与自动复检版)")
    print("="*65)
    print(f" [系统] 当前 Python 路径: {sys.executable}")
    print(f" [系统] Python 版本: {sys.version}")
    print("-" * 65)
    
    # 主脚本所需的全部核心依赖库列表：(模块名, pip安装名)
    libraries = [
        ("cv2", "opencv-python"),
        ("numpy", "numpy"),
        ("pyautogui", "PyAutoGUI"),
        ("keyboard", "keyboard"),
        ("requests", "requests"),
        ("dxcam", "dxcam"),
        ("PIL", "Pillow"),  # 图像处理底层库
        ("rapidocr_onnxruntime", "rapidocr-onnxruntime")
    ]
    
    def check_libs():
        missing = []
        print(" 📦 正在逐一扫描核心依赖组件...")
        for module_name, pip_name in libraries:
            try:
                __import__(module_name)
                print(f"  [✔] 组件 {module_name:<20} 正常")
            except ImportError as e:
                print(f"  [❌] 组件 {module_name:<20} 缺失! ({e})")
                if pip_name not in missing: missing.append(pip_name)
            except Exception as e:
                print(f"  [❌] 组件 {module_name:<20} 加载异常! 报错: {e}")
                if pip_name not in missing: missing.append(pip_name)
        return missing

    missing_libs = check_libs()
    print("-" * 65)
    
    # 第一阶段：处理表面库缺失
    if missing_libs:
        print(" 🚨 诊断结论：发现缺失的基础组件！这正是脚本打不开的原因。")
        print(" 🚀 正在尝试一键【强制暴力重装】所有缺失组件 (可能需要十几秒，请耐心等待)...")
        try:
            # 引入 --force-reinstall 强制覆盖损坏的旧文件
            cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--force-reinstall"] + missing_libs + ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]
            subprocess.check_call(cmd)
            
            print(" 🧹 正在顺手清理 requests 烦人警告...")
            subprocess.call([sys.executable, "-m", "pip", "install", "--upgrade", "requests", "urllib3", "chardet", "charset_normalizer", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"])
            
            print("\n🔄 修复过程执行完毕，正在进行立即复检...")
            time.sleep(2)
            
            missing_libs_retry = check_libs()
            if missing_libs_retry:
                print("\n☢️ 自动暴力修复后依然失败！你的系统可能拦截了 Python 脚本调用安装程序。")
                print("👇 请【务必】复制下面这行极度精确的代码，按 Win+R 输入 cmd 回车，然后在黑框里鼠标右键粘贴执行：")
                exact_cmd = f'"{sys.executable}" -m pip install --upgrade --force-reinstall {" ".join(missing_libs_retry)} -i https://pypi.tuna.tsinghua.edu.cn/simple'
                print(f"\n{exact_cmd}\n")
            else:
                print("\n🎉 二次复检全绿！所有缺失的组件已被完美补齐！")
                print("👉 现在你可以直接去双击运行你的【2号电脑抢购脚本】了！")
                
        except Exception as e:
            print(f"\n☢️ 自动安装过程发生错误: {e}")
            print("👇 请复制下面这行精确指令到 CMD 黑框中手动执行：")
            exact_cmd = f'"{sys.executable}" -m pip install --upgrade --force-reinstall {" ".join(missing_libs)} -i https://pypi.tuna.tsinghua.edu.cn/simple'
            print(f"\n{exact_cmd}\n")
    
    # 第二阶段：处理深层引擎冲突（表面组件都有，但运行崩溃）
    else:
        print(" ✅ 基础诊断：所有表面组件均已安装。")
        print(" 🔍 正在进行深层引擎运行测试 (排查隐性 C++ 冲突)...")
        try:
            from rapidocr_onnxruntime import RapidOCR
            print("  -> 正在向显卡与内存申请空间，尝试唤醒 RapidOCR 引擎...")
            engine = RapidOCR()
            print("  [✔] RapidOCR 引擎唤醒成功！底层计算环境完美。")
            
            print("\n🎉 最终结论：你的电脑 Python 运行环境目前没有任何问题！")
            print(" 👉 现在主脚本绝对可以正常运行了！")
            
        except Exception as e:
            print("\n 💥 抓到元凶了！深层引擎唤醒测试时发生崩溃：")
            print("="*65)
            traceback.print_exc()
            print("="*65)
            print(" 💡 上方就是导致闪退的真实报错代码！")
            
    print("\n" + "="*65)
    print("👉 若仍有红字，请将该文本文件 (env_diagnostics_report.txt) 发送给 AI！")
    print("="*65)
    os.system('pause')

if __name__ == "__main__":
    run_comprehensive_diagnostics()
