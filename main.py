"""
唯一入口：初始化、加载资源并启动自动化流程。
"""
import ctypes
import sys
import os
import time
import threading
import subprocess
from urllib import error as urllib_error
from urllib import request as urllib_request
from datetime import datetime, timedelta
import cv2


# ===== 0. 自动提权 =====
SCHEDULED_TASK_NAME = "codex-PYjiaoben-Launcher"
SCHEDULED_TASK_FLAG = "FROM_SCHEDULED_TASK"
SKIP_ELEVATE_FLAG = "CODEX_SKIP_ELEVATE"


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def _is_started_from_scheduled_task():
    return os.environ.get(SCHEDULED_TASK_FLAG) == "1"


def _relaunch_as_admin():
    script_path = os.path.abspath(__file__)
    script_args = [script_path, *sys.argv[1:]]
    params = subprocess.list2cmdline(script_args)
    workdir = os.path.dirname(script_path)
    ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        sys.executable,
        params,
        workdir,
        1,
    )


def ensure_admin_context():
    if is_admin():
        return

    if _is_started_from_scheduled_task():
        print("计划任务启动失败：当前不是管理员权限。")
        print(f"请重新执行 scripts/register_scheduled_task.ps1，确认计划任务 {SCHEDULED_TASK_NAME} 已设置为“使用最高权限运行”。")
        sys.exit(1)

    if os.environ.get(SKIP_ELEVATE_FLAG) == "1":
        return

    print("正在申请管理员权限...")
    _relaunch_as_admin()
    sys.exit()


ensure_admin_context()


try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    print("缺少 rapidocr_onnxruntime，请运行: pip install rapidocr-onnxruntime")
    os.system('pause')
    sys.exit()


import dxcam
import config
import state
from launcher_gui import show_launcher
from local_switch_account_config import (
    get_execution_slot_count,
    get_execution_slot_server_coord_indexes,
)
from config import (
    MONITOR_JIAOYIHANG, MONITOR_SHOP,
    FIX_SHOP_POS1, FIX_SHOP_POS2,
    ACCOUNT_LIMIT_COOLDOWN_SECONDS,
)
from account_db import (
    ACCOUNT_DB_MODE_ACCESSORY,
    ACCOUNT_DB_MODE_STONE,
    CANONICAL_ACCOUNT_STATS_TABLE,
    CANONICAL_RESET_MODE_AGGRESSIVE,
    ROUND_STATUS_MANUAL_PAUSE,
    ensure_canonical_account_stats_table,
    ensure_canonical_execution_slot_seed_records,
    ensure_account_stats_store_for_mode,
    ensure_local_canonical_account_stats_store,
    find_account_stats_store_for_mode,
    find_canonical_account_stats_store,
    inspect_canonical_account_stats_cleanup_scope,
    normalize_canonical_round_status_values,
    reset_canonical_account_stats_legacy_fields,
    read_preferred_canonical_account_stats_record_by_execution_slot,
    read_canonical_account_stats_record,
    read_canonical_account_stats_record_by_execution_slot,
    restore_ready_account_status_if_needed,
)
from round_persistence import (
    persist_item_balance_and_schedule_snapshot,
    persist_accessory_round_status_snapshot,
    persist_temporary_account_snapshot,
    persist_final_round_snapshot,
    refresh_account_limit_reached_at,
    reset_round_runtime_state,
    reset_temporary_account_snapshot_for_new_round,
    restore_runtime_window_state,
    resolve_shutdown_final_status,
)
from utils import safe_sleep, safe_get_frame, safe_imread, fast_click, gc_checkpoint
from utils import async_push_msg, logger
from vision import is_image_present, load_digit_templates
from overlay import hide_overlay_until_hidden, shutdown_overlay, start_overlay, ui_print, update_score_text
from listing import execute_listing_routine
from purchase import recognize_latest_balance_at_trade, run_brutal_purchase_loop, run_purchase_loop, reset_purchase_counters
from startup_listing_mode import run_startup_listing_mode, select_normal_mode_handoff_target
from switch import (
    detect_current_execution_slot_from_launcher,
    enter_accessory_trade_from_current_scene,
    enter_startup_listing_target_slot,
    pause_thread6_failure,
    refresh_latest_balance_route,
    resolve_execution_slot_transition,
    switch_account_for_temporary_target_slot,
    switch_server_within_account_after_slot_boundary,
    startup_temporary_from_qidong,
    startup_accessory_from_server_list,
    startup_from_server_list,
    switch_account_after_slot_boundary,
    wait_for_verified_slot_cooldown_before_launch,
)
# 保留原有的定时配置流程。
def setup_schedule():
    while True:
        print("\n" + "=" * 40)
        print(" 请选择启动模式：")
        print(" [1] 设置定时自动暂停")
        print(" [回车] 先自动上架，再开始抢购")
        print("=" * 40)
        choice = input("直接回车或输入选项: ").strip()

        if choice == '1':
            while True:
                time_str = input("请输入运行时间（例如 1.30 表示 1 小时 30 分）: ").strip()
                try:
                    if '.' in time_str:
                        h, m = time_str.split('.')
                        hours = int(h) if h else 0
                        minutes = int(m) if m else 0
                    else:
                        hours = int(time_str)
                        minutes = 0
                    state.target_stop_seconds = hours * 3600 + minutes * 60
                    if state.target_stop_seconds <= 0:
                        continue
                    print(f"设置成功：脚本将在 {hours} 小时 {minutes} 分后自动暂停。")
                    state.start_mode = 1
                    return
                except ValueError:
                    pass
        else:
            print("已确认：先执行一轮自动上架，再开始抢购。")
            state.start_mode = 2
            return


def run_automation():
    setup_schedule()
    start_overlay()

    if os.name == 'nt':
        try:
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(handle, 0x00000100)
            ctypes.windll.kernel32.SetProcessAffinityMask(handle, 0x0055)
        except:
            pass

    try:
        state.ocr_engine = RapidOCR()
        ui_print("本地文字识别引擎已加载")
    except Exception as e:
        ui_print(f"文字识别引擎加载失败: {e}")
        time.sleep(5)
        return

    templates = {str(i): safe_imread(("logo", "jiage", f"{i}.png"), 0) for i in range(10)}
    temp_success = safe_imread(("logo", "tezhengtu", "chenggong.png"), 0)
    temp_shop = safe_imread(("logo", "tezhengtu", "dianpu.png"), 0)
    state.temp_shop = temp_shop
    state.temp_jiaoyi = safe_imread(("logo", "tezhengtu", "jiaoyihang.png"), 0)
    temp_goumai = safe_imread(("logo", "tezhengtu", "goumai.png"), 0)
    temp_meihuo = safe_imread(("logo", "tezhengtu", "meihuo.png"), 0)
    temp_diyici = safe_imread(("logo", "tezhengtu", "diyici.png"), 0)
    state.TEMP_ITEM = safe_imread(("logo", "shangjia", "pojiaoshi.png"), cv2.IMREAD_COLOR)
    state.TEMP_TISHI = safe_imread(("logo", "shangjia", "tishi.png"), 0)
    state.TEMP_POPUP = safe_imread(("logo", "shangjia", "shangjiatan.png"), 0)

    missing = []
    if any(v is None for v in templates.values()):
        missing.append("logo/jiage/0.png - 9.png")
    if temp_success is None:
        missing.append("logo/tezhengtu/chenggong.png")
    if temp_shop is None:
        missing.append("logo/tezhengtu/dianpu.png")
    if state.temp_jiaoyi is None:
        missing.append("logo/tezhengtu/jiaoyihang.png")
    if temp_goumai is None:
        missing.append("logo/tezhengtu/goumai.png")
    if temp_meihuo is None:
        missing.append("logo/tezhengtu/meihuo.png")
    if temp_diyici is None:
        missing.append("logo/tezhengtu/diyici.png")
    if state.TEMP_ITEM is None:
        missing.append("logo/shangjia/pojiaoshi.png")
    if state.TEMP_TISHI is None:
        missing.append("logo/shangjia/tishi.png")

    if missing:
        ui_print(f"素材缺失: {', '.join(missing)}", save_log=True)
        time.sleep(10)
        return

    if state.TEMP_POPUP is not None:
        ui_print("上架弹窗检测：模板匹配模式")
    else:
        ui_print("上架弹窗检测：帧差异模式")

    if load_digit_templates():
        ui_print("容量识别：模板匹配模式")
    else:
        ui_print("容量识别：文字识别模式")

    try:
        camera = dxcam.create(output_color="BGRA")
        camera.start(target_fps=144)
    except Exception as e:
        ui_print(f"截图引擎启动失败: {e}")
        time.sleep(5)
        return

    if state.start_mode == 2:
        safe_sleep(1.0)
        ui_print("正在检查交易行场景...")
        while True:
            if state.IS_PAUSED:
                time.sleep(0.5)
                continue
            f_start = safe_get_frame(camera)
            if f_start is None:
                time.sleep(0.1)
                continue
            if (is_image_present(f_start, MONITOR_JIAOYIHANG, state.temp_jiaoyi, 0.7) and
                    is_image_present(f_start, MONITOR_SHOP, temp_shop, 0.7)):
                ui_print("已确认当前位于交易行。", save_log=True)
                break
            else:
                ui_print("当前不在交易行，尝试自动恢复...", save_log=True)
                fast_click(FIX_SHOP_POS1)
                safe_sleep(1.0)
                fast_click(FIX_SHOP_POS2)
                safe_sleep(1.5)

        ui_print("开始执行预上架流程...")
        execute_listing_routine(camera)
        reset_purchase_counters("上架完成")

    run_purchase_loop(camera, templates, temp_success, temp_shop,
                      temp_goumai, temp_meihuo, temp_diyici)


