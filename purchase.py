"""
抢购主循环 + 余额/限制检测 + 推送
"""
import gc
import re
import time

import state
from accessory_purchase import run_accessory_purchase_loop
from config import (
    ACCOUNT_MAX_PURCHASE_SECONDS,
    BALANCE_INSUFFICIENT_THRESHOLD,
    ACCOUNT_RUNTIME_CONTINUE_BALANCE_THRESHOLD,
    ACCOUNT_LIMIT_THRESHOLD,
    BUY_POS,
    CONFIRM_DELAY,
    CONFIRM_POS,
    DIYICI_CLICK_POS,
    EQUIPMENT_BUY_GUARD_POS,
    EQUIPMENT_BUY_GUARD_RGB,
    EQUIPMENT_LOOP_RETRY_WAIT_SECONDS,
    EQUIPMENT_POST_SAVE_GUARD_POS,
    EQUIPMENT_POST_SAVE_GUARD_RGB,
    EQUIPMENT_POST_SAVE_GUARD_TIMEOUT_SECONDS,
    EQUIPMENT_POST_SAVE_PRICE_SCAN_SECONDS,
    EQUIPMENT_SUCCESS_TO_REENTER_DELAY_SECONDS,
    EXIT_DELAY,
    FIX_SHOP_POS1,
    FIX_SHOP_POS2,
    FRAME_MAX_AGE,
    LISTING_PAGE_VERIFY_MATCH_THRESHOLD,
    LISTING_PAGE_VERIFY_REGION,
    MISMATCH_EXIT_DELAY,
    MONITOR_DIYICI,
    MONITOR_GOUMAI,
    MONITOR_JIAOYIHANG,
    MONITOR_MEIHUO,
    MONITOR_SHOP,
    MONITOR_SUCCESS,
    REFRESH_POS,
    STUCK_PUSH_INTERVAL,
    SUCCESS_CONFIRM_POS,
)
from overlay import toggle_pause, ui_print, update_score_text
from round_persistence import (
    ensure_active_runtime_window_state,
    mature_stone_unlocks_for_current_account,
    persist_account_limit_reached_if_needed,
    persist_temporary_account_snapshot,
    persist_minimal_item_balance_sync,
    record_stone_purchase_success_for_current_account,
    record_daily_purchase_fail,
    record_daily_purchase_success,
)
from switch import (
    prepare_equipment_detail_and_filter_from_current_scene,
    reenter_equipment_detail_and_filter_via_gumu,
    refresh_equipment_filter_from_detail,
    is_at_gumu,
    navigate_to_trade,
    refresh_latest_balance_route,
    try_return_to_gumu,
)
from utils import (
    async_push_msg as shared_async_push_msg,
    click_exit,
    fast_click,
    gc_checkpoint,
    get_current_elapsed,
    get_push_machine_label,
    logger,
    precise_sleep,
    safe_imread,
    safe_get_frame,
    smart_wait,
)
from vision import get_balance_recognition, get_equipment_price_decision, get_price_decision, is_image_present


_LISTING_PAGE_TEMPLATE = None


def _load_listing_page_template():
    global _LISTING_PAGE_TEMPLATE
    if _LISTING_PAGE_TEMPLATE is None:
        _LISTING_PAGE_TEMPLATE = safe_imread(("logo", "shangjia", "shangjiaye1.png"), 0)
    return _LISTING_PAGE_TEMPLATE


def _is_listing_page(frame):
    listing_page_template = _load_listing_page_template()
    if listing_page_template is None:
        return False
    return is_image_present(
        frame,
        LISTING_PAGE_VERIFY_REGION,
        listing_page_template,
        threshold=LISTING_PAGE_VERIFY_MATCH_THRESHOLD,
    )


def async_push_msg(title, content):
    shared_async_push_msg(title, content)


def _refresh_live_round_score():
    if state.overlay_root:
        try:
            state.overlay_root.after(0, update_score_text)
        except:
            pass


def _sync_temporary_snapshot(reason, trigger_remote_snapshot=False):
    if not state.temporary_purchase_mode:
        return
    persist_temporary_account_snapshot(
        reason,
        trigger_remote_snapshot=trigger_remote_snapshot,
    )


def clear_live_listing_count_for_account_switch(reason):
    """启动页上架模式下号成功后，立刻清空上架成功显示口径。"""
    previous_listing_success = int(state.round_listing_success_count)
    state.total_listed_count = 0
    state.round_listing_success_count = 0
    print(f"[清零] {reason}，上架成功已清零。原值={previous_listing_success}")
    logger.info("[清零] %s，上架成功已清零。原值=%s", reason, previous_listing_success)
    _refresh_live_round_score()


def clear_live_round_triplet_for_account_switch(reason):
    """正常模式命中切号状态时，立刻清空当前账号三项显示口径。"""
    previous_purchase_success = int(state.round_purchase_success_count)
    previous_listing_success = int(state.round_listing_success_count)
    previous_purchase_fail = int(state.round_purchase_fail_count)
    state.success_count = 0
    state.total_listed_count = 0
    state.fail_count = 0
    state.round_purchase_success_count = 0
    state.round_listing_success_count = 0
    state.round_purchase_fail_count = 0
    print(
        f"[清零] {reason}，三项已清零。"
        f"抢购成功={previous_purchase_success}，上架成功={previous_listing_success}，抢购失败={previous_purchase_fail}"
    )
    logger.info(
        "[清零] %s，三项已清零。抢购成功=%s 上架成功=%s 抢购失败=%s",
        reason,
        previous_purchase_success,
        previous_listing_success,
        previous_purchase_fail,
    )
    _refresh_live_round_score()


