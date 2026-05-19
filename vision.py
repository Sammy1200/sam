"""
截图裁剪、模板匹配、文字识别、余额识别、容量识别
"""
import cv2
import numpy as np
import re
import time
import unicodedata
import state
from local_switch_account_config import load_equipment_price_rule_config, load_purchase_price_rule_config
from config import (
    MONITOR_PRICE, MONITOR_PRICE_SECONDARY, MONITOR_CAPACITY, MONITOR_BALANCE, ACCESSORY_MONITOR_BALANCE,
    EQUIPMENT_PRICE_MONITOR,
    UPSCALE, STANDARD_W, STANDARD_H, TEMPLATE_DIR,
    BALANCE_TEMPLATE_DIR, BALANCE_TEMPLATE_MATCH_THRESHOLD, BALANCE_TEMPLATE_DUPLICATE_GAP,
    BALANCE_TEMPLATE_DOT_MATCH_THRESHOLD, BALANCE_TEMPLATE_UNIT_MATCH_THRESHOLD,
    BALANCE_BINARY_BLUR_SIZE, BALANCE_SEGMENT_MIN_COMPONENT_AREA, BALANCE_SEGMENT_CLOSE_KERNEL_SIZE,
    BALANCE_SEGMENT_MERGE_GAP, BALANCE_SEGMENT_MAX_GROUP_SIZE,
    BALANCE_DOT_MAX_WIDTH, BALANCE_DOT_MAX_HEIGHT, BALANCE_DOT_MAX_AREA,
    BALANCE_DOT_BASELINE_OFFSET_RATIO, BALANCE_DOT_MAX_NEIGHBOR_GAP, BALANCE_UNIT_MIN_WIDTH,
    BALANCE_LEADING_ICON_MIN_GAP, BALANCE_LEADING_ICON_MAX_CLUSTER_WIDTH,
    BALANCE_LEADING_ICON_MAX_AMOUNT_START_X, BALANCE_TRAILING_NOISE_MIN_GAP,
    BALANCE_TRAILING_NOISE_MAX_CLUSTER_WIDTH,
    LISTING_TIMER_REGION,
    LISTING_TIMER_UPSCALE, LISTING_TIMER_BLUR_SIZE, LISTING_TIMER_THRESHOLD_SHIFT,
    LISTING_TIMER_CLOSE_KERNEL_SIZE, LISTING_TIMER_MIN_COMPONENT_AREA,
    LISTING_TIMER_MIN_COMPONENT_HEIGHT, LISTING_TIMER_MAX_COMPONENT_WIDTH,
    LISTING_TIMER_MIN_COMPONENT_X, LISTING_TIMER_SCORE_MARGIN,
    LISTING_TIMER_DIGIT4_KEEP_THRESHOLD, LISTING_TIMER_DIGIT6_KEEP_THRESHOLD,
    LISTING_TIMER_DIGIT7_KEEP_THRESHOLD, LISTING_TIMER_OTHER_MAX_4_SCORE,
    LISTING_TIMER_OTHER_MIN_67_SCORE, LISTING_TIMER_OTHER_MAX_67_SCORE,
    LISTING_TIMER_SEQUENCE_UPSCALE, LISTING_TIMER_SEQUENCE_BLUR_SIZE,
    LISTING_TIMER_SEQUENCE_THRESHOLD_SHIFT, LISTING_TIMER_SEQUENCE_CLOSE_KERNEL_SIZE,
    LISTING_TIMER_SEQUENCE_MIN_COMPONENT_AREA, LISTING_TIMER_SEQUENCE_MIN_COMPONENT_HEIGHT,
    LISTING_TIMER_SEQUENCE_MAX_COMPONENT_WIDTH, LISTING_TIMER_SEQUENCE_MIN_COMPONENT_X,
    LISTING_TIMER_SEQUENCE_SCORE_MARGIN, LISTING_TIMER_SEQUENCE_DUPLICATE_GAP,
    LISTING_TIMER_SEQUENCE_DIGIT4_THRESHOLD, LISTING_TIMER_SEQUENCE_DIGIT6_THRESHOLD,
    LISTING_TIMER_SEQUENCE_DIGIT7_THRESHOLD,
)
from utils import safe_sleep, safe_get_frame
import os


BALANCE_TEMPLATE_FILE_MAP = {str(d): f"{d}.png" for d in range(10)}
BALANCE_TEMPLATE_FILE_MAP.update({
    ".": "dian.png",
    "万": "wan.png",
    "亿": "yi.png",
})
_BALANCE_TEMPLATES = None
_BALANCE_TEMPLATE_LOAD_ATTEMPTED = False
_LISTING_TIMER_TEMPLATES = None
_LISTING_TIMER_TEMPLATE_LOAD_ATTEMPTED = False
PURCHASE_PRICE_RULE_CONFIG = load_purchase_price_rule_config()[0]
EQUIPMENT_PRICE_RULE_CONFIG = load_equipment_price_rule_config()[0]


def _get_purchase_price_rule_config():
    global PURCHASE_PRICE_RULE_CONFIG
    PURCHASE_PRICE_RULE_CONFIG = load_purchase_price_rule_config()[0]
    return PURCHASE_PRICE_RULE_CONFIG


def _get_equipment_price_rule_config():
    global EQUIPMENT_PRICE_RULE_CONFIG
    EQUIPMENT_PRICE_RULE_CONFIG = load_equipment_price_rule_config()[0]
    return EQUIPMENT_PRICE_RULE_CONFIG


def crop_frame(frame, monitor):
    t, l = monitor["top"], monitor["left"]
    return frame[t:t + monitor["height"], l:l + monitor["width"]]


def _to_gray(image):
    if len(image.shape) == 2:
        return image
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def is_image_present(frame, monitor, template, threshold=0.8):
    try:
        cropped = crop_frame(frame, monitor)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        return cv2.minMaxLoc(res)[1] > threshold
    except:
        return False


def _is_stone_price_guard_present(frame):
    try:
        pixel_color = frame[207, 1320]
        target_bgr = [51, 205, 255]
        color_diff = (abs(int(pixel_color[0]) - target_bgr[0]) +
                      abs(int(pixel_color[1]) - target_bgr[1]) +
                      abs(int(pixel_color[2]) - target_bgr[2]))
        return color_diff <= 45
    except:
        return False


def get_number(frame, templates, monitor=MONITOR_PRICE, source_key="primary", price_guard_present=None):
    try:
        if price_guard_present is None:
            price_guard_present = _is_stone_price_guard_present(frame)
        if not price_guard_present:
            return None
        cropped = crop_frame(frame, monitor)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        # 同一区域完全不变时，直接复用上一帧识别结果，避免重复模板匹配。
        roi_bytes = (source_key, gray.tobytes())
        if state.price_roi_cache_bytes == roi_bytes:
            return state.price_roi_cache_value

        detected = []
        for digit in range(10):
            num = str(digit)
            temp = templates.get(num)
            if temp is None:
                continue
            res = cv2.matchTemplate(gray, temp, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= 0.75)
            for pt in zip(*loc[::-1]):
                detected.append((pt[0], num, res[pt[1], pt[0]]))
        if not detected:
            state.price_roi_cache_bytes = roi_bytes
            state.price_roi_cache_value = None
            return None
        detected.sort(key=lambda item: item[0])
        final_list = []
        last = detected[0]
        for i in range(1, len(detected)):
            if detected[i][0] - last[0] < 5:
                if detected[i][2] > last[2]:
                    last = detected[i]
            else:
                final_list.append(last)
                last = detected[i]
        final_list.append(last)
        res_str = "".join([item[1] for item in final_list])
        result = int(res_str) if len(res_str) >= 6 else None
        state.price_roi_cache_bytes = roi_bytes
        state.price_roi_cache_value = result
        return result
    except:
        return None


