import cv2
import numpy as np
import time
import os
import sys
import ctypes
import keyboard
import re
import dxcam
import threading
import logging
from datetime import datetime
from rapidocr_onnxruntime import RapidOCR


# ================================================================
#  0. 日志系统
# ================================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

log_filename = datetime.now().strftime("run_%Y%m%d_%H%M%S.log")
log_filepath = os.path.join(LOG_DIR, log_filename)

logger = logging.getLogger("ListingBot")
logger.setLevel(logging.DEBUG)

file_handler = logging.FileHandler(log_filepath, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)-7s] %(message)s", datefmt="%H:%M:%S"
))

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("%(message)s"))

logger.addHandler(file_handler)
logger.addHandler(console_handler)


# ================================================================
#  1. 配置常量
# ================================================================

EXPECTED_WIDTH  = 1920
EXPECTED_HEIGHT = 1080

CLICK_1         = (1850, 990)
CLICK_2         = (1855, 269)
CLICK_JIAOSHI   = (1730, 370)

MONITOR_TEXT_SHANGJIA = {"left": 70,   "top": 80,  "width": 110, "height": 50}
MONITOR_TEXT_JIAOSHI  = {"left": 1700, "top": 350, "width": 60,  "height": 40}
MONITOR_CAPACITY      = {"left": 179,  "top": 103, "width": 51,  "height": 27}
MONITOR_JIAOYIHANG    = {"left": 1698, "top": 184, "width": 64,  "height": 87}

CLICK_PRE_DELAY  = 0.10
CLICK_POST_DELAY = 0.15
OCR_TIMEOUT      = 5.0
MAX_RETRY        = 3
RETRY_INTERVAL   = 0.8
CAMERA_FPS       = 30

# ---- 模板匹配专用 ----
UPSCALE    = 4          # 容量区域放大倍数
STANDARD_W = 20         # 模板标准宽度（像素）
STANDARD_H = 28         # 模板标准高度（像素）

# ---- 模板文件夹路径 ----
TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "logo", "shangjia")


# ================================================================
#  2. 素材读取
# ================================================================

def safe_imread(filename, flags=0):
    """安全读取图片，支持中文路径"""
    filepath = os.path.join(SCRIPT_DIR, filename)
    if not os.path.exists(filepath):
        logger.error(f"素材文件不存在: {filepath}")
        return None
    img = cv2.imdecode(np.fromfile(filepath, dtype=np.uint8), flags)
    if img is None:
        logger.error(f"素材文件损坏: {filepath}")
    return img

TEMP_JIAOYI = safe_imread("jiaoyihang.png", 0)


# ================================================================
#  3. 全局状态
# ================================================================

ocr_engine      = None
camera          = None
game_hwnd       = None
run_lock        = threading.Lock()
DIGIT_TEMPLATES = {}   # {'0': img, '1': img, ..., '/': img}


# ================================================================
#  4. 底层工具函数
# ================================================================

def check_resolution():
    w = ctypes.windll.user32.GetSystemMetrics(0)
    h = ctypes.windll.user32.GetSystemMetrics(1)
    if w != EXPECTED_WIDTH or h != EXPECTED_HEIGHT:
        logger.warning(
            f"⚠️ 分辨率 {w}×{h}，坐标基于 {EXPECTED_WIDTH}×{EXPECTED_HEIGHT}")
        return False
    logger.info(f"✅ 分辨率校验通过: {w}×{h}")
    return True


def capture_game_hwnd():
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if hwnd:
        logger.info(f"✅ 游戏窗口句柄: {hwnd}")
    else:
        logger.warning("⚠️ 未能捕获前台窗口句柄")
    return hwnd


def ensure_foreground(hwnd):
    if hwnd:
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)


def fast_click(pos, hwnd=None):
    if hwnd:
        ensure_foreground(hwnd)
    x, y = pos
    ctypes.windll.user32.SetCursorPos(x, y)
    time.sleep(CLICK_PRE_DELAY)
    ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
    ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)
    time.sleep(CLICK_POST_DELAY)
    logger.debug(f"点击 ({x}, {y})")


