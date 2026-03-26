"""
截图裁剪、模板匹配、OCR 读取、余额识别、容量识别
"""
import cv2
import numpy as np
import re
import time
import state
from config import (
    MONITOR_PRICE, MONITOR_CAPACITY, MONITOR_BALANCE,
    UPSCALE, STANDARD_W, STANDARD_H, TEMPLATE_DIR
)
from utils import safe_sleep, safe_get_frame
import os


def crop_frame(frame, monitor):
    t, l = monitor["top"], monitor["left"]
    return frame[t:t + monitor["height"], l:l + monitor["width"]]


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
        target_bgr = [110, 237, 255]
        color_diff = (abs(int(pixel_color[0]) - target_bgr[0]) +
                      abs(int(pixel_color[1]) - target_bgr[1]) +
                      abs(int(pixel_color[2]) - target_bgr[2]))
        if color_diff > 45:
            return None
        cropped = crop_frame(frame, MONITOR_PRICE)
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        detected = []
        for num, temp in templates.items():
            res = cv2.matchTemplate(gray, temp, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= 0.75)
            for pt in zip(*loc[::-1]):
                detected.append({'x': pt[0], 'num': num, 'score': res[pt[1], pt[0]]})
        if not detected:
            return None
        detected.sort(key=lambda x: x['x'])
        final_list = []
        last = detected[0]
        for i in range(1, len(detected)):
            if detected[i]['x'] - last['x'] < 5:
                if detected[i]['score'] > last['score']:
                    last = detected[i]
            else:
                final_list.append(last)
                last = detected[i]
        final_list.append(last)
        res_str = "".join([i['num'] for i in final_list])
        return int(res_str) if len(res_str) >= 6 else None
    except:
        return None


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

def get_balance(frame):
    try:
        if not state.ocr_engine:
            return None
        cropped = crop_frame(frame, MONITOR_BALANCE)
        tiny = cv2.resize(cropped, (8, 8))
        current_hash = tiny.tobytes()
        if state._last_balance_hash is not None and current_hash == state._last_balance_hash:
            return state.current_balance
        gray_img = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
        resized = cv2.resize(gray_img, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        sharpened = cv2.filter2D(resized, -1, kernel)
        padded = cv2.copyMakeBorder(sharpened, 30, 30, 30, 30, cv2.BORDER_REPLICATE)
        final_img = cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)
        result, _ = state.ocr_engine(final_img)
        if result and len(result) > 0:
            res_str = "".join([item[1] for item in result])
            if res_str:
                if any(u in res_str for u in ['万', '亿']):
                    res_str = res_str.replace("。", ".").replace(",", ".")
                else:
                    res_str = res_str.replace("。", "").replace(",", "").replace(".", "")
                res_str = re.sub(
                    r'[^\d\.万亿]', '',
                    res_str.replace(" ", "").replace("·", ".").replace("'", ".").replace("`", "."))
                if res_str:
                    state._last_balance_hash = current_hash
            return res_str if res_str else None
        return None
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
