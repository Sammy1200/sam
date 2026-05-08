"""饰品抢购模式的独立循环，不接普通价格判断和上架链路。"""
import time
from datetime import datetime

import state
from config import (
    ACCOUNT_MAX_PURCHASE_SECONDS,
    ACCESSORY_ACTION_DELAY_SECONDS,
    ACCESSORY_BUY_COLOR_CLICK_OFFSET,
    ACCESSORY_BUY_COLOR_RGB,
    ACCESSORY_BUY_COLOR_X_RANGES,
    ACCESSORY_BUY_COLOR_Y_RANGE,
    ACCESSORY_COLOR_CLICK_INTERVAL_SECONDS,
    ACCESSORY_COLOR_CLICK_WINDOW_SECONDS,
    ACCESSORY_DIANPU_MONITOR,
    ACCESSORY_DIANPU_RECOVER_INTERVAL_SECONDS,
    ACCESSORY_DIANPU_RECOVER_RETRY_COUNT,
    ACCESSORY_DIANPU_RECOVER_WAIT_SECONDS,
    ACCESSORY_EXCEPTION_RECOVER_RETRY_COUNT,
    ACCESSORY_EXIT_FIRST_CHECK_SECONDS,
    ACCESSORY_EXIT_RETRY_INTERVAL_SECONDS,
    ACCESSORY_EXIT_TO_NEXT_PAGE_SECONDS,
    ACCESSORY_ITEM_ENTER_RETRY_COUNT,
    ACCESSORY_ITEM_ENTER_RETRY_INTERVAL_SECONDS,
    ACCESSORY_ITEM_POSITIONS,
    ACCESSORY_NO_BUY_PRE_ESC_DELAY_SECONDS,
    ACCESSORY_NO_BUY_RETURN_NEXT_ITEM_DELAY_SECONDS,
    ACCESSORY_PAGE_GUARD_POLL_SECONDS,
    ACCESSORY_PAGE_GUARD_POS,
    ACCESSORY_PAGE_GUARD_RGB,
    ACCESSORY_RECOVER_POS1,
    ACCESSORY_RECOVER_POS2,
    ACCESSORY_RETURN_ESC_RETRY_COUNT,
    ACCESSORY_TRADE_PAGE_MONITOR,
    ACCESSORY_TRADE_READY_CONFIRM_DELAY_SECONDS,
    ACCESSORY_TRACE_ENABLED,
    BUY_POS,
    CONFIRM_DELAY,
    CONFIRM_POS,
    FRAME_MAX_AGE,
    MONITOR_SUCCESS,
    SUCCESS_CONFIRM_POS,
)
from overlay import toggle_pause, ui_print, update_score_text
from round_persistence import (
    ensure_active_runtime_window_state,
    persist_minimal_item_balance_sync,
    record_daily_purchase_fail,
    record_daily_purchase_success,
)
from switch import enter_accessory_trade_from_current_scene
from utils import (
    async_push_msg as shared_async_push_msg,
    click_exit,
    fast_click,
    gc_checkpoint,
    get_current_elapsed,
    logger,
    precise_sleep,
    safe_get_frame,
    safe_imread,
)
from vision import is_image_present


_ACCESSORY_TRADE_PAGE_TEMPLATE = None


def _load_accessory_trade_page_template():
    global _ACCESSORY_TRADE_PAGE_TEMPLATE
    if _ACCESSORY_TRADE_PAGE_TEMPLATE is None:
        _ACCESSORY_TRADE_PAGE_TEMPLATE = safe_imread(("logo", "tezhengtu", "shipinjiaoyihang.png"), 0)
    return _ACCESSORY_TRADE_PAGE_TEMPLATE


def _pixel_matches_rgb(frame, pos, target_rgb):
    if frame is None:
        return False
    x, y = int(pos[0]), int(pos[1])
    if y < 0 or x < 0 or y >= frame.shape[0] or x >= frame.shape[1]:
        return False
    pixel = frame[y, x]
    b, g, r = int(pixel[0]), int(pixel[1]), int(pixel[2])
    return (r, g, b) == tuple(int(value) for value in target_rgb)


