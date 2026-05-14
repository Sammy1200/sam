"""
Switch helpers for launcher/server/account flow.

Public APIs:
  startup_from_launcher(camera, server_index)
  startup_accessory_from_server_list(camera, server_index)
  enter_accessory_trade_from_current_scene(camera)
  full_switch_server(camera, server_index)
  is_at_gumu(camera)
  navigate_to_trade(camera)
  pause_thread6_failure(step_name, detail)
  enter_startup_listing_target_slot(camera, target_execution_slot, ...)
  resolve_execution_slot_transition(current_execution_slot)
  switch_server_within_account_after_slot_boundary(camera)
  switch_account_after_slot_boundary(camera)
  switch_account_for_temporary_target_slot(camera, target_execution_slot)
  wait_for_verified_slot_cooldown_before_launch(slot_number, ...)
"""

import ctypes
import os
import time
import traceback
from ctypes import wintypes
from datetime import datetime, timedelta

import cv2
import pyautogui

import config
import state
from account_db import (
    ACCOUNT_DB_MODE_ACCESSORY,
    ACCOUNT_DB_MODE_STONE,
    CANONICAL_ACCOUNT_STATS_TABLE,
    ROUND_STATUS_RUNNING,
    ensure_account_stats_store_for_mode,
    find_account_stats_store_for_mode,
    find_canonical_account_stats_store,
    read_preferred_canonical_account_stats_record_by_execution_slot,
    restore_ready_account_status_if_needed,
    update_canonical_account_status_fields,
)
from local_switch_account_config import (
    get_execution_slot_count,
    get_execution_slot_nickname_template_files,
    get_execution_slot_server_coord_indexes,
    load_boundary_switch_accounts,
    load_execution_slot_config,
    load_local_nickname_match_config,
    resolve_account_switch_source_slot_for_execution_slot,
    resolve_execution_slot_account_index,
)
from round_persistence import mature_stone_unlocks_for_current_account
from overlay import toggle_pause, ui_print
from utils import (
    async_push_msg,
    fast_click,
    flush_logger_handlers,
    get_clipboard_text,
    hotkey,
    logger,
    press_key,
    push_msg_sync,
    restore_overlay,
    safe_get_frame,
    safe_sleep,
    set_overlay_mini,
    type_digits,
    update_overlay_mini,
)


_TPL_CACHE = {}
_ACCESSORY_DIANPU_TEMPLATE = None
_ACCESSORY_TRADE_PAGE_TEMPLATE = None
_TPL_FILES = {
    "f4": "f4queding.png",
    "qd": "qidong.png",
    "kg": "kongge.png",
    "1tc": "1tanchuang.png",
    "gumu": "gumudating.png",
    "qiehuan": "qiehuan.png",
    "denglu": "denglu.png",
    "heping": "hepingjingying.png",
    "shoucan": "shoucan.png",
}
_BOUNDARY_SWITCH_ACCOUNTS_CACHE = None
_LOCAL_NICKNAME_MATCH_CONFIG_CACHE = None
_SWITCH_WAIT_STEP_LABELS = {
    "boundary start qidong check": "边界启动页确认",
    "switch-user entry": "进入切号入口",
    "account input verify": "账号输入校验",
    "heping verify": "切号结果确认",
    "denglu click": "点击登录按钮",
    "nickname verify": "昵称模板校验",
    "server list": "打开大区列表",
    "server select": "选择目标大区",
}
_SWITCH_WAIT_KEY_LABELS = {
    "retry_count": "重试次数",
    "retry_interval": "重试间隔秒数",
    "fixup_retry_count": "修复后重试次数",
    "fixup_retry_interval": "修复后重试间隔秒数",
    "click_wait": "点击后等待秒数",
    "entry_timeout": "入口识别超时秒数",
    "login_click_wait": "登录点击后等待秒数",
    "login_timeout": "登录页识别超时秒数",
    "login_retry_count": "登录页重试次数",
    "verify_wait": "校验等待秒数",
    "heping_timeout": "和平精英页识别超时秒数",
    "maximize_wait": "窗口最大化等待秒数",
    "select_wait": "选区后等待秒数",
    "verify_timeout": "识别超时秒数",
    "open_wait": "打开列表前等待秒数",
    "qidong_timeout": "启动按钮识别超时秒数",
}
_GOLD_STEP_SKIP_CLOSE = "skip_close"
_GOLD_STEP_NEED_CLOSE = "need_close"


def _schedule_status_change_snapshot(event_name):
    try:
        from remote_sync import schedule_local_snapshot_report
    except Exception as exc:
        logger.warning("[网页同步] 状态变更快照模块加载失败：event=%s error=%s", event_name, exc)
        return

    try:
        result = schedule_local_snapshot_report(event_name)
    except Exception as exc:
        logger.warning("[网页同步] 状态变更快照触发失败：event=%s error=%s", event_name, exc)
        return

    status = str(result.get("status") or "").strip()
    if status == "scheduled":
        logger.info("[网页同步] 已安排状态变更最小快照：%s", event_name)
    elif status == "error":
        logger.warning("[网页同步] 状态变更最小快照失败：event=%s reason=%s", event_name, result.get("message"))


