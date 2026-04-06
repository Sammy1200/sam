"""
Switch helpers for launcher/server/account flow.

Public APIs:
  startup_from_launcher(camera, server_index)
  full_switch_server(camera, server_index)
  is_at_gumu(camera)
  navigate_to_trade(camera)
  pause_thread6_failure(step_name, detail)
  resolve_execution_slot_transition(current_execution_slot)
  switch_server_within_account_after_slot_boundary(camera)
  switch_account_after_slot_boundary(camera)
"""

import os
import time
import traceback

import cv2
import pyautogui

import config
import state
from local_switch_account_config import (
    load_boundary_switch_accounts,
    load_local_nickname_match_config,
)
from overlay import toggle_pause
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
    "verify_wait": "校验等待秒数",
    "heping_timeout": "和平精英页识别超时秒数",
    "maximize_wait": "窗口最大化等待秒数",
    "select_wait": "选区后等待秒数",
    "verify_timeout": "识别超时秒数",
    "open_wait": "打开列表前等待秒数",
    "qidong_timeout": "启动按钮识别超时秒数",
}


def _tpl(key):
    """按需加载模板并缓存。"""
    if key not in _TPL_CACHE:
        path = os.path.join("logo", "huanhao", _TPL_FILES[key])
        img = cv2.imread(path)
        if img is None:
            logger.error("[切换流程] 模板缺失：%s", path)
        _TPL_CACHE[key] = img
    return _TPL_CACHE[key]


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
    for attempt in range(1, config.SWITCH_BOUNDARY_START_QIDONG_RETRY_COUNT + 1):
        if _match(
            camera,
            "qd",
            config.SWITCH_BOUNDARY_START_QIDONG_REGION,
            threshold=config.SWITCH_UI_MATCH_THRESHOLD,
        ):
            print(f"[切换流程] 已在第 {attempt} 次识别到启动按钮。")
            logger.info("[切换流程] 已在第 %s 次识别到启动按钮。", attempt)
            return True
        safe_sleep(config.SWITCH_BOUNDARY_START_QIDONG_RETRY_INTERVAL_SECONDS)

    # 原等待上限内仍未看到启动按钮时，先尝试窗口最大化修复一次，再补 5 次识别，避免只是窗口状态导致误判失败。
    print("[切换流程] 启动按钮未出现，尝试窗口最大化后重试。")
    logger.info("[切换流程] 启动按钮未出现，尝试窗口最大化后重试。")
    pyautogui.hotkey("winleft", "up")
    for attempt in range(1, config.SWITCH_BOUNDARY_START_QIDONG_FIXUP_RETRY_COUNT + 1):
        if _match(
            camera,
            "qd",
            config.SWITCH_BOUNDARY_START_QIDONG_REGION,
            threshold=config.SWITCH_UI_MATCH_THRESHOLD,
        ):
            print(f"[切换流程] 窗口修复后第 {attempt} 次识别到启动按钮。")
            logger.info("[切换流程] 窗口修复后第 %s 次识别到启动按钮。", attempt)
            return True
        safe_sleep(config.SWITCH_BOUNDARY_START_QIDONG_FIXUP_RETRY_INTERVAL_SECONDS)

    return pause_thread6_failure(
        "返回启动页确认",
        "未能在边界切换前确认回到启动页（qidong.png 未匹配）。",
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

    next_slot = config.EXECUTION_SLOT_NEXT_SLOT_MAP.get(current_slot)
    if next_slot is None:
        return None

    slot_index = next_slot - 1
    requires_account_switch = current_slot in config.EXECUTION_SLOT_SWITCH_TARGETS
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
        "server_coord_index": config.EXECUTION_SLOT_SERVER_COORD_INDEXES[slot_index],
        "requires_account_switch": requires_account_switch,
        "config_error": config_error,
    }


def _resolve_switch_target(current_execution_slot):
    """根据当前执行位解析小阶段目标执行位。"""
    target = resolve_execution_slot_transition(current_execution_slot)
    if not target or not target["requires_account_switch"]:
        return None
    return target


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


