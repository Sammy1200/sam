"""
换区辅助函数。

对外接口：
  startup_from_launcher(camera, server_index)
  full_switch_server(camera, server_index)
  is_at_gumu(camera)
  navigate_to_trade(camera)
"""

import time
import cv2
import pyautogui
import state
import config
from utils import (
    async_push_msg,
    fast_click,
    logger,
    press_key,
    set_overlay_mini,
    update_overlay_mini,
    restore_overlay,
)


_TPL_CACHE = {}
_TPL_FILES = {
    "f4": "f4queding.png",
    "qd": "qidong.png",
    "kg": "kongge.png",
    "1tc": "1tanchuang.png",
    "gumu": "gumudating.png",
}


def _tpl(key):
    """按需加载模板并缓存。"""
    if key not in _TPL_CACHE:
        path = f"logo/huanhao/{_TPL_FILES[key]}"
        img = cv2.imread(path)
        if img is None:
            raise FileNotFoundError(f"模板文件不存在：{path}")
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


def _match(camera, key, region, threshold=0.8):
    """执行单次模板匹配。"""
    frame = camera.get_latest_frame()
    if frame is None:
        return False
    x1, y1, x2, y2 = region
    roi = frame[y1:y2, x1:x2]
    tpl = _tpl(key)
    roi = _normalize_match_image(roi)
    tpl = _normalize_match_image(tpl)
    if roi is None or tpl is None:
        return False
    th, tw = tpl.shape[:2]
    rh, rw = roi.shape[:2]
    if rh < th or rw < tw:
        return False
    res = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
    _, val, _, _ = cv2.minMaxLoc(res)
    return val >= threshold


def _match_center(camera, key, region, threshold=0.8):
    """返回模板匹配中心坐标，未命中时返回 None。"""
    frame = camera.get_latest_frame()
    if frame is None:
        return None
    x1, y1, x2, y2 = region
    roi = frame[y1:y2, x1:x2]
    tpl = _tpl(key)
    roi = _normalize_match_image(roi)
    tpl = _normalize_match_image(tpl)
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


def _wait_for(camera, key, region, timeout, label=""):
    """等待模板出现，并再次确认一次。"""
    end = time.time() + timeout
    while time.time() < end:
        if _match(camera, key, region):
            time.sleep(1)
            if _match(camera, key, region):
                return True
        time.sleep(1)
    return False


def _wait_for_match_center(camera, key, region, timeout, threshold=0.8):
    """循环等待模板出现，并返回中心坐标。"""
    end = time.time() + timeout
    while time.time() < end:
        center = _match_center(camera, key, region, threshold=threshold)
        if center is not None:
            return center
        time.sleep(1)
    return None


def _wait_gone(camera, key, region, timeout):
    """等待模板消失，并再次确认一次。"""
    end = time.time() + timeout
    while time.time() < end:
        if not _match(camera, key, region):
            time.sleep(1)
            if not _match(camera, key, region):
                return True
        time.sleep(1)
    return False


def _pixels_white(camera):
    """检查两个探针像素是否都接近白色。"""
    frame = camera.get_latest_frame()
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
    time.sleep(1)
    return _pixels_white(camera)


def _step01_exit(camera):
    """步骤1：ALT+F4 并确认退出。"""
    update_overlay_mini("【换区中】步骤1：退出游戏")
    print("[退出游戏] 开始识别退出按钮...")
    print("[退出游戏] 识别结果: True, 坐标: Alt+F4")
    pyautogui.hotkey("alt", "F4")
    print("[退出游戏] 已发送 Alt+F4")
    time.sleep(1)
    fast_click((1050, 686))
    print("[退出游戏] 已点击确认按钮 (1050, 686)")
    time.sleep(2)
    print("[退出游戏] 等待游戏退出完成")
    return True


def _step02_server_list(camera):
    """步骤2：打开大区列表。"""
    update_overlay_mini("【换区中】步骤2：打开服务器列表")
    time.sleep(5)
    pyautogui.click(1500, 990)
    time.sleep(1)

    if not _wait_for(camera, "qd", config.RGN_QD, timeout=30, label="启动按钮"):
        async_push_msg("【换区】30 秒内未检测到启动按钮")
        return False
    return True


def _step03_select(camera, idx):
    """步骤3：点击目标大区。"""
    update_overlay_mini("【换区中】步骤3：选择大区")
    if idx < 0 or idx >= len(config.SERVER_COORDS):
        async_push_msg(f"【换区】大区索引 {idx} 超出范围（共 {len(config.SERVER_COORDS)} 个）")
        return False

    coord = config.SERVER_COORDS[idx]
    pyautogui.click(*coord)
    time.sleep(2)

    if _match(camera, "qd", config.RGN_QD):
        return True

    pyautogui.click(*coord)
    time.sleep(2)

    if _match(camera, "qd", config.RGN_QD):
        return True

    async_push_msg("【换区】选择大区后未检测到启动按钮")
    return False