def reset_purchase_counters(reason):
    """换号或上架结束后清零会跨账号残留的计数器。"""
    counters_to_reset = (
        ("fail_count", "失败计数"),
        ("limit_count", "限制计数"),
        ("unknown_page_count", "未知页面计数"),
    )

    for counter_name, counter_label in counters_to_reset:
        setattr(state, counter_name, 0)
        print(f"[重置] {reason}，{counter_label}已清零。")

    _refresh_live_round_score()


def _update_balance_state_from_recognition(recognition):
    recognized_balance_text = str(recognition.get("text") or "").strip()
    recognized_balance_confirmed = bool(recognition.get("confirmed")) and bool(recognized_balance_text)

    previous_confirmed_balance_text = str(state.last_valid_balance or "").strip()
    previous_confirmed_balance_value = parse_balance_text_to_value(previous_confirmed_balance_text)
    recognized_balance_value = parse_balance_text_to_value(recognized_balance_text)

    effective_balance_text = previous_confirmed_balance_text
    effective_balance_value = previous_confirmed_balance_value
    balance_display_mode = "沿" if previous_confirmed_balance_text else ""

    if recognized_balance_confirmed:
        effective_balance_text = recognized_balance_text
        effective_balance_value = recognized_balance_value
        balance_display_mode = "新"
        if effective_balance_value is not None:
            state.last_valid_balance = effective_balance_text
    elif previous_confirmed_balance_text:
        effective_balance_text = previous_confirmed_balance_text
        effective_balance_value = previous_confirmed_balance_value
        balance_display_mode = "沿"
    else:
        effective_balance_text = str(state.current_balance or "").strip()
        effective_balance_value = None
        balance_display_mode = "待确认"

    state.balance_display_mode = balance_display_mode
    if effective_balance_text:
        state.current_balance = effective_balance_text
        state.round_current_balance = effective_balance_text
    elif balance_display_mode == "待确认":
        state.round_current_balance = ""
    if state.overlay_root:
        state.overlay_root.after(0, update_score_text)

    return {
        "effective_text": effective_balance_text,
        "effective_value": effective_balance_value,
    }


def _finalize_balance_insufficient(balance_text, send_push=True):
    balance_text = str(balance_text or "").strip()
    state.account_round_end_status = "余额不足"
    state.overlay_status = "余额不足"
    ui_print(f"余额不足，当前余额：{balance_text}，准备自动换号", save_log=True)
    print(f"[余额不足] 当前余额：{balance_text}，已触发自动换号")
    if send_push:
        async_push_msg("【余额不足】准备换号换区", f"当前余额：{balance_text}，已触发自动换号。")
    if not state.temporary_purchase_mode:
        clear_live_round_triplet_for_account_switch("余额不足触发换号前")
    else:
        _sync_temporary_snapshot("临时模式余额不足", trigger_remote_snapshot=True)
    state.need_switch_server = True
    return False


def recognize_latest_balance_at_trade(camera):
    """等待交易行并做一次确认态余额识别；失败返回 None。"""
    start_time = time.time()
    while time.time() - start_time < 1.4:
        if state.IS_PAUSED:
            return None

        frame = safe_get_frame(camera)
        if frame is None:
            time.sleep(0.05)
            continue

        if not is_image_present(frame, MONITOR_JIAOYIHANG, state.temp_jiaoyi, threshold=0.7):
            time.sleep(0.05)
            continue

        recognition = get_balance_recognition(frame)
        recognized_balance_text = str(recognition.get("text") or "").strip()
        recognized_balance_confirmed = bool(recognition.get("confirmed")) and bool(recognized_balance_text)
        if not recognized_balance_confirmed:
            time.sleep(0.05)
            continue

        recognized_balance_value = parse_balance_text_to_value(recognized_balance_text)
        if recognized_balance_value is None:
            time.sleep(0.05)
            continue

        state.balance_display_mode = "新"
        state.current_balance = recognized_balance_text
        state.last_valid_balance = recognized_balance_text
        state.round_current_balance = recognized_balance_text
        if state.overlay_root:
            state.overlay_root.after(0, update_score_text)
        return {"text": recognized_balance_text, "value": recognized_balance_value}

    return None


def check_balance_limit(frame, camera=None, try_refresh_on_low=False):
    """识别余额；可选在余额不足时先补金币再决定是否换号。"""
    balance_info = _update_balance_state_from_recognition(get_balance_recognition(frame))
    effective_balance_text = balance_info["effective_text"]
    effective_balance_value = balance_info["effective_value"]

    try:
        if effective_balance_value is None:
            return True
        if effective_balance_value < BALANCE_INSUFFICIENT_THRESHOLD:
            if try_refresh_on_low and camera is not None:
                refresh_result = refresh_latest_balance_route(camera)
                if refresh_result["status"] == "success":
                    refreshed_balance = recognize_latest_balance_at_trade(camera)
                    if refreshed_balance is not None:
                        if refreshed_balance["value"] >= BALANCE_INSUFFICIENT_THRESHOLD:
                            state.overlay_status = "抢购中"
                            ui_print(f"补领金币后余额恢复：{refreshed_balance['text']}", save_log=True)
                            return True
                        return _finalize_balance_insufficient(refreshed_balance["text"], send_push=False)
                return _finalize_balance_insufficient(
                    effective_balance_text,
                    send_push=False,
                )
    except:
        pass

    return True


def get_latest_runtime_balance_text():
    for balance_text in (state.current_balance, state.last_valid_balance, state.round_current_balance):
        text = str(balance_text or "").strip()
        if text and not text.startswith("获取中"):
            return text
    return ""


def parse_balance_text_to_value(balance_text):
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