PRICE_MATCH_THRESHOLD = 0.75
PRICE_DUPLICATE_GAP = 5


def _merge_digit_hits(detected):
    if not detected:
        return []
    detected.sort(key=lambda item: item[0])
    merged = []
    last = detected[0]
    for current in detected[1:]:
        if current[0] - last[0] < PRICE_DUPLICATE_GAP:
            if current[2] > last[2]:
                last = current
        else:
            merged.append(last)
            last = current
    merged.append(last)
    return merged


def _match_digit_hits(gray, templates, digit_order):
    detected = []
    for digit in digit_order:
        num = str(digit)
        temp = templates.get(num)
        if temp is None:
            continue
        res = cv2.matchTemplate(gray, temp, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= PRICE_MATCH_THRESHOLD)
        for pt in zip(*loc[::-1]):
            detected.append((pt[0], num, float(res[pt[1], pt[0]]), temp.shape[1]))
    return _merge_digit_hits(detected)


def _cache_price_decision(roi_bytes, decision, price_value, price_text, source_key):
    state.price_decision_cache_bytes = roi_bytes
    state.price_decision_cache_decision = decision
    state.price_decision_cache_value = price_value
    state.price_decision_cache_text = price_text
    state.price_decision_cache_source = source_key


def _get_price_prefix_decision(gray, templates):
    rule_config = _get_purchase_price_rule_config()
    if rule_config.get("stone_purchase_price_mode") != "prefix":
        return None, None

    digit_hits = _match_digit_hits(gray, templates, range(0, 10))
    if not digit_hits:
        return None, None

    first_digit = digit_hits[0][1]
    two_digit_prefix = f"{digit_hits[0][1]}{digit_hits[1][1]}" if len(digit_hits) >= 2 else None

    if two_digit_prefix:
        if two_digit_prefix in rule_config["direct_accept_prefixes_2digit"]:
            return "accept", two_digit_prefix
        if two_digit_prefix in rule_config["skip_item_click_prefixes_2digit"]:
            return "accept_skip_item_click", two_digit_prefix
        if two_digit_prefix in rule_config["direct_reject_prefixes_2digit"]:
            return "reject", two_digit_prefix
        if two_digit_prefix in rule_config["full_check_prefixes_2digit"]:
            return None, two_digit_prefix

    if first_digit in rule_config["direct_accept_prefixes_1digit"]:
        return "accept", first_digit
    if first_digit in rule_config["skip_item_click_prefixes_1digit"]:
        return "accept_skip_item_click", first_digit
    if first_digit in rule_config["direct_reject_prefixes_1digit"]:
        return "reject", first_digit
    if first_digit in rule_config["full_check_prefixes_1digit"]:
        return None, first_digit

    return None, two_digit_prefix or first_digit


def _get_price_decision_for_monitor(frame, templates, monitor, source_key, price_guard_present=None):
    try:
        if price_guard_present is None:
            price_guard_present = _is_stone_price_guard_present(frame)
        if not price_guard_present:
            return "unknown", None, None, source_key

        cropped = crop_frame(frame, monitor)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        roi_bytes = (source_key, gray.tobytes())
        if state.price_decision_cache_bytes == roi_bytes:
            return (
                state.price_decision_cache_decision,
                state.price_decision_cache_value,
                state.price_decision_cache_text,
                state.price_decision_cache_source,
            )

        prefix_decision, prefix_text = _get_price_prefix_decision(gray, templates)
        if prefix_decision is not None:
            _cache_price_decision(roi_bytes, prefix_decision, None, prefix_text, source_key)
            return prefix_decision, None, prefix_text, source_key

        price_value = get_number(frame, templates, monitor, source_key, price_guard_present=price_guard_present)
        if price_value is None:
            _cache_price_decision(roi_bytes, "unknown", None, None, source_key)
            return "unknown", None, None, source_key

        price_text = str(price_value)
        rule_config = _get_purchase_price_rule_config()
        if rule_config.get("stone_purchase_price_mode") == "fixed_range":
            matched = (
                rule_config["stone_fixed_price_min_inclusive"]
                <= price_value
                <= rule_config["stone_fixed_price_max_inclusive"]
            )
        else:
            matched = (
                rule_config["min_exclusive"]
                < price_value
                < rule_config["max_exclusive"]
            )

        if matched:
            decision = "accept"
        else:
            decision = "reject"
        _cache_price_decision(roi_bytes, decision, price_value, price_text, source_key)
        return decision, price_value, price_text, source_key
    except:
        return "unknown", None, None, source_key


def get_price_decision(frame, templates):
    price_guard_present = _is_stone_price_guard_present(frame)
    primary_result = _get_price_decision_for_monitor(
        frame,
        templates,
        MONITOR_PRICE,
        "primary",
        price_guard_present=price_guard_present,
    )
    if primary_result[0] in ("accept", "accept_skip_item_click"):
        return primary_result

    secondary_result = _get_price_decision_for_monitor(
        frame,
        templates,
        MONITOR_PRICE_SECONDARY,
        "secondary",
        price_guard_present=price_guard_present,
    )
    if secondary_result[0] != "unknown":
        return secondary_result

    return primary_result


def get_equipment_price_decision(frame, templates):
    """装备模式专用价格识别：只读第二识别区，不使用颜色守卫和前缀规则。"""
    source_key = "equipment_secondary"
    try:
        cropped = crop_frame(frame, EQUIPMENT_PRICE_MONITOR)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        roi_bytes = (source_key, gray.tobytes())
        if state.price_decision_cache_bytes == roi_bytes:
            return (
                state.price_decision_cache_decision,
                state.price_decision_cache_value,
                state.price_decision_cache_text,
                state.price_decision_cache_source,
            )

        digit_hits = _match_digit_hits(gray, templates, range(0, 10))
        if not digit_hits:
            _cache_price_decision(roi_bytes, "unknown", None, None, source_key)
            return "unknown", None, None, source_key

        price_text = "".join([item[1] for item in digit_hits])
        price_value = int(price_text) if len(price_text) >= 5 else None
        if price_value is None:
            _cache_price_decision(roi_bytes, "unknown", None, None, source_key)
            return "unknown", None, None, source_key

        equipment_rule_config = _get_equipment_price_rule_config()
        if (
            equipment_rule_config["equipment_price_min_exclusive"]
            < price_value
            < equipment_rule_config["equipment_price_max_exclusive"]
        ):
            decision = "accept_skip_item_click"
        else:
            decision = "reject"
        _cache_price_decision(roi_bytes, decision, price_value, price_text, source_key)
        return decision, price_value, price_text, source_key
    except:
        return "unknown", None, None, source_key


