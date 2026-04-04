"""Mutable global state; keep variables only, no functions."""
import pyautogui

pyautogui.FAILSAFE = False

# --- script control ---
IS_PAUSED = False
start_mode = 0
target_stop_seconds = 0
temporary_purchase_mode = False

# --- 现有流程兼容计数器（后续线程再与线程 2 正式字段对接） ---
success_count = 0
fail_count = 0
total_listed_count = 0
limit_count = 0
unknown_page_count = 0

# --- 现有流程兼容计时 ---
total_running_time = 0.0
last_resume_time = None
last_list_time = 0.0
purchase_timer_active = False

# --- 现有流程兼容余额 ---
current_balance = "\u83b7\u53d6\u4e2d..."
last_valid_balance = ""
_last_balance_hash = None
price_roi_cache_bytes = None
price_roi_cache_value = None
price_decision_cache_bytes = None
price_decision_cache_decision = None
price_decision_cache_value = None
price_decision_cache_text = None

# --- runtime-loaded engines/templates ---
ocr_engine = None
temp_jiaoyi = None
temp_shop = None
TEMP_ITEM = None
TEMP_TISHI = None
TEMP_POPUP = None
DIGIT_TEMPLATES = {}

# --- overlay refs ---
overlay_root = None
log_text_var = None
score_var = None
log_lines = []
overlay_last_log_replaceable = False

current_server_index = 0
current_account_index = 0
need_switch_server = False
switch_flow_paused = False
switch_last_unknown_detail = ""
slot_nicknames = {}

# --- 线程 2：基线字段 ---
current_nickname = ""
baseline_item_count = 0
current_execution_slot = 1

# --- 线程 2：本轮过程字段 ---
round_purchase_success_count = 0
round_listing_success_count = 0
round_purchase_fail_count = 0
round_current_balance = ""
listing_scan_miss_count = 0
listing_periodic_disabled = False
listing_periodic_disabled_reason = ""
listing_periodic_skip_logged = False

# --- 线程 2：状态字段 ---
round_status = "手动结束"

# --- 线程 2：时间字段 ---
round_purchase_running_seconds = 0.0
runtime_window_start_time = None
last_limit_time = None
last_account_end_time = None
updated_at = None
account_limit_reached_at = None

# --- 账号读库 / 等待流程兼容字段 ---
account_db_path = ""
account_db_table_name = ""
account_record_loaded = False
account_allow_purchase = True
account_allow_start_time = None
account_read_status = ""
account_is_waiting = False
account_read_error = ""
overlay_status = ""

# --- 轮次写回兼容字段 ---
account_round_end_status = ""
account_round_finalized = False
account_round_writeback_failed = False
account_round_writeback_error = ""
