"""
所有常量、坐标、阈值、路径配置
规则：只有 = 赋值，不写任何函数和 import（os 除外）
"""
import os

# --- 脚本路径 ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "logo", "shangjia")

# --- 监控区域 ---
MONITOR_PRICE = {"left": 1473, "top": 181, "width": 79, "height": 22}
MONITOR_SUCCESS = {"left": 780, "top": 190, "width": 370, "height": 143}
MONITOR_SHOP = {"left": 1600, "top": 100, "width": 66, "height": 55}
MONITOR_JIAOYIHANG = {"left": 1698, "top": 184, "width": 64, "height": 87}
MONITOR_GOUMAI = {"left": 883, "top": 367, "width": 80, "height": 33}
MONITOR_MEIHUO = {"left": 590, "top": 838, "width": 117, "height": 46}
MONITOR_DIYICI = {"left": 780, "top": 673, "width": 107, "height": 43}
MONITOR_BALANCE = {"left": 1690, "top": 10, "width": 150, "height": 36}
MONITOR_TEXT_SHANGJIA = {"left": 70, "top": 80, "width": 110, "height": 50}
MONITOR_TEXT_JIAOSHI = {"left": 1700, "top": 350, "width": 60, "height": 40}
MONITOR_CAPACITY = {"left": 179, "top": 103, "width": 51, "height": 27}
POPUP_REGION = {"left": 300, "top": 200, "width": 188, "height": 63}
SCAN_REGION = {"left": 1212, "top": 94, "width": 468, "height": 956}
MONITOR_TISHI = {"left": 737, "top": 664, "width": 188, "height": 263}

# --- 点击坐标 ---
REFRESH_POS = (1400, 230)
EXIT_POS = (1893, 34)
BUY_POS = (641, 859)
CONFIRM_POS = (1096, 687)
SUCCESS_CONFIRM_POS = (960, 830)
FIX_SHOP_POS1 = (1850, 270)
FIX_SHOP_POS2 = (1850, 355)
DIYICI_CLICK_POS = (833, 694)
CLICK_1 = (1850, 990)
CLICK_2 = (1855, 269)
CLICK_JIAOSHI = (1730, 370)
PRICE_INPUT_POS = (1219, 736)
CONFIRM_BTN_POS = (1386, 802)
SCROLL_POS = (1400, 520)

# --- 抢购参数 ---
MAX_PRICE = 1300001
MIN_PRICE = 325000
CONFIRM_DELAY = 0.01
PRE_EXIT_CLICK_DELAY = 0.03
EXIT_DELAY = 1.88
MISMATCH_EXIT_DELAY = 1.88
ACCOUNT_LIMIT_THRESHOLD = 20
IDLE_PUSH_INTERVAL = 1800
STUCK_PUSH_INTERVAL = 300
FRAME_MAX_AGE = 0.2

# --- 上架参数 ---
TARGET_PRICE = "3249911"
SIMILARITY_THRESHOLD = 0.95
POST_LIST_WAIT = 1.5
MAX_LISTING_RETRY = 3
ITEM_THRESHOLD = 0.75
POPUP_THRESHOLD = 0.85
LIST_INTERVAL = 55 * 60

# --- 容量模板参数 ---
UPSCALE = 4
STANDARD_W = 20
STANDARD_H = 28
