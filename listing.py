"""
自动上架子系统
"""
import time
import cv2
import state
from config import (
    MONITOR_TISHI, MONITOR_TEXT_SHANGJIA, MONITOR_TEXT_JIAOSHI,
    CLICK_1, CLICK_2, CLICK_JIAOSHI, PRICE_INPUT_POS, CONFIRM_BTN_POS,
    TARGET_PRICE, POPUP_REGION, SCAN_REGION, SIMILARITY_THRESHOLD,
    POST_LIST_WAIT, MAX_LISTING_RETRY, POPUP_THRESHOLD, LIST_INTERVAL
)
from utils import (
    safe_sleep, safe_get_frame, gc_checkpoint, fast_click,
    press_key, hotkey, type_digits, scroll_down, get_clipboard_text,
    get_current_elapsed
)
from vision import (
    crop_frame, is_image_present, wait_for_ocr_text, read_capacity,
    compare_region_similarity, match_item_in_scan
)
from overlay import ui_print, move_overlay, update_score_text


def check_and_click_tishi(camera_obj):
    safe_sleep(0.6)
    frame = safe_get_frame(camera_obj)
    if frame is None:
        return
    cropped = crop_frame(frame, MONITOR_TISHI)
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGRA2GRAY)
    res = cv2.matchTemplate(gray, state.TEMP_TISHI, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val > 0.7:
        th, tw = state.TEMP_TISHI.shape[:2]
        abs_x = MONITOR_TISHI["left"] + max_loc[0] + tw // 2
        abs_y = MONITOR_TISHI["top"] + max_loc[1] + th // 2
        ui_print("🚨 检测到首次上架提示弹窗，执行消除...", save_log=True)
        safe_sleep(0.08)
        fast_click((abs_x, abs_y))
        safe_sleep(0.5)


def input_price_with_verify():
    safe_sleep(0.08)
    for attempt in range(1, 4):
        safe_sleep(0.08)
        fast_click(PRICE_INPUT_POS)
        safe_sleep(0.15)
        hotkey(0x11, 0x41)
        type_digits(TARGET_PRICE)
        safe_sleep(0.2)
        hotkey(0x11, 0x41)
        safe_sleep(0.1)
        hotkey(0x11, 0x43)
        safe_sleep(0.15)
        clipboard_raw = get_clipboard_text()
        actual = ''.join(c for c in clipboard_raw if c.isdigit())
        if actual == TARGET_PRICE:
            press_key(0x23)
            return True
        ui_print(f"  ❌ 价格验证失败({attempt}/3)，重试...")
    press_key(0x1B)
    safe_sleep(0.5)
    return False


def execute_listing_routine(camera_obj):
    gc_checkpoint()

    if not state.IS_PAUSED and state.last_resume_time is not None:
        state.total_running_time += (time.time() - state.last_resume_time)
        state.last_resume_time = None
    ui_print("⏸️ [系统] 抢购计时已冻结，正在执行自动化上架...")
    move_overlay("+600+0")

    first_popup_checked = False

    try:
        ui_print("👉 [步骤] 开始寻路进入背包...")
        safe_sleep(0.08)
        fast_click(CLICK_1)
        safe_sleep(0.08)
        if not wait_for_ocr_text(camera_obj, MONITOR_TEXT_SHANGJIA, ["上架", "数量"]):
            return
        safe_sleep(0.08)
        fast_click(CLICK_2)
        safe_sleep(0.08)
        if not wait_for_ocr_text(camera_obj, MONITOR_TEXT_JIAOSHI, ["角石"]):
            return
        safe_sleep(0.08)
        fast_click(CLICK_JIAOSHI)
        safe_sleep(0.5)

        capacity_result = None
        for _ in range(5):
            safe_sleep(0.08)
            frame = safe_get_frame(camera_obj)
            if frame is not None:
                capacity_result = read_capacity(frame)
                if capacity_result is not None:
                    break
            safe_sleep(0.1)

        if not capacity_result:
            ui_print("❌ 额度解析失败，退出上架。")
            return

        original_current, original_total = capacity_result
        if original_total - original_current <= 0:
            ui_print(f"⛔ 容量已满 ({original_current}/{original_total})，无需上架。")
            return

        remaining = original_total - original_current
        ui_print(f"📊 额度充足: 已上架 {original_current}，还可以上架 {remaining} 个。")

        listed = 0
        fail_strike = 0
        while listed < remaining:
            safe_sleep(0.08)
            frame = safe_get_frame(camera_obj)
            if frame is None:
                continue

            safe_sleep(0.08)
            found, abs_x, abs_y = match_item_in_scan(frame)

            if found:
                safe_sleep(0.08)
                fast_click((abs_x, abs_y))
                safe_sleep(0.5)

                popup_found = False
                if state.TEMP_POPUP is not None:
                    for _ in range(15):
                        safe_sleep(0.15)
                        f2 = safe_get_frame(camera_obj)
                        if f2 is not None and is_image_present(f2, POPUP_REGION, state.TEMP_POPUP, threshold=0.7):
                            popup_found = True
                            break
                else:
                    for _ in range(10):
                        safe_sleep(0.08)
                        f2 = safe_get_frame(camera_obj)
                        if f2 is not None:
                            sim = compare_region_similarity(frame, f2, POPUP_REGION)
                            if sim < POPUP_THRESHOLD:
                                popup_found = True
                                break
                        safe_sleep(0.2)

                if popup_found and input_price_with_verify():
                    safe_sleep(0.08)
                    fast_click(CONFIRM_BTN_POS)

                    if not first_popup_checked:
                        check_and_click_tishi(camera_obj)
                        first_popup_checked = True

                    safe_sleep(POST_LIST_WAIT)

                    expected_current = original_current + listed + 1
                    verified = None
                    for _ in range(5):
                        vf = safe_get_frame(camera_obj)
                        if vf is not None:
                            vc = read_capacity(vf)
                            if vc is not None:
                                if vc[0] >= expected_current:
                                    verified = True
                                    break
                                else:
                                    verified = False
                        safe_sleep(0.15)

                    if verified is True:
                        listed += 1
                        state.total_listed_count += 1
                        fail_strike = 0
                        ui_print(f"📦 ✅ 上架验证通过 {listed}/{remaining}")
                    elif verified is False:
                        fail_strike += 1
                        ui_print(f"📦 ❌ 上架疑似失败 (容量未变化), 重试 {fail_strike}/{MAX_LISTING_RETRY}")
                    else:
                        listed += 1
                        state.total_listed_count += 1
                        fail_strike = 0
                        ui_print(f"📦 ⚠️ 上架 {listed}/{remaining} (无法验证容量，按成功计)")
                else:
                    fail_strike += 1
                    if fail_strike >= MAX_LISTING_RETRY:
                        ui_print("🔄 连续失败达上限，翻页跳过")
                        before_frame = safe_get_frame(camera_obj)
                        safe_sleep(0.08)
                        scroll_down()
                        safe_sleep(0.5)
                        after_frame = safe_get_frame(camera_obj)
                        if before_frame is not None and after_frame is not None:
                            sim = compare_region_similarity(before_frame, after_frame, SCAN_REGION)
                            if sim >= SIMILARITY_THRESHOLD:
                                ui_print("[翻页] 截图对比相似度极高，确认已到底，结束上架！")
                                break
                        fail_strike = 0
            else:
                fail_strike = 0
                ui_print("[扫描] 未找到道具，翻页...")
                before_frame = frame
                safe_sleep(0.08)
                scroll_down()
                safe_sleep(0.5)
                after_frame = safe_get_frame(camera_obj)
                if after_frame is not None:
                    sim = compare_region_similarity(before_frame, after_frame, SCAN_REGION)
                    if sim < SIMILARITY_THRESHOLD:
                        ui_print("[翻页] 翻页成功，继续扫描")
                        continue
                    else:
                        ui_print("[翻页] 截图对比相似度极高，确认已到底，结束上架！")
                        break

        ui_print(f"✅ 上架流水线执行完毕，共上架 {listed} 个。")

    except Exception as e:
        ui_print(f"❌ 上架过程出现意外报错: {e}")
    finally:
        time.sleep(1.0)
        ui_print("🔙 退出背包，按 ESC 返回交易行开启抢购！")
        press_key(0x1B)
        time.sleep(1.0)
        state._last_balance_hash = None
        move_overlay("+20+20")
        if not state.IS_PAUSED:
            state.last_resume_time = time.time()
        state.last_list_time = get_current_elapsed()
        ui_print("▶️ [系统] 抢购计时已恢复！")


def check_trigger_listing(camera):
    elapsed = get_current_elapsed()
    if elapsed - state.last_list_time >= LIST_INTERVAL:
        execute_listing_routine(camera)