# Legacy: 命令行模式选择入口，已被 launcher_gui.show_launcher() 替代
def _prompt_main_mode():
    while True:
        print("\n" + "=" * 40)
        print(" 请选择启动方式：")
        print(" [回车] 从启动器开始（自动识别昵称 -> 自动解析大区 -> 进游戏 -> 交易行）")
        print(" [2] 启动页临时抢购模式")
        print("=" * 40)
        choice = input("直接回车或输入选项: ").strip()
        if choice == "":
            return "launcher"
        if choice == "2":
            return "temporary_launcher"
        print("请输入回车或 2。")


# Legacy: 命令行模式选择入口，已被 launcher_gui.show_launcher() 替代
def _prompt_temporary_target_execution_slot():
    return None


def _prompt_server_index():
    server_count = len(config.SERVER_COORDS)
    while True:
        raw = input(f"请输入目标大区编号(1-{server_count}): ").strip()
        try:
            server_number = int(raw)
        except ValueError:
            print(f"请输入 1 到 {server_count} 的数字编号。")
            continue
        if 1 <= server_number <= server_count:
            return server_number - 1
        print(f"请输入 1 到 {server_count} 之间的大区编号。")


def _resolve_server_index_from_execution_slot(execution_slot):
    """根据执行位解析启动器应选中的大区索引。"""
    try:
        slot_number = int(execution_slot)
    except (TypeError, ValueError):
        return None

    server_coord_indexes = get_execution_slot_server_coord_indexes()
    if slot_number < 1 or slot_number > len(server_coord_indexes):
        return None

    server_index = server_coord_indexes[slot_number - 1]
    if 0 <= server_index < len(config.SERVER_COORDS):
        return server_index
    return None


def _prepare_launcher_start_context_from_nickname():
    """正常模式启动前，只按昵称读 SQLite 并自动推出执行位与大区。"""
    if not _load_current_account_context():
        return False

    server_index = _resolve_server_index_from_execution_slot(state.current_execution_slot)
    if server_index is None:
        message = (
            f"[启动] 昵称 {state.current_nickname} 对应的执行位 "
            f"{state.current_execution_slot} 无法解析到有效大区。"
        )
        print(message)
        logger.error(message)
        state.overlay_status = "未知异常"
        return False

    state.current_server_index = server_index
    ui_print(
        f"自动解析：昵称 {state.current_nickname}，"
        f"执行位 {state.current_execution_slot}，大区 {server_index + 1}"
    )
    logger.info(
        "[启动] 已按昵称自动解析执行位与大区：昵称=%s 执行位=%s 大区=%s",
        state.current_nickname,
        state.current_execution_slot,
        server_index + 1,
    )
    return True


def _prepare_default_launcher_start(camera):
    """默认回车启动：先识别当前执行位，再按 SQLite 自动推出昵称与大区。"""
    detected_slot = detect_current_execution_slot_from_launcher(camera)
    if detected_slot is None:
        return False

    state.current_nickname = str(detected_slot)
    return _prepare_launcher_start_context_from_nickname()


def _format_account_time(value):
    if value is None:
        return "无"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _parse_slot_from_nickname_hint(nickname):
    raw = (nickname or "").strip()
    if not raw.isdigit():
        return None
    slot_number = int(raw)
    if 1 <= slot_number <= int(get_execution_slot_count()):
        return slot_number
    return None


def _freeze_purchase_timer():
    was_active = state.purchase_timer_active
    if was_active and not state.IS_PAUSED and state.last_resume_time is not None:
        refresh_account_limit_reached_at()
        state.total_running_time += (time.time() - state.last_resume_time)
    state.last_resume_time = None
    state.purchase_timer_active = False
    return was_active


def _resume_purchase_timer(should_resume):
    state.purchase_timer_active = should_resume
    if state.IS_PAUSED or not should_resume:
        state.last_resume_time = None
    else:
        state.last_resume_time = time.time()


def _format_timer_state():
    last_resume_text = "None"
    if state.last_resume_time is not None:
        last_resume_text = f"{state.last_resume_time:.3f}"
    return (
        f"total_running_time={state.total_running_time:.3f}, "
        f"purchase_timer_active={state.purchase_timer_active}, "
        f"last_resume_time={last_resume_text}"
    )


def _log_and_schedule_ready_restore_success(reason, nickname):
    print(f"[账号数据] {reason}，账号状态已自动恢复为“已准备”：{nickname}")
    logger.info("[账号数据] %s，账号状态已自动恢复为“已准备”：%s", reason, nickname)
    _schedule_remote_snapshot_event("冷却结束自动恢复已准备")


def _restore_current_account_ready_status(reason):
    if state.temporary_purchase_mode:
        return None
    if not state.account_record_loaded or not state.account_db_path:
        return None

    restored_record, restore_result = restore_ready_account_status_if_needed(
        state.account_db_path,
        state.current_nickname,
        table_name=state.account_db_table_name or CANONICAL_ACCOUNT_STATS_TABLE,
        now=datetime.now(),
    )
    if restore_result.status != "success" or restored_record is None:
        if restore_result.status not in ("skipped", "account_not_found"):
            print(f"[账号数据] {reason}自动恢复“已准备”失败：{restore_result.reason}")
            logger.warning("[账号数据] %s自动恢复“已准备”失败：%s", reason, restore_result.reason)
        return restore_result

    state.current_nickname = restored_record.nickname
    state.baseline_item_count = restored_record.baseline_item_count
    state.last_limit_time = restored_record.last_limit_time
    state.last_account_end_time = restored_record.last_account_end_time
    state.updated_at = restored_record.updated_at
    if restored_record.current_execution_slot is not None:
        state.current_execution_slot = restored_record.current_execution_slot
    state.success_count = restored_record.round_purchase_success_count
    state.total_listed_count = restored_record.round_listing_success_count
    state.fail_count = restored_record.round_purchase_fail_count
    state.round_purchase_success_count = restored_record.round_purchase_success_count
    state.round_listing_success_count = restored_record.round_listing_success_count
    state.round_purchase_fail_count = restored_record.round_purchase_fail_count
    state.round_current_balance = restored_record.current_balance
    state.total_running_time = float(restored_record.purchase_running_seconds)
    state.round_purchase_running_seconds = float(restored_record.purchase_running_seconds)
    state.runtime_window_start_time = restored_record.runtime_window_start_time
    state.round_status = restored_record.round_status
    state.account_allow_purchase = True
    state.account_allow_start_time = datetime.now()
    state.account_read_status = "ready"
    state.account_is_waiting = False
    state.account_read_error = ""
    state.overlay_status = "抢购中"
    _log_and_schedule_ready_restore_success(reason, restored_record.nickname)
    return restore_result