def read_text_from_area(frame, monitor, is_number_mode=False):
    try:
        cropped = crop_frame(frame, monitor)
        gray_img = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        if is_number_mode:
            padded = cv2.copyMakeBorder(gray_img, 20, 20, 20, 20, cv2.BORDER_REPLICATE)
            final_img = cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)
            result, _ = state.ocr_engine(final_img)
            if result:
                text = "".join([item[1] for item in result]).replace(" ", "")
                text = text.replace("O", "0").replace("o", "0").replace("Q", "0").replace("D", "0")
                text = re.sub(r'[lI|\\i]+', '/', text)
                return text
            return ""
        else:
            resized = cv2.resize(gray_img, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
            padded = cv2.copyMakeBorder(resized, 20, 20, 20, 20, cv2.BORDER_REPLICATE)
            final_img = cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)
            result, _ = state.ocr_engine(final_img)
            return "".join([item[1] for item in result]) if result else ""
    except:
        return ""


def wait_for_ocr_text(camera_obj, monitor, keywords, timeout=3.0):
    elapsed = 0
    while elapsed < timeout:
        if state.IS_PAUSED:
            time.sleep(0.1)
            continue
        frame = safe_get_frame(camera_obj)
        if frame is None:
            time.sleep(0.05)
            elapsed += 0.05
            continue
        text = read_text_from_area(frame, monitor, is_number_mode=False)
        if text and any(kw in text for kw in keywords):
            return True
        time.sleep(0.05)
        elapsed += 0.05
    return False


# ---- 容量识别 ----

def preprocess_template(img):
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.shape[2] == 3 else cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
    else:
        gray = img.copy()
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    border = np.concatenate([binary[0], binary[-1], binary[:, 0], binary[:, -1]])
    if np.mean(border) > 127:
        binary = cv2.bitwise_not(binary)
    coords = cv2.findNonZero(binary)
    if coords is not None:
        x, y, w, h = cv2.boundingRect(coords)
        binary = binary[y:y + h, x:x + w]
    norm = cv2.resize(binary, (STANDARD_W, STANDARD_H), interpolation=cv2.INTER_CUBIC)
    _, norm = cv2.threshold(norm, 127, 255, cv2.THRESH_BINARY)
    return norm