def wait_and_recognize_balance(wait_time, camera, start_total=None):
    """等待回到交易行，并在此阶段检查余额是否不足。"""
    gc_checkpoint()
    start_total = start_total or time.time()
    while time.time() - start_total < 1.4:
        if state.IS_PAUSED:
            return False

        frame = safe_get_frame(camera)
        if frame is not None:
            if is_image_present(frame, MONITOR_JIAOYIHANG, state.temp_jiaoyi, threshold=0.7):
                if not check_balance_limit(frame, camera=camera, try_refresh_on_low=True):
                    return False
                break

        time.sleep(0.05)

    elapsed = time.time() - start_total
    remaining = wait_time - elapsed
    if remaining > 0:
        wait_result = smart_wait(remaining)
        if wait_result:
            _sync_temporary_snapshot("临时模式余额刷新")
        return wait_result
    _sync_temporary_snapshot("临时模式余额刷新")
    return True


def _build_brutal_end_summary(reason, balance_text=None):
    machine_label = get_push_machine_label()
    latest_balance_text = str(balance_text or get_latest_runtime_balance_text() or "").strip() or "未识别"
    success_count = int(state.round_purchase_success_count)
    fail_count = int(state.round_purchase_fail_count)
    return (
        f"机器：{machine_label}\n"
        f"结束原因：{reason}\n"
        f"抢购总道具数量：{success_count}\n"
        f"抢购成功次数：{success_count}\n"
        f"抢购失败次数：{fail_count}\n"
        f"当前余额：{latest_balance_text}"
    )


def _recover_brutal_shop_from_trade_page():
    ui_print("店铺异常", is_replace=True)
    fast_click(FIX_SHOP_POS1)
    precise_sleep(1.0)
    fast_click(FIX_SHOP_POS2)


def _check_brutal_balance_limit(frame, camera=None, finish_callback=None):
    balance_info = _update_balance_state_from_recognition(get_balance_recognition(frame))
    effective_balance_text = balance_info["effective_text"]
    effective_balance_value = balance_info["effective_value"]

    if effective_balance_value is None:
        return True
    if effective_balance_value >= BALANCE_INSUFFICIENT_THRESHOLD:
        return True

    final_balance_text = effective_balance_text
    if camera is not None:
        refresh_result = refresh_latest_balance_route(camera)
        if refresh_result["status"] == "success":
            refreshed_balance = recognize_latest_balance_at_trade(camera)
            if refreshed_balance is not None:
                final_balance_text = refreshed_balance["text"]
                if refreshed_balance["value"] >= BALANCE_INSUFFICIENT_THRESHOLD:
                    state.overlay_status = "暴力抢购"
                    ui_print("余额恢复", save_log=True)
                    return True

    state.account_round_end_status = "余额不足"
    state.overlay_status = "余额不足"
    state.need_switch_server = False
    ui_print("余额不足", save_log=True)
    if finish_callback is not None:
        finish_callback("余额不足", final_balance_text)
    return False


def _wait_trade_without_balance(wait_time, camera, finish_callback=None):
    """暴力模式：等待回到交易行并识别余额，不写库、不换号。"""
    gc_checkpoint()
    start_total = time.time()
    while time.time() - start_total < 1.4:
        if state.IS_PAUSED:
            return False

        frame = safe_get_frame(camera)
        if frame is not None and is_image_present(frame, MONITOR_JIAOYIHANG, state.temp_jiaoyi, threshold=0.7):
            if not _check_brutal_balance_limit(frame, camera=camera, finish_callback=finish_callback):
                return False
            break
        time.sleep(0.05)

    elapsed = time.time() - start_total
    remaining = wait_time - elapsed
    if remaining > 0:
        return smart_wait(remaining)
    return True


def _check_brutal_purchase_limit(finish_callback=None):
    if not getattr(state, "brutal_purchase_limit_enabled", False):
        return False
    limit = int(getattr(state, "brutal_purchase_limit", 0) or 0)
    if limit <= 0:
        return False
    if int(state.round_purchase_success_count) < limit:
        return False

    ui_print(f"暴力上限{limit}", save_log=True)
    state.overlay_status = "暴力暂停"
    state.need_switch_server = False
    if finish_callback is not None:
        finish_callback("抢购上限")
    if not state.IS_PAUSED:
        toggle_pause()
    return True


def _equipment_pause_for_manual(reason):
    state.overlay_status = "未知异常"
    state.need_switch_server = False
    if not state.account_round_end_status:
        state.account_round_end_status = "未知异常"
    ui_print(reason, save_log=True)
    logger.error("[装备抢购] %s，已暂停等待人工处理。", reason)
    if not state.IS_PAUSED:
        toggle_pause()


def _equipment_refresh_filter_or_reenter(camera):
    if refresh_equipment_filter_from_detail(camera):
        return True
    logger.warning("[装备抢购] 详情页刷新筛选失败，尝试重新进入装备详情页。")
    return prepare_equipment_detail_and_filter_from_current_scene(camera)


def _equipment_click_purchase_buttons():
    buy_click_end_time = time.perf_counter() + 0.02
    while time.perf_counter() < buy_click_end_time:
        fast_click(BUY_POS)
        precise_sleep(0.002)
    precise_sleep(CONFIRM_DELAY)
    confirm_click_end_time = time.perf_counter() + 0.05
    while time.perf_counter() < confirm_click_end_time:
        fast_click(CONFIRM_POS)
        precise_sleep(0.005)


def _get_frame_rgb(frame, pos):
    if frame is None:
        return None
    x, y = pos
    if y < 0 or x < 0 or y >= frame.shape[0] or x >= frame.shape[1]:
        return None
    b, g, r = (int(value) for value in frame[y, x][:3])
    return r, g, b


def _get_equipment_buy_guard_rgb(frame):
    return _get_frame_rgb(frame, EQUIPMENT_BUY_GUARD_POS)


def _is_equipment_buy_guard_ready(frame):
    return _get_equipment_buy_guard_rgb(frame) == tuple(int(value) for value in EQUIPMENT_BUY_GUARD_RGB)


