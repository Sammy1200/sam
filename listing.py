"""
自动上架子系统
"""
import os
import re
import time

import cv2
import numpy as np

import state
from local_switch_account_config import load_listing_target_price
from config import (
    CLICK_1,
    CLICK_2,
    CLICK_JIAOSHI,
    CONFIRM_BTN_POS,
    LIST_INTERVAL,
    LISTING_ROUND_SUCCESS_LIMIT,
    LISTING_SCAN_MISS_THRESHOLD,
    LISTING_SKIP_BALANCE_THRESHOLD,
    MAX_LISTING_RETRY,
    MONITOR_TEXT_JIAOSHI,
    MONITOR_TEXT_SHANGJIA,
    MONITOR_TISHI,
    TEMPLATE_DIR,
    POPUP_REGION,
    POPUP_THRESHOLD,
    PRICE_INPUT_POS,
    SCAN_REGION,
    SIMILARITY_THRESHOLD,
    LISTING_UNLIST_BUTTON_POS,
    LISTING_UNLIST_CAPACITY_RETRY_COUNT,
    LISTING_UNLIST_CAPACITY_RETRY_INTERVAL,
    LISTING_UNLIST_CONFIRM_REGION,
    LISTING_UNLIST_CONFIRM_MATCH_THRESHOLD,
    LISTING_UNLIST_MAX_LOOP_COUNT,
    LISTING_UNLIST_NEXT_CYCLE_DELAY,
    LISTING_UNLIST_POST_CONFIRM_DELAY,
    LISTING_UNLIST_PRE_ACTION_DELAY,
)
from overlay import move_overlay, toggle_pause, ui_print, update_score_text
from round_persistence import (
    persist_minimal_item_balance_sync,
    record_daily_listing_success,
    refresh_account_limit_reached_at,
)
from utils import (
    async_push_msg,
    fast_click,
    flush_logger_handlers,
    gc_checkpoint,
    get_clipboard_text,
    get_current_elapsed,
    hotkey,
    logger,
    press_key,
    safe_get_frame,
    safe_sleep,
    scroll_down,
    type_digits,
)
from vision import (
    compare_region_similarity,
    crop_frame,
    is_image_present,
    match_item_in_scan,
    recognize_listing_timer_action,
    read_capacity,
    wait_for_ocr_text,
    crop_frame,
)

LISTING_TARGET_PRICE = load_listing_target_price()[0]
_UNLIST_CONFIRM_TEMPLATE = None


def _parse_balance_text_to_value(balance_text):
    try:
        text = str(balance_text or "").strip()
        if not text:
            return None
        match = re.search(r"[\d\.]+", text)
        if not match:
            return None

        num_val = float(match.group())
        if "亿" in text:
            return int(round(num_val * 100000000))
        if "万" in text:
            return int(round(num_val * 10000))
        return int(num_val)
    except:
        return None