def load_digit_templates():
    if not os.path.exists(TEMPLATE_DIR):
        return False
    all_files = os.listdir(TEMPLATE_DIR)
    png_files = [f for f in all_files if f.lower().endswith('.png')]
    name_map = {f"{d}.png": str(d) for d in range(10)}
    for sn in ["slash.png", "斜杠.png", "xiegang.png", "_.png"]:
        name_map[sn] = '/'
    for fname in png_files:
        label = name_map.get(fname)
        if label is None:
            continue
        fpath = os.path.join(TEMPLATE_DIR, fname)
        raw = cv2.imdecode(np.fromfile(fpath, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if raw is None:
            continue
        state.DIGIT_TEMPLATES[label] = preprocess_template(raw)
    return len(state.DIGIT_TEMPLATES) > 0


def binarize_capacity_region(frame):
    cropped = crop_frame(frame, MONITOR_CAPACITY)
    gray = (cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY) if frame.shape[2] == 4
            else cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY))
    h, w = gray.shape
    big = cv2.resize(gray, (w * UPSCALE, h * UPSCALE), interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    border = np.concatenate([binary[0], binary[-1], binary[:, 0], binary[:, -1]])
    if np.mean(border) > 127:
        binary = cv2.bitwise_not(binary)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    return binary


def segment_characters(binary):
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w >= 4 and h >= 10:
            boxes.append((x, y, w, h))
    boxes.sort(key=lambda b: b[0])
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
    try:
        binary = binarize_capacity_region(frame)
        chars, boxes = segment_characters(binary)
        if len(chars) == 0:
            return None
        recognized = []
        min_confidence = 1.0
        for char_img in chars:
            coords = cv2.findNonZero(char_img)
            if coords is not None:
                cx, cy, cw, ch = cv2.boundingRect(coords)
                char_img = char_img[cy:cy + ch, cx:cx + cw]
            norm = cv2.resize(char_img, (STANDARD_W, STANDARD_H), interpolation=cv2.INTER_CUBIC)
            _, norm = cv2.threshold(norm, 127, 255, cv2.THRESH_BINARY)
            best_char, best_score = '?', -1
            for label, template in state.DIGIT_TEMPLATES.items():
                score = cv2.matchTemplate(norm, template, cv2.TM_CCOEFF_NORMED)[0][0]
                if score > best_score:
                    best_score = score
                    best_char = label
            min_confidence = min(min_confidence, best_score)
            recognized.append(best_char)
        text = ''.join(recognized)
        if min_confidence < 0.5:
            return None
        if '/' in text:
            parts = text.split('/')
            if len(parts) == 2:
                try:
                    c, t = int(parts[0]), int(parts[1])
                    if 0 <= c <= t <= 99:
                        return (c, t)
                except ValueError:
                    pass
        return None
    except:
        return None


def read_capacity(frame):
    if state.DIGIT_TEMPLATES:
        result = recognize_capacity_by_template(frame)
        if result is not None:
            return result
    raw = read_text_from_area(frame, MONITOR_CAPACITY, is_number_mode=True)
    if raw and "/" in raw:
        parts = raw.split("/")
        try:
            c = int(parts[0]) if parts[0].isdigit() else -1
            t = int(parts[1]) if parts[1].isdigit() else -1
            if 0 <= c <= t <= 99:
                return (c, t)
        except:
            pass
    return None


# ---- 余额 ----

def _prepare_balance_template(raw):
    gray = _to_gray(raw)
    if len(raw.shape) == 3 and raw.shape[2] == 4:
        alpha = raw[:, :, 3]
        mask = cv2.threshold(alpha, 0, 255, cv2.THRESH_BINARY)[1]
    else:
        mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    coords = cv2.findNonZero(mask)
    if coords is None:
        return None
    x, y, w, h = cv2.boundingRect(coords)
    binary = cv2.threshold(gray[y:y + h, x:x + w], 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    return {
        "image": binary,
        "height": h,
        "label": "",
        "width": w,
    }


def load_balance_templates():
    global _BALANCE_TEMPLATES, _BALANCE_TEMPLATE_LOAD_ATTEMPTED

    if _BALANCE_TEMPLATE_LOAD_ATTEMPTED:
        return bool(_BALANCE_TEMPLATES)

    _BALANCE_TEMPLATE_LOAD_ATTEMPTED = True
    _BALANCE_TEMPLATES = {}
    if not os.path.isdir(BALANCE_TEMPLATE_DIR):
        return False

    for label, filename in BALANCE_TEMPLATE_FILE_MAP.items():
        path = os.path.join(BALANCE_TEMPLATE_DIR, filename)
        if not os.path.isfile(path):
            continue
        raw = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if raw is None:
            continue
        prepared = _prepare_balance_template(raw)
        if prepared is not None:
            prepared["label"] = label
            _BALANCE_TEMPLATES[label] = prepared
    return bool(_BALANCE_TEMPLATES)


def _get_balance_match_threshold(label):
    if label == ".":
        return BALANCE_TEMPLATE_DOT_MATCH_THRESHOLD
    if label in ("万", "亿"):
        return BALANCE_TEMPLATE_UNIT_MATCH_THRESHOLD
    return BALANCE_TEMPLATE_MATCH_THRESHOLD


def _get_balance_params(overrides=None):
    params = {
        "binary_blur_size": BALANCE_BINARY_BLUR_SIZE,
        "digit_threshold": BALANCE_TEMPLATE_MATCH_THRESHOLD,
        "dot_baseline_offset_ratio": BALANCE_DOT_BASELINE_OFFSET_RATIO,
        "dot_max_area": BALANCE_DOT_MAX_AREA,
        "dot_max_height": BALANCE_DOT_MAX_HEIGHT,
        "dot_max_neighbor_gap": BALANCE_DOT_MAX_NEIGHBOR_GAP,
        "dot_max_width": BALANCE_DOT_MAX_WIDTH,
        "dot_threshold": BALANCE_TEMPLATE_DOT_MATCH_THRESHOLD,
        "leading_icon_max_amount_start_x": BALANCE_LEADING_ICON_MAX_AMOUNT_START_X,
        "leading_icon_max_cluster_width": BALANCE_LEADING_ICON_MAX_CLUSTER_WIDTH,
        "leading_icon_min_gap": BALANCE_LEADING_ICON_MIN_GAP,
        "min_component_area": BALANCE_SEGMENT_MIN_COMPONENT_AREA,
        "segment_close_kernel_size": BALANCE_SEGMENT_CLOSE_KERNEL_SIZE,
        "segment_max_group_size": BALANCE_SEGMENT_MAX_GROUP_SIZE,
        "segment_merge_gap": BALANCE_SEGMENT_MERGE_GAP,
        "trailing_noise_max_cluster_width": BALANCE_TRAILING_NOISE_MAX_CLUSTER_WIDTH,
        "trailing_noise_min_gap": BALANCE_TRAILING_NOISE_MIN_GAP,
        "unit_min_width": BALANCE_UNIT_MIN_WIDTH,
        "unit_threshold": BALANCE_TEMPLATE_UNIT_MATCH_THRESHOLD,
    }
    if overrides:
        params.update(overrides)

    blur_size = int(params["binary_blur_size"] or 0)
    if blur_size > 1 and blur_size % 2 == 0:
        blur_size += 1
    params["binary_blur_size"] = blur_size
    params["segment_close_kernel_size"] = max(1, int(params["segment_close_kernel_size"]))
    params["segment_max_group_size"] = max(1, int(params["segment_max_group_size"]))
    params["segment_merge_gap"] = max(0, int(params["segment_merge_gap"]))
    params["min_component_area"] = max(1, int(params["min_component_area"]))
    params["dot_max_width"] = max(1, int(params["dot_max_width"]))
    params["dot_max_height"] = max(1, int(params["dot_max_height"]))
    params["dot_max_area"] = max(1, int(params["dot_max_area"]))
    params["dot_max_neighbor_gap"] = max(0, int(params["dot_max_neighbor_gap"]))
    params["unit_min_width"] = max(1, int(params["unit_min_width"]))
    params["leading_icon_min_gap"] = max(0, int(params["leading_icon_min_gap"]))
    params["leading_icon_max_cluster_width"] = max(1, int(params["leading_icon_max_cluster_width"]))
    params["leading_icon_max_amount_start_x"] = max(0, int(params["leading_icon_max_amount_start_x"]))
    params["trailing_noise_min_gap"] = max(0, int(params["trailing_noise_min_gap"]))
    params["trailing_noise_max_cluster_width"] = max(1, int(params["trailing_noise_max_cluster_width"]))
    params["dot_baseline_offset_ratio"] = max(0.0, float(params["dot_baseline_offset_ratio"]))
    return params


def _binarize_balance_region(gray, params=None):
    params = _get_balance_params(params)
    working = gray
    blur_size = params["binary_blur_size"]
    if blur_size > 1:
        working = cv2.GaussianBlur(gray, (blur_size, blur_size), 0)

    binary = cv2.threshold(working, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    border = np.concatenate([binary[0], binary[-1], binary[:, 0], binary[:, -1]])
    if np.mean(border) > 127:
        binary = cv2.bitwise_not(binary)
    return binary


def _remove_small_balance_components(binary, params=None):
    params = _get_balance_params(params)
    component_count, component_labels, component_stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    cleaned = np.zeros_like(binary)
    for component_index in range(1, component_count):
        _, _, width, height, area = component_stats[component_index]
        if area < params["min_component_area"]:
            continue
        if width < 2 or height < 2:
            continue
        cleaned[component_labels == component_index] = 255
    if params["segment_close_kernel_size"] > 1:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (params["segment_close_kernel_size"], params["segment_close_kernel_size"]),
        )
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel)
    return cleaned


def _extract_balance_blocks(binary, params=None):
    params = _get_balance_params(params)
    active_columns = np.any(binary > 0, axis=0)
    blocks = []
    start_x = None
    for column_index, is_active in enumerate(active_columns):
        if is_active and start_x is None:
            start_x = column_index
        elif not is_active and start_x is not None:
            end_x = column_index
            block_slice = binary[:, start_x:end_x]
            active_rows = np.where(np.any(block_slice > 0, axis=1))[0]
            if active_rows.size > 0:
                start_y = int(active_rows[0])
                end_y = int(active_rows[-1]) + 1
                block_image = block_slice[start_y:end_y, :]
                area = int(cv2.countNonZero(block_image))
                if area >= params["min_component_area"]:
                    blocks.append({
                        "area": area,
                        "bottom": end_y,
                        "height": end_y - start_y,
                        "image": block_image,
                        "width": end_x - start_x,
                        "x": start_x,
                        "y": start_y,
                    })
            start_x = None
    if start_x is not None:
        block_slice = binary[:, start_x:]
        active_rows = np.where(np.any(block_slice > 0, axis=1))[0]
        if active_rows.size > 0:
            start_y = int(active_rows[0])
            end_y = int(active_rows[-1]) + 1
            block_image = block_slice[start_y:end_y, :]
            area = int(cv2.countNonZero(block_image))
            if area >= params["min_component_area"]:
                blocks.append({
                    "area": area,
                    "bottom": end_y,
                    "height": end_y - start_y,
                    "image": block_image,
                    "width": binary.shape[1] - start_x,
                    "x": start_x,
                    "y": start_y,
                })
    return blocks


def _merge_balance_blocks(blocks, start_index, end_index):
    merged_blocks = blocks[start_index:end_index + 1]
    left = int(merged_blocks[0]["x"])
    right = int(merged_blocks[-1]["x"]) + int(merged_blocks[-1]["width"])
    top = min(int(block["y"]) for block in merged_blocks)
    bottom = max(int(block["bottom"]) for block in merged_blocks)

    merged_image = np.zeros((bottom - top, right - left), dtype=np.uint8)
    area = 0
    for block in merged_blocks:
        offset_x = int(block["x"]) - left
        offset_y = int(block["y"]) - top
        block_image = block["image"]
        height, width = block_image.shape[:2]
        merged_image[offset_y:offset_y + height, offset_x:offset_x + width] = np.maximum(
            merged_image[offset_y:offset_y + height, offset_x:offset_x + width],
            block_image,
        )
        area += int(block["area"])
    return {
        "area": area,
        "bottom": bottom,
        "height": bottom - top,
        "image": merged_image,
        "part_count": end_index - start_index + 1,
        "width": right - left,
        "x": left,
        "y": top,
    }


def _split_balance_block(block):
    if int(block["width"]) < 14 or int(block["height"]) < 16:
        return [block]

    image = block["image"]
    column_counts = np.count_nonzero(image > 0, axis=0)
    if column_counts.size < 6:
        return [block]

    search_start = max(2, int(column_counts.size * 0.25))
    search_end = min(column_counts.size - 2, int(column_counts.size * 0.75))
    if search_end <= search_start:
        return [block]

    local_counts = column_counts[search_start:search_end]
    valley_offset = int(np.argmin(local_counts))
    valley_index = search_start + valley_offset
    valley_value = int(column_counts[valley_index])
    valley_limit = max(2, int(block["height"] * 0.18))
    if valley_value > valley_limit:
        return [block]

    left_slice = image[:, :valley_index]
    right_slice = image[:, valley_index:]
    split_blocks = []
    for offset_x, block_slice in ((0, left_slice), (valley_index, right_slice)):
        active_columns = np.where(np.any(block_slice > 0, axis=0))[0]
        active_rows = np.where(np.any(block_slice > 0, axis=1))[0]
        if active_columns.size == 0 or active_rows.size == 0:
            return [block]
        start_x = int(active_columns[0])
        end_x = int(active_columns[-1]) + 1
        start_y = int(active_rows[0])
        end_y = int(active_rows[-1]) + 1
        cropped = block_slice[start_y:end_y, start_x:end_x]
        if cropped.shape[1] < 2:
            return [block]
        split_blocks.append({
            "area": int(cv2.countNonZero(cropped)),
            "bottom": int(block["y"]) + end_y,
            "height": end_y - start_y,
            "image": cropped,
            "width": end_x - start_x,
            "x": int(block["x"]) + offset_x + start_x,
            "y": int(block["y"]) + start_y,
        })
    return split_blocks


def _refine_balance_blocks(blocks):
    refined = []
    for block in blocks:
        refined.extend(_split_balance_block(block))
    refined.sort(key=lambda item: int(item["x"]))
    return refined


def _normalize_balance_block_to_template(block_image, template_image):
    template_height, template_width = template_image.shape[:2]
    block_height, block_width = block_image.shape[:2]
    if template_height <= 0 or template_width <= 0 or block_height <= 0 or block_width <= 0:
        return None

    scale = min(template_width / float(block_width), template_height / float(block_height))
    resized_width = max(1, min(template_width, int(round(block_width * scale))))
    resized_height = max(1, min(template_height, int(round(block_height * scale))))
    resized = cv2.resize(block_image, (resized_width, resized_height), interpolation=cv2.INTER_NEAREST)

    canvas = np.zeros((template_height, template_width), dtype=np.uint8)
    offset_x = (template_width - resized_width) // 2
    offset_y = (template_height - resized_height) // 2
    canvas[offset_y:offset_y + resized_height, offset_x:offset_x + resized_width] = resized
    return canvas


def _score_balance_block(block_image, template_image):
    normalized = _normalize_balance_block_to_template(block_image, template_image)
    if normalized is None:
        return 0.0

    block_mask = normalized > 0
    template_mask = template_image > 0
    block_foreground = int(np.count_nonzero(block_mask))
    template_foreground = int(np.count_nonzero(template_mask))
    if block_foreground == 0 or template_foreground == 0:
        return 0.0

    intersection = int(np.count_nonzero(np.logical_and(block_mask, template_mask)))
    if intersection == 0:
        return 0.0

    union = int(np.count_nonzero(np.logical_or(block_mask, template_mask)))
    if union == 0:
        return 0.0

    iou = intersection / float(union)
    similarity = cv2.matchTemplate(
        normalized.astype(np.float32),
        template_image.astype(np.float32),
        cv2.TM_CCOEFF_NORMED,
    )[0][0]
    if np.isnan(similarity):
        similarity = 0.0
    similarity = max(0.0, float(similarity))

    block_ratio = block_image.shape[1] / float(block_image.shape[0])
    template_ratio = template_image.shape[1] / float(template_image.shape[0])
    ratio_gap = abs(block_ratio - template_ratio) / max(template_ratio, 1e-6)
    ratio_penalty = 1.0 - min(0.35, ratio_gap * 0.18)

    block_fill_ratio = block_foreground / float(normalized.size)
    template_fill_ratio = template_foreground / float(template_image.size)
    fill_gap = abs(block_fill_ratio - template_fill_ratio)
    fill_penalty = 1.0 - min(0.20, fill_gap * 0.35)

    return (iou * 0.55 + similarity * 0.45) * ratio_penalty * fill_penalty


def _get_best_balance_label_score(block_image, labels):
    best_label = None
    best_score = 0.0
    for label in labels:
        template = _BALANCE_TEMPLATES.get(label)
        if template is None:
            continue
        score = _score_balance_block(block_image, template["image"])
        if score > best_score:
            best_score = score
            best_label = label
    return best_label, best_score


def _get_balance_candidates(blocks, index, baseline_bottom, max_block_height, params):
    params = _get_balance_params(params)
    candidates = []
    max_end_index = min(len(blocks), index + params["segment_max_group_size"])
    digit_labels = tuple(str(digit) for digit in range(10))

    for end_index in range(index, max_end_index):
        if end_index > index:
            previous_block = blocks[end_index - 1]
            current_block = blocks[end_index]
            merge_gap = int(current_block["x"]) - int(previous_block["x"]) - int(previous_block["width"])
            if merge_gap > params["segment_merge_gap"]:
                break

        merged_block = _merge_balance_blocks(blocks, index, end_index)
        block_image = merged_block["image"]
        best_digit_label, best_digit_score = _get_best_balance_label_score(block_image, digit_labels)
        best_unit_label, best_unit_score = _get_best_balance_label_score(block_image, ("万", "亿"))
        _, dot_score = _get_best_balance_label_score(block_image, (".",))

        if merged_block["part_count"] == 1:
            left_gap = params["dot_max_neighbor_gap"] + 1
            right_gap = params["dot_max_neighbor_gap"] + 1
            if index > 0:
                previous_block = blocks[index - 1]
                left_gap = int(merged_block["x"]) - int(previous_block["x"]) - int(previous_block["width"])
            if index < len(blocks) - 1:
                next_block = blocks[index + 1]
                right_gap = int(next_block["x"]) - int(merged_block["x"]) - int(merged_block["width"])

            is_dot_candidate = (
                0 < index < len(blocks) - 1
                and int(merged_block["width"]) <= params["dot_max_width"]
                and int(merged_block["height"]) <= params["dot_max_height"]
                and int(merged_block["area"]) <= params["dot_max_area"]
                and int(merged_block["bottom"]) >= baseline_bottom - 1
                and int(merged_block["y"]) >= baseline_bottom - int(max_block_height * params["dot_baseline_offset_ratio"])
                and int(blocks[index - 1]["height"]) > int(merged_block["height"])
                and int(blocks[index + 1]["height"]) > int(merged_block["height"])
                and left_gap <= params["dot_max_neighbor_gap"]
                and right_gap <= params["dot_max_neighbor_gap"]
            )
            if (
                is_dot_candidate
                and dot_score >= params["dot_threshold"]
            ):
                candidates.append((end_index + 1, ".", dot_score))

        if best_digit_label is not None and best_digit_score >= params["digit_threshold"]:
            candidates.append((end_index + 1, best_digit_label, best_digit_score))

        if (
            end_index == len(blocks) - 1
            and int(merged_block["width"]) >= params["unit_min_width"]
            and best_unit_label is not None
            and best_unit_score >= params["unit_threshold"]
        ):
            candidates.append((end_index + 1, best_unit_label, best_unit_score))

    candidates.sort(key=lambda item: item[2], reverse=True)
    return candidates


def _search_balance_sequence(blocks, params=None):
    if not blocks:
        return None

    params = _get_balance_params(params)
    max_block_height = max(int(block["height"]) for block in blocks)
    reference_blocks = [block for block in blocks if int(block["height"]) >= max(8, int(max_block_height * 0.55))]
    baseline_bottom = int(np.median([block["bottom"] for block in reference_blocks])) if reference_blocks else 0
    block_count = len(blocks)
    cache = {}

    def dfs(index, state_name):
        cache_key = (index, state_name)
        if cache_key in cache:
            return cache[cache_key]

        results = []
        if state_name in ("int_tail", "frac_tail"):
            results.append((index, "", 0.0, 0))
        if index >= block_count:
            cache[cache_key] = results
            return results

        for next_index, label, score in _get_balance_candidates(blocks, index, baseline_bottom, max_block_height, params):
            if state_name == "int" and label.isdigit():
                next_state = "int_tail"
            elif state_name == "int_tail" and label.isdigit():
                next_state = "int_tail"
            elif state_name == "int_tail" and label == ".":
                next_state = "frac_first"
            elif state_name == "int_tail" and label in ("万", "亿"):
                if next_index == block_count:
                    results.append((next_index, label, score, 1))
                continue
            elif state_name == "frac_first" and label.isdigit():
                next_state = "frac_tail"
            elif state_name == "frac_tail" and label.isdigit():
                next_state = "frac_tail"
            elif state_name == "frac_tail" and label in ("万", "亿"):
                if next_index == block_count:
                    results.append((next_index, label, score, 1))
                continue
            else:
                continue

            for end_index, suffix_text, suffix_score, suffix_count in dfs(next_index, next_state):
                results.append((end_index, label + suffix_text, score + suffix_score, suffix_count + 1))

        cache[cache_key] = results
        return results

    best_text = None
    best_rank = None
    for start_index in range(block_count):
        for end_index, text, score, token_count in dfs(start_index, "int"):
            if end_index != block_count or not text:
                continue
            rank = (token_count, score, -start_index)
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best_text = text
    return best_text


def _match_balance_text(gray, params=None):
    if not load_balance_templates():
        return None

    params = _get_balance_params(params)
    binary = _binarize_balance_region(gray, params)
    cleaned = _remove_small_balance_components(binary, params)
    blocks = _extract_balance_blocks(cleaned, params)
    blocks = _refine_balance_blocks(blocks)
    if not blocks:
        return None
    blocks = _drop_leading_balance_icon_blocks(blocks, params)
    blocks = _trim_trailing_balance_noise_blocks(blocks, params)
    return _search_balance_sequence(blocks, params)


def _sanitize_balance_text(raw_text):
    text = re.sub(r"[^\d\.万亿]", "", str(raw_text or "").strip())
    if not text:
        return None
    if re.fullmatch(r"\d+", text):
        return text
    if re.fullmatch(r"\d+\.\d+", text):
        return text
    if re.fullmatch(r"\d+(\.\d+)?[万亿]", text):
        return text
    return None


def _drop_leading_balance_icon_blocks(blocks, params=None):
    if len(blocks) < 4:
        return blocks

    params = _get_balance_params(params)
    min_icon_gap = max(int(params["leading_icon_min_gap"]), int(params["segment_merge_gap"]) + 5)
    max_icon_cluster_width = int(params["leading_icon_max_cluster_width"])
    max_amount_start_x = int(params["leading_icon_max_amount_start_x"])
    max_split_index = min(3, len(blocks) - 2)
    saw_icon_like_cluster = False

    for split_index in range(1, max_split_index + 1):
        previous_block = blocks[split_index - 1]
        next_block = blocks[split_index]
        previous_right = int(previous_block["x"]) + int(previous_block["width"])
        gap = int(next_block["x"]) - previous_right
        if gap < min_icon_gap:
            continue

        first_block = blocks[0]
        leading_cluster_width = previous_right - int(first_block["x"])
        if leading_cluster_width > max_icon_cluster_width:
            continue
        if int(next_block["x"]) > max_amount_start_x:
            continue

        saw_icon_like_cluster = True
        remaining_blocks = blocks[split_index:]
        cleaned_remaining_blocks = _trim_trailing_balance_noise_blocks(remaining_blocks, params)
        if _sanitize_balance_text(_search_balance_sequence(cleaned_remaining_blocks, params)):
            return cleaned_remaining_blocks

    if saw_icon_like_cluster:
        return []
    return blocks


def _trim_trailing_balance_noise_blocks(blocks, params=None):
    if len(blocks) < 3:
        return blocks

    params = _get_balance_params(params)
    min_noise_gap = int(params["trailing_noise_min_gap"])
    max_noise_cluster_width = int(params["trailing_noise_max_cluster_width"])
    min_split_index = max(1, len(blocks) - 3)
    saw_trailing_noise = False

    for split_index in range(len(blocks) - 1, min_split_index - 1, -1):
        prefix_blocks = blocks[:split_index]
        trailing_blocks = blocks[split_index:]
        prefix_right = int(prefix_blocks[-1]["x"]) + int(prefix_blocks[-1]["width"])
        trailing_left = int(trailing_blocks[0]["x"])
        gap = trailing_left - prefix_right
        if gap < min_noise_gap:
            continue

        trailing_right = int(trailing_blocks[-1]["x"]) + int(trailing_blocks[-1]["width"])
        trailing_width = trailing_right - trailing_left
        if trailing_width > max_noise_cluster_width:
            continue

        saw_trailing_noise = True
        prefix_text = _sanitize_balance_text(_search_balance_sequence(prefix_blocks, params))
        if prefix_text and prefix_text.endswith(("万", "亿")):
            return prefix_blocks

    if saw_trailing_noise:
        return []
    return blocks


def _get_active_balance_monitor():
    if bool(getattr(state, "accessory_purchase_mode", False)):
        return ACCESSORY_MONITOR_BALANCE
    return MONITOR_BALANCE


def recognize_balance_image(image, roi_already_cropped=False, params=None):
    if image is None:
        return None
    cropped = image if roi_already_cropped else crop_frame(image, _get_active_balance_monitor())
    return _sanitize_balance_text(_match_balance_text(_to_gray(cropped), params))


def get_balance_recognition(frame):
    try:
        active_monitor = _get_active_balance_monitor()
        cropped = crop_frame(frame, active_monitor)
        tiny = cv2.resize(cropped, (8, 8))
        current_hash = (tuple(sorted(active_monitor.items())), tiny.tobytes())
        last_balance_hash = getattr(state, "_last_balance_hash", None)
        if last_balance_hash is not None and current_hash == last_balance_hash:
            return {
                "confirmed": bool(getattr(state, "balance_last_recognition_confirmed", False)),
                "text": str(getattr(state, "balance_last_recognition_text", "") or "").strip() or None,
            }

        balance_text = recognize_balance_image(cropped, roi_already_cropped=True)
        confirmed = bool(balance_text)
        setattr(state, "_last_balance_hash", current_hash)
        state.balance_last_recognition_text = str(balance_text or "").strip()
        state.balance_last_recognition_confirmed = confirmed
        return {
            "confirmed": confirmed,
            "text": balance_text if confirmed else None,
        }
    except:
        state.balance_last_recognition_text = ""
        state.balance_last_recognition_confirmed = False
        return {
            "confirmed": False,
            "text": None,
        }


def get_balance(frame):
    recognition = get_balance_recognition(frame)
    if recognition.get("confirmed"):
        return recognition.get("text")
    return None


# ---- 上架倒计时 ----

_LISTING_TIMER_TEMPLATE_FILE_MAP = {
    "4": ("4.png", "4-4.png"),
    "6": ("6.png", "6-6.png"),
    "7": ("7.png", "7-7.png"),
}


def _prepare_listing_timer_template(raw):
    gray = _to_gray(raw)
    if len(raw.shape) == 3 and raw.shape[2] == 4:
        alpha = raw[:, :, 3]
        mask = cv2.threshold(alpha, 0, 255, cv2.THRESH_BINARY)[1]
        canvas = np.zeros_like(gray)
        canvas[mask > 0] = gray[mask > 0]
        gray = canvas
    else:
        mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        border = np.concatenate([mask[0], mask[-1], mask[:, 0], mask[:, -1]])
        if np.mean(border) > 127:
            mask = cv2.bitwise_not(mask)
    coords = cv2.findNonZero(mask)
    if coords is None:
        return None
    x, y, w, h = cv2.boundingRect(coords)
    return gray[y:y + h, x:x + w]


def _load_listing_timer_templates():
    global _LISTING_TIMER_TEMPLATES, _LISTING_TIMER_TEMPLATE_LOAD_ATTEMPTED

    if _LISTING_TIMER_TEMPLATE_LOAD_ATTEMPTED:
        return bool(_LISTING_TIMER_TEMPLATES)

    _LISTING_TIMER_TEMPLATE_LOAD_ATTEMPTED = True
    _LISTING_TIMER_TEMPLATES = {}
    for label, filenames in _LISTING_TIMER_TEMPLATE_FILE_MAP.items():
        variants = []
        for filename in filenames:
            path = os.path.join(TEMPLATE_DIR, filename)
            if not os.path.isfile(path):
                continue
            raw = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if raw is None:
                continue
            prepared = _prepare_listing_timer_template(raw)
            if prepared is not None:
                variants.append(prepared)
        if variants:
            _LISTING_TIMER_TEMPLATES[label] = variants
    return bool(_LISTING_TIMER_TEMPLATES)


def _get_listing_timer_action_params(overrides=None):
    params = {
        "blur_size": LISTING_TIMER_BLUR_SIZE,
        "close_kernel_size": LISTING_TIMER_CLOSE_KERNEL_SIZE,
        "digit4_keep_threshold": LISTING_TIMER_DIGIT4_KEEP_THRESHOLD,
        "digit6_keep_threshold": LISTING_TIMER_DIGIT6_KEEP_THRESHOLD,
        "digit7_keep_threshold": LISTING_TIMER_DIGIT7_KEEP_THRESHOLD,
        "max_component_width": LISTING_TIMER_MAX_COMPONENT_WIDTH,
        "min_component_area": LISTING_TIMER_MIN_COMPONENT_AREA,
        "min_component_height": LISTING_TIMER_MIN_COMPONENT_HEIGHT,
        "min_component_x": LISTING_TIMER_MIN_COMPONENT_X,
        "other_max_4_score": LISTING_TIMER_OTHER_MAX_4_SCORE,
        "other_max_67_score": LISTING_TIMER_OTHER_MAX_67_SCORE,
        "other_min_67_score": LISTING_TIMER_OTHER_MIN_67_SCORE,
        "score_margin": LISTING_TIMER_SCORE_MARGIN,
        "threshold_shift": LISTING_TIMER_THRESHOLD_SHIFT,
        "upscale": LISTING_TIMER_UPSCALE,
    }
    if overrides:
        params.update(overrides)

    params["blur_size"] = max(0, int(params["blur_size"] or 0))
    if params["blur_size"] > 1 and params["blur_size"] % 2 == 0:
        params["blur_size"] += 1
    params["close_kernel_size"] = max(1, int(params["close_kernel_size"] or 1))
    params["max_component_width"] = max(1, int(params["max_component_width"] or 1))
    params["min_component_area"] = max(1, int(params["min_component_area"] or 1))
    params["min_component_height"] = max(1, int(params["min_component_height"] or 1))
    params["min_component_x"] = max(0, int(params["min_component_x"] or 0))
    params["score_margin"] = max(0.0, float(params["score_margin"] or 0.0))
    params["threshold_shift"] = int(params["threshold_shift"] or 0)
    params["upscale"] = max(1, int(params["upscale"] or 1))
    return params


def _get_listing_timer_sequence_params(overrides=None):
    params = {
        "blur_size": LISTING_TIMER_SEQUENCE_BLUR_SIZE,
        "close_kernel_size": LISTING_TIMER_SEQUENCE_CLOSE_KERNEL_SIZE,
        "digit4_threshold": LISTING_TIMER_SEQUENCE_DIGIT4_THRESHOLD,
        "digit6_threshold": LISTING_TIMER_SEQUENCE_DIGIT6_THRESHOLD,
        "digit7_threshold": LISTING_TIMER_SEQUENCE_DIGIT7_THRESHOLD,
        "duplicate_gap": LISTING_TIMER_SEQUENCE_DUPLICATE_GAP,
        "max_component_width": LISTING_TIMER_SEQUENCE_MAX_COMPONENT_WIDTH,
        "min_component_area": LISTING_TIMER_SEQUENCE_MIN_COMPONENT_AREA,
        "min_component_height": LISTING_TIMER_SEQUENCE_MIN_COMPONENT_HEIGHT,
        "min_component_x": LISTING_TIMER_SEQUENCE_MIN_COMPONENT_X,
        "score_margin": LISTING_TIMER_SEQUENCE_SCORE_MARGIN,
        "threshold_shift": LISTING_TIMER_SEQUENCE_THRESHOLD_SHIFT,
        "upscale": LISTING_TIMER_SEQUENCE_UPSCALE,
    }
    if overrides:
        params.update(overrides)

    params["blur_size"] = max(0, int(params["blur_size"] or 0))
    if params["blur_size"] > 1 and params["blur_size"] % 2 == 0:
        params["blur_size"] += 1
    params["close_kernel_size"] = max(1, int(params["close_kernel_size"] or 1))
    params["duplicate_gap"] = max(0, int(params["duplicate_gap"] or 0))
    params["max_component_width"] = max(1, int(params["max_component_width"] or 1))
    params["min_component_area"] = max(1, int(params["min_component_area"] or 1))
    params["min_component_height"] = max(1, int(params["min_component_height"] or 1))
    params["min_component_x"] = max(0, int(params["min_component_x"] or 0))
    params["score_margin"] = max(0.0, float(params["score_margin"] or 0.0))
    params["threshold_shift"] = int(params["threshold_shift"] or 0)
    params["upscale"] = max(1, int(params["upscale"] or 1))
    return params


def _resize_listing_timer_patch(image, width=24, height=32):
    image_height, image_width = image.shape[:2]
    if image_height <= 0 or image_width <= 0:
        return None
    scale = min(width / float(image_width), height / float(image_height))
    resized_width = max(1, int(round(image_width * scale)))
    resized_height = max(1, int(round(image_height * scale)))
    resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_CUBIC)
    canvas = np.zeros((height, width), dtype=np.uint8)
    offset_x = (width - resized_width) // 2
    offset_y = (height - resized_height) // 2
    canvas[offset_y:offset_y + resized_height, offset_x:offset_x + resized_width] = resized
    return canvas