def _set_account_state_defaults():
    listing_enabled = bool(getattr(state, "listing_enabled", True))
    listing_disabled_for_session = bool(getattr(state, "listing_disabled_for_session", False))
    listing_global_skip_logged = bool(getattr(state, "listing_global_skip_logged", False))
    brutal_purchase_mode = bool(getattr(state, "brutal_purchase_mode", False))
    brutal_purchase_limit = int(getattr(state, "brutal_purchase_limit", 0) or 0)
    brutal_purchase_limit_enabled = bool(getattr(state, "brutal_purchase_limit_enabled", False))
    accessory_purchase_mode = bool(getattr(state, "accessory_purchase_mode", False))
    state.success_count = 0
    state.fail_count = 0
    state.total_listed_count = 0
    state.total_running_time = 0.0
    state.last_resume_time = None
    state.purchase_timer_active = False
    state.current_balance = "获取中..."
    state.last_valid_balance = ""
    state.baseline_item_count = 0
    state.last_limit_time = None
    state.last_account_end_time = None
    state.updated_at = None
    state.account_db_path = ""
    state.account_db_table_name = ""
    state.account_db_mode = ACCOUNT_DB_MODE_ACCESSORY if accessory_purchase_mode else ACCOUNT_DB_MODE_STONE
    state.account_record_loaded = False
    state.account_allow_purchase = False
    state.account_allow_start_time = None
    state.account_read_status = ""
    state.account_is_waiting = False
    state.account_read_error = ""
    state.round_purchase_success_count = 0
    state.round_listing_success_count = 0
    state.round_purchase_fail_count = 0
    state.round_current_balance = ""
    state.listing_scan_miss_count = 0
    state.listing_periodic_disabled = False
    state.listing_periodic_disabled_reason = ""
    state.listing_periodic_skip_logged = False
    state.round_purchase_running_seconds = 0.0
    state.runtime_window_start_time = None
    state.round_status = ROUND_STATUS_MANUAL_PAUSE
    state.overlay_status = ""
    state.account_round_end_status = ""
    state.account_round_finalized = False
    state.account_round_writeback_failed = False
    state.account_round_writeback_error = ""
    state.account_limit_reached_at = None
    state.temporary_purchase_mode = False
    state.temporary_target_execution_slot = None
    state.startup_listing_mode_active = False
    state.accessory_item_click_started_at = None
    state.accessory_skip_trade_ready_wait_once = False
    state.accessory_next_item_click_not_before = None
    state.listing_enabled = listing_enabled
    state.listing_disabled_for_session = listing_disabled_for_session
    state.listing_global_skip_logged = listing_global_skip_logged
    state.brutal_purchase_mode = brutal_purchase_mode
    state.brutal_purchase_limit = brutal_purchase_limit
    state.brutal_purchase_limit_enabled = brutal_purchase_limit_enabled
    state.accessory_purchase_mode = accessory_purchase_mode


def _is_listing_enabled_for_session():
    return bool(state.listing_enabled) and not bool(getattr(state, "listing_disabled_for_session", False))


def _log_listing_disabled_once():
    if state.listing_global_skip_logged:
        return
    ui_print("上架已关闭", save_log=True)
    state.listing_global_skip_logged = True


def _prepare_temporary_purchase_context():
    """线程10B：临时模式只初始化运行态，不读取账号库。"""
    _set_account_state_defaults()
    state.accessory_purchase_mode = False
    state.temporary_purchase_mode = True
    state.temporary_target_execution_slot = None
    state.need_switch_server = False
    state.current_nickname = "临时号"
    state.current_execution_slot = None
    state.baseline_item_count = 0
    state.account_allow_purchase = True
    state.account_is_waiting = False
    state.overlay_status = "临时抢购中"
    reset_round_runtime_state("进入临时抢购模式")
    reset_purchase_counters("进入临时抢购模式")
    reset_temporary_account_snapshot_for_new_round()
    persist_temporary_account_snapshot("临时模式启动", trigger_remote_snapshot=True)
    ui_print("临时抢购模式，库存基线从 0 开始", save_log=True)
    print("[临时模式] 已启动，库存基线=0")
    logger.info("[临时模式] 已启动，库存基线=%s", 0)


def _ensure_temporary_target_switch_store_context():
    """临时模式定向切换前，补齐 canonical 主库路径上下文。"""
    database_path = str(state.account_db_path or "").strip()
    table_name = state.account_db_table_name or CANONICAL_ACCOUNT_STATS_TABLE
    if database_path:
        return True

    database_path, table_name = find_canonical_account_stats_store()
    if not database_path:
        database_path, table_name, inserted_seed_records = ensure_local_canonical_account_stats_store()
        print(f"[账号数据] 临时模式定向切换前未找到现成账号库，已自动初始化本地主数据库：{database_path}")
        logger.info("[账号数据] 临时模式定向切换前未找到现成账号库，已自动初始化本地主数据库：%s", database_path)
        if inserted_seed_records:
            inserted_slots = ",".join(str(record.current_execution_slot) for record in inserted_seed_records)
            inserted_nicknames = ",".join(record.nickname for record in inserted_seed_records)
            print(f"[账号数据] 临时模式定向切换前已补齐执行位建档：执行位={inserted_slots}，昵称={inserted_nicknames}")
            logger.info(
                "[账号数据] 临时模式定向切换前已补齐执行位建档：执行位=%s 昵称=%s",
                inserted_slots,
                inserted_nicknames,
            )

    ensure_canonical_account_stats_table(database_path, table_name)
    ensure_canonical_execution_slot_seed_records(database_path, table_name)
    state.account_db_path = database_path
    state.account_db_table_name = table_name
    return True


def _format_canonical_status_counts(status_counts):
    if not status_counts:
        return "无"
    return "，".join(
        f"{status_name}:{status_counts[status_name]}"
        for status_name in sorted(status_counts)
    )


def _prepare_canonical_cleanup_once():
    """启动时先盘点 canonical 库，再按强重置版做一次统一清理。"""
    if getattr(state, "canonical_cleanup_completed", False):
        return

    database_path, table_name = find_canonical_account_stats_store()
    if not database_path:
        database_path, table_name, inserted_seed_records = ensure_local_canonical_account_stats_store()
        print(f"[账号数据] 未找到现成 canonical 主库，已初始化本地主数据库：{database_path}")
        logger.info("[账号数据] 未找到现成 canonical 主库，已初始化本地主数据库：%s", database_path)
        if inserted_seed_records:
            inserted_slots = ",".join(str(record.current_execution_slot) for record in inserted_seed_records)
            print(f"[账号数据] 初始化时已补齐执行位建档：执行位={inserted_slots}")
            logger.info("[账号数据] 初始化时已补齐执行位建档：执行位=%s", inserted_slots)

    ensure_canonical_account_stats_table(database_path, table_name)
    before_summary = inspect_canonical_account_stats_cleanup_scope(database_path, table_name)
    print(
        "[账号数据] canonical 旧规则盘点："
        f"总记录={before_summary['total_records']}，"
        f"旧状态残留={before_summary['legacy_status_count']}，"
        f"非法状态={before_summary['invalid_status_count']}，"
        f"旧轮次残留={before_summary['round_field_residue_count']}，"
        f"旧运行态残留={before_summary['runtime_field_residue_count']}，"
        f"冷却字段存在={before_summary['cooldown_present_count']}。"
    )
    logger.info(
        "[账号数据] canonical 旧规则盘点：总记录=%s 旧状态残留=%s 非法状态=%s 旧轮次残留=%s 旧运行态残留=%s 冷却字段存在=%s",
        before_summary["total_records"],
        before_summary["legacy_status_count"],
        before_summary["invalid_status_count"],
        before_summary["round_field_residue_count"],
        before_summary["runtime_field_residue_count"],
        before_summary["cooldown_present_count"],
    )
    print(
        "[账号数据] 强重置版保留原值字段："
        f"{'、'.join(before_summary['preserved_foundation_fields'])}；"
        "更新时间字段：updated_at 会清空为 NULL；"
        f"重置字段：{'、'.join(before_summary['resettable_runtime_fields'])}。"
    )

    cleanup_result = reset_canonical_account_stats_legacy_fields(
        database_path,
        table_name,
        mode=CANONICAL_RESET_MODE_AGGRESSIVE,
    )
    if cleanup_result.get("status") == "error":
        raise RuntimeError(f"canonical 强重置版清理失败：{cleanup_result.get('reason')}")
    normalized_count = normalize_canonical_round_status_values(database_path, table_name)
    after_summary = inspect_canonical_account_stats_cleanup_scope(database_path, table_name)
    print(
        "[账号数据] 强重置版清理完成："
        f"更新行数={cleanup_result.get('updated_rows', 0)}，"
        f"补充状态迁移={normalized_count}，"
        f"当前状态分布={_format_canonical_status_counts(after_summary['status_counts'])}。"
    )
    logger.info(
        "[账号数据] 强重置版清理完成：更新行数=%s 补充状态迁移=%s 当前状态分布=%s",
        cleanup_result.get("updated_rows", 0),
        normalized_count,
        _format_canonical_status_counts(after_summary["status_counts"]),
    )
    state.canonical_cleanup_completed = True


