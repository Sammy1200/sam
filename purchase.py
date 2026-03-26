"""
抢购主循环 + 余额/限制检测 + 推送
"""
import time
import gc
import re
import threading
import requests
import state
from config import (
    MONITOR_SUCCESS, MONITOR_SHOP, MONITOR_JIAOYIHANG, MONITOR_GOUMAI,
    MONITOR_MEIHUO, MONITOR_DIYICI, REFRESH_POS, BUY_POS, CONFIRM_POS,
    SUCCESS_CONFIRM_POS, FIX_SHOP_POS1, FIX_SHOP_POS2, DIYICI_CLICK_POS,
    MAX_PRICE, MIN_PRICE, CONFIRM_DELAY, EXIT_DELAY, MISMATCH_EXIT_DELAY,
    ACCOUNT_LIMIT_THRESHOLD, STUCK_PUSH_INTERVAL, FRAME_MAX_AGE
)
from utils import (
    safe_get_frame, gc_checkpoint, fast_click, press_key,
    precise_sleep, click_exit, get_current_elapsed, smart_wait
)
from vision import (
    is_image_present, get_number, get_balance, crop_frame
)
from overlay import ui_print, update_score_text, toggle_pause


def get_battle_report():
    elapsed = int(get_current_elapsed())
    h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
    bal_str = str(state.current_balance)
    return (
        f"--------------------\n"
        f"💰 当前余额: {bal_str}\n"
        f"✔ 成功抢购: {state.success_count} 次\n"
        f"✖ 失败抢购: {state.fail_count} 次\n"
        f"📦 累计上架: {state.total_listed_count} 件\n"
        f"⏱️ 运行时间: {h}小时{m}分{s}秒"
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


def check_balance_limit(frame):
    bal_str = get_balance(frame)
    if bal_str:
        state.current_balance = bal_str
        if state.overlay_root:
            state.overlay_root.after(0, update_score_text)
        try:
            match = re.search(r'[\d\.]+', bal_str)
            if match:
                num_val = float(match.group())
                if '亿' in bal_str:
                    real_val = int(round(num_val * 100000000))
                elif '万' in bal_str:
                    real_val = int(round(num_val * 10000))
                else:
                    real_val = int(num_val)
                if real_val < 1300001:
                    ui_print(f"🛑 余额不足！金额 {bal_str}，自动暂停。", save_log=True)
                    if not state.IS_PAUSED:
                        toggle_pause()
                    return False
        except:
            pass
    return True


def wait_and_recognize_balance(wait_time, camera):
    gc_checkpoint()
    start_total = time.time()
    while time.time() - start_total < 1.4:
        if state.IS_PAUSED:
            return False
        frame = safe_get_frame(camera)
        if frame is not None:
            if is_image_present(frame, MONITOR_JIAOYIHANG, state.temp_jiaoyi, threshold=0.7):
                check_balance_limit(frame)
                break
        time.sleep(0.05)
    elapsed = time.time() - start_total
    remaining = wait_time - elapsed
    if remaining > 0:
        return smart_wait(remaining)
    return True


def run_purchase_loop(camera, templates, temp_success, temp_shop,
                      temp_goumai, temp_meihuo, temp_diyici):
    """抢购主循环，由 main.py 调用"""
    from listing import check_trigger_listing

    last_refresh = time.time()
    last_frame = None
    last_frame_time = time.time()
    last_abnormal_print_sec = 0
    last_stuck_push_time = time.time()
    last_idle_push_time = time.time()
    last_success_time = time.time()

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

                if (current_time - last_refresh > STUCK_PUSH_INTERVAL and
                        current_time - last_stuck_push_time > STUCK_PUSH_INTERVAL):
                    async_push_msg("🚨 [2号电脑] 脚本卡死警告", "超 5 分钟未执行刷新。")
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

                price = get_number(frame, templates)

                if price is not None:
                    state.limit_count = state.unknown_page_count = 0
                    last_refresh = time.time()

                    if MIN_PRICE < price < MAX_PRICE:
                        fast_click(BUY_POS)
                        precise_sleep(CONFIRM_DELAY)
                        fast_click(CONFIRM_POS)
                        time.sleep(0.8)

                        frame_after = safe_get_frame(camera)
                        if frame_after is not None and is_image_present(frame_after, MONITOR_SUCCESS, temp_success):
                            state.success_count += 1
                            last_success_time = last_idle_push_time = time.time()
                            if state.overlay_root:
                                state.overlay_root.after(0, update_score_text)
                            ui_print(f"✔ 抢到! 识别价格: {price}", save_log=True, show_console=False)
                            precise_sleep(0.2)
                            fast_click(SUCCESS_CONFIRM_POS)
                            precise_sleep(0.2)
                            fast_click(SUCCESS_CONFIRM_POS)
                        else:
                            state.fail_count += 1
                            if state.overlay_root:
                                state.overlay_root.after(0, update_score_text)
                            ui_print(f"✖ 错过! 识别价格: {price}", save_log=True, show_console=False)
                            click_exit()

                        if wait_and_recognize_balance(EXIT_DELAY, camera):
                            check_trigger_listing(camera)
                            fast_click(REFRESH_POS)
                            last_refresh = time.time()
                    else:
                        ui_print(f"⏭️ 价格不符: {price}", is_replace=True)
                        click_exit()
                        if wait_and_recognize_balance(MISMATCH_EXIT_DELAY, camera):
                            check_trigger_listing(camera)
                            fast_click(REFRESH_POS)
                            last_refresh = time.time()
                else:
                    if is_image_present(frame, MONITOR_MEIHUO, temp_meihuo):
                        state.unknown_page_count = 0
                        ui_print("⚡ 识别到售空！", is_replace=True)
                        click_exit()
                        if wait_and_recognize_balance(EXIT_DELAY, camera):
                            check_trigger_listing(camera)
                            fast_click(REFRESH_POS)
                            last_refresh = time.time()
                        continue

                    time_since_last_action = time.time() - last_refresh
                    if time_since_last_action > 3.0:
                        is_normal_empty = (
                            is_image_present(frame, MONITOR_JIAOYIHANG, state.temp_jiaoyi) and
                            is_image_present(frame, MONITOR_SHOP, temp_shop))
                        if is_normal_empty:
                            state.limit_count += 1
                            state.unknown_page_count = 0
                            ui_print(f"🔄 店铺空置 ({state.limit_count}/{ACCOUNT_LIMIT_THRESHOLD})",
                                     is_replace=True)
                            if state.limit_count >= ACCOUNT_LIMIT_THRESHOLD:
                                async_push_msg("🛑 [2号电脑] 账号被限", "连续多次店铺为空，自动休眠。")
                                state.limit_count = 0
                                if not state.IS_PAUSED:
                                    toggle_pause()
                                continue
                            if not check_balance_limit(frame):
                                continue
                            check_trigger_listing(camera)
                            fast_click(REFRESH_POS)
                            gc_checkpoint()
                            last_refresh = time.time()
                        else:
                            if state.unknown_page_count == 0 or time_since_last_action > 10.0:
                                ui_print("\n⚠️ 画面异常！全场景识别...", save_log=True)
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
                                else:
                                    is_unknown_page = True
                                    state.unknown_page_count += 1
                                    if state.unknown_page_count >= 20:
                                        async_push_msg("🚨 [2号电脑] 未知死锁", "长时卡在未知页面。")
                                        state.unknown_page_count = 0
                                        if not state.IS_PAUSED:
                                            toggle_pause()
                                    else:
                                        last_refresh = time.time()
                                        last_abnormal_print_sec = 0

                                if not is_unknown_page:
                                    state.unknown_page_count = 0
                                    if smart_wait(1.0):
                                        check_trigger_listing(camera)
                                        fast_click(REFRESH_POS)
                                        last_refresh = time.time()
                            else:
                                current_sec = int(time_since_last_action)
                                if current_sec != last_abnormal_print_sec:
                                    ui_print(f"⏳ 等待场景识别介入 ({current_sec}s/10s)",
                                             is_replace=True)
                                    last_abnormal_print_sec = current_sec

                time.sleep(0.002)
            except Exception:
                time.sleep(0.5)
    finally:
        camera.stop()