def _score_listing_timer_patch(block_gray, template_gray):
    normalized_block = _resize_listing_timer_patch(block_gray, width=24, height=32)
    normalized_template = _resize_listing_timer_patch(template_gray, width=24, height=32)
    if normalized_block is None or normalized_template is None:
        return 0.0
    score = cv2.matchTemplate(
        normalized_block.astype(np.float32),
        normalized_template.astype(np.float32),
        cv2.TM_CCOEFF_NORMED,
    )[0][0]
    if np.isnan(score):
        return 0.0
    return max(0.0, float(score))


def _prepare_listing_timer_images(image, params):
    gray = _to_gray(image)
    if gray is None or gray.size == 0:
        return None, None

    working_gray = cv2.resize(
        gray,
        None,
        fx=params["upscale"],
        fy=params["upscale"],
        interpolation=cv2.INTER_CUBIC,
    )
    if params["blur_size"] > 1:
        working_gray = cv2.GaussianBlur(
            working_gray,
            (params["blur_size"], params["blur_size"]),
            0,
        )

    otsu_threshold, _ = cv2.threshold(working_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    threshold_value = max(0, min(255, int(otsu_threshold + params["threshold_shift"])))
    _, binary = cv2.threshold(working_gray, threshold_value, 255, cv2.THRESH_BINARY)
    border = np.concatenate([binary[0], binary[-1], binary[:, 0], binary[:, -1]])
    if np.mean(border) > 127:
        binary = cv2.bitwise_not(binary)
    if params["close_kernel_size"] > 1:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (params["close_kernel_size"], params["close_kernel_size"]),
        )
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    return working_gray, binary