def _click_switch_user_and_wait_login(camera):
    """打开账号列表并进入切号登录页面。"""
    _log_switch_waits(
        "switch-user entry",
        click_wait=config.SWITCH_ACCOUNT_LIST_CLICK_WAIT_SECONDS,
        entry_timeout=config.SWITCH_USER_ENTRY_MATCH_TIMEOUT_SECONDS,
        login_click_wait=config.SWITCH_SWITCH_USER_CLICK_WAIT_SECONDS,
        login_timeout=config.SWITCH_LOGIN_PAGE_MATCH_TIMEOUT_SECONDS,
    )
    fast_click(config.SWITCH_ACCOUNT_LIST_BUTTON_POS)
    safe_sleep(config.SWITCH_ACCOUNT_LIST_CLICK_WAIT_SECONDS)

    logger.info("[切换流程] 切换账号入口模板：qiehuan.png")
    print("[切换流程] 切换账号入口模板：qiehuan.png")

    center = _wait_for_match_center(
        camera,
        "qiehuan",
        config.SWITCH_USER_TEMPLATE_REGION,
        timeout=config.SWITCH_USER_ENTRY_MATCH_TIMEOUT_SECONDS,
        threshold=config.SWITCH_UI_MATCH_THRESHOLD,
    )
    if center is None:
        pause_thread6_failure(
            "切换账号入口",
            "点击账号列表后未匹配到切换账号入口（qiehuan.png）。",
        )
        return None

    fast_click(center)
    safe_sleep(config.SWITCH_SWITCH_USER_CLICK_WAIT_SECONDS)

    login_center = _wait_for_match_center(
        camera,
        "denglu",
        config.SWITCH_LOGIN_TEMPLATE_REGION,
        timeout=config.SWITCH_LOGIN_PAGE_MATCH_TIMEOUT_SECONDS,
        threshold=config.SWITCH_UI_MATCH_THRESHOLD,
    )
    if login_center is None:
        pause_thread6_failure(
            "进入登录页",
            "点击切换账号入口后未匹配到登录页（denglu.png）。",
        )
        return None

    return login_center


def _input_and_verify_account(account_id):
    """输入账号并用剪贴板校验。"""
    _log_switch_waits(
        "account input verify",
        verify_wait=config.SWITCH_ACCOUNT_INPUT_VERIFY_WAIT_SECONDS,
    )
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
    expected = _digits_only(account_id)
    if actual != expected:
        return pause_thread6_failure(
            "账号输入校验",
            f"账号输入校验失败，期望账号 {expected}，实际剪贴板为 {actual or '空'}。",
        )
    return True


def _confirm_account_switched(camera):
    """确认切号后已回到可换区页面。"""
    _log_switch_waits(
        "heping verify",
        login_click_wait=config.SWITCH_LOGIN_CLICK_WAIT_SECONDS,
        heping_timeout=config.SWITCH_HEPING_MATCH_TIMEOUT_SECONDS,
        maximize_wait=config.SWITCH_MAXIMIZE_WAIT_SECONDS,
    )
    if _wait_for(
        camera,
        "heping",
        config.SWITCH_HEPING_REGION_PRIMARY,
        timeout=config.SWITCH_HEPING_MATCH_TIMEOUT_SECONDS,
        threshold=config.SWITCH_UI_MATCH_THRESHOLD,
    ):
        fast_click((45, 277))
        safe_sleep(0.8)
        return True

    if _match(
        camera,
        "heping",
        config.SWITCH_HEPING_REGION_SECONDARY,
        threshold=config.SWITCH_UI_MATCH_THRESHOLD,
    ):
        pyautogui.hotkey("winleft", "up")
        safe_sleep(config.SWITCH_MAXIMIZE_WAIT_SECONDS)
        if _wait_for(
            camera,
            "heping",
            config.SWITCH_HEPING_REGION_PRIMARY,
            timeout=config.SWITCH_HEPING_MATCH_TIMEOUT_SECONDS,
            threshold=config.SWITCH_UI_MATCH_THRESHOLD,
        ):
            fast_click((45, 277))
            safe_sleep(0.8)
            return True

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
    if slot_number < 1 or slot_number > len(config.EXECUTION_SLOT_NICKNAME_TEMPLATE_FILES):
        return None, ""

    nickname_match_config = _get_local_nickname_match_config()
    template_name = config.EXECUTION_SLOT_NICKNAME_TEMPLATE_FILES[slot_number - 1]
    template_path = os.path.join(nickname_match_config["template_dir"], template_name)
    template = cv2.imread(template_path)
    return template, template_path