def _to_gray_image(image):
    if image is None:
        return None
    if len(image.shape) == 2:
        return image
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _load_unlist_confirm_template():
    global _UNLIST_CONFIRM_TEMPLATE
    if _UNLIST_CONFIRM_TEMPLATE is not None:
        return _UNLIST_CONFIRM_TEMPLATE

    template_path = os.path.join(TEMPLATE_DIR, "queding1.png")
    if not os.path.isfile(template_path):
        return None

    raw = cv2.imdecode(np.fromfile(template_path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if raw is None:
        return None
    _UNLIST_CONFIRM_TEMPLATE = _to_gray_image(raw)
    return _UNLIST_CONFIRM_TEMPLATE


def _find_template_center(frame, monitor, template, threshold):
    if frame is None or template is None:
        return None

    cropped = crop_frame(frame, monitor)
    cropped_gray = _to_gray_image(cropped)
    template_gray = _to_gray_image(template)
    if cropped_gray is None or template_gray is None:
        return None

    template_height, template_width = template_gray.shape[:2]
    if (
        cropped_gray.shape[0] < template_height
        or cropped_gray.shape[1] < template_width
    ):
        return None

    result = cv2.matchTemplate(cropped_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None

    center_x = monitor["left"] + max_loc[0] + template_width // 2
    center_y = monitor["top"] + max_loc[1] + template_height // 2
    return center_x, center_y


def _get_available_listing_slots(capacity_result):
    if not capacity_result:
        return None
    current_count, total_count = capacity_result
    return max(0, int(total_count) - int(current_count))


def _read_capacity_with_retry(camera_obj, retry_count=5, interval_seconds=0.15):
    for _ in range(retry_count):
        frame = safe_get_frame(camera_obj)
        if frame is not None:
            capacity_result = read_capacity(frame)
            if capacity_result is not None:
                return capacity_result
        safe_sleep(interval_seconds)
    return None


def _pause_listing_recovery(detail):
    ui_print("上下架异常", save_log=True)
    logger.error(detail)
    flush_logger_handlers()
    try:
        async_push_msg("【上架】上下架异常", detail)
    except Exception as exc:
        logger.error("上架异常推送失败：%s", exc)
    if not state.IS_PAUSED:
        toggle_pause()
    return {"status": "pause"}


def _click_unlist_confirm(camera_obj):
    confirm_template = _load_unlist_confirm_template()
    if confirm_template is None:
        return False

    safe_sleep(0.08)
    fast_click(LISTING_UNLIST_BUTTON_POS)
    for _ in range(10):
        safe_sleep(0.12)
        frame = safe_get_frame(camera_obj)
        confirm_center = _find_template_center(
            frame,
            LISTING_UNLIST_CONFIRM_REGION,
            confirm_template,
            LISTING_UNLIST_CONFIRM_MATCH_THRESHOLD,
        )
        if confirm_center is not None:
            safe_sleep(0.08)
            fast_click(confirm_center)
            return True
    return False


def _wait_unlist_capacity_change(camera_obj, expected_available):
    safe_sleep(LISTING_UNLIST_POST_CONFIRM_DELAY)

    last_capacity_result = None
    max_attempts = 1 + LISTING_UNLIST_CAPACITY_RETRY_COUNT
    for attempt_index in range(max_attempts):
        if attempt_index > 0:
            ui_print("下架校验重试", save_log=True)
            safe_sleep(LISTING_UNLIST_CAPACITY_RETRY_INTERVAL)
        capacity_result = _read_capacity_with_retry(camera_obj, retry_count=2, interval_seconds=0.08)
        if capacity_result is not None:
            last_capacity_result = capacity_result
        available_slots = _get_available_listing_slots(capacity_result)
        if available_slots == expected_available + 1:
            return {"status": "confirmed", "capacity": capacity_result}
    return {"status": "skipped", "capacity": last_capacity_result}


def _handle_capacity_full_recovery(camera_obj, capacity_result):
    current_capacity = capacity_result
    freed_any_slot = False
    recovery_count = 0

    while True:
        frame = safe_get_frame(camera_obj)
        timer_action = recognize_listing_timer_action(frame) if frame is not None else None
        if timer_action == "keep":
            ui_print("命中46/47", save_log=True)
            if freed_any_slot:
                return {"status": "resume", "capacity": current_capacity}
            return {"status": "skip"}

        if timer_action is None:
            ui_print("时间未确认", save_log=True)

        recovery_count += 1
        if recovery_count > LISTING_UNLIST_MAX_LOOP_COUNT:
            return _pause_listing_recovery("容量满恢复链路反复执行下架，已触发循环保护。")

        available_before = _get_available_listing_slots(current_capacity)
        if available_before is None:
            return _pause_listing_recovery("容量满恢复链路读取可上架数量失败。")

        ui_print("执行下架", save_log=True)
        safe_sleep(LISTING_UNLIST_PRE_ACTION_DELAY)
        if not _click_unlist_confirm(camera_obj):
            return _pause_listing_recovery("未识别到下架确认弹窗，无法继续恢复上架位。")

        capacity_check_result = _wait_unlist_capacity_change(camera_obj, available_before)
        updated_capacity = capacity_check_result.get("capacity")
        if capacity_check_result.get("status") == "skipped":
            ui_print("下架跳过校验", save_log=True)
        if updated_capacity is not None:
            current_capacity = updated_capacity
        freed_any_slot = True
        available_after = _get_available_listing_slots(current_capacity)
        if available_after is None:
            return _pause_listing_recovery("下架成功后读取可上架数量失败。")
        if available_after >= 20:
            ui_print("可上架满20", save_log=True)
            return {"status": "resume", "capacity": current_capacity}
        if capacity_check_result.get("status") == "confirmed":
            safe_sleep(LISTING_UNLIST_NEXT_CYCLE_DELAY)


def _should_skip_listing_by_last_valid_balance():
    last_valid_balance_text = str(state.last_valid_balance or "").strip()
    last_valid_balance_value = _parse_balance_text_to_value(last_valid_balance_text)
    if (
        last_valid_balance_value is not None
        and last_valid_balance_value > LISTING_SKIP_BALANCE_THRESHOLD
    ):
        ui_print("余额超4亿跳上架", save_log=True)
        return True
    return False


def _should_disable_listing_by_round_success_limit():
    if state.round_listing_success_count < LISTING_ROUND_SUCCESS_LIMIT:
        return False
    _disable_periodic_listing(f"[上架限制]本轮上架已达 {LISTING_ROUND_SUCCESS_LIMIT}")
    return True


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
        ui_print("检测到提示弹窗，执行消除。", save_log=True)
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
        type_digits(LISTING_TARGET_PRICE)
        safe_sleep(0.2)
        hotkey(0x11, 0x41)
        safe_sleep(0.1)
        hotkey(0x11, 0x43)
        safe_sleep(0.15)
        clipboard_raw = get_clipboard_text()
        actual = "".join(ch for ch in clipboard_raw if ch.isdigit())
        if actual == LISTING_TARGET_PRICE:
            press_key(0x23)
            return True
        ui_print(f"价格校验失败（{attempt}/3），重试中。")

    press_key(0x1B)
    safe_sleep(0.5)
    return False


def _reset_listing_scan_miss_count():
    if state.listing_scan_miss_count > 0:
        ui_print(
            f"找到上架道具，未找到计数清零（此前 {state.listing_scan_miss_count} 次）。"
        )
    state.listing_scan_miss_count = 0


def _disable_periodic_listing(reason):
    if state.listing_periodic_disabled and state.listing_periodic_disabled_reason == reason:
        return

    state.listing_periodic_disabled = True
    state.listing_periodic_disabled_reason = reason
    state.listing_periodic_skip_logged = False
    ui_print(reason, save_log=True)


def execute_listing_routine(camera_obj, is_periodic=False, force_balance_check_after_switch=False):
    gc_checkpoint()

    resume_timer_after_listing = state.purchase_timer_active
    if resume_timer_after_listing and not state.IS_PAUSED and state.last_resume_time is not None:
        refresh_account_limit_reached_at()
        state.total_running_time += (time.time() - state.last_resume_time)
    state.last_resume_time = None
    state.purchase_timer_active = False
    state.overlay_status = "上架中"
    ui_print("已冻结抢购计时，执行自动上架。")
    move_overlay("+600+0")

    first_popup_checked = False

    def _sync_listing_success():
        """上架成功后立即扣减真实库存并同步网页读取源。"""
        if state.baseline_item_count > 0:
            state.baseline_item_count -= 1
        else:
            state.baseline_item_count = 0
            ui_print("上架成功后库存已为 0，核对真实库存。", save_log=True)

        if state.overlay_root:
            try:
                state.overlay_root.after(0, update_score_text)
            except Exception:
                pass

        record_daily_listing_success()
        sync_result = persist_minimal_item_balance_sync()
        if sync_result.status not in ("success", "skipped"):
            ui_print(f"实时库存同步失败：{sync_result.reason}", save_log=True)

    try:
        if _should_skip_listing_by_last_valid_balance():
            return
        if _should_disable_listing_by_round_success_limit():
            return

        ui_print("开始进入背包并执行上架流程。")
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

        capacity_result = _read_capacity_with_retry(camera_obj)
        if not capacity_result:
            ui_print("容量解析失败，退出上架。")
            return

        total_listed = 0
        current_capacity = capacity_result
        while True:
            original_current, original_total = current_capacity
            remaining = original_total - original_current
            if remaining <= 0:
                ui_print("容量满看时", save_log=True)
                recovery_result = _handle_capacity_full_recovery(camera_obj, current_capacity)
                if recovery_result.get("status") == "resume":
                    current_capacity = recovery_result["capacity"]
                    continue
                return

            ui_print(f"已上架 {original_current}，还可继续上架 {remaining} 个。")

            cycle_listed = 0
            fail_strike = 0
            while cycle_listed < remaining:
                safe_sleep(0.08)
                frame = safe_get_frame(camera_obj)
                if frame is None:
                    continue

                safe_sleep(0.08)
                found, abs_x, abs_y = match_item_in_scan(frame)

                if found:
                    _reset_listing_scan_miss_count()
                    safe_sleep(0.08)
                    fast_click((abs_x, abs_y))
                    safe_sleep(0.5)

                    popup_found = False
                    if state.TEMP_POPUP is not None:
                        for _ in range(15):
                            safe_sleep(0.15)
                            frame_popup = safe_get_frame(camera_obj)
                            if frame_popup is not None and is_image_present(
                                frame_popup,
                                POPUP_REGION,
                                state.TEMP_POPUP,
                                threshold=0.7,
                            ):
                                popup_found = True
                                break
                    else:
                        for _ in range(10):
                            safe_sleep(0.08)
                            frame_popup = safe_get_frame(camera_obj)
                            if frame_popup is not None:
                                similarity = compare_region_similarity(frame, frame_popup, POPUP_REGION)
                                if similarity < POPUP_THRESHOLD:
                                    popup_found = True
                                    break
                            safe_sleep(0.2)

                    if popup_found and input_price_with_verify():
                        safe_sleep(0.08)
                        fast_click(CONFIRM_BTN_POS)

                        if not first_popup_checked:
                            check_and_click_tishi(camera_obj)
                            first_popup_checked = True

                        safe_sleep(0.8)

                        expected_current = original_current + cycle_listed + 1
                        verified = None
                        latest_capacity = None
                        for _ in range(5):
                            verify_frame = safe_get_frame(camera_obj)
                            if verify_frame is not None:
                                verify_capacity = read_capacity(verify_frame)
                                if verify_capacity is not None:
                                    latest_capacity = verify_capacity
                                    if verify_capacity[0] >= expected_current:
                                        verified = True
                                        break
                                    verified = False
                            safe_sleep(0.15)

                        if verified is True:
                            cycle_listed += 1
                            total_listed += 1
                            state.total_listed_count += 1
                            state.round_listing_success_count += 1
                            _sync_listing_success()
                            if latest_capacity is not None:
                                current_capacity = latest_capacity
                            fail_strike = 0
                            ui_print(f"上架验证通过 {cycle_listed}/{remaining}")
                        elif verified is False:
                            fail_strike += 1
                            ui_print(f"上架疑似失败（容量未变化），重试 {fail_strike}/{MAX_LISTING_RETRY}")
                        else:
                            cycle_listed += 1
                            total_listed += 1
                            state.total_listed_count += 1
                            state.round_listing_success_count += 1
                            _sync_listing_success()
                            fail_strike = 0
                            ui_print(f"上架 {cycle_listed}/{remaining}（无法验证容量，按成功记）")
                    else:
                        fail_strike += 1
                        if fail_strike >= MAX_LISTING_RETRY:
                            ui_print("连续失败达到上限，翻页跳过。")
                            before_frame = safe_get_frame(camera_obj)
                            safe_sleep(0.08)
                            scroll_down()
                            safe_sleep(0.3)
                            after_frame = safe_get_frame(camera_obj)
                            if before_frame is not None and after_frame is not None:
                                similarity = compare_region_similarity(before_frame, after_frame, SCAN_REGION)
                                if similarity >= SIMILARITY_THRESHOLD:
                                    _disable_periodic_listing("[上架限制] 翻页到底，本轮停止上架。")
                                    ui_print("[翻页] 相似度过高，确认已经到底，结束上架。")
                                    break
                            fail_strike = 0
                else:
                    fail_strike = 0
                    ui_print("[扫描] 未找到道具，继续翻页。")
                    before_frame = frame
                    safe_sleep(0.08)
                    scroll_down()
                    safe_sleep(0.3)
                    after_frame = safe_get_frame(camera_obj)
                    if after_frame is not None:
                        similarity = compare_region_similarity(before_frame, after_frame, SCAN_REGION)
                        if similarity < SIMILARITY_THRESHOLD:
                            state.listing_scan_miss_count += 1
                            ui_print(
                                f"[翻页] 翻页成功，继续扫描（连续未找到 {state.listing_scan_miss_count}/{LISTING_SCAN_MISS_THRESHOLD}）。"
                            )
                            if state.listing_scan_miss_count >= LISTING_SCAN_MISS_THRESHOLD:
                                _disable_periodic_listing(
                                    f"[上架限制]{LISTING_SCAN_MISS_THRESHOLD} 次未找到道具，本轮停止上架。"
                                )
                                break
                            continue
                        _disable_periodic_listing("[上架限制] 翻页到底，本轮停止上架。")
                        ui_print("[翻页] 相似度过高，确认已经到底，结束上架。")
                        break

            if state.listing_periodic_disabled:
                break
            if cycle_listed < remaining:
                break
            if state.baseline_item_count <= 0:
                break

            latest_capacity = _read_capacity_with_retry(camera_obj, retry_count=3, interval_seconds=0.08)
            if latest_capacity is None:
                break
            current_capacity = latest_capacity
            if _get_available_listing_slots(latest_capacity) > 0:
                continue

            ui_print("容量满看时", save_log=True)
            recovery_result = _handle_capacity_full_recovery(camera_obj, latest_capacity)
            if recovery_result.get("status") == "resume":
                current_capacity = recovery_result["capacity"]
                continue
            break

        ui_print(f"上架流程执行完毕，共上架 {total_listed} 个。")

    except Exception as exc:
        ui_print(f"上架过程出现意外报错：{exc}")
    finally:
        time.sleep(0.5)
        ui_print("返回交易行继续抢购。")
        press_key(0x1B)
        time.sleep(0.5)
        state._last_balance_hash = None
        move_overlay("+20+20")
        state.purchase_timer_active = resume_timer_after_listing
        if resume_timer_after_listing and not state.IS_PAUSED:
            state.last_resume_time = time.time()
        else:
            state.last_resume_time = None
        state.last_list_time = get_current_elapsed()
        state.overlay_status = "等待抢购时间" if state.account_is_waiting else "抢购中"
        ui_print("系统已恢复抢购计时。")


def check_trigger_listing(camera):
    elapsed = get_current_elapsed()
    if state.listing_periodic_disabled:
        if not state.listing_periodic_skip_logged:
            reason = state.listing_periodic_disabled_reason or "当前轮次已停用 10 分钟自动上架。"
            ui_print("[上架限制]已跳过本轮后续动上架", save_log=True)
            state.listing_periodic_skip_logged = True
        return True
    if elapsed - state.last_list_time >= LIST_INTERVAL:
        execute_listing_routine(camera, is_periodic=True)
        if state.account_round_writeback_failed:
            return False
    return True
