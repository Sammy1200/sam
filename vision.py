"""
截图裁剪、模板匹配、文字识别、余额识别、容量识别
"""
import cv2
import numpy as np
import re
import time
import unicodedata
import state
from config import (
    MONITOR_PRICE, MONITOR_CAPACITY, MONITOR_BALANCE,
    MIN_PRICE, MAX_PRICE,
    UPSCALE, STANDARD_W, STANDARD_H, TEMPLATE_DIR,
    BALANCE_TEMPLATE_DIR, BALANCE_TEMPLATE_MATCH_THRESHOLD, BALANCE_TEMPLATE_DUPLICATE_GAP,
    PRICE_DECISION_MAX_PRICE,
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


def get_number(frame, templates):
    try:
        pixel_color = frame[207, 1320]
        target_bgr = [51, 205, 255]
        color_diff = (abs(int(pixel_color[0]) - target_bgr[0]) +
                      abs(int(pixel_color[1]) - target_bgr[1]) +
                      abs(int(pixel_color[2]) - target_bgr[2]))
        if color_diff > 45:
            return None
        cropped = crop_frame(frame, MONITOR_PRICE)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        # 价格区域完全不变时，直接复用上一帧识别结果，避免重复模板匹配。
        roi_bytes = gray.tobytes()
        # 价格区域完全不变时，直接复用上一帧识别结果，避免重复模板匹配。
        roi_bytes = gray.tobytes()
        roi_bytes = gray.tobytes()
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
FAST_ACCEPT_FIRST_DIGITS = {"4", "5", "6", "7", "8", "9"}
FAST_ACCEPT_SECOND_DIGITS = {"0", "1", "2", "3", "4", "5"}
FAST_REJECT_FIRST_DIGITS = {"2"}
FAST_REJECT_SECOND_DIGITS = {"7", "8", "9"}


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


def _cache_price_decision(roi_bytes, decision, price_value, price_text):
    state.price_decision_cache_bytes = roi_bytes
    state.price_decision_cache_decision = decision
    state.price_decision_cache_value = price_value
    state.price_decision_cache_text = price_text


def _get_price_prefix_decision(gray, templates):
    digit_hits = _match_digit_hits(gray, templates, range(0, 10))
    if not digit_hits:
        return None, None

    first_digit = digit_hits[0][1]
    if first_digit in FAST_ACCEPT_FIRST_DIGITS:
        return "accept", first_digit
    if first_digit in FAST_REJECT_FIRST_DIGITS:
        return "reject", first_digit
    if first_digit == "3":
        return None, None
    if first_digit != "1":
        return None, None

    if len(digit_hits) < 2:
        return None, None

    second_digit = digit_hits[1][1]
    prefix_text = f"{first_digit}{second_digit}"
    if second_digit in FAST_ACCEPT_SECOND_DIGITS:
        return "accept", prefix_text
    if second_digit in FAST_REJECT_SECOND_DIGITS:
        return "reject", prefix_text
    return None, None


def get_price_decision(frame, templates):
    try:
        pixel_color = frame[207, 1320]
        target_bgr = [51, 205, 255]
        color_diff = (abs(int(pixel_color[0]) - target_bgr[0]) +
                      abs(int(pixel_color[1]) - target_bgr[1]) +
                      abs(int(pixel_color[2]) - target_bgr[2]))
        if color_diff > 45:
            return "unknown", None, None

        cropped = crop_frame(frame, MONITOR_PRICE)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        roi_bytes = gray.tobytes()
        if state.price_decision_cache_bytes == roi_bytes:
            return (
                state.price_decision_cache_decision,
                state.price_decision_cache_value,
                state.price_decision_cache_text,
            )

        prefix_decision, prefix_text = _get_price_prefix_decision(gray, templates)
        if prefix_decision is not None:
            _cache_price_decision(roi_bytes, prefix_decision, None, prefix_text)
            return prefix_decision, None, prefix_text

        price_value = get_number(frame, templates)
        if price_value is None:
            _cache_price_decision(roi_bytes, "unknown", None, None)
            return "unknown", None, None

        price_text = str(price_value)
        if MIN_PRICE < price_value < PRICE_DECISION_MAX_PRICE:
            decision = "accept"
        else:
            decision = "reject"
        _cache_price_decision(roi_bytes, decision, price_value, price_text)
        return decision, price_value, price_text
    except:
        return "unknown", None, None


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
            _BALANCE_TEMPLATES[label] = prepared
    return bool(_BALANCE_TEMPLATES)


def _merge_balance_hits(detected):
    if not detected:
        return []

    detected.sort(key=lambda item: item[0])
    merged = []
    last = detected[0]
    for current in detected[1:]:
        is_overlapping = current[0] <= (last[0] + last[3] - 1)
        is_adjacent_duplicate = (
            current[1] == last[1]
            and current[0] - last[0] <= BALANCE_TEMPLATE_DUPLICATE_GAP
        )
        if is_overlapping or is_adjacent_duplicate:
            if current[2] > last[2]:
                last = current
        else:
            merged.append(last)
            last = current
    merged.append(last)
    return merged


def _match_balance_text(gray):
    if not load_balance_templates():
        return None

    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    border = np.concatenate([binary[0], binary[-1], binary[:, 0], binary[:, -1]])
    if np.mean(border) > 127:
        binary = cv2.bitwise_not(binary)

    detected = []
    for label, template in _BALANCE_TEMPLATES.items():
        tpl_image = template["image"]
        if binary.shape[0] < tpl_image.shape[0] or binary.shape[1] < tpl_image.shape[1]:
            continue
        result = cv2.matchTemplate(binary, tpl_image, cv2.TM_CCORR_NORMED)
        loc = np.where(result >= BALANCE_TEMPLATE_MATCH_THRESHOLD)
        for pt in zip(*loc[::-1]):
            detected.append((pt[0], label, float(result[pt[1], pt[0]]), template["width"]))

    if not detected:
        return None

    merged = _merge_balance_hits(detected)
    if not merged:
        return None
    return "".join(item[1] for item in merged)


def _sanitize_balance_text(raw_text):
    text = re.sub(r"[^\d\.万亿]", "", str(raw_text or ""))
    if not text:
        return None

    units = [char for char in text if char in ("万", "亿")]
    if len(units) > 1:
        return None

    unit = units[0] if units else ""
    if unit:
        if text[-1] != unit or text.count(unit) != 1:
            return None
        number_part = text[:-1]
    else:
        number_part = text

    if not number_part:
        return None

    if unit:
        if number_part.count(".") > 1:
            first_dot = number_part.find(".")
            number_part = number_part[:first_dot + 1] + number_part[first_dot + 1:].replace(".", "")
        if number_part.startswith(".") or number_part.endswith("."):
            return None
        if not re.fullmatch(r"\d+(\.\d+)?", number_part):
            return None
    else:
        number_part = number_part.replace(".", "")
        if not number_part.isdigit():
            return None

    return f"{number_part}{unit}" if unit else number_part


def get_balance(frame):
    try:
        cropped = crop_frame(frame, MONITOR_BALANCE)
        tiny = cv2.resize(cropped, (8, 8))
        current_hash = tiny.tobytes()
        last_balance_hash = getattr(state, "_last_balance_hash", None)
        if last_balance_hash is not None and current_hash == last_balance_hash:
            return state.current_balance

        balance_text = _match_balance_text(_to_gray(cropped))
        balance_text = _sanitize_balance_text(balance_text)
        if balance_text:
            setattr(state, "_last_balance_hash", current_hash)
        return balance_text
    except:
        return None


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