def _clear_price_decision_cache():
    state.price_decision_cache_bytes = None
    state.price_decision_cache_decision = None
    state.price_decision_cache_value = None
    state.price_decision_cache_text = None
    state.price_decision_cache_source = None


def _scan_equipment_post_save_price(camera, templates):
    guard_target = tuple(int(value) for value in EQUIPMENT_POST_SAVE_GUARD_RGB)
    guard_deadline = time.perf_counter() + EQUIPMENT_POST_SAVE_GUARD_TIMEOUT_SECONDS
    last_guard_rgb = None
    _clear_price_decision_cache()

    while time.perf_counter() < guard_deadline:
        frame = safe_get_frame(camera)
        if frame is None:
            continue

        guard_rgb = _get_frame_rgb(frame, EQUIPMENT_POST_SAVE_GUARD_POS)
        last_guard_rgb = guard_rgb
        if guard_rgb != guard_target:
            continue

        logger.info("[装备抢购] 保存后守卫命中：guard_rgb=%s", guard_rgb)
        price_deadline = time.perf_counter() + EQUIPMENT_POST_SAVE_PRICE_SCAN_SECONDS
        while time.perf_counter() < price_deadline:
            price_frame = safe_get_frame(camera)
            if price_frame is None:
                continue
            price_guard_rgb = _get_frame_rgb(price_frame, EQUIPMENT_POST_SAVE_GUARD_POS)
            _clear_price_decision_cache()
            price_action, price_value, price_text, _price_source = get_equipment_price_decision(price_frame, templates)
            if price_action == "accept_skip_item_click":
                price = price_text if price_value is not None else "--"
                return "matched", price, price_frame, price_guard_rgb

        logger.info("[装备抢购] 守卫命中后价格连识别未命中：last_guard_rgb=%s", last_guard_rgb)
        return "no_price", None, None, last_guard_rgb

    logger.info("[装备抢购] 保存后守卫超时：last_guard_rgb=%s", last_guard_rgb)
    return "guard_timeout", None, None, last_guard_rgb

def _handle_equipment_retry(camera, reason):
    ui_print(reason, is_replace=True, save_log=True, show_console=False)
    if not _equipment_refresh_filter_or_reenter(camera):
        _equipment_pause_for_manual("装备刷新失败")
        return False
    _clear_price_decision_cache()
    return True


def _handle_equipment_success(camera):
    stone_inventory_result = record_stone_purchase_success_for_current_account()
    if stone_inventory_result.status not in ("success", "skipped"):
        logger.warning("[装备抢购] 抢购成功后库存写入失败：%s", stone_inventory_result.reason)
        ui_print("库存写入失败", save_log=True)
        if not state.IS_PAUSED:
            toggle_pause()
        return False

    sync_result = persist_minimal_item_balance_sync()
    if sync_result.status not in ("success", "skipped"):
        ui_print(f"库存同步失败：{sync_result.reason}", save_log=True)

    if not prepare_equipment_detail_and_filter_from_current_scene(camera):
        _equipment_pause_for_manual("装备重进失败")
        return False
    return True