def _clear_runtime_state_after_account_finalize(reason):
    """当前账号最终写库后，立刻清空悬浮窗与本号运行态。"""
    previous_nickname = (state.current_nickname or "").strip() or "未设置"
    previous_slot = state.current_execution_slot
    _set_account_state_defaults()
    state.current_nickname = ""

    message = (
        f"[账号数据] {reason}：当前账号最终写库完成，"
        f"已清空悬浮窗与运行态数据。原昵称={previous_nickname}，执行位={previous_slot}"
    )
    print(message)
    logger.info(message)

    if state.overlay_root:
        try:
            state.overlay_root.after(0, update_score_text)
        except Exception:
            pass


def _load_current_account_context():
    nickname = (state.current_nickname or "").strip()
    _set_account_state_defaults()
    state.current_nickname = nickname

    if not nickname:
        state.account_read_status = "nickname_missing"
        state.account_read_error = "当前账号昵称为空，无法读取主 SQLite 数据库。"
        state.overlay_status = "未知异常"
        print(f"[账号数据] 读取失败：{state.account_read_error}")
        logger.error(f"[账号数据] 读取失败：{state.account_read_error}")
        return False

    account_db_mode = ACCOUNT_DB_MODE_ACCESSORY if state.accessory_purchase_mode else ACCOUNT_DB_MODE_STONE
    state.account_db_mode = account_db_mode
    database_path, table_name = find_account_stats_store_for_mode(account_db_mode)
    if not database_path:
        database_path, table_name, inserted_seed_records = ensure_account_stats_store_for_mode(account_db_mode)
        mode_label = "饰品库" if account_db_mode == ACCOUNT_DB_MODE_ACCESSORY else "本地主数据库"
        print(f"[账号数据] 未找到现成账号库，已自动初始化{mode_label}：{database_path}")
        logger.info("[账号数据] 未找到现成账号库，已自动初始化%s：%s", mode_label, database_path)
        if inserted_seed_records:
            inserted_slots = ",".join(str(record.current_execution_slot) for record in inserted_seed_records)
            inserted_nicknames = ",".join(record.nickname for record in inserted_seed_records)
            print(f"[账号数据] 初始化时已补齐执行位建档：执行位={inserted_slots}，昵称={inserted_nicknames}")
            logger.info(
                "[账号数据] 初始化时已补齐执行位建档：执行位=%s 昵称=%s",
                inserted_slots,
                inserted_nicknames,
            )

    ensure_canonical_account_stats_table(database_path, table_name)
    inserted_seed_records = ensure_canonical_execution_slot_seed_records(database_path, table_name)
    if inserted_seed_records:
        inserted_slots = ",".join(str(record.current_execution_slot) for record in inserted_seed_records)
        inserted_nicknames = ",".join(record.nickname for record in inserted_seed_records)
        print(f"[账号数据] 已自动补齐缺失建档：执行位={inserted_slots}，昵称={inserted_nicknames}")
        logger.info(
            "[账号数据] 已自动补齐缺失建档：执行位=%s 昵称=%s",
            inserted_slots,
            inserted_nicknames,
        )

    normalized_count = normalize_canonical_round_status_values(database_path, table_name)
    if normalized_count > 0:
        print(f"[账号数据] 已归一旧状态样本数据：{normalized_count} 条")
        logger.info("[账号数据] 已归一旧状态样本数据：%s 条", normalized_count)

    slot_hint = _parse_slot_from_nickname_hint(nickname)
    record = None
    if slot_hint is not None:
        record = read_preferred_canonical_account_stats_record_by_execution_slot(
            database_path,
            slot_hint,
            table_name,
        )
        if record is not None:
            print(
                f"[账号数据] 数字昵称 {nickname} 已按执行位 {slot_hint} "
                f"优先读取为昵称 {record.nickname}。"
            )
            logger.info(
                "[账号数据] 数字昵称 %s 已按执行位 %s 优先读取为昵称 %s。",
                nickname,
                slot_hint,
                record.nickname,
            )

    if record is None:
        record = read_canonical_account_stats_record(database_path, nickname, table_name)
    if record is None and slot_hint is not None:
        record = read_canonical_account_stats_record_by_execution_slot(
            database_path,
            slot_hint,
            table_name,
        )
        if record is not None:
            print(
                f"[账号数据] 昵称 {nickname} 未直接命中，已按执行位 {slot_hint} "
                f"兼容读取为昵称 {record.nickname}。"
            )
            logger.info(
                "[账号数据] 昵称 %s 未直接命中，已按执行位 %s 兼容读取为昵称 %s。",
                nickname,
                slot_hint,
                record.nickname,
            )
    if record is None:
        state.account_read_status = "account_not_found"
        state.account_read_error = f"主 SQLite 数据库中未找到昵称为 {nickname} 的账号记录。"
        state.account_db_path = database_path
        state.account_db_table_name = table_name
        state.overlay_status = "账号未建档"
        print(f"[账号数据] 读取失败：{state.account_read_error}")
        logger.error(f"[账号数据] 读取失败：{state.account_read_error}")
        return False

    restored_record, restore_result = restore_ready_account_status_if_needed(
        database_path,
        record.nickname,
        table_name,
        now=datetime.now(),
    )
    if restore_result.status == "success" and restored_record is not None:
        record = restored_record
        _log_and_schedule_ready_restore_success("读取账号后检测到冷却已结束", record.nickname)
    elif restore_result.status not in ("skipped", "account_not_found"):
        print(f"[账号数据] 读取账号后自动恢复“已准备”失败：{restore_result.reason}")
        logger.warning("[账号数据] 读取账号后自动恢复“已准备”失败：%s", restore_result.reason)

    state.current_nickname = record.nickname
    state.baseline_item_count = record.baseline_item_count
    state.last_limit_time = record.last_limit_time
    state.last_account_end_time = record.last_account_end_time
    state.updated_at = record.updated_at
    if record.current_execution_slot is not None:
        state.current_execution_slot = record.current_execution_slot
    state.success_count = record.round_purchase_success_count
    state.total_listed_count = record.round_listing_success_count
    state.fail_count = record.round_purchase_fail_count
    state.round_purchase_success_count = record.round_purchase_success_count
    state.round_listing_success_count = record.round_listing_success_count
    state.round_purchase_fail_count = record.round_purchase_fail_count
    state.round_current_balance = record.current_balance
    state.total_running_time = float(record.purchase_running_seconds)
    state.round_purchase_running_seconds = float(record.purchase_running_seconds)
    state.runtime_window_start_time = record.runtime_window_start_time
    state.round_status = record.round_status
    state.account_db_path = database_path
    state.account_db_table_name = table_name
    state.account_db_mode = account_db_mode
    state.account_record_loaded = True
    runtime_window_sync_result = restore_runtime_window_state()
    now = datetime.now()
    allow_start_time = now
    allow_purchase = True
    if state.last_limit_time is not None:
        allow_start_time = state.last_limit_time + timedelta(seconds=ACCOUNT_LIMIT_COOLDOWN_SECONDS)
        allow_purchase = now >= allow_start_time
    state.account_allow_purchase = allow_purchase
    state.account_allow_start_time = allow_start_time
    state.account_read_status = "ready" if allow_purchase else "waiting_limit_time"
    state.account_is_waiting = not allow_purchase
    state.account_read_error = ""
    state.overlay_status = "抢购中" if allow_purchase else "等待抢购时间"
    if runtime_window_sync_result["changed"]:
        for action_text in runtime_window_sync_result["actions"]:
            print(f"[运行窗口] {action_text}")
            logger.info("[运行窗口] %s", action_text)

    print(
        "[账号数据] 昵称={0}，当前道具库存={1}，最后一次限制时间={2}，最后下号时间={3}，更新时间={4}，执行位={5}，允许开始时间={6}，当前可抢购={7}，累计抢购秒数={8}，运行窗口起点={9}".format(
            state.current_nickname,
            state.baseline_item_count,
            _format_account_time(state.last_limit_time),
            _format_account_time(state.last_account_end_time),
            _format_account_time(state.updated_at),
            state.current_execution_slot,
            _format_account_time(state.account_allow_start_time),
            "是" if state.account_allow_purchase else "否",
            int(state.total_running_time),
            _format_account_time(state.runtime_window_start_time),
        )
    )
    logger.info(
        "[账号数据] 昵称=%s 当前道具库存=%s 最后一次限制时间=%s 最后下号时间=%s 更新时间=%s 执行位=%s 允许开始时间=%s 当前可抢购=%s 累计抢购秒数=%s 运行窗口起点=%s 来源=%s:%s",
        state.current_nickname,
        state.baseline_item_count,
        _format_account_time(state.last_limit_time),
        _format_account_time(state.last_account_end_time),
        _format_account_time(state.updated_at),
        state.current_execution_slot,
        _format_account_time(state.account_allow_start_time),
        state.account_allow_purchase,
        int(state.total_running_time),
        _format_account_time(state.runtime_window_start_time),
        database_path,
        table_name,
    )
    return True