def _format_cooldown_duration(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _resolve_canonical_store_for_switch():
    database_path = str(state.account_db_path or "").strip()
    table_name = str(state.account_db_table_name or "").strip() or CANONICAL_ACCOUNT_STATS_TABLE
    if database_path:
        return database_path, table_name

    if bool(getattr(state, "accessory_purchase_mode", False)):
        account_db_mode = ACCOUNT_DB_MODE_ACCESSORY
        database_path, table_name = find_account_stats_store_for_mode(account_db_mode, table_name)
        if not database_path:
            database_path, table_name, _ = ensure_account_stats_store_for_mode(account_db_mode, table_name)
        if database_path:
            state.account_db_path = database_path
            state.account_db_table_name = table_name or CANONICAL_ACCOUNT_STATS_TABLE
            state.account_db_mode = account_db_mode
            return state.account_db_path, state.account_db_table_name
        return "", table_name

    database_path, table_name = find_canonical_account_stats_store()
    if database_path:
        state.account_db_path = database_path
        state.account_db_table_name = table_name or CANONICAL_ACCOUNT_STATS_TABLE
        state.account_db_mode = ACCOUNT_DB_MODE_STONE
        return state.account_db_path, state.account_db_table_name

    return "", table_name


def _freeze_switch_cooldown_timer():
    was_active = bool(getattr(state, "purchase_timer_active", False))
    if was_active and not state.IS_PAUSED and state.last_resume_time is not None:
        state.total_running_time += time.time() - state.last_resume_time
    state.last_resume_time = None
    state.purchase_timer_active = False
    return was_active


def _apply_verified_slot_record_to_state(record, allow_start_time=None, allow_purchase=True):
    if record is None:
        return
    state.current_nickname = record.nickname
    state.baseline_item_count = record.baseline_item_count
    state.locked_item_count = record.locked_item_count
    state.tradable_item_count = record.tradable_item_count
    state.next_tradable_at = record.next_tradable_at
    state.last_limit_time = record.last_limit_time
    state.last_account_end_time = record.last_account_end_time
    state.updated_at = record.updated_at
    if record.current_execution_slot is not None:
        state.current_execution_slot = record.current_execution_slot
    state.round_status = record.round_status
    state.account_record_loaded = True
    state.account_allow_purchase = bool(allow_purchase)
    state.account_allow_start_time = allow_start_time or datetime.now()
    state.account_read_status = "ready" if allow_purchase else "waiting_limit_time"
    state.account_is_waiting = not allow_purchase
    mature_stone_unlocks_for_current_account("换号读账号后")
    state.account_read_error = ""
    state.overlay_status = "抢购中" if allow_purchase else "等待抢购时间"


def wait_for_verified_slot_cooldown_before_launch(
    slot_number,
    sync_running_status_after_wait=False,
):
    """昵称校验后、点击启动游戏前，若目标账号仍冷却则停留选区页等待。"""
    database_path, table_name = _resolve_canonical_store_for_switch()
    if not database_path:
        logger.warning("[冷却等待] 未找到 canonical 数据库，跳过执行位 %s 的启动前冷却等待。", slot_number)
        if sync_running_status_after_wait:
            _sync_verified_slot_status_to_running(slot_number)
        return True

    record = read_preferred_canonical_account_stats_record_by_execution_slot(
        database_path,
        slot_number,
        table_name,
    )
    if record is None:
        logger.warning("[冷却等待] 执行位 %s 未解析到账号记录，跳过启动前冷却等待。", slot_number)
        if sync_running_status_after_wait:
            _sync_verified_slot_status_to_running(slot_number)
        return True

    state.account_db_path = database_path
    state.account_db_table_name = table_name
    now = datetime.now()
    allow_start_time = now
    if record.last_limit_time is not None:
        allow_start_time = record.last_limit_time + timedelta(
            seconds=config.ACCOUNT_LIMIT_COOLDOWN_SECONDS
        )

    if record.last_limit_time is None or now >= allow_start_time:
        restored_record, restore_result = restore_ready_account_status_if_needed(
            database_path,
            record.nickname,
            table_name,
            now=now,
        )
        if restore_result.status == "success" and restored_record is not None:
            record = restored_record
            _schedule_status_change_snapshot("启动前冷却结束自动恢复已准备")
            logger.info("[冷却等待] 执行位 %s 冷却已结束，账号状态已恢复为“已准备”。", slot_number)
        elif restore_result.status not in ("skipped", "account_not_found"):
            logger.warning("[冷却等待] 执行位 %s 自动恢复“已准备”失败：%s", slot_number, restore_result.reason)
        _apply_verified_slot_record_to_state(record, allow_start_time=datetime.now(), allow_purchase=True)
        if sync_running_status_after_wait:
            _sync_verified_slot_status_to_running(slot_number)
        return True

    _freeze_switch_cooldown_timer()
    state.account_allow_purchase = False
    state.account_allow_start_time = allow_start_time
    state.account_read_status = "waiting_limit_time"
    state.account_is_waiting = True
    state.overlay_status = "等待抢购时间"
    _apply_verified_slot_record_to_state(record, allow_start_time=allow_start_time, allow_purchase=False)

    print(
        f"[冷却等待] 执行位 {slot_number} 昵称 {record.nickname} 冷却未结束，"
        f"停留选区页等待至 {allow_start_time.strftime('%Y-%m-%d %H:%M:%S')}。"
    )
    logger.info(
        "[冷却等待] 执行位 %s 昵称 %s 冷却未结束，停留选区页等待至 %s。",
        slot_number,
        record.nickname,
        allow_start_time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    while True:
        remaining_seconds = (allow_start_time - datetime.now()).total_seconds()
        if remaining_seconds <= 0:
            break
        display_seconds = max(1, int(remaining_seconds + 0.999))
        update_overlay_mini(f"冷却 {_format_cooldown_duration(display_seconds)}")
        time.sleep(0.5 if state.IS_PAUSED else min(1.0, max(0.1, remaining_seconds)))

    restored_record, restore_result = restore_ready_account_status_if_needed(
        database_path,
        record.nickname,
        table_name,
        now=datetime.now(),
    )
    if restore_result.status == "success" and restored_record is not None:
        record = restored_record
        _schedule_status_change_snapshot("启动前冷却等待结束")
    elif restored_record is not None:
        record = restored_record
    elif restore_result.status not in ("skipped", "account_not_found"):
        logger.warning("[冷却等待] 等待结束后恢复“已准备”失败：%s", restore_result.reason)

    _apply_verified_slot_record_to_state(record, allow_start_time=datetime.now(), allow_purchase=True)
    update_overlay_mini("冷却结束")
    if sync_running_status_after_wait:
        _sync_verified_slot_status_to_running(slot_number)
    print(f"[冷却等待] 执行位 {slot_number} 冷却结束，继续启动游戏。")
    logger.info("[冷却等待] 执行位 %s 冷却结束，继续启动游戏。", slot_number)
    return True


def _get_window_text(hwnd):
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
    return str(buffer.value or "").strip()


def _find_window_by_title_fragment(title_fragment, prefer_exact_title=None):
    if os.name != "nt":
        return None, ""

    title_fragment = str(title_fragment or "").strip()
    if not title_fragment:
        return None, ""

    user32 = ctypes.windll.user32
    matches = []
    enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @enum_windows_proc
    def _enum_proc(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True

        title = _get_window_text(hwnd)
        if title_fragment.lower() in title.lower():
            matches.append((hwnd, title))
        return True

    user32.EnumWindows(_enum_proc, 0)
    if not matches:
        return None, ""

    exact_title = str(prefer_exact_title or "").strip()
    matches.sort(key=lambda item: (0 if exact_title and item[1] == exact_title else 1, len(item[1])))
    return matches[0]


def _try_bring_window_to_front(title_fragment, label, prefer_exact_title=None, wait_seconds=None):
    if os.name != "nt":
        return False

    hwnd, title = _find_window_by_title_fragment(title_fragment, prefer_exact_title=prefer_exact_title)
    if hwnd is None:
        logger.info("[切换流程] 未找到%s窗口：title_fragment=%s", label, title_fragment)
        return False

    user32 = ctypes.windll.user32
    sw_restore = 9
    sw_showmaximized = 3
    swp_nomove = 0x0002
    swp_nosize = 0x0001
    swp_showwindow = 0x0040

    try:
        logger.info("[切换流程] 尝试将%s窗口拉到前台：title=%s hwnd=%s", label, title, hwnd)
        user32.ShowWindow(hwnd, sw_restore)
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, swp_nomove | swp_nosize | swp_showwindow)
        user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, swp_nomove | swp_nosize | swp_showwindow)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.ShowWindow(hwnd, sw_showmaximized)
        if wait_seconds is None:
            wait_seconds = config.SWITCH_MAXIMIZE_WAIT_SECONDS
        safe_sleep(wait_seconds)
        logger.info("[切换流程] 已尝试将%s窗口拉到前台。", label)
        return True
    except Exception as exc:
        logger.warning("[切换流程] 拉起%s窗口失败：%s", label, exc)
        return False


def _try_bring_wegame_to_front():
    return _try_bring_window_to_front("wegame", "WeGame", prefer_exact_title="WeGame")


def _try_bring_game_window_to_front():
    return _try_bring_window_to_front(
        config.SWITCH_GAME_WINDOW_TITLE,
        "游戏",
        wait_seconds=config.SWITCH_GAME_WINDOW_FOREGROUND_WAIT_SECONDS,
    )


def _tpl(key):
    """按需加载模板并缓存。"""
    if key not in _TPL_CACHE:
        path = os.path.join("logo", "huanhao", _TPL_FILES[key])
        img = cv2.imread(path)
        if img is None:
            logger.error("[切换流程] 模板缺失：%s", path)
        _TPL_CACHE[key] = img
    return _TPL_CACHE[key]


def _accessory_dianpu_tpl():
    """按需加载饰品交易行店铺确认模板。"""
    global _ACCESSORY_DIANPU_TEMPLATE
    if _ACCESSORY_DIANPU_TEMPLATE is None:
        path = os.path.join("logo", "tezhengtu", "dianpu.png")
        img = cv2.imread(path)
        if img is None:
            logger.error("[饰品抢购] 模板缺失：%s", path)
        _ACCESSORY_DIANPU_TEMPLATE = img
    return _ACCESSORY_DIANPU_TEMPLATE


def _accessory_trade_page_tpl():
    """按需加载饰品交易行页面模板。"""
    global _ACCESSORY_TRADE_PAGE_TEMPLATE
    if _ACCESSORY_TRADE_PAGE_TEMPLATE is None:
        path = os.path.join("logo", "tezhengtu", "shipinjiaoyihang.png")
        img = cv2.imread(path)
        if img is None:
            logger.error("[饰品抢购] 模板缺失：%s", path)
        _ACCESSORY_TRADE_PAGE_TEMPLATE = img
    return _ACCESSORY_TRADE_PAGE_TEMPLATE


def _normalize_match_image(img):
    if img is None or img.size == 0:
        return None
    if len(img.shape) == 2:
        normalized = img
    else:
        channels = img.shape[2]
        if channels == 4:
            normalized = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
        elif channels == 3:
            normalized = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            return None
    if normalized.dtype.name not in ("uint8", "float32"):
        normalized = normalized.astype("uint8", copy=False)
    return normalized


def _match_image(camera, template, region, threshold=0.8):
    """对指定区域执行单次模板匹配。"""
    frame = safe_get_frame(camera)
    if frame is None:
        return False
    x1, y1, x2, y2 = region
    roi = frame[y1:y2, x1:x2]
    roi = _normalize_match_image(roi)
    tpl = _normalize_match_image(template)
    if roi is None or tpl is None:
        return False
    th, tw = tpl.shape[:2]
    rh, rw = roi.shape[:2]
    if rh < th or rw < tw:
        return False
    res = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
    _, val, _, _ = cv2.minMaxLoc(res)
    return val >= threshold


def _match_image_center(camera, template, region, threshold=0.8):
    """返回模板匹配中心坐标。"""
    frame = safe_get_frame(camera)
    if frame is None:
        return None
    x1, y1, x2, y2 = region
    roi = frame[y1:y2, x1:x2]
    roi = _normalize_match_image(roi)
    tpl = _normalize_match_image(template)
    if roi is None or tpl is None:
        return None
    th, tw = tpl.shape[:2]
    rh, rw = roi.shape[:2]
    if rh < th or rw < tw:
        return None
    res = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
    _, val, _, max_loc = cv2.minMaxLoc(res)
    if val < threshold:
        return None
    center_x = x1 + max_loc[0] + tw // 2
    center_y = y1 + max_loc[1] + th // 2
    return center_x, center_y


def _match(camera, key, region, threshold=0.8):
    """执行单次模板匹配。"""
    return _match_image(camera, _tpl(key), region, threshold=threshold)


def _match_center(camera, key, region, threshold=0.8):
    """返回模板匹配中心坐标。"""
    return _match_image_center(camera, _tpl(key), region, threshold=threshold)


def _wait_for(camera, key, region, timeout, threshold=0.8):
    """等待模板出现，并再次确认一次。"""
    end = time.time() + timeout
    while time.time() < end:
        if _match(camera, key, region, threshold=threshold):
            safe_sleep(1)
            if _match(camera, key, region, threshold=threshold):
                return True
        safe_sleep(1)
    return False


def _wait_for_match_center(camera, key, region, timeout, threshold=0.8):
    """等待模板出现并返回中心坐标。"""
    end = time.time() + timeout
    while time.time() < end:
        center = _match_center(camera, key, region, threshold=threshold)
        if center is not None:
            return center
        safe_sleep(1)
    return None


def _pixels_white(camera):
    """检查两个探针像素是否都接近白色。"""
    frame = safe_get_frame(camera)
    if frame is None:
        return False
    for (x, y) in [(190, 58), (227, 55)]:
        if y >= frame.shape[0] or x >= frame.shape[1]:
            return False
        b, g, r = int(frame[y, x, 0]), int(frame[y, x, 1]), int(frame[y, x, 2])
        if not (r >= 250 and g >= 250 and b >= 250):
            return False
    return True


def _confirm_white(camera):
    """0.5 秒后再次确认白色像素。"""
    if not _pixels_white(camera):
        return False
    # 白点刚出现时页面可能还在轻微过渡，这里缩短为 0.5 秒复检，既保留二次确认又减少阻塞。
    safe_sleep(config.SWITCH_WHITE_CONFIRM_INTERVAL_SECONDS)
    return _pixels_white(camera)


def _detect_launcher_state(camera):
    """识别当前是否位于启动页，以及是否处于非全屏状态。"""
    heping_center = _match_center(
        camera,
        "heping",
        config.SWITCH_HEPING_REGION_PRIMARY,
        threshold=config.SWITCH_UI_MATCH_THRESHOLD,
    )
    if heping_center is not None:
        return "launcher_fullscreen", heping_center

    heping_center = _match_center(
        camera,
        "heping",
        config.SWITCH_HEPING_REGION_SECONDARY,
        threshold=config.SWITCH_UI_MATCH_THRESHOLD,
    )
    if heping_center is not None:
        return "launcher_windowed", heping_center

    return "unknown", None


def _click_launcher_heping_center(heping_center):
    """已确认在启动页时，先点击 heping 中心点，再继续后续启动页点击任务。"""
    if heping_center is None:
        return False

    print("[切换流程] 已识别到启动页，先点击 heping 中心点。")
    logger.info("[切换流程] 已识别到启动页，先点击 heping 中心点。")
    fast_click(heping_center)
    safe_sleep(config.SWITCH_DETECTED_CLICK_DELAY_SECONDS)
    return True


def _restore_launcher_fullscreen_from_heping_center(heping_center):
    """命中启动页非全屏模板后，先点击中心点，再恢复全屏。"""
    if heping_center is None:
        return False

    print("[切换流程] 识别到启动页非全屏，点击中心点后恢复全屏。")
    logger.info("[切换流程] 识别到启动页非全屏，点击中心点后恢复全屏。")
    fast_click(heping_center)
    safe_sleep(config.SWITCH_DETECTED_CLICK_DELAY_SECONDS)
    pyautogui.hotkey("winleft", "up")
    safe_sleep(config.SWITCH_MAXIMIZE_WAIT_SECONDS)
    return True


def _check_launcher_ready_with_heping_fix(camera):
    """统一判断启动页状态；仅 heping 命中才视为已识别到启动页。"""
    launcher_state, heping_center = _detect_launcher_state(camera)
    if launcher_state == "launcher_fullscreen":
        return True, launcher_state

    if launcher_state == "launcher_windowed":
        if not _restore_launcher_fullscreen_from_heping_center(heping_center):
            return False, "windowed_no_center"
        launcher_state, _ = _detect_launcher_state(camera)
        if launcher_state == "launcher_fullscreen":
            return True, f"restored_{launcher_state}"
        return False, "restored_unknown"

    return False, launcher_state


def _wait_for_launcher_heping_ready(camera, timeout_seconds):
    """等待启动页 heping 出现；若首次未识别到则尝试拉前台后重试。"""
    end_time = time.time() + max(0.1, float(timeout_seconds))
    while time.time() < end_time:
        launcher_ready, launcher_source = _check_launcher_ready_with_heping_fix(camera)
        if launcher_ready:
            return True, launcher_source
        safe_sleep(0.5)

    logger.info("[切换流程] 未识别到启动页，尝试将 WeGame 拉到前台。")
    if _try_bring_wegame_to_front():
        for _ in range(3):
            launcher_ready, launcher_source = _check_launcher_ready_with_heping_fix(camera)
            if launcher_ready:
                return True, launcher_source
            safe_sleep(0.5)

    return False, "launcher_not_detected"


def _ensure_launcher_click_ready(camera):
    """启动页点击统一前置守卫：先识别 heping，必要时拉前台，再点中心点。"""
    launcher_state, heping_center = _detect_launcher_state(camera)
    if launcher_state == "unknown":
        logger.info("[切换流程] 启动页点击前未识别到 heping，尝试将 WeGame 拉到前台。")
        if _try_bring_wegame_to_front():
            launcher_state, heping_center = _detect_launcher_state(camera)

    if launcher_state == "launcher_fullscreen":
        if _click_launcher_heping_center(heping_center):
            return True, ""
        return False, "已识别到启动页，但未定位到 hepingjingying.png 中心点。"

    if launcher_state == "launcher_windowed":
        if not _restore_launcher_fullscreen_from_heping_center(heping_center):
            return False, "识别到启动页非全屏，但未定位到 hepingjingying.png 中心点。"
        launcher_state, _ = _detect_launcher_state(camera)
        if launcher_state == "launcher_fullscreen":
            return True, ""
        return False, "识别到启动页非全屏，恢复全屏后仍未确认启动页。"

    return False, "未识别到启动页（hepingjingying.png），拉前台重试后仍失败。"


def _find_exact_rgb_point(camera, region, target_rgb, tolerance=0):
    """在指定区域内查找 RGB 颜色，返回首个命中的绝对坐标。"""
    frame = safe_get_frame(camera)
    if frame is None:
        return None

    x1, y1, x2, y2 = region
    if x1 >= x2 or y1 >= y2:
        return None
    if y2 > frame.shape[0] or x2 > frame.shape[1]:
        return None

    target_r, target_g, target_b = (int(target_rgb[0]), int(target_rgb[1]), int(target_rgb[2]))
    tolerance = int(max(0, tolerance))
    for y in range(y1, y2):
        for x in range(x1, x2):
            pixel = frame[y, x]
            b, g, r = int(pixel[0]), int(pixel[1]), int(pixel[2])
            if (
                abs(r - target_r) <= tolerance
                and abs(g - target_g) <= tolerance
                and abs(b - target_b) <= tolerance
            ):
                return x, y
    return None


def _click_detected_point(point):
    """统一处理识别成功后的点击延迟。"""
    if point is None:
        return
    time.sleep(config.SWITCH_DETECTED_CLICK_DELAY_SECONDS)
    fast_click(point)


def try_return_to_gumu(camera, retry_count=3):
    """非阻断返回古墓大厅；失败时仅返回 False。"""
    for _ in range(retry_count):
        for attempt in range(config.SWITCH_RETURN_GUMU_CLOSE_CLICK_COUNT):
            fast_click(config.SWITCH_RETURN_GUMU_CLOSE_POS)
            time.sleep(config.SWITCH_RETURN_GUMU_CLOSE_CLICK_INTERVAL_SECONDS)
            press_key(0x1B)
            if attempt < config.SWITCH_RETURN_GUMU_CLOSE_CLICK_COUNT - 1:
                time.sleep(config.SWITCH_RETURN_GUMU_CLOSE_CLICK_INTERVAL_SECONDS)

        time.sleep(config.SWITCH_DETECTED_CLICK_DELAY_SECONDS)
        fast_click(config.SWITCH_RETURN_GUMU_CONFIRM_POS)
        if _wait_for(
            camera,
            "gumu",
            config.RGN_GUMU,
            timeout=config.SWITCH_RETURN_GUMU_VERIFY_TIMEOUT_SECONDS,
            threshold=config.SWITCH_UI_MATCH_THRESHOLD,
        ):
            return True
    return False


def _return_to_gumu_or_fail(camera, reason):
    """统一执行返回古墓大厅固定操作，失败时走现有暂停/推送治理出口。"""
    if try_return_to_gumu(camera, retry_count=config.SWITCH_RETURN_GUMU_RETRY_COUNT):
        return True

    ui_print("返回古墓失败", save_log=True)
    return pause_thread6_failure("返回古墓大厅", reason)


def _pause_switch_flow(title, detail):
    """失败时推送并停在当前界面。"""
    state.switch_flow_paused = True
    state.switch_last_unknown_detail = detail
    state.overlay_status = "未知异常"
    print(detail)
    logger.error(detail)
    restore_overlay()
    if not state.IS_PAUSED:
        toggle_pause()
    flush_logger_handlers()
    try:
        push_msg_sync(title, detail)
    except Exception as exc:
        push_fail_message = f"[线程6] 微信推送发送失败：{exc}"
        print(push_fail_message)
        logger.error(push_fail_message)
        flush_logger_handlers()
    block_message = "[线程6] 已进入阻塞停机，请人工确认后按任意键继续。"
    print(block_message)
    logger.error(block_message)
    flush_logger_handlers()
    os.system('pause')


def pause_thread6_failure(step_name, detail):
    """线程 6 统一失败出口：日志、微信推送、暂停。"""
    message = f"[\u7ebf\u7a0b6] \u5931\u8d25\u6b65\u9aa4\uff1a{step_name}\uff1b{detail}"
    _pause_switch_flow(f"[\u7ebf\u7a0b6] {step_name}\u5931\u8d25", message)
    return False


def _pause_thread6_exception(step_name, exc):
    """线程 6 异常统一失败出口。"""
    logger.error("[线程6] 步骤 %s 出现未处理异常：%s", step_name, exc)
    logger.error(traceback.format_exc())
    return pause_thread6_failure(step_name, f"出现未处理异常：{exc}")


def _run_thread6_step(step_name, detail, fn):
    """线程 6 步骤级统一守卫。"""
    logger.info("[线程6] 步骤开始：%s", step_name)
    try:
        result = fn()
    except Exception as exc:
        return _pause_thread6_exception(step_name, exc)

    if result:
        logger.info("[线程6] 步骤完成：%s", step_name)
        return True

    if state.switch_flow_paused:
        logger.info("[线程6] 步骤失败已由下层处理：%s", step_name)
        return False

    return pause_thread6_failure(step_name, detail)


def _run_thread6_chain(chain_name, fn):
    """线程 6 链路级统一守卫。"""
    logger.info("[线程6] 链路开始：%s", chain_name)
    try:
        result = fn()
    except Exception as exc:
        return _pause_thread6_exception(chain_name, exc)

    if result:
        logger.info("[线程6] 链路完成：%s", chain_name)
        return True

    if state.switch_flow_paused:
        logger.info("[线程6] 链路失败已由下层处理：%s", chain_name)
        return False

    return pause_thread6_failure(chain_name, "链路执行失败，但未命中具体步骤级失败出口。")


def _wait_for_boundary_start_qidong(camera):
    """边界换号时，先确认是否已回到启动页面。"""
    _log_switch_waits(
        "boundary start qidong check",
        retry_count=config.SWITCH_BOUNDARY_START_QIDONG_RETRY_COUNT,
        retry_interval=config.SWITCH_BOUNDARY_START_QIDONG_RETRY_INTERVAL_SECONDS,
        fixup_retry_count=config.SWITCH_BOUNDARY_START_QIDONG_FIXUP_RETRY_COUNT,
        fixup_retry_interval=config.SWITCH_BOUNDARY_START_QIDONG_FIXUP_RETRY_INTERVAL_SECONDS,
    )
    timeout_seconds = (
        config.SWITCH_BOUNDARY_START_QIDONG_RETRY_COUNT
        * config.SWITCH_BOUNDARY_START_QIDONG_RETRY_INTERVAL_SECONDS
    )
    launcher_ready, launcher_source = _wait_for_launcher_heping_ready(camera, timeout_seconds)
    if launcher_ready:
        if str(launcher_source).startswith("restored_"):
            print("[切换流程] 修复全屏后已确认启动页。")
            logger.info("[切换流程] 修复全屏后已确认启动页。")
        else:
            print("[切换流程] 已识别到启动页。")
            logger.info("[切换流程] 已识别到启动页。")
        return True

    return pause_thread6_failure(
        "返回启动页确认",
        "未能在边界切换前确认回到启动页（hepingjingying.png 未匹配）。",
    )


def _get_boundary_switch_accounts():
    """读取并缓存 4 区后 / 8 区后的本机换号账号配置。"""
    global _BOUNDARY_SWITCH_ACCOUNTS_CACHE

    if _BOUNDARY_SWITCH_ACCOUNTS_CACHE is None:
        accounts, source_path = load_boundary_switch_accounts()
        _BOUNDARY_SWITCH_ACCOUNTS_CACHE = accounts
        message = f"[线程6] 已加载本机换号配置文件：{os.path.basename(source_path)}"
        print(message)
        logger.info(message)

    return _BOUNDARY_SWITCH_ACCOUNTS_CACHE


def _get_local_nickname_match_config():
    """读取并缓存本机昵称模板配置。"""
    global _LOCAL_NICKNAME_MATCH_CONFIG_CACHE

    if _LOCAL_NICKNAME_MATCH_CONFIG_CACHE is None:
        nickname_match_config, source_path = load_local_nickname_match_config()
        _LOCAL_NICKNAME_MATCH_CONFIG_CACHE = nickname_match_config
        message = (
            f"[线程6] 已加载本机昵称模板配置：文件={os.path.basename(source_path)}，"
            f"模板目录={nickname_match_config['template_dir']}，"
            f"识别区域={nickname_match_config['verify_region']}，"
            f"阈值={nickname_match_config['match_threshold']}"
        )
        print(message)
        logger.info(message)

    return _LOCAL_NICKNAME_MATCH_CONFIG_CACHE


def resolve_execution_slot_transition(current_execution_slot):
    """根据当前执行位解析下一目标执行位和切换类型。"""
    try:
        current_slot = int(current_execution_slot)
    except (TypeError, ValueError):
        return None

    try:
        execution_slot_config, _ = load_execution_slot_config()
    except Exception:
        raise

    next_slot = execution_slot_config["next_slot_map"].get(current_slot)
    if next_slot is None:
        return None

    slot_index = next_slot - 1
    server_coord_indexes = execution_slot_config["server_coord_indexes"]
    if slot_index < 0 or slot_index >= len(server_coord_indexes):
        return None

    requires_account_switch = current_slot in execution_slot_config["switch_targets"]
    account_id = None
    config_error = ""

    if requires_account_switch:
        try:
            account_id = _get_boundary_switch_accounts().get(current_slot)
        except Exception as exc:
            config_error = f"本机换号配置读取失败：{exc}"
        if not config_error and not account_id:
            config_error = f"本机换号配置缺少执行位 {current_slot} 的换号账号。"

    return {
        "current_slot": current_slot,
        "next_slot": next_slot,
        "account_id": account_id,
        "server_coord_index": server_coord_indexes[slot_index],
        "requires_account_switch": requires_account_switch,
        "config_error": config_error,
    }


def _resolve_switch_target(current_execution_slot):
    """根据当前执行位解析小阶段目标执行位。"""
    target = resolve_execution_slot_transition(current_execution_slot)
    if not target or not target["requires_account_switch"]:
        return None
    return target


def _resolve_account_id_for_execution_slot_group(slot_number):
    """按执行位所属账号组，沿用本机换号配置解析目标账号。"""
    try:
        normalized_slot_number = int(slot_number)
    except (TypeError, ValueError):
        return None, "目标执行位不是有效整数。"

    try:
        server_coord_indexes = get_execution_slot_server_coord_indexes()
    except Exception as exc:
        return None, f"本机执行位配置读取失败：{exc}"

    if normalized_slot_number < 1 or normalized_slot_number > len(server_coord_indexes):
        return None, f"目标执行位 {normalized_slot_number} 超出有效范围。"

    try:
        boundary_accounts = _get_boundary_switch_accounts()
    except Exception as exc:
        return None, f"本机换号配置读取失败：{exc}"

    source_slot = resolve_account_switch_source_slot_for_execution_slot(normalized_slot_number)
    if source_slot is None:
        return None, f"本机执行位配置缺少执行位 {normalized_slot_number} 对应的跨账号边界。"

    account_id = boundary_accounts.get(source_slot)
    if not account_id:
        return None, f"本机换号配置缺少 after_slot_{source_slot}_account_id。"
    return account_id, ""


def _build_temporary_target_transition(target_execution_slot):
    """临时模式结束后，直接解析目标执行位对应的账号组和大区。"""
    try:
        target_slot = int(target_execution_slot)
    except (TypeError, ValueError):
        return {
            "target_slot": None,
            "account_id": None,
            "server_coord_index": None,
            "config_error": "目标执行位不是有效整数。",
        }

    try:
        server_coord_indexes = get_execution_slot_server_coord_indexes()
    except Exception as exc:
        return {
            "target_slot": target_slot,
            "account_id": None,
            "server_coord_index": None,
            "config_error": f"本机执行位配置读取失败：{exc}",
        }

    if target_slot < 1 or target_slot > len(server_coord_indexes):
        return {
            "target_slot": target_slot,
            "account_id": None,
            "server_coord_index": None,
            "config_error": f"目标执行位 {target_slot} 超出有效范围。",
        }

    account_id, config_error = _resolve_account_id_for_execution_slot_group(target_slot)
    return {
        "target_slot": target_slot,
        "account_id": account_id,
        "server_coord_index": server_coord_indexes[target_slot - 1],
        "config_error": config_error,
    }


def _digits_only(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _log_switch_waits(step_name, **kwargs):
    display_step_name = _SWITCH_WAIT_STEP_LABELS.get(step_name, step_name)
    details = "，".join(
        f"{_SWITCH_WAIT_KEY_LABELS.get(key, key)}={value}"
        for key, value in kwargs.items()
    )
    message = f"[切换流程] {display_step_name}等待参数：{details}"
    print(message)
    logger.info(message)


def _wait_for_switch_user_entry_with_foreground_retry(camera):
    """识别切换账号入口；首次失败时尝试拉前台后重试 1 次。"""
    launcher_ready, detail = _ensure_launcher_click_ready(camera)
    if not launcher_ready:
        logger.error("[切换流程] 切换账号入口前置守卫失败：%s", detail)
        return None, detail

    logger.info("[切换流程] 切换账号入口模板：qiehuan.png")
    print("[切换流程] 切换账号入口模板：qiehuan.png")

    fast_click(config.SWITCH_ACCOUNT_LIST_BUTTON_POS)
    safe_sleep(config.SWITCH_ACCOUNT_LIST_CLICK_WAIT_SECONDS)

    center = _wait_for_match_center(
        camera,
        "qiehuan",
        config.SWITCH_USER_TEMPLATE_REGION,
        timeout=config.SWITCH_USER_ENTRY_MATCH_TIMEOUT_SECONDS,
        threshold=config.SWITCH_UI_MATCH_THRESHOLD,
    )
    if center is not None:
        return center, ""

    logger.warning("[切换流程] 未匹配到切换账号入口，准备尝试拉前台后重试 1 次。")
    print("[切换流程] 未匹配到切换账号入口，准备尝试拉前台后重试 1 次。")
    _try_bring_wegame_to_front()
    safe_sleep(1.0)

    fast_click(config.SWITCH_ACCOUNT_LIST_BUTTON_POS)
    safe_sleep(config.SWITCH_ACCOUNT_LIST_CLICK_WAIT_SECONDS)

    retry_center = _wait_for_match_center(
        camera,
        "qiehuan",
        config.SWITCH_USER_TEMPLATE_REGION,
        timeout=config.SWITCH_USER_ENTRY_MATCH_TIMEOUT_SECONDS,
        threshold=config.SWITCH_UI_MATCH_THRESHOLD,
    )
    if retry_center is not None:
        return retry_center, ""
    return None, "点击账号列表后未匹配到切换账号入口（qiehuan.png），拉前台重试后仍失败。"


def _click_switch_user_and_wait_login(camera):
    """打开账号列表并进入切号登录页面。"""
    _log_switch_waits(
        "switch-user entry",
        click_wait=config.SWITCH_ACCOUNT_LIST_CLICK_WAIT_SECONDS,
        entry_timeout=config.SWITCH_USER_ENTRY_MATCH_TIMEOUT_SECONDS,
        login_click_wait=config.SWITCH_SWITCH_USER_CLICK_WAIT_SECONDS,
        login_timeout=config.SWITCH_LOGIN_PAGE_MATCH_TIMEOUT_SECONDS,
        login_retry_count=config.SWITCH_LOGIN_PAGE_RETRY_COUNT,
    )
    center, failure_detail = _wait_for_switch_user_entry_with_foreground_retry(camera)
    if center is None:
        pause_thread6_failure(
            "切换账号入口",
            failure_detail,
        )
        return None

    fast_click(center)
    safe_sleep(config.SWITCH_SWITCH_USER_CLICK_WAIT_SECONDS)

    login_center = _wait_for_login_page_with_retries(camera)
    if login_center is None:
        pause_thread6_failure(
            "进入登录页",
            "点击切换账号入口后未匹配到登录页（denglu.png）。",
        )
        return None

    return login_center


def _wait_for_login_page_with_retries(camera):
    """等待登录页出现；首次失败后继续重试指定次数。"""
    max_attempts = config.SWITCH_LOGIN_PAGE_RETRY_COUNT + 1
    for attempt_index in range(1, max_attempts + 1):
        login_center = _wait_for_match_center(
            camera,
            "denglu",
            config.SWITCH_LOGIN_TEMPLATE_REGION,
            timeout=config.SWITCH_LOGIN_PAGE_MATCH_TIMEOUT_SECONDS,
            threshold=config.SWITCH_UI_MATCH_THRESHOLD,
        )
        if login_center is not None:
            return login_center

        if attempt_index < max_attempts:
            retry_index = attempt_index
            message = (
                f"[切换流程] 登录页未匹配到，准备重试 "
                f"{retry_index}/{config.SWITCH_LOGIN_PAGE_RETRY_COUNT}。"
            )
            print(message)
            logger.warning(message)

    return None


def _input_and_verify_account(account_id):
    """输入账号并用剪贴板校验。"""
    _log_switch_waits(
        "account input verify",
        verify_wait=config.SWITCH_ACCOUNT_INPUT_VERIFY_WAIT_SECONDS,
    )
    verified, detail = _retry_account_input_verify(account_id)
    if not verified:
        return pause_thread6_failure("账号输入校验", detail)
    return True


def _retry_account_input_verify(account_id):
    """输入账号并校验；失败后重新点击输入框补重试。"""
    expected = _digits_only(account_id)

    for attempt in range(1, config.SWITCH_ACCOUNT_INPUT_RETRY_COUNT + 2):
        fast_click(config.SWITCH_ACCOUNT_INPUT_POS)
        safe_sleep(config.SWITCH_ACCOUNT_INPUT_VERIFY_WAIT_SECONDS)
        hotkey(0x11, 0x41)
        safe_sleep(config.SWITCH_ACCOUNT_INPUT_VERIFY_WAIT_SECONDS)
        type_digits(str(account_id))
        safe_sleep(config.SWITCH_ACCOUNT_INPUT_VERIFY_WAIT_SECONDS)
        hotkey(0x11, 0x41)
        safe_sleep(config.SWITCH_ACCOUNT_INPUT_VERIFY_WAIT_SECONDS)
        hotkey(0x11, 0x43)
        safe_sleep(config.SWITCH_ACCOUNT_INPUT_VERIFY_WAIT_SECONDS)

        actual = _digits_only(get_clipboard_text())
        if actual == expected:
            if attempt > 1:
                logger.info("[切换流程] 账号输入校验在第 %s 次尝试后成功。", attempt)
            return True, ""

        if attempt <= config.SWITCH_ACCOUNT_INPUT_RETRY_COUNT:
            logger.warning(
                "[切换流程] 账号输入校验失败，准备重试 %s/%s：期望=%s 实际=%s",
                attempt,
                config.SWITCH_ACCOUNT_INPUT_RETRY_COUNT,
                expected,
                actual or "空",
            )

    return False, (
        f"账号输入校验失败，已重新点击输入框重试 {config.SWITCH_ACCOUNT_INPUT_RETRY_COUNT} 次，"
        f"期望账号 {expected}，实际剪贴板为 {actual or '空'}。"
    )


def _confirm_account_switched(camera):
    """确认切号后已回到可换区页面。"""
    _log_switch_waits(
        "heping verify",
        login_click_wait=config.SWITCH_LOGIN_CLICK_WAIT_SECONDS,
        heping_timeout=config.SWITCH_HEPING_MATCH_TIMEOUT_SECONDS,
        maximize_wait=config.SWITCH_MAXIMIZE_WAIT_SECONDS,
    )
    launcher_ready, _launcher_source = _wait_for_launcher_heping_ready(
        camera,
        config.SWITCH_HEPING_MATCH_TIMEOUT_SECONDS,
    )
    if launcher_ready:
        guard_ok, guard_detail = _ensure_launcher_click_ready(camera)
        if guard_ok:
            fast_click((45, 277))
            safe_sleep(0.8)
            return True
        logger.error("[切换流程] 切号登录后的启动页前置守卫失败：%s", guard_detail)

    return pause_thread6_failure(
        "确认账号切换结果",
        "账号登录后未匹配到和平精英页（hepingjingying.png）。",
    )


def _switch_account_for_slot(camera, account_id):
    """执行本阶段所需的切号流程。"""
    login_center = _click_switch_user_and_wait_login(camera)
    if login_center is None:
        return False
    if not _input_and_verify_account(account_id):
        return False

    _log_switch_waits(
        "denglu click",
        login_click_wait=config.SWITCH_LOGIN_CLICK_WAIT_SECONDS,
    )
    fast_click(login_center)
    safe_sleep(config.SWITCH_LOGIN_CLICK_WAIT_SECONDS)
    return _confirm_account_switched(camera)


def _load_nickname_template(slot_number):
    """按执行位加载昵称模板。"""
    template_files = get_execution_slot_nickname_template_files()
    if slot_number < 1 or slot_number > len(template_files):
        return None, ""

    nickname_match_config = _get_local_nickname_match_config()
    template_name = template_files[slot_number - 1]
    template_path = os.path.join(nickname_match_config["template_dir"], template_name)
    template = cv2.imread(template_path)
    return template, template_path


def _verify_slot_nickname(camera, slot_number):
    """选区后执行昵称模板校验。"""
    verified, failure_detail = _try_verify_slot_nickname_once(camera, slot_number)
    if verified:
        return True

    return pause_thread6_failure(
        "昵称模板校验",
        failure_detail,
    )


def _try_verify_slot_nickname_once(camera, slot_number, sync_running_status=True):
    """执行一次昵称模板匹配，返回是否成功和失败详情。"""
    update_overlay_mini(f"正在校验执行位 {slot_number} 的昵称")
    try:
        nickname_match_config = _get_local_nickname_match_config()
    except Exception as exc:
        return False, f"读取本机昵称模板配置失败：{exc}"

    template, template_path = _load_nickname_template(slot_number)
    if template is None:
        return False, f"昵称模板缺失：{template_path or 'unresolved path'}。"

    _log_switch_waits(
        "nickname verify",
        select_wait=config.SWITCH_SERVER_SELECT_WAIT_SECONDS,
        verify_timeout=config.SWITCH_NICKNAME_VERIFY_TIMEOUT_SECONDS,
    )
    safe_sleep(config.SWITCH_SERVER_SELECT_WAIT_SECONDS)
    end = time.time() + config.SWITCH_NICKNAME_VERIFY_TIMEOUT_SECONDS
    while time.time() < end:
        if _match_image(
            camera,
            template,
            nickname_match_config["verify_region"],
            threshold=nickname_match_config["match_threshold"],
        ):
            print(f"[切换流程] 执行位 {slot_number} 的昵称模板校验通过：{template_path}")
            logger.info("[切换流程] 执行位 %s 的昵称模板校验通过：%s", slot_number, template_path)
            if sync_running_status:
                _sync_verified_slot_status_to_running(slot_number)
            return True, ""
        safe_sleep(0.5)

    return False, f"执行位 {slot_number} 的昵称模板校验失败：{template_path}。"


def _retry_slot_nickname_verification_from_server_select(
    camera,
    target_slot,
    server_coord_index,
    sync_running_status=True,
):
    """线程 6 专用：昵称校验失败后，重登同执行位账号再回选区重试。"""
    verified, failure_detail = _try_verify_slot_nickname_once(
        camera,
        target_slot,
        sync_running_status=sync_running_status,
    )
    if verified:
        return True

    account_id, config_error = _resolve_account_id_for_execution_slot_group(target_slot)
    if config_error:
        return pause_thread6_failure("读取本机换号配置", config_error)

    for retry_index in range(1, config.SWITCH_NICKNAME_RELOGIN_RETRY_COUNT + 1):
        ui_print(f"重登重试{retry_index}/2", save_log=True)

        if not _switch_account_for_slot(camera, account_id):
            return pause_thread6_failure(
                "重新登录账号",
                f"昵称模板重试 {retry_index}/2 时未能重新登录执行位 {target_slot} 对应账号。",
            )

        if not _step02_server_list(camera, suppress_failure_output=True):
            return pause_thread6_failure(
                "打开大区列表",
                f"昵称模板重试 {retry_index}/2 前未能重新打开大区列表。",
            )

        if not _step03_select(camera, server_coord_index, suppress_failure_output=True):
            return pause_thread6_failure(
                "选择目标大区",
                f"昵称模板重试 {retry_index}/2 时未能重新选择目标大区。",
            )

        verified, failure_detail = _try_verify_slot_nickname_once(
            camera,
            target_slot,
            sync_running_status=sync_running_status,
        )
        if verified:
            print(f"[切换流程] 执行位 {target_slot} 的昵称模板在第 {retry_index} 次重登重试后校验通过。")
            logger.info(
                "[切换流程] 执行位 %s 的昵称模板在第 %s 次重登重试后校验通过。",
                target_slot,
                retry_index,
            )
            return True

    return pause_thread6_failure("昵称模板校验", failure_detail)


def _sync_verified_slot_status_to_running(slot_number):
    """昵称模板校验成功后，把目标执行位账号状态补写为运行中。"""
    database_path, table_name = _resolve_canonical_store_for_switch()
    if not database_path:
        logger.warning("[线程6] 昵称模板校验通过后未写入“运行中”：canonical 数据库路径为空。")
        return

    record = read_preferred_canonical_account_stats_record_by_execution_slot(
        database_path,
        slot_number,
        table_name,
    )
    if record is None:
        logger.warning("[线程6] 昵称模板校验通过后未写入“运行中”：执行位 %s 未解析到账号记录。", slot_number)
        return

    result = update_canonical_account_status_fields(
        database_path,
        record.nickname,
        ROUND_STATUS_RUNNING,
        table_name=table_name,
    )
    if result.status == "success":
        _schedule_status_change_snapshot("昵称校验通过改运行中")
        logger.info(
            "[线程6] 昵称模板校验通过后已写入“运行中”：执行位=%s 昵称=%s",
            slot_number,
            record.nickname,
        )
        return

    logger.warning(
        "[线程6] 昵称模板校验通过后写入“运行中”失败：执行位=%s 昵称=%s 原因=%s",
        slot_number,
        record.nickname,
        result.reason,
    )


def _detect_slot_nickname_once(camera, nickname_match_config):
    """在昵称校验区域内扫描当前命中的执行位模板。"""
    for slot_number in range(1, int(get_execution_slot_count()) + 1):
        template, _ = _load_nickname_template(slot_number)
        if template is None:
            continue
        if _match_image(
            camera,
            template,
            nickname_match_config["verify_region"],
            threshold=nickname_match_config["match_threshold"],
        ):
            return slot_number
    return None


def detect_current_execution_slot_from_launcher(camera):
    """启动入口：进入选区页后，复用线程6昵称模板链路识别当前执行位。"""
    set_overlay_mini("启动中：识别昵称")
    if not _step02_server_list(camera, suppress_failure_output=True):
        print("[启动] 未能进入启动器选区页，无法识别当前昵称。")
        logger.error("[启动] 未能进入启动器选区页，无法识别当前昵称。")
        return None

    try:
        nickname_match_config = _get_local_nickname_match_config()
    except Exception as exc:
        message = f"[启动] 本机昵称模板配置读取失败：{exc}"
        print(message)
        logger.error(message)
        return None

    print("[启动] 已进入选区页，开始识别当前昵称模板。")
    logger.info("[启动] 已进入选区页，开始识别当前昵称模板。")
    end = time.time() + config.SWITCH_NICKNAME_VERIFY_TIMEOUT_SECONDS
    while time.time() < end:
        slot_number = _detect_slot_nickname_once(camera, nickname_match_config)
        if slot_number is not None:
            print(f"[启动] 已识别当前执行位：{slot_number}")
            logger.info("[启动] 已识别当前执行位：%s", slot_number)
            return slot_number
        safe_sleep(0.5)

    print("[启动] 当前昵称模板识别失败，未匹配到任何执行位模板。")
    logger.error("[启动] 当前昵称模板识别失败，未匹配到任何执行位模板。")
    return None


def _find_exit_confirm_center(camera):
    """查找退出确认按钮中心，优先原区域，再用宽区域兜底。"""
    regions = [config.RGN_F4]
    wide_region = getattr(config, "RGN_F4_WIDE", None)
    if wide_region is not None and wide_region not in regions:
        regions.append(wide_region)

    for region in regions:
        center = _match_center(
            camera,
            "f4",
            region,
            threshold=config.SWITCH_UI_MATCH_THRESHOLD,
        )
        if center is not None:
            return center, region
    return None, None


def _step01_exit(camera):
    """步骤1：ALT+F4 并确认退出。"""
    update_overlay_mini("换号中：退出游戏")
    print("[切换流程] 正在尝试退出游戏。")
    pyautogui.hotkey("alt", "F4")
    time.sleep(0.5)

    retry_count = int(getattr(config, "SWITCH_EXIT_CONFIRM_RETRY_COUNT", 3))
    retry_interval = float(getattr(config, "SWITCH_EXIT_CONFIRM_RETRY_INTERVAL_SECONDS", 0.5))
    launcher_verify_timeout = float(getattr(config, "SWITCH_EXIT_LAUNCHER_VERIFY_TIMEOUT_SECONDS", 2.0))

    for attempt_index in range(1, retry_count + 1):
        confirm_center, confirm_region = _find_exit_confirm_center(camera)
        if confirm_center is not None:
            logger.info(
                "[切换流程] 第 %s 次识别退出确认按钮，区域=%s，点击中心：%s。",
                attempt_index,
                confirm_region,
                confirm_center,
            )
            fast_click(confirm_center)
        else:
            logger.warning(
                "[切换流程] 第 %s 次未识别退出确认按钮，沿用固定坐标兜底点击。",
                attempt_index,
            )
            fast_click((1050, 686))

        safe_sleep(retry_interval)
        if _wait_for_launcher_ready_nonblocking(camera, launcher_verify_timeout):
            logger.info("[切换流程] 退出游戏后已确认回到启动页。")
            return True

        confirm_center, _confirm_region = _find_exit_confirm_center(camera)
        if confirm_center is None:
            logger.info("[切换流程] 退出确认弹窗已消失，继续等待启动页。")
            if _wait_for_launcher_ready_nonblocking(camera, launcher_verify_timeout):
                logger.info("[切换流程] 弹窗消失后已确认回到启动页。")
                return True
        else:
            logger.warning("[切换流程] 退出确认弹窗仍存在，准备重试确认点击。")

    logger.error("[切换流程] 退出确认弹窗重试后仍未完成退出。")
    return False


def _step02_server_list(camera, suppress_failure_output=False):
    """步骤2：打开大区列表。"""
    update_overlay_mini("换区中：打开大区列表")
    launcher_ready, detail = _ensure_launcher_click_ready(camera)
    if not launcher_ready:
        if not suppress_failure_output:
            async_push_msg("【切换流程】启动页识别失败", detail)
        return False

    _log_switch_waits(
        "server list",
        open_wait=config.SWITCH_SERVER_LIST_OPEN_WAIT_SECONDS,
        qidong_timeout=config.SWITCH_QIDONG_MATCH_TIMEOUT_SECONDS,
    )
    # 启动器刚回到前台时控件可能还没稳定，先等 3 秒再点，避免点在页面过渡阶段导致后续选区失效。
    safe_sleep(config.SWITCH_SERVER_LIST_OPEN_WAIT_SECONDS)
    pyautogui.click(1480, 990)

    if not _wait_for(camera, "qd", config.RGN_QD, timeout=config.SWITCH_QIDONG_MATCH_TIMEOUT_SECONDS):
        if not suppress_failure_output:
            async_push_msg("【切换流程】未找到启动按钮", "打开大区列表后 30 秒内未识别到启动按钮。")
        return False
    return True


def _step03_select(camera, idx, suppress_failure_output=False):
    """步骤3：点击目标大区。"""
    update_overlay_mini("换区中：选择目标大区")
    if idx < 0 or idx >= len(config.SERVER_COORDS):
        if not suppress_failure_output:
            async_push_msg("【切换流程】目标大区无效", f"目标大区索引无效：{idx}。")
        return False

    launcher_ready, detail = _ensure_launcher_click_ready(camera)
    if not launcher_ready:
        if not suppress_failure_output:
            async_push_msg("【切换流程】启动页识别失败", detail)
        return False

    _log_switch_waits(
        "server select",
        select_wait=config.SWITCH_SERVER_SELECT_WAIT_SECONDS,
    )
    coord = config.SERVER_COORDS[idx]
    pyautogui.click(*coord)
    safe_sleep(config.SWITCH_SERVER_SELECT_WAIT_SECONDS)

    if _match(camera, "qd", config.RGN_QD):
        return True

    pyautogui.click(*coord)
    safe_sleep(config.SWITCH_SERVER_SELECT_WAIT_SECONDS)

    if _match(camera, "qd", config.RGN_QD):
        return True

    if not suppress_failure_output:
        async_push_msg("【切换流程】选择大区失败", "选择目标大区后未重新识别到启动按钮。")
    return False


def _step04_launch(camera, suppress_failure_output=False):
    """步骤4：点击启动游戏。"""
    update_overlay_mini("启动中：启动游戏")
    launcher_ready, detail = _ensure_launcher_click_ready(camera)
    if not launcher_ready:
        if not suppress_failure_output:
            async_push_msg("【切换流程】启动页识别失败", detail)
        return False

    center = _wait_for_match_center(camera, "qd", config.RGN_QD, timeout=15)
    if center is None:
        if not suppress_failure_output:
            async_push_msg("【切换流程】未找到启动按钮", "15 秒内未识别到启动按钮。")
        return False
    fast_click(center)
    time.sleep(0.5)
    press_key(0x20)
    return True


def _step05_space(camera, suppress_failure_output=False):
    """步骤5：处理启动弹窗。"""
    update_overlay_mini("启动中：处理空格弹窗")

    def _retry_space_after_game_foreground(reason):
        logger.warning("[切换流程] %s，尝试拉起游戏窗口后重试空格弹窗识别。", reason)
        update_overlay_mini("拉起游戏窗")
        if not _try_bring_game_window_to_front():
            logger.warning("[切换流程] 游戏窗口拉起失败或未找到，继续原空格弹窗重试节奏。")
            return None
        center_after_foreground = _wait_for_match_center(
            camera,
            "kg",
            config.RGN_KG,
            timeout=1.0,
        )
        if center_after_foreground is not None:
            logger.info("[切换流程] 拉起游戏窗口后已识别到空格弹窗。")
        else:
            logger.warning("[切换流程] 拉起游戏窗口后仍未识别到空格弹窗。")
        return center_after_foreground

    center = _wait_for_match_center(
        camera,
        "kg",
        config.RGN_KG,
        timeout=config.SWITCH_SPACE_MATCH_TIMEOUT_SECONDS,
    )
    if center is None:
        center = _retry_space_after_game_foreground("首次未识别到空格弹窗")

    if center is None:
        logger.warning("[切换流程] 空格弹窗仍未识别到，准备按 10 秒间隔重试。")
        for retry_index in range(1, config.SWITCH_SPACE_RETRY_COUNT + 1):
            update_overlay_mini(f"空格重试{retry_index}")
            safe_sleep(config.SWITCH_SPACE_RETRY_INTERVAL_SECONDS)
            center = _wait_for_match_center(
                camera,
                "kg",
                config.RGN_KG,
                timeout=1.0,
            )
            if center is not None:
                logger.info("[切换流程] 空格弹窗在第 %s 次补重试后识别成功。", retry_index)
                break
            center = _retry_space_after_game_foreground(
                f"第 {retry_index} 次补重试仍未识别到空格弹窗"
            )
            if center is not None:
                logger.info("[切换流程] 空格弹窗在第 %s 次拉起游戏窗口后识别成功。", retry_index)
                break

        if center is None:
            if not suppress_failure_output:
                async_push_msg(
                    "【切换流程】未找到空格弹窗",
                    f"首次识别失败后，已按 10 秒间隔重试 {config.SWITCH_SPACE_RETRY_COUNT} 次，仍未识别到空格弹窗。",
                )
            return False

    # 弹窗刚识别到时按钮可能还没完全可点，点击前后各留 1 秒，避免点空或页面还没吃到输入。
    time.sleep(config.SWITCH_SPACE_BEFORE_CLICK_WAIT_SECONDS)
    fast_click(center)
    time.sleep(config.SWITCH_SPACE_AFTER_CLICK_WAIT_SECONDS)
    press_key(0x20)
    # 按空格后保留 5 秒固定等待，让启动过渡页完成切换，避免后面广告清理过早进入。
    time.sleep(config.SWITCH_SPACE_AFTER_PRESS_WAIT_SECONDS)
    return True


def _step06_ads(camera, suppress_failure_output=False):
    """步骤6：持续按 ESC 清理广告流程。"""
    update_overlay_mini("进场中：清理广告和弹窗")
    end = time.time() + config.SWITCH_ADS_TIMEOUT_SECONDS
    while time.time() < end:
        center = _match_center(camera, "1tc", config.RGN_1TC)
        if center is not None:
            # 广告弹窗刚被识别到时常有轻微动画，先等 0.5 秒再点，减少识图过早导致的空点。
            time.sleep(config.SWITCH_ADS_POPUP_BEFORE_CLICK_WAIT_SECONDS)
            fast_click(center)
            if _wait_for(camera, "gumu", config.RGN_GUMU, timeout=30):
                return True
        pyautogui.press("escape")
        # ESC 后统一等待 2 秒，再做白点复检，避免刚退出遮挡层就立刻误判页面已稳定。
        time.sleep(config.SWITCH_ADS_AFTER_ESC_WAIT_SECONDS)
        if _confirm_white(camera):
            return True

    if not suppress_failure_output:
        async_push_msg("【切换流程】清理广告超时", "160 秒内未能完成广告和弹窗清理。")
    return False


def _step07_gumu(camera, suppress_failure_output=False):
    """步骤7：传送到古墓大厅。"""
    update_overlay_mini("进场中：前往古墓大厅")
    if is_at_gumu(camera):
        return True
    pyautogui.click(190, 58)
    time.sleep(1)

    if not _wait_for(camera, "gumu", config.RGN_GUMU, timeout=30):
        if not suppress_failure_output:
            async_push_msg("【切换流程】未到达古墓大厅", "30 秒内未能到达古墓大厅。")
        return False
    return True


def _run_gold_step(camera, pause_on_failure):
    """执行一次金币链；可选阻断式或非阻断式失败治理。"""
    update_overlay_mini("进场中：领取金币")
    gold_entry_point = _find_exact_rgb_point(
        camera,
        config.RGN_GOLD_ENTRY,
        config.GOLD_ENTRY_RGB,
    )
    if gold_entry_point is None:
        ui_print("无需领金币", save_log=True)
        return {"status": "no_gold", "detail": "未识别到金币入口。"}

    _click_detected_point(gold_entry_point)
    time.sleep(config.SWITCH_GOLD_CLICK_WAIT_SECONDS)

    gold_step2_point = _find_exact_rgb_point(
        camera,
        config.RGN_GOLD_STEP2,
        config.GOLD_STEP_RGB,
    )
    if gold_step2_point is None:
        ui_print("金币异常回大厅", save_log=True)
        reason = "金币链路第 2 步找色失败。"
        if pause_on_failure:
            _return_to_gumu_or_fail(camera, reason)
        else:
            try_return_to_gumu(camera, retry_count=config.SWITCH_RETURN_GUMU_RETRY_COUNT)
        return {"status": "failed", "detail": reason}
    _click_detected_point(gold_step2_point)
    time.sleep(config.SWITCH_GOLD_CLICK_WAIT_SECONDS)

    time.sleep(config.SWITCH_GOLD_CONFIRM_FIND_START_DELAY_SECONDS)
    gold_confirm_point = None
    for attempt in range(config.SWITCH_GOLD_CONFIRM_FIND_RETRY_COUNT):
        gold_confirm_point = _find_exact_rgb_point(
            camera,
            config.RGN_GOLD_CONFIRM,
            config.GOLD_CONFIRM_RGB,
            tolerance=config.GOLD_CONFIRM_RGB_TOLERANCE,
        )
        if gold_confirm_point is not None:
            break
        if attempt < config.SWITCH_GOLD_CONFIRM_FIND_RETRY_COUNT - 1:
            time.sleep(config.SWITCH_GOLD_CONFIRM_FIND_RETRY_INTERVAL_SECONDS)
    if gold_confirm_point is None:
        ui_print("金币异常回大厅", save_log=True)
        reason = "金币链路第 3 步找色失败。"
        if pause_on_failure:
            _return_to_gumu_or_fail(camera, reason)
        else:
            try_return_to_gumu(camera, retry_count=config.SWITCH_RETURN_GUMU_RETRY_COUNT)
        return {"status": "failed", "detail": reason}

    time.sleep(config.SWITCH_GOLD_CONFIRM_PRE_CLICK_DELAY_SECONDS)
    fast_click(gold_confirm_point)
    time.sleep(config.SWITCH_GOLD_CONFIRM_POST_CLICK_DELAY_SECONDS)
    fast_click(config.SWITCH_GOLD_SUCCESS_POPUP_POS)
    return {"status": _GOLD_STEP_NEED_CLOSE, "detail": ""}


def _step08_gold(camera):
    """步骤8：领取金币。返回是否需要执行关闭面板收口。"""
    result = _run_gold_step(camera, pause_on_failure=True)
    if result["status"] == "no_gold":
        return _GOLD_STEP_SKIP_CLOSE
    if result["status"] == _GOLD_STEP_NEED_CLOSE:
        return _GOLD_STEP_NEED_CLOSE
    return False


def _close_gold_panel(camera, pause_on_failure):
    """关闭金币面板并确认仍在古墓大厅。"""
    update_overlay_mini("进场中：关闭面板")
    for _ in range(config.SWITCH_CLOSE_PANEL_ESC_COUNT):
        pyautogui.click(*config.SWITCH_RETURN_GUMU_CLOSE_POS)
        time.sleep(config.SWITCH_CLOSE_PANEL_ESC_INTERVAL_SECONDS)
        pyautogui.press("escape")
        time.sleep(config.SWITCH_CLOSE_PANEL_ESC_INTERVAL_SECONDS)
    time.sleep(config.SWITCH_CLOSE_PANEL_AFTER_ESC_WAIT_SECONDS)

    pyautogui.click(1890, 20)
    time.sleep(config.SWITCH_CLOSE_PANEL_AFTER_ESC_WAIT_SECONDS)
    pyautogui.click(830, 690)
    time.sleep(config.SWITCH_CLOSE_PANEL_AFTER_CLICK_WAIT_SECONDS)

    if _wait_for(
        camera,
        "gumu",
        config.RGN_GUMU,
        timeout=config.SWITCH_RETURN_GUMU_VERIFY_TIMEOUT_SECONDS,
        threshold=config.SWITCH_UI_MATCH_THRESHOLD,
    ):
        return True

    if pause_on_failure:
        return _return_to_gumu_or_fail(camera, "关闭面板后未能返回古墓大厅。")
    return try_return_to_gumu(camera, retry_count=config.SWITCH_RETURN_GUMU_RETRY_COUNT)


def _step09_close(camera, suppress_failure_output=False):
    """步骤9：关闭面板并确认仍在古墓大厅。"""
    return _close_gold_panel(camera, pause_on_failure=True)


def _step10_trade(camera):
    """步骤10：从古墓大厅前往交易行。"""
    update_overlay_mini("进场中：返回交易行")
    # 第一步是打开通往交易行的入口，等待 1.8 秒让页面切到下一层，避免第二次点击打在旧界面。
    pyautogui.click(1470, 1032)
    time.sleep(config.SWITCH_TRADE_FIRST_CLICK_WAIT_SECONDS)

    # 第二步最容易因为页面还没稳定而点空，这里补“收藏”模板识图；若没识别到就重复第二次点击，最多 3 次。
    trade_ready = False
    for attempt in range(1, config.SWITCH_TRADE_SECOND_CLICK_MAX_RETRY + 1):
        pyautogui.click(470, 50)
        time.sleep(config.SWITCH_TRADE_SECOND_CLICK_WAIT_SECONDS)
        if _match(
            camera,
            "shoucan",
            config.SWITCH_TRADE_SHOUCAN_REGION,
            threshold=config.SWITCH_UI_MATCH_THRESHOLD,
        ):
            trade_ready = True
            break
        if attempt < config.SWITCH_TRADE_SECOND_CLICK_MAX_RETRY:
            print(f"[切换流程] 交易行第二次点击重试第 {attempt} 次，仍未识别到收藏入口。")
            logger.info("[切换流程] 交易行第二次点击重试第 %s 次，仍未识别到收藏入口。", attempt)

    if not trade_ready:
        logger.info("[切换流程] 第二次点击多次重试后仍未识别到收藏入口，继续沿用现有进场链路。")

    # 第三步继续进入交易行，仍保留固定等待 1.8 秒，避免最后一次点击后立刻切回业务链路。
    pyautogui.click(1850, 350)
    time.sleep(config.SWITCH_TRADE_THIRD_CLICK_WAIT_SECONDS)
    restore_overlay()
    return True


def is_accessory_trade_page(camera):
    """返回当前场景是否为饰品交易行。"""
    return _match_image(
        camera,
        _accessory_trade_page_tpl(),
        config.ACCESSORY_TRADE_PAGE_REGION,
        threshold=config.SWITCH_UI_MATCH_THRESHOLD,
    )


def _is_accessory_dianpu_ready(camera):
    return _match_image(
        camera,
        _accessory_dianpu_tpl(),
        config.ACCESSORY_DIANPU_REGION,
        threshold=config.SWITCH_UI_MATCH_THRESHOLD,
    )


def _recover_accessory_dianpu(camera):
    if not is_accessory_trade_page(camera):
        return False
    if _is_accessory_dianpu_ready(camera):
        return True

    for _attempt in range(1, config.ACCESSORY_DIANPU_RECOVER_RETRY_COUNT + 1):
        fast_click(config.ACCESSORY_RECOVER_POS1)
        safe_sleep(config.ACCESSORY_DIANPU_RECOVER_WAIT_SECONDS)
        fast_click(config.ACCESSORY_RECOVER_POS2)
        safe_sleep(config.ACCESSORY_DIANPU_RECOVER_INTERVAL_SECONDS)
        if _is_accessory_dianpu_ready(camera):
            return True
    return False


def _wait_accessory_trade_page(camera, timeout_seconds=2.0):
    end_time = time.time() + float(timeout_seconds)
    while time.time() < end_time:
        if is_accessory_trade_page(camera):
            if not _recover_accessory_dianpu(camera):
                return False
            safe_sleep(config.ACCESSORY_TRADE_READY_CONFIRM_DELAY_SECONDS)
            return is_accessory_trade_page(camera) and _is_accessory_dianpu_ready(camera)
        safe_sleep(0.1)
    return False


def enter_accessory_trade_from_gumu(camera):
    """从古墓大厅进入饰品交易行。"""
    update_overlay_mini("饰品进场")
    for round_index in range(1, config.ACCESSORY_TRADE_REENTER_RETRY_COUNT + 1):
        fast_click(config.ACCESSORY_ENTRY_POS)
        safe_sleep(config.ACCESSORY_ACTION_DELAY_SECONDS)

        shoucan_center = None
        for _attempt in range(1, config.ACCESSORY_TRADE_ENTRY_RETRY_COUNT + 1):
            shoucan_center = _match_center(
                camera,
                "shoucan",
                config.ACCESSORY_SHOUCAN_REGION,
                threshold=config.SWITCH_UI_MATCH_THRESHOLD,
            )
            if shoucan_center is not None:
                break
            fast_click(config.ACCESSORY_SHOUCAN_CENTER_POS)
            safe_sleep(config.ACCESSORY_ACTION_DELAY_SECONDS)

        if shoucan_center is not None:
            fast_click(shoucan_center)
            safe_sleep(config.ACCESSORY_ACTION_DELAY_SECONDS)
            if _wait_accessory_trade_page(camera, timeout_seconds=config.ACCESSORY_TRADE_READY_TIMEOUT_SECONDS):
                restore_overlay()
                return True

        if round_index < config.ACCESSORY_TRADE_REENTER_RETRY_COUNT:
            logger.info("[饰品抢购] 未进入饰品交易行，准备返回古墓大厅后重试。")
            if not try_return_to_gumu(camera, retry_count=config.SWITCH_RETURN_GUMU_RETRY_COUNT):
                return False

    ui_print("饰品进场失败", save_log=True)
    return False


def enter_accessory_trade_from_current_scene(camera):
    """从当前场景恢复到古墓大厅，再进入饰品交易行。"""
    if not is_at_gumu(camera):
        if not try_return_to_gumu(camera, retry_count=config.SWITCH_RETURN_GUMU_RETRY_COUNT):
            return False
    return enter_accessory_trade_from_gumu(camera)


def startup_accessory_from_server_list(camera, server_index):
    """已位于选区页时，继续执行后续启动链路并进入饰品交易行。"""
    set_overlay_mini("饰品启动中")
    state.current_server_index = server_index
    steps = [
        ("选择目标大区", lambda: _step03_select(camera, server_index)),
        ("启动游戏", lambda: _step04_launch(camera)),
        ("处理空格弹窗", lambda: _step05_space(camera)),
        ("清理广告和弹窗", lambda: _step06_ads(camera)),
        ("进入古墓大厅", lambda: _step07_gumu(camera)),
    ]

    for name, fn in steps:
        logger.info("[饰品抢购] %s开始。", name)
        if not fn():
            logger.error("[饰品抢购] %s失败。", name)
            restore_overlay()
            return False
        logger.info("[饰品抢购] %s完成。", name)

    logger.info("[饰品抢购] 领取金币开始。")
    gold_step_result = _step08_gold(camera)
    if not gold_step_result:
        logger.error("[饰品抢购] 领取金币失败。")
        restore_overlay()
        return False
    logger.info("[饰品抢购] 领取金币完成。")

    if gold_step_result == _GOLD_STEP_NEED_CLOSE:
        logger.info("[饰品抢购] 关闭面板开始。")
        if not _step09_close(camera):
            logger.error("[饰品抢购] 关闭面板失败。")
            restore_overlay()
            return False
        logger.info("[饰品抢购] 关闭面板完成。")

    logger.info("[饰品抢购] 进入饰品交易行开始。")
    if not enter_accessory_trade_from_gumu(camera):
        logger.error("[饰品抢购] 进入饰品交易行失败。")
        restore_overlay()
        return False
    logger.info("[饰品抢购] 已进入饰品交易行。")
    restore_overlay()
    return True


def _run_startup_from_launcher(camera, server_index, skip_open_server_list=False):
    """执行从启动器到交易行的完整流程。"""
    set_overlay_mini("启动准备中")
    state.current_server_index = server_index

    steps = []
    if not skip_open_server_list:
        steps.append(("打开大区列表", lambda: _step02_server_list(camera)))
    steps.extend([
        ("选择目标大区", lambda: _step03_select(camera, server_index)),
        ("启动游戏", lambda: _step04_launch(camera)),
        ("处理空格弹窗", lambda: _step05_space(camera)),
        ("清理广告和弹窗", lambda: _step06_ads(camera)),
        ("进入古墓大厅", lambda: _step07_gumu(camera)),
    ])

    for name, fn in steps:
        logger.info("[切换流程] %s开始。", name)
        if not fn():
            logger.error("[切换流程] %s失败。", name)
            restore_overlay()
            return False
        logger.info("[切换流程] %s完成。", name)

    logger.info("[切换流程] 领取金币开始。")
    gold_step_result = _step08_gold(camera)
    if not gold_step_result:
        logger.error("[切换流程] 领取金币失败。")
        restore_overlay()
        return False
    logger.info("[切换流程] 领取金币完成。")

    if gold_step_result == _GOLD_STEP_NEED_CLOSE:
        logger.info("[切换流程] 关闭面板开始。")
        if not _step09_close(camera):
            logger.error("[切换流程] 关闭面板失败。")
            restore_overlay()
            return False
        logger.info("[切换流程] 关闭面板完成。")

    logger.info("[切换流程] 返回交易行开始。")
    if not _step10_trade(camera):
        logger.error("[切换流程] 返回交易行失败。")
        restore_overlay()
        return False
    logger.info("[切换流程] 返回交易行完成。")

    logger.info("[切换流程] 目标大区 %s 已就绪。", server_index + 1)
    return True


def startup_from_launcher(camera, server_index):
    """执行从启动器到交易行的完整流程。"""
    return _run_startup_from_launcher(camera, server_index, skip_open_server_list=False)


def startup_from_server_list(camera, server_index):
    """已位于选区页时，继续执行后续启动链路。"""
    return _run_startup_from_launcher(camera, server_index, skip_open_server_list=True)


def startup_temporary_from_qidong(camera):
    """临时模式：从已可见 qidong.png 的启动页直接进场到交易行。"""
    set_overlay_mini("临时启动中")
    steps = [
        ("启动游戏", lambda: _step04_launch(camera)),
        ("处理空格弹窗", lambda: _step05_space(camera)),
        ("清理广告和弹窗", lambda: _step06_ads(camera)),
        ("进入古墓大厅", lambda: _step07_gumu(camera)),
    ]

    for name, fn in steps:
        logger.info("[临时模式] %s开始。", name)
        if not fn():
            logger.error("[临时模式] %s失败。", name)
            restore_overlay()
            return False
        logger.info("[临时模式] %s完成。", name)

    logger.info("[临时模式] 领取金币开始。")
    gold_step_result = _step08_gold(camera)
    if not gold_step_result:
        logger.error("[临时模式] 领取金币失败。")
        restore_overlay()
        return False
    logger.info("[临时模式] 领取金币完成。")

    if gold_step_result == _GOLD_STEP_NEED_CLOSE:
        logger.info("[临时模式] 关闭面板开始。")
        if not _step09_close(camera):
            logger.error("[临时模式] 关闭面板失败。")
            restore_overlay()
            return False
        logger.info("[临时模式] 关闭面板完成。")

    logger.info("[临时模式] 返回交易行开始。")
    if not _step10_trade(camera):
        logger.error("[临时模式] 返回交易行失败。")
        restore_overlay()
        return False
    logger.info("[临时模式] 已回到交易行。")
    restore_overlay()
    return True


def full_switch_server(camera, server_index):
    """运行中换区：先退出游戏，再复用启动器流程。"""
    set_overlay_mini("换区准备中")
    logger.info("[切换流程] 开始执行退出游戏步骤。")
    if not _step01_exit(camera):
        logger.error("[切换流程] 退出游戏失败。")
        restore_overlay()
        return False
    logger.info("[切换流程] 退出游戏完成。")

    result = startup_from_launcher(camera, server_index)
    if not result:
        restore_overlay()
    return result


def is_at_gumu(camera):
    """返回当前场景是否为古墓大厅。"""
    if _match(camera, "gumu", config.RGN_GUMU, threshold=config.SWITCH_UI_MATCH_THRESHOLD):
        time.sleep(1)
        return _match(camera, "gumu", config.RGN_GUMU, threshold=config.SWITCH_UI_MATCH_THRESHOLD)
    time.sleep(1)
    return _match(camera, "gumu", config.RGN_GUMU, threshold=config.SWITCH_UI_MATCH_THRESHOLD)


def navigate_to_trade(camera):
    """从古墓大厅前往交易行。"""
    return _step10_trade(camera)


def refresh_latest_balance_route(camera):
    """非阻断执行：回古墓 -> 尝试领金币 -> 回交易行。"""
    if not is_at_gumu(camera):
        if not try_return_to_gumu(camera, retry_count=3):
            return {"status": "failed", "detail": "返回古墓大厅失败。"}

    gold_result = _run_gold_step(camera, pause_on_failure=False)
    if gold_result["status"] == "no_gold":
        return {"status": "no_gold", "detail": "没有金币可领取。"}
    if gold_result["status"] != _GOLD_STEP_NEED_CLOSE:
        return {"status": "failed", "detail": gold_result["detail"] or "领取金币失败。"}

    if not _close_gold_panel(camera, pause_on_failure=False):
        return {"status": "failed", "detail": "关闭金币面板后未能返回古墓大厅。"}
    if not _step10_trade(camera):
        return {"status": "failed", "detail": "返回交易行失败。"}
    return {"status": "success", "detail": "已返回交易行。"}


def _run_thread6_resume_steps(camera):
    resume_steps = [
        ("启动游戏", lambda: _step04_launch(camera, suppress_failure_output=True), "未匹配到启动按钮或启动点击失败。"),
        ("处理空格弹窗", lambda: _step05_space(camera, suppress_failure_output=True), "未匹配到空格弹窗或处理失败。"),
        ("进入游戏场景", lambda: _step06_ads(camera, suppress_failure_output=True), "未能完成进入游戏场景前的页面清理。"),
        ("确认古墓大厅", lambda: _step07_gumu(camera, suppress_failure_output=True), "未能进入或确认古墓大厅。"),
    ]
    for step_name, fn, detail in resume_steps:
        if not _run_thread6_step(step_name, detail, fn):
            return False

    gold_step_result = {"value": False}

    def _run_gold_step():
        gold_step_result["value"] = _step08_gold(camera)
        return bool(gold_step_result["value"])

    if not _run_thread6_step("领取金币", "领取金币步骤执行失败。", _run_gold_step):
        return False

    if gold_step_result["value"] == _GOLD_STEP_NEED_CLOSE:
        if not _run_thread6_step(
            "关闭面板",
            "关闭面板后未能确认仍在古墓大厅。",
            lambda: _step09_close(camera, suppress_failure_output=True),
        ):
            return False

    if not _run_thread6_step("返回交易行", "未能完成返回交易行步骤。", lambda: _step10_trade(camera)):
        return False
    return True


def switch_server_within_account_after_slot_boundary(camera, transition=None):
    """线程 6 小阶段：非 4/8 边界切到下一执行位并做昵称校验。"""
    def _chain_impl():
        target = transition or resolve_execution_slot_transition(state.current_execution_slot)
        if target is None:
            return pause_thread6_failure("解析目标执行位", "同账号跨区切换时未能解析下一目标执行位。")
        if target["requires_account_switch"]:
            return pause_thread6_failure("校验切换类型", "同账号跨区切换链路收到了需要跨账号切换的目标。")

        set_overlay_mini("边界换区准备中")
        print(
            f"[切换流程] 当前执行位={target['current_slot']}，"
            f"下一执行位={target['next_slot']}，目标大区索引={target['server_coord_index']}"
        )
        logger.info(
            "[切换流程] 当前执行位=%s 下一执行位=%s 目标大区索引=%s",
            target["current_slot"],
            target["next_slot"],
            target["server_coord_index"],
        )

        if not _run_thread6_step("退出游戏", "未能在同账号跨区切换前完成退出游戏。", lambda: _step01_exit(camera)):
            return False

        if not _run_thread6_step("返回启动页确认", "未能在同账号跨区切换前确认回到启动页。", lambda: _wait_for_boundary_start_qidong(camera)):
            return False

        if not _run_thread6_step(
            "打开大区列表",
            "未能在同账号跨区切换前打开大区列表。",
            lambda: _step02_server_list(camera, suppress_failure_output=True),
        ):
            return False

        if not _run_thread6_step(
            "选择目标大区",
            f"未能切换到目标执行位 {target['next_slot']} 对应的大区。",
            lambda: _step03_select(camera, target["server_coord_index"], suppress_failure_output=True),
        ):
            return False

        if not _run_thread6_step(
            "昵称模板校验",
            f"执行位 {target['next_slot']} 的昵称模板校验失败。",
            lambda: _retry_slot_nickname_verification_from_server_select(
                camera,
                target["next_slot"],
                target["server_coord_index"],
                sync_running_status=False,
            ),
        ):
            return False

        if not _run_thread6_step(
            "启动前冷却等待",
            f"执行位 {target['next_slot']} 冷却等待失败。",
            lambda: wait_for_verified_slot_cooldown_before_launch(
                target["next_slot"],
                sync_running_status_after_wait=True,
            ),
        ):
            return False

        if not _run_thread6_step("恢复进场链路", "同账号跨区切换后未能完成回到交易行的后续步骤。", lambda: _run_thread6_resume_steps(camera)):
            return False

        state.current_execution_slot = target["next_slot"]
        state.current_server_index = target["server_coord_index"]
        state.current_account_index = resolve_execution_slot_account_index(target["next_slot"])
        state.current_nickname = str(target["next_slot"])
        state.need_switch_server = False
        state.switch_flow_paused = False
        state.switch_last_unknown_detail = ""
        restore_overlay()
        print(
            f"[切换流程] 同账号边界换区完成：下一执行位={target['next_slot']}，"
            f"目标大区索引={target['server_coord_index']}，已回到交易行。"
        )
        logger.info(
            "[切换流程] 同账号边界换区完成：下一执行位=%s 目标大区索引=%s 已回到交易行。",
            target["next_slot"],
            target["server_coord_index"],
        )
        return True

    return _run_thread6_chain("同账号跨区切换链路", _chain_impl)


def switch_account_after_slot_boundary(camera):
    """线程 6 小阶段：4/8 区结束后切号、选区并做昵称模板校验。"""
    def _chain_impl():
        target = _resolve_switch_target(state.current_execution_slot)
        if target is None:
            return pause_thread6_failure("解析目标执行位", "跨账号切换链路未能解析 4->5 或 8->1 的目标执行位。")
        if target.get("config_error"):
            return pause_thread6_failure("读取本机换号配置", target["config_error"])

        set_overlay_mini("边界换号准备中")
        print(
            f"[切换流程] 当前执行位={target['current_slot']}，"
            f"下一执行位={target['next_slot']}，目标账号={target['account_id']}"
        )
        logger.info(
            "[切换流程] 当前执行位=%s 下一执行位=%s 目标账号=%s",
            target["current_slot"],
            target["next_slot"],
            target["account_id"],
        )

        if not _run_thread6_step("退出游戏", "未能在跨账号切换前完成退出游戏。", lambda: _step01_exit(camera)):
            return False

        if not _run_thread6_step("返回启动页确认", "未能在跨账号切换前确认回到启动页。", lambda: _wait_for_boundary_start_qidong(camera)):
            return False

        if not _run_thread6_step(
            "执行跨账号切换",
            f"未能切换到账号 {target['account_id']}。",
            lambda: _switch_account_for_slot(camera, target["account_id"]),
        ):
            return False

        if not _run_thread6_step(
            "打开大区列表",
            "跨账号切换后未能打开大区列表。",
            lambda: _step02_server_list(camera, suppress_failure_output=True),
        ):
            return False

        if not _run_thread6_step(
            "选择目标大区",
            f"跨账号切换后未能切换到目标执行位 {target['next_slot']} 对应的大区。",
            lambda: _step03_select(camera, target["server_coord_index"], suppress_failure_output=True),
        ):
            return False

        if not _run_thread6_step(
            "昵称模板校验",
            f"执行位 {target['next_slot']} 的昵称模板校验失败。",
            lambda: _retry_slot_nickname_verification_from_server_select(
                camera,
                target["next_slot"],
                target["server_coord_index"],
                sync_running_status=False,
            ),
        ):
            return False

        if not _run_thread6_step(
            "启动前冷却等待",
            f"执行位 {target['next_slot']} 冷却等待失败。",
            lambda: wait_for_verified_slot_cooldown_before_launch(
                target["next_slot"],
                sync_running_status_after_wait=True,
            ),
        ):
            return False

        if not _run_thread6_step("恢复进场链路", "跨账号切换后未能完成回到交易行的后续步骤。", lambda: _run_thread6_resume_steps(camera)):
            return False

        state.current_execution_slot = target["next_slot"]
        state.current_server_index = target["server_coord_index"]
        state.current_account_index = resolve_execution_slot_account_index(target["next_slot"])
        state.current_nickname = str(target["next_slot"])
        state.need_switch_server = False
        state.switch_flow_paused = False
        state.switch_last_unknown_detail = ""
        restore_overlay()
        print(
            f"[切换流程] 边界换号完成：下一执行位={target['next_slot']}，"
            f"目标账号={target['account_id']}，已回到交易行。"
        )
        logger.info(
            "[切换流程] 边界换号完成：下一执行位=%s 目标账号=%s 已回到交易行。",
            target["next_slot"],
            target["account_id"],
        )
        return True

    return _run_thread6_chain("跨账号边界切换链路", _chain_impl)


def switch_account_for_temporary_target_slot(camera, target_execution_slot):
    """临时模式结束后，直接切到目标账号组、目标大区并做昵称校验。"""
    def _chain_impl():
        target = _build_temporary_target_transition(target_execution_slot)
        if target.get("config_error"):
            return pause_thread6_failure("解析临时模式目标执行位", target["config_error"])

        set_overlay_mini("临时模式定向切换中")
        print(
            f"[切换流程] 临时模式目标执行位={target['target_slot']}，"
            f"目标账号={target['account_id']}，目标大区索引={target['server_coord_index']}"
        )
        logger.info(
            "[切换流程] 临时模式目标执行位=%s 目标账号=%s 目标大区索引=%s",
            target["target_slot"],
            target["account_id"],
            target["server_coord_index"],
        )

        if not _run_thread6_step("退出游戏", "未能在临时模式定向切换前完成退出游戏。", lambda: _step01_exit(camera)):
            return False

        if not _run_thread6_step("返回启动页确认", "未能在临时模式定向切换前确认回到启动页。", lambda: _wait_for_boundary_start_qidong(camera)):
            return False

        if not _run_thread6_step(
            "执行跨账号切换",
            f"未能切换到目标账号 {target['account_id']}。",
            lambda: _switch_account_for_slot(camera, target["account_id"]),
        ):
            return False

        if not _run_thread6_step(
            "打开大区列表",
            "临时模式定向切换后未能打开大区列表。",
            lambda: _step02_server_list(camera, suppress_failure_output=True),
        ):
            return False

        if not _run_thread6_step(
            "选择目标大区",
            f"临时模式定向切换后未能切换到目标执行位 {target['target_slot']} 对应的大区。",
            lambda: _step03_select(camera, target["server_coord_index"], suppress_failure_output=True),
        ):
            return False

        if not _run_thread6_step(
            "昵称模板校验",
            f"目标执行位 {target['target_slot']} 的昵称模板校验失败。",
            lambda: _retry_slot_nickname_verification_from_server_select(
                camera,
                target["target_slot"],
                target["server_coord_index"],
            ),
        ):
            return False

        if not _run_thread6_step("恢复进场链路", "临时模式定向切换后未能完成回到交易行的后续步骤。", lambda: _run_thread6_resume_steps(camera)):
            return False

        state.current_execution_slot = target["target_slot"]
        state.current_server_index = target["server_coord_index"]
        state.current_account_index = resolve_execution_slot_account_index(target["target_slot"])
        state.current_nickname = str(target["target_slot"])
        state.need_switch_server = False
        state.switch_flow_paused = False
        state.switch_last_unknown_detail = ""
        restore_overlay()
        print(
            f"[切换流程] 临时模式定向切换完成：目标执行位={target['target_slot']}，"
            f"目标账号={target['account_id']}，已回到交易行。"
        )
        logger.info(
            "[切换流程] 临时模式定向切换完成：目标执行位=%s 目标账号=%s 已回到交易行。",
            target["target_slot"],
            target["account_id"],
        )
        return True

    return _run_thread6_chain("临时模式定向切换链路", _chain_impl)


def _wait_for_launcher_ready_nonblocking(camera, timeout_seconds):
    """非阻断确认启动页 heping 已出现。"""
    launcher_ready, _launcher_source = _wait_for_launcher_heping_ready(camera, timeout_seconds)
    return launcher_ready


def _switch_account_for_slot_nonblocking(camera, account_id):
    """启动页上架模式专用：切号失败时只返回失败信息，不进入线程 6 阻断停机。"""
    _log_switch_waits(
        "switch-user entry",
        click_wait=config.SWITCH_ACCOUNT_LIST_CLICK_WAIT_SECONDS,
        entry_timeout=config.SWITCH_USER_ENTRY_MATCH_TIMEOUT_SECONDS,
        login_click_wait=config.SWITCH_SWITCH_USER_CLICK_WAIT_SECONDS,
        login_timeout=config.SWITCH_LOGIN_PAGE_MATCH_TIMEOUT_SECONDS,
        login_retry_count=config.SWITCH_LOGIN_PAGE_RETRY_COUNT,
    )
    switch_center, failure_detail = _wait_for_switch_user_entry_with_foreground_retry(camera)
    if switch_center is None:
        return False, failure_detail

    fast_click(switch_center)
    safe_sleep(config.SWITCH_SWITCH_USER_CLICK_WAIT_SECONDS)

    login_center = _wait_for_login_page_with_retries(camera)
    if login_center is None:
        return False, "点击切换账号入口后未匹配到登录页。"

    _log_switch_waits(
        "account input verify",
        verify_wait=config.SWITCH_ACCOUNT_INPUT_VERIFY_WAIT_SECONDS,
    )
    verified, detail = _retry_account_input_verify(account_id)
    if not verified:
        return False, detail

    _log_switch_waits(
        "denglu click",
        login_click_wait=config.SWITCH_LOGIN_CLICK_WAIT_SECONDS,
    )
    fast_click(login_center)
    safe_sleep(config.SWITCH_LOGIN_CLICK_WAIT_SECONDS)

    _log_switch_waits(
        "heping verify",
        login_click_wait=config.SWITCH_LOGIN_CLICK_WAIT_SECONDS,
        heping_timeout=config.SWITCH_HEPING_MATCH_TIMEOUT_SECONDS,
        maximize_wait=config.SWITCH_MAXIMIZE_WAIT_SECONDS,
    )
    launcher_ready, _launcher_source = _wait_for_launcher_heping_ready(
        camera,
        config.SWITCH_HEPING_MATCH_TIMEOUT_SECONDS,
    )
    if not launcher_ready:
        return False, "账号登录后未匹配到和平精英页。"

    guard_ok, guard_detail = _ensure_launcher_click_ready(camera)
    if not guard_ok:
        return False, guard_detail

    fast_click((45, 277))
    safe_sleep(0.8)
    return True, ""


def _verify_startup_listing_slot_nonblocking(camera, target_slot, server_coord_index):
    """启动页上架模式专用：昵称校验失败时重登同执行位账号后再重试。"""
    verified, failure_detail = _try_verify_slot_nickname_once(
        camera,
        target_slot,
        sync_running_status=False,
    )
    if verified:
        return True, ""

    account_id, config_error = _resolve_account_id_for_execution_slot_group(target_slot)
    if config_error:
        return False, config_error

    for retry_index in range(1, config.SWITCH_NICKNAME_RELOGIN_RETRY_COUNT + 1):
        ui_print(f"重登重试{retry_index}/2", save_log=True)
        switched, switch_detail = _switch_account_for_slot_nonblocking(camera, account_id)
        if not switched:
            return False, f"昵称模板重试 {retry_index}/2 时未能重新登录执行位 {target_slot} 对应账号：{switch_detail}"
        if not _step02_server_list(camera, suppress_failure_output=True):
            return False, f"昵称模板重试 {retry_index}/2 前未能重新打开大区列表。"
        if not _step03_select(camera, server_coord_index, suppress_failure_output=True):
            return False, f"昵称模板重试 {retry_index}/2 时未能重新选择目标大区。"

        verified, failure_detail = _try_verify_slot_nickname_once(
            camera,
            target_slot,
            sync_running_status=False,
        )
        if verified:
            return True, ""

    return False, failure_detail


def enter_startup_listing_target_slot(
    camera,
    target_execution_slot,
    force_login=False,
    already_at_launcher=False,
):
    """启动页上架模式专用：进入任意执行位并回到交易行，不改线程 6 现有链路。"""
    target = _build_temporary_target_transition(target_execution_slot)
    if target.get("config_error"):
        return {
            "status": "failed",
            "detail": target["config_error"],
            "target_slot": target.get("target_slot"),
            "account_id": target.get("account_id"),
            "server_coord_index": target.get("server_coord_index"),
        }

    set_overlay_mini(f"上架模式{target['target_slot']}")

    if already_at_launcher:
        if not _wait_for_launcher_ready_nonblocking(camera, 3.0):
            return {
                "status": "failed",
                "detail": "当前不在启动页，无法开始启动页上架模式进场。",
                "target_slot": target["target_slot"],
                "account_id": target["account_id"],
                "server_coord_index": target["server_coord_index"],
            }
    else:
        if not _step01_exit(camera):
            return {
                "status": "failed",
                "detail": "退出当前游戏失败。",
                "target_slot": target["target_slot"],
                "account_id": target["account_id"],
                "server_coord_index": target["server_coord_index"],
            }
        launcher_wait_seconds = (
            config.SWITCH_BOUNDARY_START_QIDONG_RETRY_COUNT
            * config.SWITCH_BOUNDARY_START_QIDONG_RETRY_INTERVAL_SECONDS
        )
        if not _wait_for_launcher_ready_nonblocking(camera, launcher_wait_seconds):
            return {
                "status": "failed",
                "detail": "退出游戏后未能确认返回启动页。",
                "target_slot": target["target_slot"],
                "account_id": target["account_id"],
                "server_coord_index": target["server_coord_index"],
            }

    if force_login:
        switched, switch_detail = _switch_account_for_slot_nonblocking(camera, target["account_id"])
        if not switched:
            return {
                "status": "failed",
                "detail": switch_detail,
                "target_slot": target["target_slot"],
                "account_id": target["account_id"],
                "server_coord_index": target["server_coord_index"],
            }

    if not _step02_server_list(camera, suppress_failure_output=True):
        return {
            "status": "failed",
            "detail": "未能打开大区列表。",
            "target_slot": target["target_slot"],
            "account_id": target["account_id"],
            "server_coord_index": target["server_coord_index"],
        }

    if not _step03_select(camera, target["server_coord_index"], suppress_failure_output=True):
        return {
            "status": "failed",
            "detail": f"未能切换到执行位 {target['target_slot']} 对应大区。",
            "target_slot": target["target_slot"],
            "account_id": target["account_id"],
            "server_coord_index": target["server_coord_index"],
        }

    verified, verify_detail = _verify_startup_listing_slot_nonblocking(
        camera,
        target["target_slot"],
        target["server_coord_index"],
    )
    if not verified:
        return {
            "status": "failed",
            "detail": verify_detail,
            "target_slot": target["target_slot"],
            "account_id": target["account_id"],
            "server_coord_index": target["server_coord_index"],
        }

    if not _step04_launch(camera, suppress_failure_output=True):
        return {
            "status": "failed",
            "detail": "未能点击启动游戏。",
            "target_slot": target["target_slot"],
            "account_id": target["account_id"],
            "server_coord_index": target["server_coord_index"],
        }
    if not _step05_space(camera, suppress_failure_output=True):
        return {
            "status": "failed",
            "detail": "未能完成空格弹窗处理。",
            "target_slot": target["target_slot"],
            "account_id": target["account_id"],
            "server_coord_index": target["server_coord_index"],
        }
    if not _step06_ads(camera, suppress_failure_output=True):
        return {
            "status": "failed",
            "detail": "未能完成广告和弹窗清理。",
            "target_slot": target["target_slot"],
            "account_id": target["account_id"],
            "server_coord_index": target["server_coord_index"],
        }
    if not _step07_gumu(camera, suppress_failure_output=True):
        return {
            "status": "failed",
            "detail": "未能进入古墓大厅。",
            "target_slot": target["target_slot"],
            "account_id": target["account_id"],
            "server_coord_index": target["server_coord_index"],
        }

    gold_step_result = _step08_gold(camera)
    if not gold_step_result:
        return {
            "status": "failed",
            "detail": "领取金币失败。",
            "target_slot": target["target_slot"],
            "account_id": target["account_id"],
            "server_coord_index": target["server_coord_index"],
        }

    if gold_step_result == _GOLD_STEP_NEED_CLOSE and not _step09_close(camera):
        return {
            "status": "failed",
            "detail": "关闭金币面板失败。",
            "target_slot": target["target_slot"],
            "account_id": target["account_id"],
            "server_coord_index": target["server_coord_index"],
        }

    if not _step10_trade(camera):
        return {
            "status": "failed",
            "detail": "未能返回交易行。",
            "target_slot": target["target_slot"],
            "account_id": target["account_id"],
            "server_coord_index": target["server_coord_index"],
        }

    state.current_execution_slot = target["target_slot"]
    state.current_server_index = target["server_coord_index"]
    state.current_account_index = resolve_execution_slot_account_index(target["target_slot"])
    state.current_nickname = str(target["target_slot"])
    state.need_switch_server = False
    state.switch_flow_paused = False
    state.switch_last_unknown_detail = ""
    restore_overlay()
    return {
        "status": "success",
        "detail": "",
        "target_slot": target["target_slot"],
        "account_id": target["account_id"],
        "server_coord_index": target["server_coord_index"],
    }


def exit_to_launcher_for_startup_listing(camera):
    """启动页上架模式专用：正常下号并确认回到启动页。"""
    set_overlay_mini("上架模式下号")
    if not _step01_exit(camera):
        return {"status": "failed", "detail": "退出当前游戏失败。"}

    launcher_wait_seconds = (
        config.SWITCH_BOUNDARY_START_QIDONG_RETRY_COUNT
        * config.SWITCH_BOUNDARY_START_QIDONG_RETRY_INTERVAL_SECONDS
    )
    if not _wait_for_launcher_ready_nonblocking(camera, launcher_wait_seconds):
        return {"status": "failed", "detail": "退出游戏后未能确认返回启动页。"}

    restore_overlay()
    return {"status": "success", "detail": ""}