def safe_get_frame(camera_obj, max_attempts=20, interval=0.1):
    for _ in range(max_attempts):
        frame = camera_obj.get_latest_frame()
        if frame is not None:
            return frame
        time.sleep(interval)
    logger.error(f"连续 {max_attempts} 次未获取到画面")
    return None


def crop_frame(frame, monitor):
    t, l = monitor["top"], monitor["left"]
    return frame[t:t + monitor["height"], l:l + monitor["width"]]


# ================================================================
#  5. 数字模板系统
# ================================================================

def preprocess_template(img):
    """
    把用户提供的原始截图 → 标准化模板
    流程：灰度 → 二值化 → 白字黑底 → 裁剪到内容 → 标准化尺寸
    """
    # ---- 转灰度 ----
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()

    # ---- Otsu 二值化 ----
    _, binary = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # ---- 确保白字黑底（边缘像素 = 背景）----
    border = np.concatenate([
        binary[0], binary[-1], binary[:, 0], binary[:, -1]
    ])
    if np.mean(border) > 127:
        binary = cv2.bitwise_not(binary)

    # ---- 裁剪到字符内容（去多余黑边）----
    coords = cv2.findNonZero(binary)
    if coords is not None:
        x, y, w, h = cv2.boundingRect(coords)
        binary = binary[y:y + h, x:x + w]

    # ---- 标准化尺寸 + 消除缩放灰边 ----
    norm = cv2.resize(binary, (STANDARD_W, STANDARD_H),
                      interpolation=cv2.INTER_CUBIC)
    _, norm = cv2.threshold(norm, 127, 255, cv2.THRESH_BINARY)

    return norm


def load_digit_templates():
    """
    从 logo/shangjia/ 加载数字模板
    期望文件: 0.png ~ 9.png + slash.png
    """
    if not os.path.exists(TEMPLATE_DIR):
        logger.error(f"⛔ 模板目录不存在: {TEMPLATE_DIR}")
        return False

    # 列出目录里有什么文件，方便排查
    all_files = os.listdir(TEMPLATE_DIR)
    png_files = [f for f in all_files if f.lower().endswith('.png')]
    logger.info(f"📁 模板目录: {TEMPLATE_DIR}")
    logger.info(f"   找到 {len(png_files)} 个 png: {sorted(png_files)}")

    # ---- 文件名 → 字符标签的映射 ----
    # 支持多种常见命名方式
    name_map = {}
    for d in range(10):
        name_map[f"{d}.png"] = str(d)

    # 斜杠支持多种命名
    slash_names = ["slash.png", "斜杠.png", "xiegang.png", "_.png"]
    for sn in slash_names:
        name_map[sn] = '/'

    # ---- 逐个加载 + 预处理 ----
    for fname in png_files:
        label = name_map.get(fname)

        if label is None:
            logger.debug(f"   跳过未识别文件: {fname}")
            continue

        fpath = os.path.join(TEMPLATE_DIR, fname)
        raw = cv2.imdecode(
            np.fromfile(fpath, dtype=np.uint8), cv2.IMREAD_UNCHANGED)

        if raw is None:
            logger.warning(f"   ⚠️ 无法读取: {fpath}")
            continue

        # 预处理：原始截图 → 标准二值模板
        template = preprocess_template(raw)
        DIGIT_TEMPLATES[label] = template
        logger.info(
            f"   ✅ '{label}' ← {fname}  "
            f"(原始 {raw.shape[1]}×{raw.shape[0]} → "
            f"标准 {STANDARD_W}×{STANDARD_H})")

    # ---- 检查完整性 ----
    loaded  = set(DIGIT_TEMPLATES.keys())
    required = set('0123456789/')
    missing  = required - loaded

    logger.info(f"\n   已加载 {len(loaded)} 个: {sorted(loaded)}")

    if missing:
        logger.error(f"   ⛔ 缺少模板: {sorted(missing)}")
        logger.error("   请检查文件命名（期望: 0.png~9.png + slash.png）")
        return False

    logger.info("   ✅ 0-9 和 / 全部就绪！")
    return True