def _is_accessory_trade_frame(frame):
    template = _load_accessory_trade_page_template()
    if frame is None or template is None:
        return False
    return is_image_present(frame, ACCESSORY_TRADE_PAGE_MONITOR, template, threshold=0.8)


def _is_accessory_dianpu_frame(frame):
    return frame is not None and is_image_present(frame, ACCESSORY_DIANPU_MONITOR, state.temp_shop, threshold=0.8)


def _is_accessory_trade_ready_frame(frame):
    return _is_accessory_trade_frame(frame) and _is_accessory_dianpu_frame(frame)


def _is_accessory_purchase_frame(frame):
    return _pixel_matches_rgb(frame, ACCESSORY_PAGE_GUARD_POS, ACCESSORY_PAGE_GUARD_RGB)


def _find_accessory_buy_color_point(frame):
    if frame is None:
        return None
    y1, y2 = ACCESSORY_BUY_COLOR_Y_RANGE
    target_r, target_g, target_b = tuple(int(value) for value in ACCESSORY_BUY_COLOR_RGB)
    max_y = min(int(y2), frame.shape[0] - 1)
    for y in range(max(0, int(y1)), max_y + 1):
        for x1, x2 in ACCESSORY_BUY_COLOR_X_RANGES:
            max_x = min(int(x2), frame.shape[1] - 1)
            for x in range(max(0, int(x1)), max_x + 1):
                b, g, r = (int(value) for value in frame[y, x][:3])
                if (r, g, b) == (target_r, target_g, target_b):
                    return x, y
    return None


def _get_accessory_item_number():
    item_count = len(ACCESSORY_ITEM_POSITIONS)
    if item_count <= 0:
        return 0
    return int(state.accessory_item_index) % item_count + 1


def _advance_accessory_item_index():
    item_count = len(ACCESSORY_ITEM_POSITIONS)
    if item_count <= 0:
        state.accessory_item_index = 0
        return
    state.accessory_item_index = (int(state.accessory_item_index) + 1) % item_count


def _reset_accessory_trace():
    if not ACCESSORY_TRACE_ENABLED:
        return
    _accessory_trace.base_time = time.perf_counter()
    _accessory_trace.last_time = _accessory_trace.base_time


def _accessory_trace(step, **fields):
    if not ACCESSORY_TRACE_ENABLED:
        return
    now = time.perf_counter()
    base_time = getattr(_accessory_trace, "base_time", now)
    last_time = getattr(_accessory_trace, "last_time", now)
    _accessory_trace.last_time = now
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info(
        "[饰品追踪] +%.1fms total=%.3fs %s%s",
        (now - last_time) * 1000,
        now - base_time,
        step,
        f" {details}" if details else "",
    )


def _clear_accessory_live_round_triplet_for_account_switch(reason):
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
    if state.overlay_root:
        state.overlay_root.after(0, update_score_text)


def _mark_accessory_account_limited(reason):
    now = datetime.now()
    state.account_round_end_status = "账号限制"
    state.round_status = "账号限制"
    state.overlay_status = "账号限制"
    state.account_limit_reached_at = now
    state.last_limit_time = now
    state.need_switch_server = True
    state.purchase_timer_active = False
    state.last_resume_time = None
    state.accessory_skip_trade_ready_wait_once = False
    state.accessory_next_item_click_not_before = None
    _clear_accessory_live_round_triplet_for_account_switch("饰品账号限制触发换号前")
    ui_print("饰品账号限制", save_log=True)
    print(f"[饰品抢购] {reason}，已判定账号限制。")
    logger.info("[饰品抢购] %s，已判定账号限制。", reason)