def run_equipment_purchase_loop(camera, templates, temp_success, temp_meihuo):
    """装备抢购模式：只用第二价格区，无颜色守卫，跳过商品点击。"""
    state.equipment_purchase_mode = True
    state.listing_enabled = False
    state.listing_disabled_for_session = True
    state.overlay_status = "装备抢购中"
    state.purchase_timer_active = True
    if not state.IS_PAUSED:
        state.last_resume_time = time.time()
    else:
        state.last_resume_time = None
    ensure_active_runtime_window_state()
    mature_stone_unlocks_for_current_account("装备抢购开始前")

    last_runtime_state_check = 0.0
    last_frame = None
    last_frame_time = time.time()

    def clear_equipment_frame_cache():
        nonlocal last_frame, last_frame_time
        last_frame = None
        last_frame_time = 0.0
        _clear_price_decision_cache()

    def handle_equipment_price_match(price, frame, guard_rgb=None):
        if guard_rgb is None:
            guard_rgb = _get_equipment_buy_guard_rgb(frame)
        _equipment_click_purchase_buttons()
        logger.info("[装备抢购] 价格命中已执行购买确认：price=%s guard_rgb=%s", price, guard_rgb)
        time.sleep(0.6)

        frame_after = safe_get_frame(camera)
        purchase_succeeded = frame_after is not None and is_image_present(frame_after, MONITOR_SUCCESS, temp_success)
        if purchase_succeeded:
            state.success_count += 1
            state.round_purchase_success_count += 1
            record_daily_purchase_success()
            if state.overlay_root:
                state.overlay_root.after(0, update_score_text)
            ui_print(f"装备抢购成功：{price}", save_log=True, show_console=False)
            precise_sleep(0.15)
            fast_click(SUCCESS_CONFIRM_POS)
            precise_sleep(0.15)
            fast_click(SUCCESS_CONFIRM_POS)
            time.sleep(EQUIPMENT_SUCCESS_TO_REENTER_DELAY_SECONDS)
            if not _handle_equipment_success(camera):
                return False
            clear_equipment_frame_cache()
        else:
            state.fail_count += 1
            state.round_purchase_fail_count += 1
            record_daily_purchase_fail()
            if state.overlay_root:
                state.overlay_root.after(0, update_score_text)
            ui_print(f"装备抢购失败：{price}", save_log=True, show_console=False)
            if not _handle_equipment_retry(camera, "装备失败刷新"):
                return False
            clear_equipment_frame_cache()
            return scan_post_save_and_buy()
        return True

    def scan_post_save_and_buy():
        scan_result = _scan_equipment_post_save_price(camera, templates)
        status, price, scan_frame, guard_rgb = scan_result
        if status == "matched":
            return handle_equipment_price_match(price, scan_frame, guard_rgb)
        if status == "guard_timeout":
            ui_print("装备守卫超时", is_replace=True, save_log=True, show_console=False)
            if not reenter_equipment_detail_and_filter_via_gumu(camera):
                _equipment_pause_for_manual("装备重进失败")
                return False
            clear_equipment_frame_cache()
            return True
        return True

    gc.disable()
    try:
        while True:
            if state.target_stop_seconds > 0 and get_current_elapsed() >= state.target_stop_seconds:
                state.target_stop_seconds = 0
                if not state.IS_PAUSED:
                    toggle_pause()
                continue

            if state.IS_PAUSED:
                gc_checkpoint()
                time.sleep(0.5)
                last_frame = None
                continue

            current_time = time.time()
            if current_time - last_runtime_state_check >= 1.0:
                ensure_active_runtime_window_state()
                persist_account_limit_reached_if_needed()
                last_runtime_state_check = current_time

            if get_current_elapsed() >= ACCOUNT_MAX_PURCHASE_SECONDS:
                persist_account_limit_reached_if_needed()
                state.overlay_status = "抢购时长已到"
                state.account_round_end_status = "抢购时长已到"
                clear_live_round_triplet_for_account_switch("装备抢购时长已到触发换号前")
                state.need_switch_server = True
                return

            raw_frame = safe_get_frame(camera)
            if raw_frame is None:
                if last_frame is not None and (time.time() - last_frame_time) < FRAME_MAX_AGE:
                    frame = last_frame
                else:
                    continue
            else:
                frame = raw_frame
                last_frame = frame
                last_frame_time = time.time()

            price_action, price_value, price_text, _price_source = get_equipment_price_decision(frame, templates)
            price = price_text if price_value is not None else "--"

            if price_action == "accept_skip_item_click":
                state.limit_count = 0
                state.unknown_page_count = 0
                guard_rgb = _get_equipment_buy_guard_rgb(frame)
                if not handle_equipment_price_match(price, frame, guard_rgb):
                    return
                continue
                _equipment_click_purchase_buttons()
                logger.info("[装备抢购] 价格命中已执行购买确认：price=%s guard_rgb=%s", price, guard_rgb)
                time.sleep(0.6)

                frame_after = safe_get_frame(camera)
                purchase_succeeded = frame_after is not None and is_image_present(frame_after, MONITOR_SUCCESS, temp_success)
                if purchase_succeeded:
                    state.success_count += 1
                    state.round_purchase_success_count += 1
                    record_daily_purchase_success()
                    if state.overlay_root:
                        state.overlay_root.after(0, update_score_text)
                    ui_print(f"装备抢购成功：{price}", save_log=True, show_console=False)
                    precise_sleep(0.15)
                    fast_click(SUCCESS_CONFIRM_POS)
                    precise_sleep(0.15)
                    fast_click(SUCCESS_CONFIRM_POS)
                    time.sleep(EQUIPMENT_SUCCESS_TO_REENTER_DELAY_SECONDS)
                    if not _handle_equipment_success(camera):
                        return
                    clear_equipment_frame_cache()
                else:
                    state.fail_count += 1
                    state.round_purchase_fail_count += 1
                    record_daily_purchase_fail()
                    if state.overlay_root:
                        state.overlay_root.after(0, update_score_text)
                    ui_print(f"装备抢购失败：{price}", save_log=True, show_console=False)
                    if not _handle_equipment_retry(camera, "装备失败刷新"):
                        return
                    clear_equipment_frame_cache()
                continue

            if price_action == "reject":
                if not _handle_equipment_retry(camera, f"装备价不符：{price}"):
                    return
                clear_equipment_frame_cache()
                if not scan_post_save_and_buy():
                    return
                continue

            if is_image_present(frame, MONITOR_MEIHUO, temp_meihuo):
                if not _handle_equipment_retry(camera, "装备已售空"):
                    return
                clear_equipment_frame_cache()
                if not scan_post_save_and_buy():
                    return
                continue

            if not _handle_equipment_retry(camera, "装备价未知"):
                return
            clear_equipment_frame_cache()
            if not scan_post_save_and_buy():
                return
    finally:
        gc.enable()


