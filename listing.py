"""
自动上架子系统
"""
import re
import time

import cv2

import state
from local_switch_account_config import load_listing_target_price
from config import (
    CLICK_1,
    CLICK_2,
    CLICK_JIAOSHI,
    CONFIRM_BTN_POS,
    LIST_INTERVAL,
    LISTING_SCAN_MISS_THRESHOLD,
    LISTING_SKIP_BALANCE_THRESHOLD,
    MAX_LISTING_RETRY,
    MONITOR_TEXT_JIAOSHI,
    MONITOR_TEXT_SHANGJIA,
    MONITOR_TISHI,
    POPUP_REGION,
    POPUP_THRESHOLD,
    PRICE_INPUT_POS,
    SCAN_REGION,
    SIMILARITY_THRESHOLD,
)
from overlay import move_overlay, ui_print, update_score_text
from round_persistence import (
    persist_minimal_item_balance_sync,
    record_daily_listing_success,
    refresh_account_limit_reached_at,
)
from utils import (
    fast_click,
    gc_checkpoint,
    get_clipboard_text,
    get_current_elapsed,
    hotkey,
    press_key,
    safe_get_frame,
    safe_sleep,
    scroll_down,
    type_digits,
)
from vision import (
    compare_region_similarity,
    crop_frame,
    get_balance,
    is_image_present,
    match_item_in_scan,
    read_capacity,
    wait_for_ocr_text,
)

LISTING_TARGET_PRICE = load_listing_target_price()[0]


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


def _force_refresh_balance_for_first_listing_after_switch(camera_obj):
    frame = safe_get_frame(camera_obj)
    if frame is None:
        return None

    # 换号后首次上架要求强制重新识别一次当前余额，不能直接沿用旧缓存。
    state._last_balance_hash = None
    balance_text = get_balance(frame)
    if not balance_text:
        return None

    normalized_balance_text = str(balance_text).strip()
    if not normalized_balance_text:
        return None

    state.current_balance = normalized_balance_text
    state.round_current_balance = normalized_balance_text
    state.last_valid_balance = normalized_balance_text
    if state.overlay_root:
        try:
            state.overlay_root.after(0, update_score_text)
        except Exception:
            pass
    return _parse_balance_text_to_value(normalized_balance_text)


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
        if force_balance_check_after_switch:
            forced_balance_value = _force_refresh_balance_for_first_listing_after_switch(camera_obj)
            if (
                forced_balance_value is not None
                and forced_balance_value > LISTING_SKIP_BALANCE_THRESHOLD
            ):
                _disable_periodic_listing("[上架限制]换后超4亿")
                return

        if _should_skip_listing_by_last_valid_balance():
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
            ui_print("容量解析失败，退出上架。")
            return

        original_current, original_total = capacity_result
        if original_total - original_current <= 0:
            ui_print(f"容量已满（{original_current}/{original_total}），无需上架。")
            return

        remaining = original_total - original_current
        ui_print(f"已上架 {original_current}，还可继续上架 {remaining} 个。")

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

                    expected_current = original_current + listed + 1
                    verified = None
                    for _ in range(5):
                        verify_frame = safe_get_frame(camera_obj)
                        if verify_frame is not None:
                            verify_capacity = read_capacity(verify_frame)
                            if verify_capacity is not None:
                                if verify_capacity[0] >= expected_current:
                                    verified = True
                                    break
                                verified = False
                        safe_sleep(0.15)

                    if verified is True:
                        listed += 1
                        state.total_listed_count += 1
                        state.round_listing_success_count += 1
                        _sync_listing_success()
                        fail_strike = 0
                        ui_print(f"上架验证通过 {listed}/{remaining}")
                    elif verified is False:
                        fail_strike += 1
                        ui_print(f"上架疑似失败（容量未变化），重试 {fail_strike}/{MAX_LISTING_RETRY}")
                    else:
                        listed += 1
                        state.total_listed_count += 1
                        state.round_listing_success_count += 1
                        _sync_listing_success()
                        fail_strike = 0
                        ui_print(f"上架 {listed}/{remaining}（无法验证容量，按成功记）")
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

        ui_print(f"上架流程执行完毕，共上架 {listed} 个。")

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