def _verify_slot_nickname(camera, slot_number):
    """选区后执行昵称模板校验。"""
    update_overlay_mini(f"正在校验执行位 {slot_number} 的昵称")
    try:
        nickname_match_config = _get_local_nickname_match_config()
    except Exception as exc:
        return pause_thread6_failure("读取本机昵称模板配置", f"读取失败：{exc}")

    template, template_path = _load_nickname_template(slot_number)
    if template is None:
        return pause_thread6_failure(
            "加载昵称模板",
            f"昵称模板缺失：{template_path or 'unresolved path'}。",
        )

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
            return True
        safe_sleep(0.5)

    return pause_thread6_failure(
        "昵称模板校验",
        f"执行位 {slot_number} 的昵称模板校验失败：{template_path}。",
    )


def _detect_slot_nickname_once(camera, nickname_match_config):
    """在昵称校验区域内扫描当前命中的执行位模板。"""
    for slot_number in range(1, int(config.EXECUTION_SLOT_COUNT) + 1):
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
    update_overlay_mini("启动中：识别当前昵称")
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


def _step01_exit(camera):
    """步骤1：ALT+F4 并确认退出。"""
    update_overlay_mini("换号中：退出游戏")
    print("[切换流程] 正在尝试退出游戏。")
    pyautogui.hotkey("alt", "F4")
    time.sleep(1)
    fast_click((1050, 686))
    time.sleep(2)
    return True


def _step02_server_list(camera, suppress_failure_output=False):
    """步骤2：打开大区列表。"""
    update_overlay_mini("换区中：打开大区列表")
    _log_switch_waits(
        "server list",
        open_wait=config.SWITCH_SERVER_LIST_OPEN_WAIT_SECONDS,
        qidong_timeout=config.SWITCH_QIDONG_MATCH_TIMEOUT_SECONDS,
    )
    # 启动器刚回到前台时控件可能还没稳定，先等 3 秒再点，避免点在页面过渡阶段导致后续选区失效。
    safe_sleep(config.SWITCH_SERVER_LIST_OPEN_WAIT_SECONDS)
    pyautogui.click(1500, 990)

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
    center = _wait_for_match_center(
        camera,
        "kg",
        config.RGN_KG,
        timeout=config.SWITCH_SPACE_MATCH_TIMEOUT_SECONDS,
    )
    if center is None:
        if not suppress_failure_output:
            async_push_msg("【切换流程】未找到空格弹窗", "30 秒内未识别到空格弹窗。")
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


def _step08_gold(camera):
    """步骤8：领取金币。"""
    update_overlay_mini("进场中：领取金币")
    # 领取金币是连续点固定入口，间隔太短容易前一步动画没收完，统一压到 0.8 秒减少空点。
    pyautogui.click(1868, 1044)
    time.sleep(config.SWITCH_GOLD_CLICK_WAIT_SECONDS)
    pyautogui.click(1767, 824)
    time.sleep(config.SWITCH_GOLD_CLICK_WAIT_SECONDS)
    pyautogui.click(1650, 1000)
    time.sleep(config.SWITCH_GOLD_CLICK_WAIT_SECONDS)
    return True