def run_brutal_purchase_loop(camera, temp_success, temp_shop, temp_goumai, temp_meihuo, temp_diyici):
    """暴力抢购模式：跳过价格识别，不写库，不接换号链路。"""
    state.brutal_purchase_mode = True
    state.overlay_status = "暴力抢购"
    state.purchase_timer_active = False
    state.last_resume_time = None

    last_refresh = time.time()
    last_frame = None
    last_frame_time = time.time()
    last_abnormal_print_sec = 0
    waiting_detail_after_refresh = False
    brutal_end_push_sent = False

    def finish_brutal_mode(reason, balance_text=None):
        nonlocal brutal_end_push_sent
        state.account_round_end_status = reason
        state.overlay_status = reason
        state.need_switch_server = False
        if not brutal_end_push_sent:
            brutal_end_push_sent = True
            async_push_msg(f"【暴力模式】{reason}", _build_brutal_end_summary(reason, balance_text))
        if not state.IS_PAUSED:
            toggle_pause()

    gc.disable()

    try:
        while True:
            if state.IS_PAUSED:
                gc_checkpoint()
                time.sleep(0.5)
                last_refresh = time.time()
                last_frame = None
                continue

            if _check_brutal_purchase_limit(finish_callback=finish_brutal_mode):
                continue

            try:
                raw_frame = safe_get_frame(camera)
                if raw_frame is None:
                    if last_frame is not None and (time.time() - last_frame_time) < FRAME_MAX_AGE:
                        frame = last_frame
                    else:
                        continue
                else:
                    frame = raw_frame
                    last_frame = frame
                    last_frame_time = time.time()

                is_trade_page = is_image_present(frame, MONITOR_JIAOYIHANG, state.temp_jiaoyi)
                if is_trade_page:
                    state.unknown_page_count = 0
                    if not _check_brutal_balance_limit(frame, camera=camera, finish_callback=finish_brutal_mode):
                        waiting_detail_after_refresh = False
                        last_refresh = time.time()
                        continue
                    if not is_image_present(frame, MONITOR_SHOP, temp_shop):
                        _recover_brutal_shop_from_trade_page()
                        last_refresh = time.time()
                        waiting_detail_after_refresh = False
                        time.sleep(0.05)
                        continue

                    if waiting_detail_after_refresh:
                        if time.time() - last_refresh <= 1.5:
                            time.sleep(0.05)
                            continue
                        state.limit_count += 1
                        ui_print(f"暂无道具{state.limit_count}/{ACCOUNT_LIMIT_THRESHOLD}", is_replace=True)
                        if state.limit_count >= ACCOUNT_LIMIT_THRESHOLD:
                            state.limit_count = 0
                            finish_brutal_mode("账号限制")
                            waiting_detail_after_refresh = False
                            last_refresh = time.time()
                            continue

                    fast_click(REFRESH_POS)
                    last_refresh = time.time()
                    waiting_detail_after_refresh = True
                    time.sleep(0.05)
                    continue

                if waiting_detail_after_refresh:
                    state.limit_count = 0
                    state.unknown_page_count = 0
                    if is_image_present(frame, MONITOR_MEIHUO, temp_meihuo):
                        ui_print("已售空", is_replace=True)
                        click_exit()
                        if _wait_trade_without_balance(EXIT_DELAY, camera, finish_callback=finish_brutal_mode):
                            fast_click(REFRESH_POS)
                            last_refresh = time.time()
                            waiting_detail_after_refresh = True
                        else:
                            waiting_detail_after_refresh = False
                        continue

                    waiting_detail_after_refresh = False
                    buy_click_end_time = time.perf_counter() + 0.022
                    while time.perf_counter() < buy_click_end_time:
                        fast_click(BUY_POS)
                        precise_sleep(0.002)
                    precise_sleep(CONFIRM_DELAY)
                    confirm_click_end_time = time.perf_counter() + 0.05
                    while time.perf_counter() < confirm_click_end_time:
                        fast_click(CONFIRM_POS)
                        precise_sleep(0.005)
                    time.sleep(0.6)

                    frame_after = safe_get_frame(camera)
                    if frame_after is not None and is_image_present(frame_after, MONITOR_SUCCESS, temp_success):
                        state.success_count += 1
                        state.round_purchase_success_count += 1
                        if state.overlay_root:
                            state.overlay_root.after(0, update_score_text)
                        ui_print("暴力成功", save_log=True, show_console=False)
                        precise_sleep(0.15)
                        fast_click(SUCCESS_CONFIRM_POS)
                        precise_sleep(0.15)
                        fast_click(SUCCESS_CONFIRM_POS)
                        if _check_brutal_purchase_limit(finish_callback=finish_brutal_mode):
                            continue
                    else:
                        state.fail_count += 1
                        state.round_purchase_fail_count += 1
                        if state.overlay_root:
                            state.overlay_root.after(0, update_score_text)
                        ui_print("暴力失败", save_log=True, show_console=False)
                        click_exit()

                    if _wait_trade_without_balance(EXIT_DELAY, camera, finish_callback=finish_brutal_mode):
                        fast_click(REFRESH_POS)
                        last_refresh = time.time()
                        waiting_detail_after_refresh = True
                    continue

                time_since_last_action = time.time() - last_refresh
                if time_since_last_action > 1.5:
                    if state.unknown_page_count == 0 or time_since_last_action > 10.0:
                        ui_print("画面异常，全场景识别。", save_log=True)
                        is_unknown_page = False
                        if is_image_present(frame, MONITOR_DIYICI, temp_diyici, threshold=0.6):
                            fast_click(DIYICI_CLICK_POS)
                        elif is_image_present(frame, MONITOR_GOUMAI, temp_goumai, threshold=0.6):
                            click_exit()
                        elif _is_listing_page(frame):
                            click_exit()
                        elif (
                            is_image_present(frame, MONITOR_JIAOYIHANG, state.temp_jiaoyi, threshold=0.6)
                            and not is_image_present(frame, MONITOR_SHOP, temp_shop, threshold=0.6)
                        ):
                            _recover_brutal_shop_from_trade_page()
                        elif is_at_gumu(camera):
                            navigate_to_trade(camera)
                        elif try_return_to_gumu(camera, retry_count=3):
                            navigate_to_trade(camera)
                        else:
                            is_unknown_page = True
                            state.unknown_page_count += 1
                            if state.unknown_page_count >= 5:
                                state.unknown_page_count = 0
                                finish_brutal_mode("未知异常")
                            else:
                                last_refresh = time.time()
                                last_abnormal_print_sec = 0

                        if not is_unknown_page:
                            state.unknown_page_count = 0
                            if smart_wait(1.0):
                                fast_click(REFRESH_POS)
                                last_refresh = time.time()
                    else:
                        current_sec = int(time_since_last_action)
                        if current_sec != last_abnormal_print_sec:
                            ui_print(f"场景识别介入（{current_sec}秒/10秒）", is_replace=True)
                            last_abnormal_print_sec = current_sec

                time.sleep(0.002)
            except Exception:
                time.sleep(0.5)
    finally:
        gc.enable()


