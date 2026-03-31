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
MAX_PRICE = 1400001
MIN_PRICE = 325000
CONFIRM_DELAY = 0.01
PRE_EXIT_CLICK_DELAY = 0.03
EXIT_DELAY = 1.88
MISMATCH_EXIT_DELAY = 1.88
ACCOUNT_LIMIT_THRESHOLD = 5
IDLE_PUSH_INTERVAL = 1800
STUCK_PUSH_INTERVAL = 300
FRAME_MAX_AGE = 0.2
ACCOUNT_MAX_PURCHASE_SECONDS = (2 * 60 + 50) * 60
ACCOUNT_LIMIT_COOLDOWN_SECONDS = (24 * 60 + 5) * 60

# --- 上架参数 ---
TARGET_PRICE = "3249911"
SIMILARITY_THRESHOLD = 0.95
POST_LIST_WAIT = 1.5
MAX_LISTING_RETRY = 3
ITEM_THRESHOLD = 0.75
POPUP_THRESHOLD = 0.85
LIST_INTERVAL = 56 * 60

# --- 容量模板参数 ---
UPSCALE = 4
STANDARD_W = 20
STANDARD_H = 28

# --- 线程 6：执行位/运行态 ---
EXECUTION_SLOT_COUNT = 8
EXECUTION_SLOT_NICKNAMES = (
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
)
THREAD6_RUNTIME_DB_PATH = os.path.join(SCRIPT_DIR, "thread6_runtime.sqlite3")
ACCOUNT_STATS_DB_PATH = os.path.join(SCRIPT_DIR, "account_stats.sqlite3")
SWITCH_STEP_MAX_RETRY = 3

# ========= 换区/换号相关 =========

SERVER_COORDS = [
    (1480, 805),   # 1区
    (1480, 850),   # 2区
    (1480, 888),   # 3区
    (1480, 928),   # 4区
]

RGN_F4   = (980,  666, 1118, 700)
RGN_QD   = (1650, 965, 1800, 1010)
RGN_WX   = (1390, 778, 1590, 944)
RGN_KG   = (900,  942, 1018, 980)
RGN_1TC  = (741,  667, 920,  725)
RGN_GUMU = (1400, 1000, 1540, 1065)

# 切号流程使用的启动器坐标。
# 若启动器布局与当前机器不一致，只调整坐标，不改流程逻辑。
LAUNCHER_SWITCH_USER_POS = (1490, 900)
ACCOUNT_SELECT_COORDS = [
    (1490, 820),   # 账号1
    (1490, 875),   # 账号2
]