def _recover_accessory_trade_page(camera):
    frame = safe_get_frame(camera)
    if _is_accessory_trade_ready_frame(frame):
        return True

    if not _is_accessory_trade_frame(frame):
        for _ in range(ACCESSORY_RETURN_ESC_RETRY_COUNT):
            click_exit()
            precise_sleep(ACCESSORY_NO_BUY_RETURN_NEXT_ITEM_DELAY_SECONDS)
            frame = safe_get_frame(camera)
            if _is_accessory_trade_ready_frame(frame):
                return True

    frame = safe_get_frame(camera)
    if not _is_accessory_trade_frame(frame):
        return False

    if _is_accessory_dianpu_frame(frame):
        return True

    for _attempt in range(1, ACCESSORY_DIANPU_RECOVER_RETRY_COUNT + 1):
        fast_click(ACCESSORY_RECOVER_POS1)
        precise_sleep(ACCESSORY_DIANPU_RECOVER_WAIT_SECONDS)
        fast_click(ACCESSORY_RECOVER_POS2)
        precise_sleep(ACCESSORY_DIANPU_RECOVER_INTERVAL_SECONDS)
        frame = safe_get_frame(camera)
        if _is_accessory_trade_ready_frame(frame):
            return True
    return False


def _open_next_accessory_item_page(camera):
    item_count = len(ACCESSORY_ITEM_POSITIONS)
    if item_count <= 0:
        _mark_accessory_account_limited("未配置饰品坐标")
        return False

    item_index = int(state.accessory_item_index) % item_count
    item_number = item_index + 1
    target_pos = ACCESSORY_ITEM_POSITIONS[item_index]
    _accessory_trace("准备进入饰品详情", item=item_number, pos=target_pos)

    for retry_index in range(1, ACCESSORY_ITEM_ENTER_RETRY_COUNT + 1):
        trade_frame = safe_get_frame(camera)
        if not _is_accessory_trade_ready_frame(trade_frame):
            ui_print("饰品未就绪", save_log=True)
            return False

        click_started_at = time.perf_counter()
        state.accessory_item_click_started_at = click_started_at
        state.accessory_skip_trade_ready_wait_once = False
        fast_click(target_pos)
        precise_sleep(ACCESSORY_ITEM_CLICK_VERIFY_DELAY_SECONDS)

        guard_deadline = click_started_at + ACCESSORY_ITEM_ENTER_RETRY_INTERVAL_SECONDS
        while time.perf_counter() < guard_deadline:
            frame = safe_get_frame(camera)
            if _is_accessory_purchase_frame(frame):
                return True
            precise_sleep(ACCESSORY_PAGE_GUARD_POLL_SECONDS)

        logger.info("[饰品抢购] 坐标 %s 第 %s/%s 次点击后未命中详情页。", item_number, retry_index, ACCESSORY_ITEM_ENTER_RETRY_COUNT)

    final_frame = safe_get_frame(camera)
    if not _is_accessory_trade_ready_frame(final_frame):
        logger.warning("[饰品抢购] 坐标 %s 未进入详情页，当前饰品交易行未就绪，交由异常恢复。", item_number)
        return False

    _mark_accessory_account_limited(
        f"坐标 {item_number} 按 1 秒节奏重试 {ACCESSORY_ITEM_ENTER_RETRY_COUNT} 次仍未进入详情页"
    )
    return False


def _exit_and_open_next_accessory_item_page(camera, cycle_started_at=None):
    precise_sleep(ACCESSORY_NO_BUY_PRE_ESC_DELAY_SECONDS)
    click_exit()

    if cycle_started_at is None:
        deadline = time.perf_counter() + ACCESSORY_EXIT_TO_NEXT_PAGE_SECONDS
    else:
        deadline = float(cycle_started_at) + ACCESSORY_EXIT_TO_NEXT_PAGE_SECONDS

    first_wait = max(0.0, min(ACCESSORY_EXIT_FIRST_CHECK_SECONDS, deadline - time.perf_counter()))
    if first_wait > 0:
        precise_sleep(first_wait)

    esc_retry_count = 0
    returned_to_trade = False
    while time.perf_counter() < deadline:
        frame = safe_get_frame(camera)
        if _is_accessory_trade_frame(frame):
            returned_to_trade = True
            break
        if esc_retry_count < ACCESSORY_RETURN_ESC_RETRY_COUNT:
            click_exit()
            esc_retry_count += 1
        precise_sleep(min(ACCESSORY_EXIT_RETRY_INTERVAL_SECONDS, max(0.0, deadline - time.perf_counter())))

    frame = safe_get_frame(camera)
    returned_to_trade = returned_to_trade or _is_accessory_trade_frame(frame)
    if not returned_to_trade:
        logger.info("[饰品抢购] %.1f 秒内未确认饰品交易行，交由异常重进场处理。", ACCESSORY_EXIT_TO_NEXT_PAGE_SECONDS)
        return False

    _advance_accessory_item_index()
    state.accessory_skip_trade_ready_wait_once = True
    state.accessory_next_item_click_not_before = None
    return True


