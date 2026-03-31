"""
Switch helpers for launcher/server/account flow.

Public APIs:
  startup_from_launcher(camera, server_index)
  full_switch_server(camera, server_index)
  is_at_gumu(camera)
  navigate_to_trade(camera)
  switch_account_after_slot_boundary(camera)
"""

import os
import time

import cv2
import pyautogui

import config
import state
from overlay import toggle_pause
from utils import (
    async_push_msg,
    fast_click,
    get_clipboard_text,
    hotkey,
    logger,
    press_key,
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
}


def _tpl(key):
    """按需加载模板并缓存。"""
    if key not in _TPL_CACHE:
        path = os.path.join("logo", "huanhao", _TPL_FILES[key])
        img = cv2.imread(path)
        if img is None:
            logger.error("[switch] template missing: %s", path)
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
    """1 秒后再次确认白色像素。"""
    if not _pixels_white(camera):
        return False
    safe_sleep(1)
    return _pixels_white(camera)


def _pause_switch_flow(title, detail):
    """失败时推送并停在当前界面。"""
    state.switch_flow_paused = True
    state.switch_last_unknown_detail = detail
    state.overlay_status = "未知异常"
    print(detail)
    logger.error(detail)
    async_push_msg(title, detail)
    restore_overlay()
    if not state.IS_PAUSED:
        toggle_pause()


def _wait_for_boundary_start_qidong(camera):
    """边界换号时，先确认是否已回到启动页面。"""
    _log_switch_waits(
        "boundary start qidong check",
        retry_count=config.SWITCH_BOUNDARY_START_QIDONG_RETRY_COUNT,
        retry_interval=config.SWITCH_BOUNDARY_START_QIDONG_RETRY_INTERVAL_SECONDS,
    )
    for attempt in range(1, config.SWITCH_BOUNDARY_START_QIDONG_RETRY_COUNT + 1):
        if _match(
            camera,
            "qd",
            config.SWITCH_BOUNDARY_START_QIDONG_REGION,
            threshold=config.SWITCH_UI_MATCH_THRESHOLD,
        ):
            print(f"[switch] boundary start qidong matched at attempt {attempt}.")
            logger.info("[switch] boundary start qidong matched at attempt %s.", attempt)
            return True
        safe_sleep(config.SWITCH_BOUNDARY_START_QIDONG_RETRY_INTERVAL_SECONDS)

    _pause_switch_flow(
        "[switch] boundary start qidong not found",
        "[switch] qidong.png was not matched in boundary start region after exit-game wait loop.",
    )
    return False


def _resolve_switch_target(current_execution_slot):
    """根据当前执行位解析小阶段目标执行位。"""
    try:
        current_slot = int(current_execution_slot)
    except (TypeError, ValueError):
        return None

    next_slot = config.EXECUTION_SLOT_SWITCH_TARGETS.get(current_slot)
    if next_slot is None:
        return None

    slot_index = next_slot - 1
    return {
        "current_slot": current_slot,
        "next_slot": next_slot,
        "account_id": config.EXECUTION_SLOT_ACCOUNT_IDS[slot_index],
        "server_coord_index": config.EXECUTION_SLOT_SERVER_COORD_INDEXES[slot_index],
    }