def _step09_close(camera, suppress_failure_output=False):
    """步骤9：关闭面板并确认仍在古墓大厅。"""
    update_overlay_mini("进场中：关闭面板")
    # 这里连续按 ESC 的目的只是稳定收起面板，按太多会拖慢节奏，按太快又可能没被页面吃到。
    for _ in range(config.SWITCH_CLOSE_PANEL_ESC_COUNT):
        pyautogui.press("escape")
        time.sleep(config.SWITCH_CLOSE_PANEL_ESC_INTERVAL_SECONDS)
    time.sleep(config.SWITCH_CLOSE_PANEL_AFTER_ESC_WAIT_SECONDS)

    # ESC 收完后再点一次中间位置，让焦点真正回到大厅，再等 0.5 秒避免马上识图过早。
    pyautogui.click(830, 690)
    time.sleep(config.SWITCH_CLOSE_PANEL_AFTER_CLICK_WAIT_SECONDS)

    if not _wait_for(camera, "gumu", config.RGN_GUMU, timeout=5):
        if not suppress_failure_output:
            async_push_msg("【切换流程】关闭面板失败", "关闭面板后未能确认仍在古墓大厅。")
        return False
    return True


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
        ("领取金币", lambda: _step08_gold(camera)),
        ("关闭面板", lambda: _step09_close(camera)),
        ("返回交易行", lambda: _step10_trade(camera)),
    ])

    for name, fn in steps:
        logger.info("[切换流程] %s开始。", name)
        if not fn():
            logger.error("[切换流程] %s失败。", name)
            restore_overlay()
            return False
        logger.info("[切换流程] %s完成。", name)

    logger.info("[切换流程] 目标大区 %s 已就绪。", server_index + 1)
    return True


def startup_from_launcher(camera, server_index):
    """执行从启动器到交易行的完整流程。"""
    return _run_startup_from_launcher(camera, server_index, skip_open_server_list=False)


def startup_from_server_list(camera, server_index):
    """已位于选区页时，继续执行后续启动链路。"""
    return _run_startup_from_launcher(camera, server_index, skip_open_server_list=True)


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
    if _match(camera, "gumu", config.RGN_GUMU):
        time.sleep(1)
        return _match(camera, "gumu", config.RGN_GUMU)
    time.sleep(1)
    return _match(camera, "gumu", config.RGN_GUMU)


def navigate_to_trade(camera):
    """从古墓大厅前往交易行。"""
    return _step10_trade(camera)


def _run_thread6_resume_steps(camera):
    resume_steps = [
        ("启动游戏", lambda: _step04_launch(camera, suppress_failure_output=True), "未匹配到启动按钮或启动点击失败。"),
        ("处理空格弹窗", lambda: _step05_space(camera, suppress_failure_output=True), "未匹配到空格弹窗或处理失败。"),
        ("进入游戏场景", lambda: _step06_ads(camera, suppress_failure_output=True), "未能完成进入游戏场景前的页面清理。"),
        ("确认古墓大厅", lambda: _step07_gumu(camera, suppress_failure_output=True), "未能进入或确认古墓大厅。"),
        ("领取金币", lambda: _step08_gold(camera), "领取金币步骤执行失败。"),
        ("关闭面板", lambda: _step09_close(camera, suppress_failure_output=True), "关闭面板后未能确认仍在古墓大厅。"),
        ("返回交易行", lambda: _step10_trade(camera), "未能完成返回交易行步骤。"),
    ]
    for step_name, fn, detail in resume_steps:
        if not _run_thread6_step(step_name, detail, fn):
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
            lambda: _verify_slot_nickname(camera, target["next_slot"]),
        ):
            return False

        if not _run_thread6_step("恢复进场链路", "同账号跨区切换后未能完成回到交易行的后续步骤。", lambda: _run_thread6_resume_steps(camera)):
            return False

        state.current_execution_slot = target["next_slot"]
        state.current_server_index = target["server_coord_index"]
        state.current_account_index = 0 if target["next_slot"] <= 4 else 1
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
            lambda: _verify_slot_nickname(camera, target["next_slot"]),
        ):
            return False

        if not _run_thread6_step("恢复进场链路", "跨账号切换后未能完成回到交易行的后续步骤。", lambda: _run_thread6_resume_steps(camera)):
            return False

        state.current_execution_slot = target["next_slot"]
        state.current_server_index = target["server_coord_index"]
        state.current_account_index = 0 if target["next_slot"] <= 4 else 1
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