def _step04_launch(camera):
    """步骤4：点击启动游戏。"""
    update_overlay_mini("【换区中】步骤4：启动游戏")
    center = _wait_for_match_center(camera, "qd", config.RGN_QD, timeout=15)
    if center is None:
        async_push_msg("【换区】15 秒内未检测到启动按钮")
        return False
    fast_click(center)
    print(f"[启动游戏] 已点击 qidong.png 中心坐标 ({center[0]}, {center[1]})")
    time.sleep(0.5)
    press_key(0x20)
    print("[启动游戏] 已按下空格键")
    return True


def _step05_space(camera):
    """步骤5：处理启动过程中的弹窗（kongge.png），按空格关闭。"""
    update_overlay_mini("【换区中】步骤5：处理启动弹窗")
    center = _wait_for_match_center(camera, "kg", config.RGN_KG, timeout=60)
    if center is None:
        async_push_msg("【换区】60 秒内未检测到空格提示弹窗")
        return False
    time.sleep(1)
    fast_click(center)
    print(f"[启动弹窗] 已点击 kongge.png 中心坐标 ({center[0]}, {center[1]})")
    time.sleep(1)
    press_key(0x20)
    print("[启动弹窗] 已按下空格键")
    time.sleep(10)
    print("[启动弹窗] 等待10秒进入游戏")
    return True


def _step06_ads(camera):
    """步骤6：持续按 ESC 清理广告流程。"""
    update_overlay_mini("【换区中】步骤6：关闭广告")
    end = time.time() + 120
    while time.time() < end:
        center = _match_center(camera, "1tc", config.RGN_1TC)
        if center is not None:
            print("[关闭广告] 检测到 1tanchuang.png")
            time.sleep(1)
            fast_click(center)
            print(f"[关闭广告] 已点击 1tanchuang.png 中心坐标 ({center[0]}, {center[1]})")
            print("[关闭广告] 通过 1tanchuang.png 入口进入古墓大厅")
            if _wait_for(camera, "gumu", config.RGN_GUMU, timeout=30, label="古墓大厅"):
                return True
        pyautogui.press("escape")
        time.sleep(1.5)
        time.sleep(2)
        if _confirm_white(camera):
            return True

    async_push_msg("【换区】120 秒内未清理完广告")
    return False


def _step07_gumu(camera):
    """步骤7：传送到古墓大厅。"""
    update_overlay_mini("【换区中】步骤7：进入古墓大厅")
    if is_at_gumu(camera):
        print("[进入古墓大厅] 已经位于古墓大厅，跳过点击")
        return True
    pyautogui.click(190, 58)
    time.sleep(1)

    if not _wait_for(camera, "gumu", config.RGN_GUMU, timeout=30, label="古墓大厅"):
        async_push_msg("【换区】30 秒内未到达古墓大厅")
        return False
    return True


def _step08_gold(camera):
    """步骤8：领取金币。"""
    update_overlay_mini("【换区中】步骤8：领取金币")
    pyautogui.click(1868, 1044)
    time.sleep(1)
    pyautogui.click(1767, 824)
    time.sleep(1)
    pyautogui.click(1650, 1000)
    time.sleep(1)
    return True


def _step09_close(camera):
    """步骤9：关闭面板并确认仍在古墓大厅。"""
    update_overlay_mini("【换区中】步骤9：关闭弹窗")
    for _ in range(5):
        pyautogui.press("escape")
        time.sleep(0.5)
    time.sleep(1)

    pyautogui.click(830, 690)
    time.sleep(1)

    if not _wait_for(camera, "gumu", config.RGN_GUMU, timeout=5, label="关闭后古墓大厅"):
        async_push_msg("【换区】关闭面板后未处于古墓大厅")
        return False
    return True


def _step10_trade(camera):
    """步骤10：从古墓大厅前往交易行。"""
    update_overlay_mini("【换区中】步骤10：进入交易行")
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
    set_overlay_mini("【换区中】准备开始...")
    state.current_server_index = server_index

    steps = [
        ("步骤2：打开大区列表", lambda: _step02_server_list(camera)),
        ("步骤3：选择大区", lambda: _step03_select(camera, server_index)),
        ("步骤4：启动游戏", lambda: _step04_launch(camera)),
        ("步骤5：等待空格提示", lambda: _step05_space(camera)),
        ("步骤6：清理广告流程", lambda: _step06_ads(camera)),
        ("步骤7：传送古墓大厅", lambda: _step07_gumu(camera)),
        ("步骤8：领取金币", lambda: _step08_gold(camera)),
        ("步骤9：关闭面板", lambda: _step09_close(camera)),
        ("步骤10：前往交易行", lambda: _step10_trade(camera)),
    ]

    for name, fn in steps:
        logger.info(f"[换区] {name}...")
        if not fn():
            logger.error(f"[换区] {name}失败")
            restore_overlay()
            return False
        logger.info(f"[换区] {name}完成")

    logger.info(f"[换区] 大区 {server_index + 1} 已就绪")
    return True


def full_switch_server(camera, server_index):
    """运行中换区：先退出游戏，再复用启动器流程。"""
    set_overlay_mini("【换区中】准备开始...")
    logger.info("[换区] 步骤1：退出游戏...")
    if not _step01_exit(camera):
        logger.error("[换区] 退出游戏失败")
        restore_overlay()
        return False
    logger.info("[换区] 退出游戏完成")

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