def _wait_accessory_next_item_click_deadline():
    deadline = getattr(state, "accessory_next_item_click_not_before", None)
    if deadline is None:
        return
    remaining = float(deadline) - time.perf_counter()
    if remaining > 0:
        precise_sleep(remaining)
    state.accessory_next_item_click_not_before = None


def _click_accessory_buy_color(color_point):
    click_pos = (
        int(color_point[0]) + int(ACCESSORY_BUY_COLOR_CLICK_OFFSET[0]),
        int(color_point[1]) + int(ACCESSORY_BUY_COLOR_CLICK_OFFSET[1]),
    )
    click_end_time = time.perf_counter() + ACCESSORY_COLOR_CLICK_WINDOW_SECONDS
    while time.perf_counter() < click_end_time:
        fast_click(click_pos)
        precise_sleep(ACCESSORY_COLOR_CLICK_INTERVAL_SECONDS)

    buy_click_end = time.perf_counter() + 0.02
    while time.perf_counter() < buy_click_end:
        fast_click(BUY_POS)
        precise_sleep(0.002)
    precise_sleep(CONFIRM_DELAY)

    confirm_click_end = time.perf_counter() + 0.02
    while time.perf_counter() < confirm_click_end:
        fast_click(CONFIRM_POS)
        precise_sleep(0.002)


def _handle_accessory_purchase_result(camera, temp_success):
    item_number = _get_accessory_item_number()
    time.sleep(0.6)
    frame_after = safe_get_frame(camera)
    result_checked_at = time.perf_counter()
    if frame_after is not None and is_image_present(frame_after, MONITOR_SUCCESS, temp_success):
        state.success_count += 1
        state.round_purchase_success_count += 1
        state.baseline_item_count += 1
        record_daily_purchase_success()
        persist_minimal_item_balance_sync()
        if state.overlay_root:
            state.overlay_root.after(0, update_score_text)
        ui_print("饰品抢购成功", save_log=True, show_console=False)
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
        ui_print("饰品抢购失败", save_log=True, show_console=False)
        click_exit()

    if not _recover_accessory_trade_page(camera):
        ui_print("饰品重进场", save_log=True)
        logger.warning("[饰品抢购] 坐标 %s 购买后未确认返回饰品交易行，尝试异常恢复。", item_number)
        return _recover_accessory_exception(camera, "饰品购买后返回失败")

    _advance_accessory_item_index()
    state.accessory_skip_trade_ready_wait_once = True
    state.accessory_next_item_click_not_before = result_checked_at + ACCESSORY_EXIT_TO_NEXT_PAGE_SECONDS
    return True


def _pause_accessory_for_manual(reason, send_push=False):
    state.overlay_status = "未知异常"
    state.need_switch_server = False
    if not state.account_round_end_status:
        state.account_round_end_status = "未知异常"
    logger.warning("[饰品抢购] %s，已暂停脚本等待人工处理。", reason)
    if send_push:
        shared_async_push_msg(
            "【饰品抢购】异常暂停",
            f"{reason}\n已尝试返回古墓大厅并重新进入饰品交易行 {ACCESSORY_EXCEPTION_RECOVER_RETRY_COUNT} 次，仍未恢复。",
        )
    if not state.IS_PAUSED:
        toggle_pause()