def _wait_until_account_ready():
    if state.account_allow_purchase:
        return True

    resume_timer_after_wait = _freeze_purchase_timer()
    state.account_read_status = "waiting_limit_time"
    state.account_is_waiting = True
    state.overlay_status = "等待抢购时间"

    print(f"[账号数据] 进入等待状态，冻结后计时器状态：{_format_timer_state()}")
    logger.info("[账号数据] 进入等待状态，冻结后计时器状态：%s", _format_timer_state())
    print(f"[账号数据] 当前账号冷却中，交易行等待至 {_format_account_time(state.account_allow_start_time)} 后再进入抢购。")
    logger.info("[账号数据] 当前账号冷却中，等待至 %s 后再进入抢购。", _format_account_time(state.account_allow_start_time))

    while True:
        if state.account_allow_start_time is None:
            break

        now = datetime.now()
        if now >= state.account_allow_start_time:
            break

        remaining = (state.account_allow_start_time - now).total_seconds()
        time.sleep(0.5 if state.IS_PAUSED else min(1.0, max(0.1, remaining)))

    state.account_allow_purchase = True
    state.account_read_status = "ready"
    state.account_is_waiting = False
    state.overlay_status = "抢购中"
    _restore_current_account_ready_status("冷却等待结束")
    _resume_purchase_timer(resume_timer_after_wait)

    print(f"[账号数据] 解除等待，恢复后计时器状态：{_format_timer_state()}")
    logger.info("[账号数据] 解除等待，恢复后计时器状态：%s", _format_timer_state())
    print("[账号数据] 冷却等待结束，允许进入抢购循环。")
    logger.info("[账号数据] 冷却等待结束，允许进入抢购循环。")
    return True


def _run_pre_listing_flow(
    camera,
    reset_runtime_before_listing=False,
    reset_reason="预上架前清空当前账号运行态",
    purchase_reset_reason="开始当前账号流程",
    force_balance_check_after_switch=False,
):
    if not _load_current_account_context():
        return False
    if reset_runtime_before_listing:
        reset_round_runtime_state(reset_reason, reset_purchase_runtime=False, reset_round_counters=False)
        reset_purchase_counters(purchase_reset_reason)
    if not _is_listing_enabled_for_session():
        _log_listing_disabled_once()
        return _wait_until_account_ready()
    ui_print("开始执行预上架流程...")
    execute_listing_routine(
        camera,
        force_balance_check_after_switch=force_balance_check_after_switch,
    )
    return _wait_until_account_ready()


def _run_accessory_account_flow(
    camera,
    reset_runtime_before_purchase=False,
    reset_reason="饰品抢购前清空当前账号运行态",
    purchase_reset_reason="开始饰品抢购账号流程",
    enter_trade=False,
):
    state.accessory_purchase_mode = True
    state.listing_enabled = False
    state.listing_disabled_for_session = True
    if not _load_current_account_context():
        return False
    if reset_runtime_before_purchase:
        reset_round_runtime_state(reset_reason, reset_purchase_runtime=False, reset_round_counters=False)
        reset_purchase_counters(purchase_reset_reason)
        state.accessory_item_index = 0
        state.accessory_item_click_started_at = None
        state.accessory_skip_trade_ready_wait_once = False
        state.accessory_next_item_click_not_before = None
    if not _wait_until_account_ready():
        return False
    state.overlay_status = "饰品抢购中"
    if enter_trade and not enter_accessory_trade_from_current_scene(camera):
        return False
    return True


def _run_direct_account_flow(camera):
    if not _load_current_account_context():
        return False
    if not state.account_allow_purchase:
        if _is_listing_enabled_for_session():
            ui_print("账号未到抢购时间，执行预上架流程...")
        else:
            ui_print("账号未到抢购时间，等待冷却...")
        return _run_pre_listing_flow(
            camera,
            reset_runtime_before_listing=True,
            reset_reason="冷却等待前预上架清空当前账号运行态",
            purchase_reset_reason="冷却等待前开始当前账号流程",
        )
    reset_round_runtime_state("已加载当前账号", reset_purchase_runtime=False, reset_round_counters=False)
    return _wait_until_account_ready()


def _prepare_launcher_start(camera):
    return startup_from_launcher(camera, state.current_server_index)


def _pause_after_launcher_start_failure():
    """启动器链路失败时，保留现场并等待人工确认。"""
    message = "启动器进入游戏流程失败，脚本暂停"
    ui_print(message, save_log=True)
    print(f"[启动器] {message}")
    logger.error("[启动器] %s", message)
    os.system('pause')


def _handle_startup_listing_normal_handoff(camera, target_slot):
    if target_slot is None:
        pause_thread6_failure("解析正常模式目标执行位", "启动页上架模式结束时未解析到目标执行位。")
        return False

    ui_print(f"上架模式结束，切回正常模式 {target_slot}", save_log=True)
    logger.info("[上架模式] 扫描完成，准备切回正常模式执行位 %s。", target_slot)

    enter_result = enter_startup_listing_target_slot(
        camera,
        target_slot,
        force_login=True,
        already_at_launcher=True,
    )
    if enter_result["status"] != "success":
        pause_thread6_failure("启动页上架切回正常模式", f"目标执行位 {target_slot} 进场失败：{enter_result['detail']}")
        return False

    if not _run_pre_listing_flow(
        camera,
        reset_runtime_before_listing=True,
        reset_reason="启动页上架结束后切回正常模式，预上架前清空当前账号运行态",
        purchase_reset_reason="启动页上架结束后开始正常模式账号流程",
        force_balance_check_after_switch=True,
    ):
        if not state.switch_flow_paused:
            pause_thread6_failure("启动页上架切回正常模式预上架衔接", "启动页上架模式切回正常模式后未能完成预上架与账号状态衔接。")
        return False
    return True


def _finalize_current_account_round(default_status):
    if state.temporary_purchase_mode:
        return True
    if not state.account_record_loaded and state.account_read_status == "":
        return True
    _freeze_purchase_timer()
    if state.accessory_purchase_mode:
        result = persist_accessory_round_status_snapshot(default_status)
        if result.status == "success":
            return True

        print(f"[账号数据] 饰品最小写回失败：{result.reason}")
        logger.error("[账号数据] 饰品最小写回失败：%s", result.reason)
        return False

    final_status = resolve_shutdown_final_status(default_status)
    result = persist_final_round_snapshot(final_status)
    if result.status == "success":
        return True

    print(f"[账号数据] 最终写回失败：{result.reason}")
    logger.error("[账号数据] 最终写回失败：%s", result.reason)
    return False