def _extract_listing_timer_components(processed_gray, binary, params):
    component_count, _, component_stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    components = []
    for component_index in range(1, component_count):
        x, y, width, height, area = component_stats[component_index]
        if area < params["min_component_area"]:
            continue
        if height < params["min_component_height"]:
            continue
        if width > params["max_component_width"]:
            continue
        if x < params["min_component_x"]:
            continue
        components.append({
            "area": int(area),
            "gray": processed_gray[y:y + height, x:x + width],
            "height": int(height),
            "width": int(width),
            "x": int(x),
            "y": int(y),
        })
    components.sort(key=lambda item: (item["x"], item["y"]))
    return components


def _classify_listing_timer_component(component_gray):
    scores = {}
    for label, variants in (_LISTING_TIMER_TEMPLATES or {}).items():
        if not variants:
            continue
        scores[label] = max(_score_listing_timer_patch(component_gray, template) for template in variants)
    return scores


def _is_confident_listing_timer_digit(scores, label, threshold, margin):
    if label not in scores:
        return False
    best_score = scores.get(label, 0.0)
    other_score = max(
        [score for other_label, score in scores.items() if other_label != label],
        default=0.0,
    )
    return best_score >= threshold and best_score - other_score >= margin


def _extract_listing_timer_hour_scores(image, roi_already_cropped=False, params=None):
    if image is None or not _load_listing_timer_templates():
        return None

    cropped = image if roi_already_cropped else crop_frame(image, LISTING_TIMER_REGION)
    params = _get_listing_timer_action_params(params)
    processed_gray, binary = _prepare_listing_timer_images(cropped, params)
    if processed_gray is None or binary is None:
        return None

    components = _extract_listing_timer_components(processed_gray, binary, params)
    if len(components) < 2:
        return None

    hour_components = components[:2]
    first_scores = _classify_listing_timer_component(hour_components[0]["gray"])
    second_scores = _classify_listing_timer_component(hour_components[1]["gray"])
    if not first_scores or not second_scores:
        return None

    return {
        "params": params,
        "first_scores": first_scores,
        "second_scores": second_scores,
    }