def _digits_only(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _log_switch_waits(step_name, **kwargs):
    details = ", ".join(f"{key}={value}" for key, value in kwargs.items())
    message = f"[switch] {step_name} waits: {details}"
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

    logger.info("[switch] switch-user entry template: qiehuan.png")
    print("[switch] switch-user entry template: qiehuan.png")

    center = _wait_for_match_center(
        camera,
        "qiehuan",
        config.SWITCH_USER_TEMPLATE_REGION,
        timeout=config.SWITCH_USER_ENTRY_MATCH_TIMEOUT_SECONDS,
        threshold=config.SWITCH_UI_MATCH_THRESHOLD,
    )
    if center is None:
        _pause_switch_flow(
            "[switch] missing switch user entry",
            "[switch] qiehuan.png was not matched in switch-user region after clicking account list button.",
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
        _pause_switch_flow(
            "[switch] login page not reached",
            "[switch] denglu.png was not matched after clicking switch-user entry.",
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
        _pause_switch_flow(
            "[switch] account input verify failed",
            f"[switch] expected account={expected}, actual clipboard={actual or 'empty'}.",
        )
        return False
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

    _pause_switch_flow(
        "[switch] heping page verify failed",
        "[switch] hepingjingying.png was not matched after account login.",
    )
    return False


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

    template_name = config.EXECUTION_SLOT_NICKNAME_TEMPLATE_FILES[slot_number - 1]
    template_path = os.path.join(config.NICKNAME_TEMPLATE_DIR, template_name)
    template = cv2.imread(template_path)
    return template, template_path


def _verify_slot_nickname(camera, slot_number):
    """选区后执行昵称模板校验。"""
    update_overlay_mini(f"[switch] verify nickname slot {slot_number}")
    template, template_path = _load_nickname_template(slot_number)
    if template is None:
        _pause_switch_flow(
            "[switch] nickname template missing",
            f"[switch] nickname template missing: {template_path or 'unresolved path'}.",
        )
        return False

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
            config.NICKNAME_VERIFY_REGION,
            threshold=config.NICKNAME_MATCH_THRESHOLD,
        ):
            print(f"[switch] nickname template ok for slot {slot_number}: {template_path}")
            logger.info("[switch] nickname template ok for slot %s: %s", slot_number, template_path)
            return True
        safe_sleep(0.5)

    _pause_switch_flow(
        "[switch] nickname template mismatch",
        f"[switch] nickname template mismatch for slot {slot_number}: {template_path}.",
    )
    return False


def _step01_exit(camera):
    """步骤1：ALT+F4 并确认退出。"""
    update_overlay_mini("[switch] step1 exit game")
    print("[switch] try exit game")
    pyautogui.hotkey("alt", "F4")
    time.sleep(1)
    fast_click((1050, 686))
    time.sleep(2)
    return True


def _step02_server_list(camera):
    """步骤2：打开大区列表。"""
    update_overlay_mini("[switch] step2 open server list")
    _log_switch_waits(
        "server list",
        open_wait=config.SWITCH_SERVER_LIST_OPEN_WAIT_SECONDS,
        qidong_timeout=config.SWITCH_QIDONG_MATCH_TIMEOUT_SECONDS,
    )
    safe_sleep(config.SWITCH_SERVER_LIST_OPEN_WAIT_SECONDS)
    pyautogui.click(1500, 990)

    if not _wait_for(camera, "qd", config.RGN_QD, timeout=config.SWITCH_QIDONG_MATCH_TIMEOUT_SECONDS):
        async_push_msg("[switch] qidong not found", "[switch] qidong button not found within 30 seconds.")
        return False
    return True


def _step03_select(camera, idx):
    """步骤3：点击目标大区。"""
    update_overlay_mini("[switch] step3 select server")
    if idx < 0 or idx >= len(config.SERVER_COORDS):
        async_push_msg("[switch] invalid server index", f"[switch] invalid server index: {idx}.")
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

    async_push_msg("[switch] server select failed", "[switch] qidong button not found after selecting server.")
    return False


def _step04_launch(camera):
    """步骤4：点击启动游戏。"""
    update_overlay_mini("[switch] step4 launch game")
    center = _wait_for_match_center(camera, "qd", config.RGN_QD, timeout=15)
    if center is None:
        async_push_msg("[switch] qidong not found", "[switch] qidong button not found within 15 seconds.")
        return False
    fast_click(center)
    time.sleep(0.5)
    press_key(0x20)
    return True


def _step05_space(camera):
    """步骤5：处理启动弹窗。"""
    update_overlay_mini("[switch] step5 handle kongge")
    center = _wait_for_match_center(camera, "kg", config.RGN_KG, timeout=60)
    if center is None:
        async_push_msg("[switch] kongge not found", "[switch] kongge popup not found within 60 seconds.")
        return False
    time.sleep(1)
    fast_click(center)
    time.sleep(1)
    press_key(0x20)
    time.sleep(10)
    return True


def _step06_ads(camera):
    """步骤6：持续按 ESC 清理广告流程。"""
    update_overlay_mini("[switch] step6 clear ads")
    end = time.time() + 120
    while time.time() < end:
        center = _match_center(camera, "1tc", config.RGN_1TC)
        if center is not None:
            time.sleep(1)
            fast_click(center)
            if _wait_for(camera, "gumu", config.RGN_GUMU, timeout=30):
                return True
        pyautogui.press("escape")
        time.sleep(1.5)
        time.sleep(2)
        if _confirm_white(camera):
            return True

    async_push_msg("[switch] ads clear timeout", "[switch] failed to clear ads within 120 seconds.")
    return False


def _step07_gumu(camera):
    """步骤7：传送到古墓大厅。"""
    update_overlay_mini("[switch] step7 gumu")
    if is_at_gumu(camera):
        return True
    pyautogui.click(190, 58)
    time.sleep(1)

    if not _wait_for(camera, "gumu", config.RGN_GUMU, timeout=30):
        async_push_msg("[switch] gumu not reached", "[switch] gumu not reached within 30 seconds.")
        return False
    return True


def _step08_gold(camera):
    """步骤8：领取金币。"""
    update_overlay_mini("[switch] step8 gold")
    pyautogui.click(1868, 1044)
    time.sleep(1)
    pyautogui.click(1767, 824)
    time.sleep(1)
    pyautogui.click(1650, 1000)
    time.sleep(1)
    return True


def _step09_close(camera):
    """步骤9：关闭面板并确认仍在古墓大厅。"""
    update_overlay_mini("[switch] step9 close panels")
    for _ in range(5):
        pyautogui.press("escape")
        time.sleep(0.5)
    time.sleep(1)

    pyautogui.click(830, 690)
    time.sleep(1)

    if not _wait_for(camera, "gumu", config.RGN_GUMU, timeout=5):
        async_push_msg("[switch] close panel failed", "[switch] gumu not visible after closing panels.")
        return False
    return True


def _step10_trade(camera):
    """步骤10：从古墓大厅前往交易行。"""
    update_overlay_mini("[switch] step10 trade")
    pyautogui.click(1470, 1032)
    time.sleep(2)
    pyautogui.click(470, 50)
    time.sleep(2)
    pyautogui.click(1850, 350)
    time.sleep(5)
    restore_overlay()
    return True


def startup_from_launcher(camera, server_index):
    """执行从启动器到交易行的完整流程。"""
    set_overlay_mini("[switch] prepare launcher flow")
    state.current_server_index = server_index

    steps = [
        ("step2 open server list", lambda: _step02_server_list(camera)),
        ("step3 select server", lambda: _step03_select(camera, server_index)),
        ("step4 launch", lambda: _step04_launch(camera)),
        ("step5 kongge", lambda: _step05_space(camera)),
        ("step6 ads", lambda: _step06_ads(camera)),
        ("step7 gumu", lambda: _step07_gumu(camera)),
        ("step8 gold", lambda: _step08_gold(camera)),
        ("step9 close", lambda: _step09_close(camera)),
        ("step10 trade", lambda: _step10_trade(camera)),
    ]

    for name, fn in steps:
        logger.info("[switch] %s ...", name)
        if not fn():
            logger.error("[switch] %s failed", name)
            restore_overlay()
            return False
        logger.info("[switch] %s done", name)

    logger.info("[switch] server %s ready", server_index + 1)
    return True


def full_switch_server(camera, server_index):
    """运行中换区：先退出游戏，再复用启动器流程。"""
    set_overlay_mini("[switch] prepare full switch")
    logger.info("[switch] step1 exit game ...")
    if not _step01_exit(camera):
        logger.error("[switch] exit game failed")
        restore_overlay()
        return False
    logger.info("[switch] exit game done")

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


def switch_account_after_slot_boundary(camera):
    """线程 6 小阶段：4/8 区结束后切号、选区并做昵称模板校验。"""
    target = _resolve_switch_target(state.current_execution_slot)
    if target is None:
        return False

    set_overlay_mini("[switch] prepare boundary account switch")
    print(
        f"[switch] current slot={target['current_slot']}, "
        f"next slot={target['next_slot']}, account={target['account_id']}"
    )
    logger.info(
        "[switch] current slot=%s next slot=%s account=%s",
        target["current_slot"],
        target["next_slot"],
        target["account_id"],
    )

    if not _step01_exit(camera):
        _pause_switch_flow("[switch] exit game failed", "[switch] failed before entering account switch flow.")
        return False

    if not _wait_for_boundary_start_qidong(camera):
        return False

    if not _switch_account_for_slot(camera, target["account_id"]):
        return False

    if not _step02_server_list(camera):
        _pause_switch_flow("[switch] server list open failed", "[switch] failed to open server list after account switch.")
        return False

    if not _step03_select(camera, target["server_coord_index"]):
        _pause_switch_flow("[switch] server select failed", "[switch] failed to select target server after account switch.")
        return False

    if not _verify_slot_nickname(camera, target["next_slot"]):
        return False

    resume_steps = [
        ("step4 launch", lambda: _step04_launch(camera)),
        ("step5 kongge", lambda: _step05_space(camera)),
        ("step6 ads", lambda: _step06_ads(camera)),
        ("step7 gumu", lambda: _step07_gumu(camera)),
        ("step8 gold", lambda: _step08_gold(camera)),
        ("step9 close", lambda: _step09_close(camera)),
        ("step10 trade", lambda: _step10_trade(camera)),
    ]
    for name, fn in resume_steps:
        logger.info("[switch] %s ...", name)
        if not fn():
            detail = f"[switch] failed during boundary post-select flow: {name}."
            print(detail)
            logger.error(detail)
            restore_overlay()
            state.switch_flow_paused = True
            state.switch_last_unknown_detail = detail
            state.overlay_status = "未知异常"
            if not state.IS_PAUSED:
                toggle_pause()
            return False
        logger.info("[switch] %s done", name)

    state.current_execution_slot = target["next_slot"]
    state.current_server_index = target["server_coord_index"]
    state.current_account_index = 0 if target["next_slot"] <= 4 else 1
    state.current_nickname = str(target["next_slot"])
    state.need_switch_server = False
    state.switch_flow_paused = False
    state.switch_last_unknown_detail = ""
    restore_overlay()
    print(
        f"[switch] boundary flow done: next slot={target['next_slot']} "
        f"account={target['account_id']} trade_ready=true"
    )
    logger.info(
        "[switch] boundary flow done: next slot=%s account=%s trade_ready=true",
        target["next_slot"],
        target["account_id"],
    )
    return True