def binarize_capacity_region(frame):
    """
    截取容量区域 → 灰度 → 放大4倍 → Otsu二值 → 白字黑底
    """
    cropped = crop_frame(frame, MONITOR_CAPACITY)
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)

    h, w = gray.shape
    big = cv2.resize(gray, (w * UPSCALE, h * UPSCALE),
                     interpolation=cv2.INTER_CUBIC)

    _, binary = cv2.threshold(
        big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    border = np.concatenate([
        binary[0], binary[-1], binary[:, 0], binary[:, -1]
    ])
    if np.mean(border) > 127:
        binary = cv2.bitwise_not(binary)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    return binary


def segment_characters(binary):
    """
    轮廓分割 → 过滤噪点 → 粘连拆分 → 按x排序
    返回：(字符图片列表, 边界框列表)
    """
    contours, _ = cv2.findContours(
        binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w >= 4 and h >= 10:
            boxes.append((x, y, w, h))
    boxes.sort(key=lambda b: b[0])

    # 粘连字符拆分
    if len(boxes) >= 2:
        widths = [w for (_, _, w, _) in boxes]
        median_w = sorted(widths)[len(widths) // 2]
        new_boxes = []
        for (x, y, w, h) in boxes:
            if w > median_w * 1.8 and w > 15:
                mid = w // 2
                new_boxes.append((x, y, mid, h))
                new_boxes.append((x + mid, y, w - mid, h))
            else:
                new_boxes.append((x, y, w, h))
        boxes = new_boxes
        boxes.sort(key=lambda b: b[0])

    chars = [binary[y:y + h, x:x + w] for (x, y, w, h) in boxes]
    return chars, boxes


def recognize_capacity_by_template(frame):
    """
    用模板匹配识别容量
    返回 (current, total) 或 None
    """
    try:
        binary = binarize_capacity_region(frame)
        chars, boxes = segment_characters(binary)

        if len(chars) == 0:
            logger.warning("模板匹配: 未分割出任何字符")
            return None

        recognized = []
        min_confidence = 1.0

        for i, char_img in enumerate(chars):
            # 裁剪到字符内容区域（和模板预处理一致）
            coords = cv2.findNonZero(char_img)
            if coords is not None:
                cx, cy, cw, ch = cv2.boundingRect(coords)
                char_img = char_img[cy:cy + ch, cx:cx + cw]

            # 标准化尺寸
            norm = cv2.resize(char_img, (STANDARD_W, STANDARD_H),
                              interpolation=cv2.INTER_CUBIC)
            _, norm = cv2.threshold(norm, 127, 255, cv2.THRESH_BINARY)

            best_char  = '?'
            best_score = -1

            for label, template in DIGIT_TEMPLATES.items():
                result = cv2.matchTemplate(
                    norm, template, cv2.TM_CCOEFF_NORMED)
                score = result[0][0]
                if score > best_score:
                    best_score = score
                    best_char  = label

            logger.debug(
                f"  字符[{i}]: '{best_char}' (置信度 {best_score:.3f})")

            min_confidence = min(min_confidence, best_score)
            recognized.append(best_char)

        text = ''.join(recognized)
        logger.info(
            f"📐 模板识别结果: '{text}'  "
            f"最低置信度: {min_confidence:.3f}")

        # 置信度太低就拒绝
        if min_confidence < 0.5:
            logger.warning(
                f"⚠️ 置信度 {min_confidence:.3f} < 0.5，不可信")
            return None

        # 解析 X/Y 格式
        if '/' in text:
            parts = text.split('/')
            if len(parts) == 2:
                try:
                    current = int(parts[0])
                    total   = int(parts[1])
                    if 0 <= current <= total <= 99:
                        return (current, total)
                except ValueError:
                    pass

        logger.warning(f"模板识别格式异常: '{text}'")
        return None

    except Exception as e:
        logger.error(f"模板识别异常: {e}", exc_info=True)
        return None


# ================================================================
#  6. OCR 系统（汉字识别 + 容量兜底）
# ================================================================

def read_text_from_area(frame, monitor):
    """OCR 读取指定区域文字"""
    try:
        cropped = crop_frame(frame, monitor)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        padded = cv2.copyMakeBorder(gray, 8, 8, 8, 8, cv2.BORDER_REPLICATE)
        bgr = cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)

        result, _ = ocr_engine(bgr)
        if not result:
            return ""

        text = "".join([item[1] for item in result])
        logger.debug(f"OCR: '{text}'")
        return text

    except Exception as e:
        logger.error(f"OCR 异常: {e}", exc_info=True)
        return ""


def parse_capacity_ocr(raw_text):
    """OCR 容量解析（备用方案）"""
    if not raw_text:
        return None

    text = raw_text.replace(" ", "")
    text = text.replace("O", "0").replace("o", "0")
    text = text.replace("Q", "0").replace("D", "0")
    text = re.sub(r'[lI|\\i]+', '/', text)

    match = re.match(r'^(\d{1,2})/(\d{1,2})$', text)
    if match:
        c, t = int(match.group(1)), int(match.group(2))
        if 0 <= c <= t <= 10:
            return (c, t)

    digits = re.findall(r'\d+', text)
    if digits:
        num_str = digits[0]
        if num_str.endswith("10") and len(num_str) >= 3:
            try:
                c = int(num_str[:-2])
                if 0 <= c <= 10:
                    return (c, 10)
            except ValueError:
                pass

    logger.warning(f"OCR 容量解析失败: '{raw_text}'")
    return None


def wait_for_ocr_text(camera_obj, monitor, keywords, timeout=OCR_TIMEOUT):
    """循环截屏+OCR，等待关键字出现"""
    start = time.time()
    logger.info(f"   ⏳ 等待 {keywords} (超时 {timeout}s)...")

    while time.time() - start < timeout:
        frame = camera_obj.get_latest_frame()
        if frame is None:
            time.sleep(0.05)
            continue

        text = read_text_from_area(frame, monitor)
        if text:
            for kw in keywords:
                if kw in text:
                    logger.info(
                        f"   ✅ 识别到 '{kw}'  "
                        f"耗时 {time.time() - start:.2f}s")
                    return True
        time.sleep(0.05)

    logger.warning(f"   ❌ 超时 ({timeout}s)")
    return False


def check_jiaoyihang(frame):
    """模板匹配判断是否在交易行"""
    if TEMP_JIAOYI is None:
        return False
    try:
        cropped = crop_frame(frame, MONITOR_JIAOYIHANG)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        res = cv2.matchTemplate(gray, TEMP_JIAOYI, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        logger.debug(f"交易行置信度: {max_val:.3f}")
        return max_val > 0.7
    except Exception as e:
        logger.error(f"模板匹配异常: {e}", exc_info=True)
        return False


# ================================================================
#  7. 统一容量读取入口
# ================================================================

def read_capacity(frame):
    """
    优先模板匹配（精度高），失败时退回 OCR
    返回 (current, total) 或 None
    """
    # ---- 模板匹配优先 ----
    if DIGIT_TEMPLATES:
        result = recognize_capacity_by_template(frame)
        if result is not None:
            return result
        logger.warning("模板匹配失败，尝试 OCR 兜底...")

    # ---- OCR 兜底 ----
    raw = read_text_from_area(frame, MONITOR_CAPACITY)
    return parse_capacity_ocr(raw)


# ================================================================
#  8. 点击-验证-重试
# ================================================================

def step_click_and_verify(step_name, click_pos, ocr_monitor, ocr_keywords,
                          camera_obj, hwnd=None,
                          max_retry=MAX_RETRY, ocr_timeout=OCR_TIMEOUT):
    for attempt in range(1, max_retry + 1):
        logger.info(f"\n👉 {step_name}  (第 {attempt}/{max_retry} 次)")
        fast_click(click_pos, hwnd)

        if wait_for_ocr_text(camera_obj, ocr_monitor, ocr_keywords,
                             timeout=ocr_timeout):
            return True

        if attempt < max_retry:
            logger.warning(f"   ⚠️ 失败，{RETRY_INTERVAL}s 后重试...")
            time.sleep(RETRY_INTERVAL)
        else:
            logger.error(f"   ❌ {step_name} 重试 {max_retry} 次仍失败")

    return False


# ================================================================
#  9. 业务主流程
# ================================================================

def run_test_sequence():
    """F12 触发的完整流程"""
    global game_hwnd

    if not run_lock.acquire(blocking=False):
        logger.warning("⚠️ 上一轮还在执行，忽略本次 F12")
        return

    try:
        logger.info("\n" + "=" * 50)
        logger.info("⏳ 2 秒后开始，请切回游戏...")
        time.sleep(2.0)

        game_hwnd = capture_game_hwnd()

        # ---- 前置检查 ----
        frame = safe_get_frame(camera)
        if frame is None:
            logger.error("⛔ 无法截屏，中止")
            return

        if not check_jiaoyihang(frame):
            logger.error("⛔ 不在交易行界面，中止")
            return

        logger.info("🚀 确认在交易行，开始跳转...\n")

        # ========== 一级跳转 ==========
        if not step_click_and_verify(
            "[一级] 功能键 → 等'上架数量'",
            CLICK_1, MONITOR_TEXT_SHANGJIA, ["上架", "数量"],
            camera, game_hwnd
        ):
            raise Exception("一级跳转失败")

        # ========== 二级跳转 ==========
        if not step_click_and_verify(
            "[二级] 入口 → 等'角石'",
            CLICK_2, MONITOR_TEXT_JIAOSHI, ["角石"],
            camera, game_hwnd
        ):
            raise Exception("二级跳转失败")

        # ========== 三级跳转 ==========
        logger.info(f"\n👉 [三级] 点击角石 {CLICK_JIAOSHI}")
        fast_click(CLICK_JIAOSHI, game_hwnd)
        time.sleep(0.5)

        # ========== 读取上架额度 ==========
        logger.info("👉 [读取] 上架额度...")
        capacity_result = None

        for attempt in range(5):
            frame = safe_get_frame(camera, max_attempts=5)
            if frame is None:
                continue
            capacity_result = read_capacity(frame)
            if capacity_result is not None:
                break
            time.sleep(0.3)

        # ---- 输出结果 ----
        if capacity_result:
            current, total = capacity_result
            remaining = total - current
            logger.info(f"\n📊 额度: {current}/{total}，剩余 {remaining}")
            if remaining <= 0:
                logger.info("⛔ 上限已满！")
            else:
                logger.info(f"✅ 还可上架 {remaining} 个")
        else:
            logger.error("❌ 额度解析失败，请检查坐标或模板")

    except Exception as e:
        logger.error(f"💥 执行中断: {e}", exc_info=True)

    finally:
        logger.info("=" * 50)
        logger.info(f"🏁 日志: {log_filepath}")
        logger.info("👉 F12 再次执行，ESC 退出\n")
        run_lock.release()


# ================================================================
#  10. 启动入口
# ================================================================

def startup_checks():
    passed = True
    check_resolution()

    if TEMP_JIAOYI is None:
        logger.error("⛔ jiaoyihang.png 缺失或损坏")
        passed = False

    return passed


def main():
    global ocr_engine, camera

    logger.info("=" * 50)
    logger.info("📦 脚本启动")
    logger.info(f"📁 日志: {log_filepath}")

    if not startup_checks():
        logger.error("⛔ 启动检查未通过")
        return

    # ---- 加载数字模板 ----
    templates_ok = load_digit_templates()
    if templates_ok:
        logger.info("🔢 容量识别模式: 模板匹配（高精度）\n")
    else:
        logger.warning("🔢 容量识别模式: OCR（精度较低）")
        logger.warning("   请在 logo/shangjia/ 放入 0.png~9.png + slash.png\n")

    # ---- 初始化 OCR（汉字识别仍需要）----
    logger.info("🔧 初始化 OCR 引擎...")
    ocr_engine = RapidOCR()

    # ---- 初始化截屏 ----
    logger.info(f"🔧 初始化 DXCam ({CAMERA_FPS} fps)...")
    camera = dxcam.create(output_color="BGRA")
    camera.start(target_fps=CAMERA_FPS)

    test_frame = safe_get_frame(camera, max_attempts=30)
    if test_frame is None:
        logger.error("⛔ DXCam 无法截屏")
        camera.stop()
        return
    logger.info(
        f"✅ 截屏可用: {test_frame.shape[1]}×{test_frame.shape[0]}")

    logger.info("✅ 就绪！按 F12 开始，ESC 退出\n")

    keyboard.add_hotkey('f12', run_test_sequence)
    keyboard.wait('esc')

    camera.stop()
    logger.info("👋 正常退出")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"💥 致命错误: {e}", exc_info=True)
    finally:
        input("\n按回车关闭窗口...")