def recognize_listing_timer_hour_value(image, roi_already_cropped=False, params=None):
    result = _extract_listing_timer_hour_scores(
        image,
        roi_already_cropped=roi_already_cropped,
        params=params,
    )
    if result is None:
        return None

    params = result["params"]
    first_scores = result["first_scores"]
    second_scores = result["second_scores"]
    if not _is_confident_listing_timer_digit(
        first_scores,
        "4",
        params["digit4_keep_threshold"],
        params["score_margin"],
    ):
        return None

    if _is_confident_listing_timer_digit(
        second_scores,
        "6",
        params["digit6_keep_threshold"],
        params["score_margin"],
    ):
        return "46"

    if _is_confident_listing_timer_digit(
        second_scores,
        "7",
        params["digit7_keep_threshold"],
        params["score_margin"],
    ):
        return "47"

    return None


def recognize_listing_timer_action(image, roi_already_cropped=False, params=None):
    result = _extract_listing_timer_hour_scores(
        image,
        roi_already_cropped=roi_already_cropped,
        params=params,
    )
    if result is None:
        return None

    params = result["params"]
    first_scores = result["first_scores"]
    second_scores = result["second_scores"]
    if not _is_confident_listing_timer_digit(
        first_scores,
        "4",
        params["digit4_keep_threshold"],
        params["score_margin"],
    ):
        return None

    if recognize_listing_timer_hour_value(
        image,
        roi_already_cropped=roi_already_cropped,
        params=params,
    ) in {"46", "47"}:
        return "keep"

    if max(second_scores.get("6", 0.0), second_scores.get("7", 0.0)) <= params["other_max_67_score"]:
        return "other"

    return None