def run_purchase_loop(camera, templates, temp_success, temp_shop,
                      temp_goumai, temp_meihuo, temp_diyici):
    """抢购主循环，由 main.py 调用。"""
    from listing import check_trigger_listing

    if state.accessory_purchase_mode:
        run_accessory_purchase_loop(camera, temp_success)
        return
    if state.equipment_purchase_mode:
        run_equipment_purchase_loop(camera, templates, temp_success, temp_meihuo)
        return

    state.overlay_status = "抢购中"
    state.purchase_timer_active = True
    if not state.IS_PAUSED:
        state.last_resume_time = time.time()
    else:
        state.last_resume_time = None
    ensure_active_runtime_window_state()
    mature_stone_unlocks_for_current_account("抢购开始前")

    last_refresh = time.time()
    last_frame = None
    last_frame_time = time.time()
    last_abnormal_print_sec = 0
    last_stuck_push_time = time.time()
    last_idle_push_time = time.time()
    last_success_time = time.time()
    last_runtime_state_check = 0.0
    last_temporary_snapshot_sync = 0.0
    runtime_reached_continue_mode = False

    gc.disable()

    try:
        while True:
            if state.target_stop_seconds > 0 and get_current_elapsed() >= state.target_stop_seconds:
                state.target_stop_seconds = 0
                if not state.IS_PAUSED:
                    toggle_pause()
                continue

            if state.IS_PAUSED:
                gc_checkpoint()
                time.sleep(0.5)
                last_refresh = time.time()
                last_success_time = last_idle_push_time = last_stuck_push_time = time.time()
                last_frame = None
                continue

            try:
                current_time = time.time()
                if current_time - last_runtime_state_check >= 1.0:
                    ensure_active_runtime_window_state()
                    persist_account_limit_reached_if_needed()
                    last_runtime_state_check = current_time
                if state.temporary_purchase_mode and current_time - last_temporary_snapshot_sync >= 5.0:
                    _sync_temporary_snapshot("临时模式运行中")
                    last_temporary_snapshot_sync = current_time

                if not runtime_reached_continue_mode and get_current_elapsed() >= ACCOUNT_MAX_PURCHASE_SECONDS:
                    persist_account_limit_reached_if_needed()
                    latest_balance_text = get_latest_runtime_balance_text()
                    latest_balance_value = parse_balance_text_to_value(latest_balance_text)
                    if (
                        latest_balance_value is not None
                        and latest_balance_value >= ACCOUNT_RUNTIME_CONTINUE_BALANCE_THRESHOLD
                    ):
                        runtime_reached_continue_mode = True
                        state.overlay_status = "抢购中"
                        ui_print(f"时间已到，余额 {latest_balance_text} 继续抢购", save_log=True)
                    else:
                        state.overlay_status = "抢购时长已到"
                        ui_print("时间已到，进入主流程收尾。", save_log=True)
                        state.account_round_end_status = "抢购时长已到"
                        if not state.temporary_purchase_mode:
                            clear_live_round_triplet_for_account_switch("抢购时长已到触发换号前")
                        else:
                            _sync_temporary_snapshot("临时模式抢购时长已到", trigger_remote_snapshot=True)
                        state.need_switch_server = True
                        return

                if (current_time - last_refresh > STUCK_PUSH_INTERVAL and
                        current_time - last_stuck_push_time > STUCK_PUSH_INTERVAL):
                    last_stuck_push_time = current_time

                raw_frame = safe_get_frame(camera)
                if raw_frame is None:
                    if last_frame is not None and (time.time() - last_frame_time) < FRAME_MAX_AGE:
                        frame = last_frame
                    else:
                        continue
                else:
                    frame = raw_frame
                    last_frame = frame
                    last_frame_time = time.time()

                price_action, price_value, price_text, price_source = get_price_decision(frame, templates)

                if price_action != "unknown":
                    state.limit_count = 0
                    state.unknown_page_count = 0
                    last_refresh = time.time()
                    price = price_text if price_value is not None else f"前缀识别 {price_text}"

                    if price_action in ("accept", "accept_skip_item_click"):
                        if price_source == "primary" and price_action != "accept_skip_item_click":
                            # 点击商品
                            window_click_end_time = time.perf_counter() + 0.008
                            while time.perf_counter() < window_click_end_time:
                                fast_click((1715, 180))
                                precise_sleep(0.002)
                        buy_click_end_time = time.perf_counter() + 0.012
                        while time.perf_counter() < buy_click_end_time:
                            fast_click(BUY_POS)
                            precise_sleep(0.002)
                        precise_sleep(CONFIRM_DELAY)
                        confirm_click_end_time = time.perf_counter() + 0.05
                        while time.perf_counter() < confirm_click_end_time:
                            fast_click(CONFIRM_POS)
                            precise_sleep(0.005)
                        time.sleep(0.6)
                        purchase_succeeded = False

                        frame_after = safe_get_frame(camera)
                        if frame_after is not None and is_image_present(frame_after, MONITOR_SUCCESS, temp_success):
                            state.success_count += 1
                            state.round_purchase_success_count += 1
                            record_daily_purchase_success()
                            purchase_succeeded = True
                            last_success_time = last_idle_push_time = time.time()
                            if state.overlay_root:
                                state.overlay_root.after(0, update_score_text)
                            ui_print(f"抢购成功，价格：{price}", save_log=True, show_console=False)
                            precise_sleep(0.15)
                            fast_click(SUCCESS_CONFIRM_POS)
                            precise_sleep(0.15)
                            fast_click(SUCCESS_CONFIRM_POS)
                        else:
                            state.fail_count += 1
                            state.round_purchase_fail_count += 1
                            record_daily_purchase_fail()
                            if state.overlay_root:
                                state.overlay_root.after(0, update_score_text)
                            ui_print(f"抢购失败，价格：{price}", save_log=True, show_console=False)
                            click_exit()

                        wait_window_started_at = time.time()
                        inventory_write_failed = False
                        if purchase_succeeded:
                            stone_inventory_result = record_stone_purchase_success_for_current_account()
                            if stone_inventory_result.status not in ("success", "skipped"):
                                logger.warning("[石头库存] 抢购成功后锁定库存写入失败：%s", stone_inventory_result.reason)
                                ui_print("锁定库存失败", save_log=True)
                                inventory_write_failed = True
                                if not state.IS_PAUSED:
                                    toggle_pause()
                            write_elapsed = time.time() - wait_window_started_at
                            if write_elapsed > EXIT_DELAY:
                                logger.warning("[石头库存] 抢购成功后写库耗时 %.3f 秒，超过等待窗口 %.3f 秒。", write_elapsed, EXIT_DELAY)

                        if wait_and_recognize_balance(EXIT_DELAY, camera, start_total=wait_window_started_at):
                            if purchase_succeeded:
                                sync_result = persist_minimal_item_balance_sync()
                                if sync_result.status not in ("success", "skipped"):
                                    ui_print(f"实时库存同步失败：{sync_result.reason}", save_log=True)
                            if not check_trigger_listing(camera):
                                return
                            fast_click(REFRESH_POS)
                            last_refresh = time.time()
                        elif state.need_switch_server:
                            return
                    else:
                        ui_print(
                            f"价格不符：{price}",
                            is_replace=True,
                            save_log=True,
                            show_console=False,
                        )
                        click_exit()
                        if wait_and_recognize_balance(MISMATCH_EXIT_DELAY, camera):
                            if not check_trigger_listing(camera):
                                return
                            fast_click(REFRESH_POS)
                            last_refresh = time.time()
                        elif state.need_switch_server:
                            return
                else:
                    if is_image_present(frame, MONITOR_MEIHUO, temp_meihuo):
                        state.unknown_page_count = 0
                        ui_print("已识别到售空。", is_replace=True)
                        click_exit()
                        if wait_and_recognize_balance(EXIT_DELAY, camera):
                            if not check_trigger_listing(camera):
                                return
                            fast_click(REFRESH_POS)
                            last_refresh = time.time()
                        elif state.need_switch_server:
                            return
                        continue

                    time_since_last_action = time.time() - last_refresh
                    if time_since_last_action > 1.5:
                        is_normal_empty = (
                            is_image_present(frame, MONITOR_JIAOYIHANG, state.temp_jiaoyi) and
                            is_image_present(frame, MONITOR_SHOP, temp_shop)
                        )
                        if is_normal_empty:
                            state.limit_count += 1
                            state.unknown_page_count = 0
                            ui_print(f"暂无道具可抢（{state.limit_count}/{ACCOUNT_LIMIT_THRESHOLD}）", is_replace=True)
                            if state.limit_count >= ACCOUNT_LIMIT_THRESHOLD:
                                if state.temporary_purchase_mode:
                                    state.account_limit_reached_at = None
                                    state.account_round_end_status = "账号限制"
                                    state.overlay_status = "临时账号限制"
                                    _sync_temporary_snapshot("临时模式账号限制", trigger_remote_snapshot=True)
                                    state.need_switch_server = True
                                    return
                                state.account_limit_reached_at = None
                                state.account_round_end_status = "账号限制"
                                state.overlay_status = "账号限制"
                                clear_live_round_triplet_for_account_switch("账号限制触发换号前")
                                state.need_switch_server = True
                                return
                            if not check_balance_limit(frame, camera=camera, try_refresh_on_low=True):
                                if state.need_switch_server:
                                    return
                                continue
                            if not check_trigger_listing(camera):
                                return
                            fast_click(REFRESH_POS)
                            gc_checkpoint()
                            last_refresh = time.time()
                        else:
                            if state.unknown_page_count == 0 or time_since_last_action > 10.0:
                                ui_print("画面异常，全场景识别。", save_log=True)
                                is_unknown_page = False
                                if is_image_present(frame, MONITOR_DIYICI, temp_diyici, threshold=0.6):
                                    fast_click(DIYICI_CLICK_POS)
                                elif is_image_present(frame, MONITOR_GOUMAI, temp_goumai, threshold=0.6):
                                    click_exit()
                                elif _is_listing_page(frame):
                                    click_exit()
                                elif (is_image_present(frame, MONITOR_JIAOYIHANG, state.temp_jiaoyi, threshold=0.6) and
                                      not is_image_present(frame, MONITOR_SHOP, temp_shop, threshold=0.6)):
                                    fast_click(FIX_SHOP_POS1)
                                    precise_sleep(1.0)
                                    fast_click(FIX_SHOP_POS2)
                                elif is_at_gumu(camera):
                                    navigate_to_trade(camera)
                                elif try_return_to_gumu(camera, retry_count=3):
                                    navigate_to_trade(camera)
                                else:
                                    is_unknown_page = True
                                    state.unknown_page_count += 1
                                    if state.unknown_page_count >= 5:
                                        state.overlay_status = "未知异常"
                                        state.unknown_page_count = 0
                                        if not state.IS_PAUSED:
                                            toggle_pause()
                                    else:
                                        last_refresh = time.time()
                                        last_abnormal_print_sec = 0

                                if not is_unknown_page:
                                    state.unknown_page_count = 0
                                    if smart_wait(1.0):
                                        if not check_trigger_listing(camera):
                                            return
                                        fast_click(REFRESH_POS)
                                        last_refresh = time.time()
                            else:
                                current_sec = int(time_since_last_action)
                                if current_sec != last_abnormal_print_sec:
                                    ui_print(f"场景识别介入（{current_sec}秒/10秒）", is_replace=True)
                                    last_abnormal_print_sec = current_sec

                time.sleep(0.002)
            except Exception:
                time.sleep(0.5)
    finally:
        if not state.need_switch_server:
            camera.stop()