def _should_dispatch_temporary_target_switch():
    if not state.temporary_purchase_mode:
        return False
    return state.account_round_end_status in ("余额不足", "抢购时长已到", "账号限制")


def _handle_temporary_target_execution_slot_dispatch(camera):
    handoff_target = select_normal_mode_handoff_target()
    target_slot = handoff_target.get("target_slot")
    if target_slot is None:
        pause_thread6_failure("解析临时模式目标执行位", "临时模式结束时未能自动选择目标执行位。")
        return "abort"

    if not _ensure_temporary_target_switch_store_context():
        pause_thread6_failure("准备临时模式账号库上下文", "临时模式定向切换前未能准备 canonical 主库路径。")
        return "abort"

    ui_print(
        f"临时模式结束，命中 {state.account_round_end_status}，自动切到执行位 {target_slot}。",
        save_log=True,
    )
    print(
        f"[临时模式] 命中结束条件：{state.account_round_end_status}，"
        f"自动选择目标执行位={target_slot}，"
        f"选择模式={handoff_target.get('selection_mode')}，选择值={handoff_target.get('selection_value')}。"
    )
    logger.info(
        "[临时模式] 命中结束条件：%s，自动选择目标执行位 %s，选择模式=%s，选择值=%s。",
        state.account_round_end_status,
        target_slot,
        handoff_target.get("selection_mode"),
        handoff_target.get("selection_value"),
    )
    persist_temporary_account_snapshot("临时模式结束", trigger_remote_snapshot=True)

    if not switch_account_for_temporary_target_slot(camera, target_slot) and not state.switch_flow_paused:
        pause_thread6_failure("临时模式定向切换链路", "链路返回失败，但未命中步骤级或链路级失败出口。")
        return "abort"
    if state.switch_flow_paused:
        return "abort"

    state.temporary_purchase_mode = False
    state.temporary_target_execution_slot = None
    if not _run_pre_listing_flow(
        camera,
        reset_runtime_before_listing=True,
        reset_reason="临时模式定向切换后预上架前清空当前账号运行态",
        purchase_reset_reason="临时模式定向切换后开始目标账号流程",
        force_balance_check_after_switch=True,
    ):
        if not state.switch_flow_paused:
            pause_thread6_failure("临时模式切换后预上架衔接", "临时模式定向切换完成后未能完成预上架与账号状态衔接。")
        return "abort"
    return "continue"


def _handle_execution_slot_dispatch(camera):
    try:
        transition = resolve_execution_slot_transition(state.current_execution_slot)
        if transition is None:
            pause_thread6_failure("解析下一目标执行位", f"当前执行位 {state.current_execution_slot} 无效，无法解析下一目标执行位。")
            state.need_switch_server = False
            return "abort"

        ui_print(
            f"线程6调度：执行位 {transition['current_slot']} 本轮结束，下一执行位 {transition['next_slot']}。",
            save_log=True,
        )
        print(
            f"[线程6调度] 执行位 {transition['current_slot']} 本轮结束，"
            f"下一目标执行位 {transition['next_slot']}。"
        )
        logger.info(
            "[线程6调度] 执行位 %s 本轮结束，下一目标执行位 %s。",
            transition["current_slot"],
            transition["next_slot"],
        )

        if transition["requires_account_switch"]:
            ui_print(
                f"线程6调度：命中 {transition['current_slot']}->{transition['next_slot']} 衔接边界，沿用原链路。",
                save_log=True,
            )
            logger.info(
                "[线程6调度] 命中 %s->%s 自动衔接边界，继续沿用原链路。",
                transition["current_slot"],
                transition["next_slot"],
            )
            if not switch_account_after_slot_boundary(camera) and not state.switch_flow_paused:
                pause_thread6_failure("跨账号边界切换链路", "链路返回失败，但未命中步骤级或链路级失败出口。")
                return "abort"
            if state.switch_flow_paused:
                return "abort"
        else:
            ui_print(
                f"线程6调度：命中 {transition['current_slot']}->{transition['next_slot']} 同账号跨区切换，自动切换。",
                save_log=True,
            )
            logger.info(
                "[线程6调度] 命中 %s->%s 同账号跨区切换，进入真实页面自动切换。",
                transition["current_slot"],
                transition["next_slot"],
            )
            if not switch_server_within_account_after_slot_boundary(camera, transition) and not state.switch_flow_paused:
                pause_thread6_failure("同账号跨区切换链路", "链路返回失败，但未命中步骤级或链路级失败出口。")
                return "abort"
            if state.switch_flow_paused:
                return "abort"

        _schedule_remote_snapshot_event("账号切换完成并回到稳定页面后")

        if state.accessory_purchase_mode:
            if not _run_accessory_account_flow(
                camera,
                reset_runtime_before_purchase=True,
                reset_reason="换号后饰品抢购前清空当前账号运行态",
                purchase_reset_reason="换号后开始饰品抢购账号流程",
                enter_trade=True,
            ):
                if not state.switch_flow_paused:
                    pause_thread6_failure("切换后饰品衔接", "线程 6 切换完成后未能进入饰品交易行。")
                return "abort"
            return "continue"

        if not _run_pre_listing_flow(
            camera,
            reset_runtime_before_listing=True,
            reset_reason="换号后预上架前清空当前账号运行态",
            purchase_reset_reason="换号后开始新账号流程",
            force_balance_check_after_switch=transition["requires_account_switch"],
        ):
            if not state.switch_flow_paused:
                pause_thread6_failure("切换后预上架衔接", "线程 6 切换完成后未能完成预上架与账号状态衔接。")
            return "abort"
        return "continue"
    except Exception as exc:
        pause_thread6_failure("线程6调度入口", f"线程 6 调度入口出现未处理异常：{exc}")
        return "abort"


def _is_web_view_service_response_valid(body_text):
    markers = (
        "账号数据查看页",
        "账号详情页",
        "<title>首页</title>",
        "石头库",
        "饰品库",
        "页面不存在。",
        "页面渲染失败",
        "提交处理失败",
    )
    return any(marker in body_text for marker in markers)


def _get_web_view_candidate_ports():
    ports = []

    def add_port(value):
        try:
            port = int(value)
        except (TypeError, ValueError):
            return
        if 1 <= port <= 65535 and port not in ports:
            ports.append(port)

    add_port(config.WEB_VIEW_PORT)
    try:
        with open(config.WEB_VIEW_SERVER_PORT_FILE, "r", encoding="utf-8") as file:
            add_port(file.read().strip())
    except Exception:
        pass
    for fallback_port in range(config.WEB_VIEW_PORT_FALLBACK_START, config.WEB_VIEW_PORT_FALLBACK_END + 1):
        add_port(fallback_port)
    return ports


def _build_web_view_service_url(port):
    return f"http://{config.WEB_VIEW_HOST}:{int(port)}"


def _probe_web_view_service(timeout=0.5, port=None):
    probe_port = int(port or config.WEB_VIEW_PORT)
    request = urllib_request.Request(
        f"{_build_web_view_service_url(probe_port)}/",
        headers={"User-Agent": "codex-main-web-check"},
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            body_text = response.read().decode("utf-8", errors="ignore")
    except urllib_error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="ignore")
        if _is_web_view_service_response_valid(body_text):
            return True, f"网页服务已可访问，端口={probe_port}，HTTP {exc.code}"
        return False, f"{probe_port} 已有其他 HTTP 服务响应，HTTP {exc.code}"
    except Exception as exc:
        return False, f"{probe_port} 网页服务不可访问：{exc}"

    if _is_web_view_service_response_valid(body_text):
        return True, f"网页服务已可访问，端口={probe_port}"
    return False, f"{probe_port} 已有其他 HTTP 服务响应"


def _probe_web_view_service_candidates(timeout=0.5):
    first_reason = None
    for port in _get_web_view_candidate_ports():
        is_running, reason = _probe_web_view_service(timeout=timeout, port=port)
        if is_running:
            return True, reason
        if first_reason is None:
            first_reason = reason
    return False, first_reason or "网页服务不可访问"