def extract_timer_467_sequence(image, params=None):
    if image is None or not _load_listing_timer_templates():
        return None

    params = _get_listing_timer_sequence_params(params)
    processed_gray, binary = _prepare_listing_timer_images(image, params)
    if processed_gray is None or binary is None:
        return None

    components = _extract_listing_timer_components(processed_gray, binary, params)
    if not components:
        return None

    sequence = []
    last_x_by_label = {}
    for component in components:
        scores = _classify_listing_timer_component(component["gray"])
        if not scores:
            continue
        best_label = max(scores, key=scores.get)
        best_score = scores[best_label]
        second_score = max(
            [score for label, score in scores.items() if label != best_label],
            default=0.0,
        )
        label_threshold = params[f"digit{best_label}_threshold"]
        if best_score < label_threshold:
            continue
        if best_score - second_score < params["score_margin"]:
            continue

        last_x = last_x_by_label.get(best_label)
        if last_x is not None and component["x"] - last_x <= params["duplicate_gap"]:
            continue

        sequence.append((component["x"], best_label))
        last_x_by_label[best_label] = component["x"]

    if not sequence:
        return None
    sequence.sort(key=lambda item: item[0])
    return "".join(label for _, label in sequence)


def compare_region_similarity(frame1, frame2, monitor):
    g1 = cv2.cvtColor(crop_frame(frame1, monitor), cv2.COLOR_BGRA2GRAY)
    g2 = cv2.cvtColor(crop_frame(frame2, monitor), cv2.COLOR_BGRA2GRAY)
    result = cv2.matchTemplate(g1, g2, cv2.TM_CCOEFF_NORMED)
    return float(result[0][0])


def match_item_in_scan(frame):
    from config import SCAN_REGION, ITEM_THRESHOLD
    if state.TEMP_ITEM is None:
        return False, 0, 0
    cropped = crop_frame(frame, SCAN_REGION)
    cropped_bgr = cv2.cvtColor(cropped, cv2.COLOR_BGRA2BGR)
    th, tw = state.TEMP_ITEM.shape[:2]
    if th > cropped_bgr.shape[0] or tw > cropped_bgr.shape[1]:
        return False, 0, 0
    res = cv2.matchTemplate(cropped_bgr, state.TEMP_ITEM, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val >= ITEM_THRESHOLD:
        abs_x = SCAN_REGION["left"] + max_loc[0] + tw // 2
        abs_y = SCAN_REGION["top"] + max_loc[1] + th // 2
        return True, abs_x, abs_y
    return False, 0, 0
