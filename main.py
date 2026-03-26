"""
唯一入口：提权 → 选模式 → 加载资源 → 启动抢购
"""
import ctypes
import sys
import os
import time
import cv2

# ===== 0. 自动提权 =====
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if not is_admin():
    print("🔄 正在申请管理员权限...")
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable,
        f'"{os.path.abspath(__file__)}"', None, 1)
    sys.exit()

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    print("❌ 缺少 rapidocr_onnxruntime，请执行: pip install rapidocr-onnxruntime")
    os.system('pause')
    sys.exit()

import dxcam
import state
from config import (
    MONITOR_JIAOYIHANG, MONITOR_SHOP,
    FIX_SHOP_POS1, FIX_SHOP_POS2
)
from utils import safe_sleep, safe_get_frame, safe_imread, fast_click, gc_checkpoint
from vision import is_image_present, load_digit_templates
from overlay import start_overlay, ui_print
from listing import execute_listing_routine
from purchase import run_purchase_loop


def setup_schedule():
    while True:
        print("\n" + "=" * 40)
        print(" ⚙️  请选择启动模式：")
        print(" [1] 设置定时暂停任务")
        print(" [回车] 启动自动上架 (完成后进入极速抢购)")
        print("=" * 40)
        choice = input("👉 请直接按回车或输入1: ").strip()

        if choice == '1':
            while True:
                time_str = input("⏳ 请输入运行时间 (例如 1.30 代表1小时30分): ").strip()
                try:
                    if '.' in time_str:
                        h, m = time_str.split('.')
                        hours = int(h) if h else 0
                        minutes = int(m) if m else 0
                    else:
                        hours = int(time_str)
                        minutes = 0
                    state.target_stop_seconds = hours * 3600 + minutes * 60
                    if state.target_stop_seconds <= 0:
                        continue
                    print(f"✅ 设置成功！脚本将在 {hours}小时{minutes}分钟后暂停。")
                    state.start_mode = 1
                    return
                except ValueError:
                    pass
        else:
            print("✅ 确认：将先进行一轮全自动上架！")
            state.start_mode = 2
            return


def run_automation():
    setup_schedule()
    start_overlay()

    if os.name == 'nt':
        try:
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(handle, 0x00000100)
            ctypes.windll.kernel32.SetProcessAffinityMask(handle, 0x0055)
        except:
            pass

    try:
        state.ocr_engine = RapidOCR()
        ui_print("✅ 本地 RapidOCR 引擎就绪！")
    except Exception as e:
        ui_print(f"❌ OCR加载失败: {e}")
        time.sleep(5)
        return

    # 加载模板
    templates = {str(i): safe_imread(("logo", "jiage", f"{i}.png"), 0) for i in range(10)}
    temp_success = safe_imread(("logo", "tezhengtu", "chenggong.png"), 0)
    temp_shop = safe_imread(("logo", "tezhengtu", "dianpu.png"), 0)
    state.temp_jiaoyi = safe_imread(("logo", "tezhengtu", "jiaoyihang.png"), 0)
    temp_goumai = safe_imread(("logo", "tezhengtu", "goumai.png"), 0)
    temp_meihuo = safe_imread(("logo", "tezhengtu", "meihuo.png"), 0)
    temp_diyici = safe_imread(("logo", "tezhengtu", "diyici.png"), 0)
    state.TEMP_ITEM = safe_imread(("logo", "shangjia", "pojiaoshi.png"), cv2.IMREAD_COLOR)
    state.TEMP_TISHI = safe_imread(("logo", "shangjia", "tishi.png"), 0)
    state.TEMP_POPUP = safe_imread(("logo", "shangjia", "shangjiatan.png"), 0)

    missing = []
    if any(v is None for v in templates.values()):
        missing.append("logo/jiage/ 的数字0-9.png")
    if temp_success is None: missing.append("logo/tezhengtu/chenggong.png")
    if temp_shop is None: missing.append("logo/tezhengtu/dianpu.png")
    if state.temp_jiaoyi is None: missing.append("logo/tezhengtu/jiaoyihang.png")
    if temp_goumai is None: missing.append("logo/tezhengtu/goumai.png")
    if temp_meihuo is None: missing.append("logo/tezhengtu/meihuo.png")
    if temp_diyici is None: missing.append("logo/tezhengtu/diyici.png")
    if state.TEMP_ITEM is None: missing.append("logo/shangjia/pojiaoshi.png")
    if state.TEMP_TISHI is None: missing.append("logo/shangjia/tishi.png")

    if missing:
        ui_print(f"❌ 素材缺失: {', '.join(missing)}", save_log=True)
        time.sleep(10)
        return

    if state.TEMP_POPUP is not None:
        ui_print("✅ 上架弹窗检测: 【模板匹配】模式")
    else:
        ui_print("ℹ️ 弹窗检测使用【帧对比】模式")

    if load_digit_templates():
        ui_print("✅ 容量识别引擎: 【模板匹配】模式")
    else:
        ui_print("⚠️ 容量识别降级为 OCR 模式")

    try:
        camera = dxcam.create(output_color="BGRA")
        camera.start(target_fps=144)
    except Exception as e:
        ui_print(f"❌ DXCAM 启动失败: {e}")
        time.sleep(5)
        return

    # 启动前上架
    if state.start_mode == 2:
        safe_sleep(2.0)
        ui_print("🚀 正在校验交易行场景...")
        while True:
            if state.IS_PAUSED:
                time.sleep(0.5)
                continue
            f_start = safe_get_frame(camera)
            if f_start is None:
                time.sleep(0.1)
                continue
            if (is_image_present(f_start, MONITOR_JIAOYIHANG, state.temp_jiaoyi, 0.7) and
                    is_image_present(f_start, MONITOR_SHOP, temp_shop, 0.7)):
                ui_print("✅ 已确认交易行界面！", save_log=True)
                break
            else:
                ui_print("🚨 场景非交易行，尝试自愈...", save_log=True)
                fast_click(FIX_SHOP_POS1)
                safe_sleep(1.0)
                fast_click(FIX_SHOP_POS2)
                safe_sleep(1.5)

        ui_print("🚀 前置上架启动！")
        execute_listing_routine(camera)

    # 进入抢购主循环
    run_purchase_loop(camera, templates, temp_success, temp_shop,
                      temp_goumai, temp_meihuo, temp_diyici)


if __name__ == "__main__":
    try:
        run_automation()
    except SystemExit:
        pass
    except KeyboardInterrupt:
        sys.exit()
    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        print("\n" + "=" * 50)
        print("💥 致命错误！")
        print("=" * 50)
        print(error_msg)
        try:
            with open("crash_log.txt", "w", encoding="utf-8") as f:
                f.write(error_msg)
            print("✅ 崩溃日志已保存至 crash_log.txt")
        except:
            pass
        os.system('pause')