def _read_text_tail(path, max_chars=1000):
    try:
        if not path or not os.path.isfile(path):
            return ""
        with open(path, "r", encoding="utf-8", errors="ignore") as file:
            text = file.read()
    except Exception:
        return ""
    return text.strip()[-max_chars:]


def _start_web_view_server_in_background():
    script_path = config.WEB_VIEW_SERVER_SCRIPT_PATH
    if not os.path.isfile(script_path):
        message = f"[网页服务] 启动失败：未找到脚本 {script_path}"
        print(message)
        logger.error(message)
        return False

    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)

    log_dir = os.path.join(config.SCRIPT_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stdout_log_path = os.path.join(log_dir, f"web_view_server_{log_stamp}.out.log")
    stderr_log_path = os.path.join(log_dir, f"web_view_server_{log_stamp}.err.log")

    try:
        with open(stdout_log_path, "w", encoding="utf-8") as stdout_log, open(
            stderr_log_path,
            "w",
            encoding="utf-8",
        ) as stderr_log:
            process = subprocess.Popen(
                [sys.executable, script_path],
                cwd=config.SCRIPT_DIR,
                stdin=subprocess.DEVNULL,
                stdout=stdout_log,
                stderr=stderr_log,
                startupinfo=startupinfo,
                creationflags=creationflags,
                close_fds=True,
            )
    except Exception as exc:
        message = f"[网页服务] 后台静默启动失败：{exc}"
        print(message)
        logger.error(message)
        return False

    logger.info("[网页服务] 已发起后台静默启动，进程号=%s", process.pid)
    print(f"[网页服务] 已发起后台静默启动，进程号={process.pid}")

    for _ in range(6):
        time.sleep(0.3)
        if process.poll() is not None:
            error_detail = _read_text_tail(stderr_log_path)
            if error_detail:
                message = f"[网页服务] 子进程已退出，返回码={process.returncode}，错误={error_detail}"
            else:
                message = f"[网页服务] 子进程已退出，返回码={process.returncode}"
            print(message)
            logger.error(message)
            return False
        is_running, reason = _probe_web_view_service_candidates(timeout=0.3)
        if is_running:
            logger.info("[网页服务] 后台静默启动完成：%s", reason)
            print(f"[网页服务] 后台静默启动完成：{reason}")
            return True

    message = "[网页服务] 已尝试后台静默启动，但暂未确认可访问，主程序继续运行。"
    print(message)
    logger.warning(message)
    return False


def ensure_web_view_server_ready():
    is_running, reason = _probe_web_view_service_candidates(timeout=0.4)
    if is_running:
        logger.info("[网页服务] 跳过启动：%s", reason)
        print(f"[网页服务] 跳过启动：{reason}")
        return True

    if "其他 HTTP 服务" in reason:
        logger.warning("[网页服务] 默认端口疑似被占用，准备尝试备用端口：%s", reason)
        print(f"[网页服务] 默认端口疑似被占用，准备尝试备用端口：{reason}")
    else:
        logger.info("[网页服务] 检查未通过，准备后台静默启动：%s", reason)
        print(f"[网页服务] 检查未通过，准备后台静默启动：{reason}")

    return _start_web_view_server_in_background()


def _start_remote_snapshot_report_worker():
    try:
        from machine_sync_config import get_machine_sync_runtime_context
        from remote_sync import run_remote_snapshot_report_loop
    except Exception as exc:
        message = f"[网页同步] 同步模块加载失败，已禁用线程 12 同步功能：{exc}"
        print(message)
        logger.error(message)
        return None

    try:
        runtime_context = get_machine_sync_runtime_context()
    except Exception as exc:
        message = f"[网页同步] 读取同步配置失败，已禁用线程 12 同步功能：{exc}"
        print(message)
        logger.error(message)
        return None

    if runtime_context.get("config_status") != "ready":
        message = f"[网页同步] 未启动后台上报线程：{runtime_context.get('config_error')}"
        print(message)
        logger.warning(message)
        return None

    if not runtime_context.get("sync_enabled"):
        message = "[网页同步] 当前机器未开启 sync_enabled，跳过后台最小账号快照上报线程。"
        print(message)
        logger.info(message)
        return None

    try:
        thread = threading.Thread(
            target=run_remote_snapshot_report_loop,
            name="remote-sync-reporter",
            daemon=True,
        )
        thread.start()
    except Exception as exc:
        message = f"[网页同步] 启动后台上报线程失败，已禁用线程 12 同步功能：{exc}"
        print(message)
        logger.error(message)
        return None

    message = "[网页同步] 后台最小账号快照上报线程已启动。"
    print(message)
    logger.info(message)
    return thread


def _schedule_remote_snapshot_event(event_name):
    try:
        from remote_sync import schedule_local_snapshot_report
    except Exception as exc:
        logger.warning("[网页同步] 事件快照模块加载失败：event=%s error=%s", event_name, exc)
        return

    try:
        result = schedule_local_snapshot_report(event_name)
    except Exception as exc:
        logger.warning("[网页同步] 事件快照触发失败：event=%s error=%s", event_name, exc)
        return

    status = str(result.get("status") or "").strip()
    if status == "scheduled":
        logger.info("[网页同步] 已安排事件触发最小快照：%s", event_name)
    elif status == "error":
        logger.warning("[网页同步] 事件触发最小快照失败：event=%s reason=%s", event_name, result.get("message"))


def _refresh_latest_balance_before_switch(camera):
    """换号前尽量刷新一次最新余额，并尽快同步到网页。"""
    refresh_result = refresh_latest_balance_route(camera)
    if refresh_result["status"] == "no_gold":
        logger.info("[换号前] 未识别到金币入口，按无金币可领继续换号。")
        return

    if refresh_result["status"] != "success":
        logger.warning("[换号前] 最新余额刷新失败：%s", refresh_result["detail"])
        return

    balance_info = recognize_latest_balance_at_trade(camera)
    if balance_info is None:
        logger.warning("[换号前] 已回到交易行，但未识别到最新余额。")
        return

    persist_result = persist_item_balance_and_schedule_snapshot("换号前刷新最新余额")
    if persist_result.status not in ("success", "skipped"):
        logger.warning("[换号前] 最新余额已识别，但同步网页失败：%s", persist_result.reason)


def main():
    ensure_web_view_server_ready()
    mode, listing_enabled = show_launcher()
    state.listing_enabled = bool(listing_enabled)
    state.listing_disabled_for_session = not bool(listing_enabled)
    state.listing_global_skip_logged = False
    state.brutal_purchase_mode = mode == "brutal_launcher"
    state.accessory_purchase_mode = mode == "accessory_launcher"
    if not state.brutal_purchase_mode:
        state.brutal_purchase_limit = 0
        state.brutal_purchase_limit_enabled = False
    start_overlay()
    try:
        if not hide_overlay_until_hidden():
            ui_print("悬浮窗隐藏失败", save_log=True)
            return

        if os.name == 'nt':
            try:
                handle = ctypes.windll.kernel32.GetCurrentProcess()
                ctypes.windll.kernel32.SetPriorityClass(handle, 0x00000100)
                ctypes.windll.kernel32.SetProcessAffinityMask(handle, 0x0055)
            except:
                pass

        try:
            state.ocr_engine = RapidOCR()
            ui_print("文字识别引擎已加载")
        except Exception as e:
            ui_print(f"文字识别引擎加载失败: {e}")
            time.sleep(5)
            return

        templates = {str(i): safe_imread(("logo", "jiage", f"{i}.png"), 0) for i in range(10)}
        temp_success = safe_imread(("logo", "tezhengtu", "chenggong.png"), 0)
        temp_shop = safe_imread(("logo", "tezhengtu", "dianpu.png"), 0)
        state.temp_shop = temp_shop
        state.temp_jiaoyi = safe_imread(("logo", "tezhengtu", "jiaoyihang.png"), 0)
        temp_goumai = safe_imread(("logo", "tezhengtu", "goumai.png"), 0)
        temp_meihuo = safe_imread(("logo", "tezhengtu", "meihuo.png"), 0)
        temp_diyici = safe_imread(("logo", "tezhengtu", "diyici.png"), 0)
        state.TEMP_ITEM = safe_imread(("logo", "shangjia", "pojiaoshi.png"), cv2.IMREAD_COLOR)
        state.TEMP_TISHI = safe_imread(("logo", "shangjia", "tishi.png"), 0)
        state.TEMP_POPUP = safe_imread(("logo", "shangjia", "shangjiatan.png"), 0)

        missing = []
        if any(v is None for v in templates.values()):
            missing.append("logo/jiage/0.png - 9.png")
        if temp_success is None:
            missing.append("logo/tezhengtu/chenggong.png")
        if temp_shop is None:
            missing.append("logo/tezhengtu/dianpu.png")
        if state.temp_jiaoyi is None:
            missing.append("logo/tezhengtu/jiaoyihang.png")
        if temp_goumai is None:
            missing.append("logo/tezhengtu/goumai.png")
        if temp_meihuo is None:
            missing.append("logo/tezhengtu/meihuo.png")
        if temp_diyici is None:
            missing.append("logo/tezhengtu/diyici.png")
        if state.TEMP_ITEM is None:
            missing.append("logo/shangjia/pojiaoshi.png")
        if state.TEMP_TISHI is None:
            missing.append("logo/shangjia/tishi.png")

        if missing:
            ui_print(f"素材缺失: {', '.join(missing)}", save_log=True)
            time.sleep(10)
            return

        if state.TEMP_POPUP is not None:
            ui_print("上架弹窗检测：模板匹配模式")
        else:
            ui_print("上架弹窗检测：帧差异模式")

        if load_digit_templates():
            ui_print("容量识别：模板匹配模式")
        else:
            ui_print("容量识别：文字识别模式")

        camera = None
        try:
            camera = dxcam.create(output_color="BGRA")
            camera.start(target_fps=144)
        except Exception as e:
            ui_print(f"截图引擎启动失败: {e}")
            time.sleep(5)
            return

        try:
            if mode == "launcher":
                state.accessory_purchase_mode = False
                if not _prepare_default_launcher_start(camera):
                    _pause_after_launcher_start_failure()
                    return
                if not wait_for_verified_slot_cooldown_before_launch(
                    state.current_execution_slot,
                    sync_running_status_after_wait=False,
                ):
                    _pause_after_launcher_start_failure()
                    return
                if not startup_from_server_list(camera, state.current_server_index):
                    _pause_after_launcher_start_failure()
                    return
                if not _run_pre_listing_flow(
                    camera,
                    reset_runtime_before_listing=True,
                    reset_reason="启动后预上架前清空当前账号运行态",
                    purchase_reset_reason="启动后开始当前账号流程",
                    force_balance_check_after_switch=True,
                ):
                    return
            elif mode == "listing_launcher":
                state.accessory_purchase_mode = False
                if not _is_listing_enabled_for_session():
                    _log_listing_disabled_once()
                    return
                ui_print("上架模式启动", save_log=True)
                listing_mode_result = run_startup_listing_mode(camera)
                if not isinstance(listing_mode_result, dict):
                    return
                if listing_mode_result.get("status") == "handoff_to_normal":
                    target_slot = listing_mode_result.get("target_slot")
                    if not _handle_startup_listing_normal_handoff(camera, target_slot):
                        return
                elif listing_mode_result.get("status") != "completed":
                    return
            elif mode == "temporary_launcher":
                state.accessory_purchase_mode = False
                ui_print("临时抢购模式在 1 秒后启动...")
                safe_sleep(1.0)
                if not startup_temporary_from_qidong(camera):
                    _pause_after_launcher_start_failure()
                    return
                _prepare_temporary_purchase_context()
                if _is_listing_enabled_for_session():
                    ui_print("开始执行预上架流程...")
                    execute_listing_routine(camera)
                else:
                    _log_listing_disabled_once()
                run_purchase_loop(
                    camera,
                    templates,
                    temp_success,
                    temp_shop,
                    temp_goumai,
                    temp_meihuo,
                    temp_diyici,
                )
                if not _should_dispatch_temporary_target_switch():
                    return

                dispatch_action = _handle_temporary_target_execution_slot_dispatch(camera)
                if dispatch_action == "continue":
                    pass
                else:
                    return
            elif mode == "accessory_launcher":
                state.accessory_purchase_mode = True
                state.listing_enabled = False
                state.listing_disabled_for_session = True
                state.accessory_item_index = 0
                ui_print("饰品抢购启动", save_log=True)
                if not _prepare_default_launcher_start(camera):
                    _pause_after_launcher_start_failure()
                    return
                if not wait_for_verified_slot_cooldown_before_launch(
                    state.current_execution_slot,
                    sync_running_status_after_wait=False,
                ):
                    _pause_after_launcher_start_failure()
                    return
                if not startup_accessory_from_server_list(camera, state.current_server_index):
                    _pause_after_launcher_start_failure()
                    return
                if not _run_accessory_account_flow(
                    camera,
                    reset_runtime_before_purchase=True,
                    reset_reason="启动后饰品抢购前清空当前账号运行态",
                    purchase_reset_reason="启动后开始饰品抢购账号流程",
                    enter_trade=False,
                ):
                    return
            elif mode == "brutal_launcher":
                state.accessory_purchase_mode = False
                state.listing_enabled = False
                state.listing_disabled_for_session = True
                state.account_record_loaded = False
                state.account_read_status = ""
                state.current_nickname = ""
                state.current_execution_slot = None
                state.overlay_status = "暴力抢购"
                state.round_purchase_success_count = 0
                state.round_purchase_fail_count = 0
                state.round_listing_success_count = 0
                state.success_count = 0
                state.fail_count = 0
                if state.overlay_root:
                    try:
                        state.overlay_root.after(0, state.overlay_root.deiconify)
                        state.overlay_root.after(0, update_score_text)
                    except Exception:
                        pass
                ui_print("暴力模式启动", save_log=True)
                run_brutal_purchase_loop(
                    camera,
                    temp_success,
                    temp_shop,
                    temp_goumai,
                    temp_meihuo,
                    temp_diyici,
                )
                return
            else:
                ui_print(f"未知启动模式：{mode}", save_log=True)
                return

            while True:
                state.need_switch_server = False
                print(f"[账号数据] 准备进入抢购循环，当前时刻={_format_account_time(datetime.now())}，计时器状态：{_format_timer_state()}")
                logger.info("[账号数据] 准备进入抢购循环，当前时刻=%s，计时器状态：%s", _format_account_time(datetime.now()), _format_timer_state())
                run_purchase_loop(
                    camera,
                    templates,
                    temp_success,
                    temp_shop,
                    temp_goumai,
                    temp_meihuo,
                    temp_diyici,
                )

                if state.account_round_writeback_failed:
                    print(f"[账号数据] 主 SQLite 数据库写回失败：{state.account_round_writeback_error}")
                    logger.error("[账号数据] 主 SQLite 数据库写回失败：%s", state.account_round_writeback_error)
                    _finalize_current_account_round("未知异常")
                    return

                if not _finalize_current_account_round("未知异常"):
                    return

                if not state.need_switch_server:
                    break

                if not state.accessory_purchase_mode:
                    _refresh_latest_balance_before_switch(camera)
                _clear_runtime_state_after_account_finalize("换号前移清理")
                dispatch_action = _handle_execution_slot_dispatch(camera)
                if dispatch_action == "continue":
                    continue
                if dispatch_action == "abort":
                    return
                break
        finally:
            if camera is not None:
                camera.stop()
    finally:
        shutdown_overlay()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        pass
    except KeyboardInterrupt:
        _finalize_current_account_round("人工暂停")
        sys.exit()
    except Exception as e:
        _finalize_current_account_round("未知异常")
        import traceback
        error_msg = traceback.format_exc()
        print("\n" + "=" * 50)
        print("致命错误")
        print("=" * 50)
        print(error_msg)
        try:
            with open("crash_log.txt", "w", encoding="utf-8") as f:
                f.write(error_msg)
            print("崩溃日志已保存到 crash_log.txt")
        except:
            pass
        os.system('pause')
