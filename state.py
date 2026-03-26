"""
所有全局可变状态，其他模块通过 import state 后用 state.xxx 读写
规则：只有变量初始化，不写函数
"""
import pyautogui
pyautogui.FAILSAFE = False

# --- 脚本控制 ---
IS_PAUSED = False
start_mode = 0
target_stop_seconds = 0

# --- 计数器 ---
success_count = 0
fail_count = 0
total_listed_count = 0
limit_count = 0
unknown_page_count = 0

# --- 时间追踪 ---
total_running_time = 0.0
last_resume_time = None
last_list_time = 0.0

# --- 余额 ---
current_balance = "获取中..."
_last_balance_hash = None

# --- 引擎/模板引用（运行时赋值）---
ocr_engine = None
temp_jiaoyi = None
TEMP_ITEM = None
TEMP_TISHI = None
TEMP_POPUP = None
DIGIT_TEMPLATES = {}

# --- 悬浮窗引用 ---
overlay_root = None
log_text_var = None
score_var = None
log_lines = []
