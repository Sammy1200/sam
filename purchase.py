"""
抢购主循环 + 余额/限制检测 + 推送
"""
import gc
import re
import threading
import time

import requests

import state
from config import (
    ACCOUNT_MAX_PURCHASE_SECONDS,
    ACCOUNT_RUNTIME_CONTINUE_BALANCE_THRESHOLD,
    ACCOUNT_LIMIT_THRESHOLD,
    BUY_POS,
    CONFIRM_DELAY,
    CONFIRM_POS,
    DIYICI_CLICK_POS,
    EXIT_DELAY,
    FIX_SHOP_POS1,
    FIX_SHOP_POS2,
    FRAME_MAX_AGE,
    MAX_PRICE,
    MIN_PRICE,
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
    persist_account_limit_reached_if_needed,
    persist_minimal_item_balance_sync,
    record_daily_purchase_fail,
    record_daily_purchase_success,
)
from switch import is_at_gumu, navigate_to_trade
from utils import (
    click_exit,
    fast_click,
    gc_checkpoint,
    get_current_elapsed,
    precise_sleep,
    safe_get_frame,
    smart_wait,
)
from vision import get_balance, get_price_decision, is_image_present


def get_battle_report():
    elapsed = int(get_current_elapsed())
    h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
    bal_str = str(state.current_balance)
    return (
        "--------------------\n"
        f"当前余额：{bal_str}\n"
        f"抢购成功：{state.success_count} 次\n"
        f"抢购失败：{state.fail_count} 次\n"
        f"累计上架：{state.total_listed_count} 件\n"
        f"运行时间：{h}小时{m}分{s}秒"
    )


def async_push_msg(title, content):
    report = get_battle_report()
    full_content = f"{content}\n\n{report}"

    def send():
        token = "59653da98d3049adb1deb19660767621"
        url = "http://www.pushplus.plus/send"
        data = {"token": token, "title": title, "content": full_content, "template": "txt"}
        try:
            requests.post(url, json=data, timeout=3)
        except:
            pass

    threading.Thread(target=send, daemon=True).start()


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

    if state.overlay_root:
        try:
            state.overlay_root.after(0, update_score_text)
        except:
            pass


def check_balance_limit(frame):
    """识别余额，余额不足时直接触发自动换号。"""
    bal_str = get_balance(frame)
    if not bal_str:
        return True

    state.current_balance = bal_str
    state.last_valid_balance = bal_str
    state.round_current_balance = bal_str
    if state.overlay_root:
        state.overlay_root.after(0, update_score_text)

    try:
        real_val = parse_balance_text_to_value(bal_str)
        if real_val is None:
            return True
        if real_val < MAX_PRICE:
            state.account_round_end_status = "余额不足"
            state.overlay_status = "余额不足"
            ui_print(f"余额不足，当前金额 {bal_str}，准备自动换号", save_log=True)
            print(f"[余额不足] 当前余额：{bal_str}，已触发自动换号")
            async_push_msg("【余额不足】准备换号换区", f"当前余额：{bal_str}，已触发自动换号。")
            state.need_switch_server = True
            return False
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


def wait_and_recognize_balance(wait_time, camera):
    """等待回到交易行，并在此阶段检查余额是否不足。"""
    gc_checkpoint()
    start_total = time.time()
    while time.time() - start_total < 1.4:
        if state.IS_PAUSED:
            return False

        frame = safe_get_frame(camera)
        if frame is not None:
            if is_image_present(frame, MONITOR_JIAOYIHANG, state.temp_jiaoyi, threshold=0.7):
                if not check_balance_limit(frame):
                    return False
                break

        time.sleep(0.05)

    elapsed = time.time() - start_total
    remaining = wait_time - elapsed
    if remaining > 0:
        return smart_wait(remaining)
    return True


def run_purchase_loop(camera, templates, temp_success, temp_shop,
                      temp_goumai, temp_meihuo, temp_diyici):
    """抢购主循环，由 main.py 调用。"""
    from listing import check_trigger_listing

    state.overlay_status = "抢购中"
    state.purchase_timer_active = True
    if not state.IS_PAUSED:
        state.last_resume_time = time.time()
    else:
        state.last_resume_time = None
    ensure_active_runtime_window_state()

    last_refresh = time.time()
    last_frame = None
    last_frame_time = time.time()
    last_abnormal_print_sec = 0
    last_stuck_push_time = time.time()
    last_idle_push_time = time.time()
    last_success_time = time.time()
    last_runtime_state_check = 0.0
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
                        state.need_switch_server = not state.temporary_purchase_mode
                        return

                if (current_time - last_refresh > STUCK_PUSH_INTERVAL and
                        current_time - last_stuck_push_time > STUCK_PUSH_INTERVAL):
                    async_push_msg("【2号电脑】脚本卡顿提醒", "已超过 5 分钟未执行刷新。")
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

                price_action, price_value, price_text = get_price_decision(frame, templates)

                if price_action != "unknown":
                    state.limit_count = 0
                    state.unknown_page_count = 0
                    last_refresh = time.time()
                    price = price_text if price_value is not None else f"前缀识别 {price_text}"

                    if price_action == "accept":
                        fast_click(BUY_POS)
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
                            state.baseline_item_count += 1
                            record_daily_purchase_success()
                            purchase_succeeded = True
                            last_success_time = last_idle_push_time = time.time()
                            if state.overlay_root:
                                state.overlay_root.after(0, update_score_text)
                            ui_print(f"抢购成功，价格：{price}", save_log=True, show_console=False)
                            precise_sleep(0.2)
                            fast_click(SUCCESS_CONFIRM_POS)
                            precise_sleep(0.2)
                            fast_click(SUCCESS_CONFIRM_POS)
                        else:
                            state.fail_count += 1
                            state.round_purchase_fail_count += 1
                            record_daily_purchase_fail()
                            if state.overlay_root:
                                state.overlay_root.after(0, update_score_text)
                            ui_print(f"抢购失败，价格：{price}", save_log=True, show_console=False)
                            click_exit()

                        if wait_and_recognize_balance(EXIT_DELAY, camera):
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
                        ui_print(f"价格不符：{price}", is_replace=True)
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
                                    estimated_total = int(state.baseline_item_count)
                                    state.account_round_end_status = "临时账号限制"
                                    state.overlay_status = "临时账号限制"
                                    async_push_msg(
                                        "【临时账号限制】停止抢购",
                                        f"连续多次店铺为空，已停止临时模式。当前道具库存：{estimated_total}",
                                    )
                                    state.need_switch_server = False
                                    return
                                state.account_round_end_status = "账号限制"
                                state.overlay_status = "账号限制"
                                async_push_msg("【账号限制】准备换号换区", "连续多次店铺为空，已触发自动切号。")
                                state.need_switch_server = True
                                return
                            if not check_balance_limit(frame):
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
                                elif (is_image_present(frame, MONITOR_JIAOYIHANG, state.temp_jiaoyi, threshold=0.6) and
                                      not is_image_present(frame, MONITOR_SHOP, temp_shop, threshold=0.6)):
                                    fast_click(FIX_SHOP_POS1)
                                    precise_sleep(1.0)
                                    fast_click(FIX_SHOP_POS2)
                                elif is_at_gumu(camera):
                                    navigate_to_trade(camera)
                                else:
                                    is_unknown_page = True
                                    state.unknown_page_count += 1
                                    if state.unknown_page_count >= 5:
                                        state.overlay_status = "未知异常"
                                        async_push_msg("【2号电脑】未知页面卡死", "长时间停留在未知页面。")
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