def _recover_accessory_exception(camera, reason):
    state.need_switch_server = False
    for retry_index in range(1, ACCESSORY_EXCEPTION_RECOVER_RETRY_COUNT + 1):
        ui_print(f"饰品恢复{retry_index}/3", save_log=True)
        logger.warning(
            "[饰品抢购] %s，尝试返回古墓大厅并重新进入饰品交易行（%s/%s）。",
            reason,
            retry_index,
            ACCESSORY_EXCEPTION_RECOVER_RETRY_COUNT,
        )
        try:
            if enter_accessory_trade_from_current_scene(camera):
                state.overlay_status = "饰品抢购中"
                state.accessory_item_click_started_at = None
                state.accessory_skip_trade_ready_wait_once = False
                state.accessory_next_item_click_not_before = None
                logger.info("[饰品抢购] 异常恢复成功，已重新进入饰品交易行。")
                return True
        except Exception as exc:
            logger.exception("[饰品抢购] 异常恢复第 %s 次执行失败：%s", retry_index, exc)
        precise_sleep(ACCESSORY_ACTION_DELAY_SECONDS)

    _pause_accessory_for_manual(reason, send_push=True)
    return False


def _mark_accessory_runtime_reached():
    state.account_round_end_status = "抢购时长已到"
    state.overlay_status = "抢购时长已到"
    state.need_switch_server = True
    state.purchase_timer_active = False
    state.last_resume_time = None
    _clear_accessory_live_round_triplet_for_account_switch("饰品抢购时长已到触发换号前")
    ui_print("饰品时长到", save_log=True)


def run_accessory_purchase_loop(camera, temp_success):
    """饰品抢购循环，由 purchase.run_purchase_loop 分流调用。"""
    _reset_accessory_trace()
    state.overlay_status = "饰品抢购中"
    state.purchase_timer_active = True
    state.last_resume_time = None if state.IS_PAUSED else time.time()
    ensure_active_runtime_window_state()

    last_frame = None
    last_frame_time = time.time()

    try:
        while True:
            gc_checkpoint()
            if state.target_stop_seconds > 0 and get_current_elapsed() >= state.target_stop_seconds:
                state.target_stop_seconds = 0
                if not state.IS_PAUSED:
                    toggle_pause()
                continue

            if state.need_switch_server:
                return

            if state.IS_PAUSED:
                state.last_resume_time = None
                precise_sleep(0.1)
                continue
            if state.last_resume_time is None:
                state.last_resume_time = time.time()

            if get_current_elapsed() >= ACCOUNT_MAX_PURCHASE_SECONDS:
                _mark_accessory_runtime_reached()
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

            if _is_accessory_trade_frame(frame):
                if not _recover_accessory_trade_page(camera):
                    ui_print("饰品未就绪", save_log=True)
                    _recover_accessory_exception(camera, "饰品交易行未就绪")
                    continue
                skip_ready_wait = bool(getattr(state, "accessory_skip_trade_ready_wait_once", False))
                state.accessory_skip_trade_ready_wait_once = False
                if not skip_ready_wait:
                    precise_sleep(ACCESSORY_TRADE_READY_CONFIRM_DELAY_SECONDS)
                _wait_accessory_next_item_click_deadline()
                _open_next_accessory_item_page(camera)
                continue

            if not _is_accessory_purchase_frame(frame):
                ui_print("饰品重进场", save_log=True)
                logger.warning("[饰品抢购] 未知异常页面，尝试返回古墓大厅并重新进入饰品交易行。")
                if not _recover_accessory_exception(camera, "饰品未知页面"):
                    ui_print("饰品场景异常", save_log=True)
                    return
                continue

            color_point = _find_accessory_buy_color_point(frame)
            if color_point is None:
                ui_print("饰品未命中", is_replace=True, show_console=False)
                cycle_started_at = getattr(state, "accessory_item_click_started_at", None)
                if not _exit_and_open_next_accessory_item_page(camera, cycle_started_at=cycle_started_at):
                    ui_print("饰品重进场", save_log=True)
                    if not _recover_accessory_exception(camera, "饰品返回失败"):
                        ui_print("饰品场景异常", save_log=True)
                        return
                continue

            _click_accessory_buy_color(color_point)
            if not _handle_accessory_purchase_result(camera, temp_success):
                return
    except Exception as exc:
        logger.exception("[饰品抢购] 未捕获异常，尝试返回古墓大厅并重新进入饰品交易行：%s", exc)
        ui_print("饰品异常", save_log=True)
        if _recover_accessory_exception(camera, "饰品未捕获异常"):
            run_accessory_purchase_loop(camera, temp_success)
            return
        while True:
            gc_checkpoint()
            time.sleep(0.5)
