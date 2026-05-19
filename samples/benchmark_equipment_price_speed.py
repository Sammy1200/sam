"""装备价格识别 0.1 秒测速脚本。

默认使用 samples/zhuangbei 下第一张图片，按当前装备价格识别函数测速。
运行：
    py samples\benchmark_equipment_price_speed.py
"""
import argparse
import os
import sys
import time

import cv2


SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import state  # noqa: E402
from utils import safe_imread  # noqa: E402
from vision import get_equipment_price_decision  # noqa: E402


def _clear_price_cache():
    state.price_decision_cache_bytes = None
    state.price_decision_cache_decision = None
    state.price_decision_cache_value = None
    state.price_decision_cache_text = None
    state.price_decision_cache_source = None


def _default_image_path():
    sample_dir = os.path.join(SCRIPT_DIR, "samples", "zhuangbei")
    for name in sorted(os.listdir(sample_dir)):
        if name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
            return os.path.join(sample_dir, name)
    raise FileNotFoundError(f"未找到样本图片：{sample_dir}")


def _load_frame(path):
    frame = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if frame is None:
        raise FileNotFoundError(f"图片读取失败：{path}")
    if len(frame.shape) == 3 and frame.shape[2] == 3:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
    return frame


def _load_price_templates():
    templates = {}
    missing = []
    for digit in range(10):
        key = str(digit)
        template = safe_imread(("logo", "jiage", f"{key}.png"), 0)
        templates[key] = template
        if template is None:
            missing.append(key)
    if missing:
        raise FileNotFoundError(f"价格数字模板缺失：{', '.join(missing)}")
    return templates


def _run_once(frame, templates, duration_seconds, clear_cache_each_call):
    count = 0
    last_result = None
    deadline = time.perf_counter() + duration_seconds
    _clear_price_cache()
    while time.perf_counter() < deadline:
        if clear_cache_each_call:
            _clear_price_cache()
        last_result = get_equipment_price_decision(frame, templates)
        count += 1
    return count, count / duration_seconds if duration_seconds > 0 else 0.0, last_result


def main():
    parser = argparse.ArgumentParser(description="装备价格识别 0.1 秒测速")
    parser.add_argument("--image", default=None, help="样本图片路径，默认取 samples/zhuangbei 第一张图")
    parser.add_argument("--duration", type=float, default=0.1, help="单轮测速秒数，默认 0.1")
    parser.add_argument("--rounds", type=int, default=5, help="重复轮数，默认 5")
    args = parser.parse_args()

    image_path = os.path.abspath(args.image) if args.image else _default_image_path()
    frame = _load_frame(image_path)
    templates = _load_price_templates()

    print(f"样本图片：{image_path}")
    print(f"测速时长：{args.duration:.3f} 秒/轮，重复 {args.rounds} 轮")
    print()

    for label, clear_cache_each_call in (("保留缓存", False), ("每次清缓存", True)):
        counts = []
        last_result = None
        for _ in range(max(1, args.rounds)):
            count, per_second, last_result = _run_once(frame, templates, args.duration, clear_cache_each_call)
            counts.append((count, per_second))
        avg_count = sum(item[0] for item in counts) / len(counts)
        avg_per_second = sum(item[1] for item in counts) / len(counts)
        action, value, text, source = last_result
        print(f"[{label}]")
        print(f"  0.1秒平均识别次数：{avg_count:.1f}")
        print(f"  折算每秒识别次数：{avg_per_second:.1f}")
        print(f"  最后识别结果：action={action}, value={value}, text={text}, source={source}")
        print()


if __name__ == "__main__":
    main()
