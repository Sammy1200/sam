"""
唯一入口：初始化、加载资源并启动自动化流程。
"""
import ctypes
import sys
import os
import time
import subprocess
from urllib import error as urllib_error
from urllib import request as urllib_request
from datetime import datetime, timedelta
import cv2


# ===== 0. 自动提权 =====
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


if os.environ.get("CODEX_SKIP_ELEVATE") != "1" and not is_admin():
    print("正在申请管理员权限...")
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable,
        f'"{os.path.abspath(__file__)}"', None, 1)
    sys.exit()


try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    print("缺少 rapidocr_onnxruntime，请运行: pip install rapidocr-onnxruntime")
    os.system('pause')
    sys.exit()


import dxcam
import config
import state
from config import (
    MONITOR_JIAOYIHANG, MONITOR_SHOP,
    FIX_SHOP_POS1, FIX_SHOP_POS2,
    ACCOUNT_LIMIT_COOLDOWN_SECONDS,
)
from account_db import (
    CANONICAL_ACCOUNT_STATS_TABLE,
    ensure_canonical_execution_slot_seed_records,
    ensure_local_canonical_account_stats_store,
    find_canonical_account_stats_store,
    normalize_canonical_round_status_values,
    read_preferred_canonical_account_stats_record_by_execution_slot,
    read_canonical_account_stats_record,
    read_canonical_account_stats_record_by_execution_slot,
)
from round_persistence import (
    persist_final_round_snapshot,
    refresh_account_limit_reached_at,
    reset_round_runtime_state,
    restore_runtime_window_state,
    resolve_shutdown_final_status,
)
from utils import safe_sleep, safe_get_frame, safe_imread, fast_click, gc_checkpoint
from utils import async_push_msg, logger
from vision import is_image_present, load_digit_templates
from overlay import shutdown_overlay, start_overlay, ui_print, update_score_text
from listing import execute_listing_routine
from purchase import run_purchase_loop, reset_purchase_counters
from switch import (
    detect_current_execution_slot_from_launcher,
    pause_thread6_failure,
    resolve_execution_slot_transition,
    switch_server_within_account_after_slot_boundary,
    startup_from_server_list,
    switch_account_after_slot_boundary,
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


def _prompt_main_mode():
    while True:
        print("\n" + "=" * 40)
        print(" 请选择启动方式：")
        print(" [回车] 从启动器开始（自动识别昵称 -> 自动解析大区 -> 进游戏 -> 交易行）")
        print(" [2] 已在交易行，临时抢购模式")
        print("=" * 40)
        choice = input("直接回车或输入选项: ").strip()
        if choice == "":
            return "launcher"
        if choice == "2":
            return choice
        print("请输入回车或 2。")


def _prompt_temporary_item_count():
    while True:
        raw = input("请输入本号当前道具库存: ").strip()
        try:
            item_count = int(raw)
        except ValueError:
            print("请输入大于等于 0 的整数。")
            continue
        if item_count < 0:
            print("请输入大于等于 0 的整数。")
            continue
        return item_count


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

    if slot_number < 1 or slot_number > len(config.EXECUTION_SLOT_SERVER_COORD_INDEXES):
        return None

    server_index = config.EXECUTION_SLOT_SERVER_COORD_INDEXES[slot_number - 1]
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
        f"启动信息已自动解析：昵称 {state.current_nickname}，"
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
    if 1 <= slot_number <= int(config.EXECUTION_SLOT_COUNT):
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


def _set_account_state_defaults():
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
    state.round_purchase_running_seconds = 0.0
    state.runtime_window_start_time = None
    state.round_status = "手动结束"
    state.overlay_status = ""
    state.account_round_end_status = ""
    state.account_round_finalized = False
    state.account_round_writeback_failed = False
    state.account_round_writeback_error = ""
    state.account_limit_reached_at = None
    state.temporary_purchase_mode = False


def _prepare_temporary_purchase_context(item_count):
    """线程10B：临时模式只初始化运行态，不读取账号库。"""
    _set_account_state_defaults()
    state.temporary_purchase_mode = True
    state.need_switch_server = False
    state.current_nickname = "临时模式"
    state.current_execution_slot = None
    state.baseline_item_count = item_count
    state.account_allow_purchase = True
    state.account_is_waiting = False
    state.overlay_status = "临时抢购中"
    reset_round_runtime_state("进入临时抢购模式")
    reset_purchase_counters("进入临时抢购模式")
    ui_print(f"临时抢购模式已启动，当前道具库存：{item_count}", save_log=True)
    print(f"[临时模式] 已启动，当前道具库存={item_count}")
    logger.info("[临时模式] 已启动，当前道具库存=%s", item_count)


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
        state.account_read_error = "当前账号昵称为空，无法读取 SQLite。"
        state.overlay_status = "未知异常"
        print(f"[账号数据] 读取失败：{state.account_read_error}")
        logger.error(f"[账号数据] 读取失败：{state.account_read_error}")
        return False

    database_path, table_name = find_canonical_account_stats_store()
    if not database_path:
        database_path, table_name, inserted_seed_records = ensure_local_canonical_account_stats_store()
        print(f"[账号数据] 未找到现成账号库，已自动初始化本地 SQLite：{database_path}")
        logger.info("[账号数据] 未找到现成账号库，已自动初始化本地 SQLite：%s", database_path)
        if inserted_seed_records:
            inserted_slots = ",".join(str(record.current_execution_slot) for record in inserted_seed_records)
            inserted_nicknames = ",".join(record.nickname for record in inserted_seed_records)
            print(f"[账号数据] 初始化时已补齐执行位建档：执行位={inserted_slots}，昵称={inserted_nicknames}")
            logger.info(
                "[账号数据] 初始化时已补齐执行位建档：执行位=%s 昵称=%s",
                inserted_slots,
                inserted_nicknames,
            )

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
        print(f"[账号数据] 已归一旧 round_status 样本数据：{normalized_count} 条")
        logger.info("[账号数据] 已归一旧 round_status 样本数据：%s 条", normalized_count)

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
        state.account_read_error = f"SQLite 中未找到昵称为 {nickname} 的账号记录。"
        state.account_db_path = database_path
        state.account_db_table_name = table_name
        state.overlay_status = "账号未建档"
        print(f"[账号数据] 读取失败：{state.account_read_error}")
        logger.error(f"[账号数据] 读取失败：{state.account_read_error}")
        return False

    now = datetime.now()
    allow_start_time = now
    allow_purchase = True

    if record.last_limit_time is not None:
        allow_start_time = record.last_limit_time + timedelta(seconds=ACCOUNT_LIMIT_COOLDOWN_SECONDS)
        allow_purchase = now >= allow_start_time

    state.current_nickname = record.nickname
    state.baseline_item_count = record.baseline_item_count
    state.last_limit_time = record.last_limit_time
    state.last_account_end_time = record.last_account_end_time
    state.updated_at = record.updated_at
    if record.current_execution_slot is not None:
        state.current_execution_slot = record.current_execution_slot
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
    state.account_record_loaded = True
    runtime_window_sync_result = restore_runtime_window_state()
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
):
    if not _load_current_account_context():
        return False
    if reset_runtime_before_listing:
        reset_round_runtime_state(reset_reason, reset_purchase_runtime=False)
        reset_purchase_counters(purchase_reset_reason)
    ui_print("开始执行预上架流程...")
    execute_listing_routine(camera)
    return _wait_until_account_ready()


def _run_direct_account_flow(camera):
    if not _load_current_account_context():
        return False
    if not state.account_allow_purchase:
        ui_print("当前账号未到允许抢购时间，先执行预上架流程...")
        return _run_pre_listing_flow(
            camera,
            reset_runtime_before_listing=True,
            reset_reason="冷却等待前预上架清空当前账号运行态",
            purchase_reset_reason="冷却等待前开始当前账号流程",
        )
    reset_round_runtime_state("已加载当前账号", reset_purchase_runtime=False)
    return _wait_until_account_ready()


def _prepare_launcher_start(camera):
    return startup_from_launcher(camera, state.current_server_index)


def _pause_after_launcher_start_failure():
    """启动器链路失败时，保留现场并等待人工确认。"""
    message = "从启动器进入游戏流程失败，脚本暂停等待人工处理。"
    ui_print(message, save_log=True)
    print(f"[启动器] {message}")
    logger.error("[启动器] %s", message)
    os.system('pause')


def _finalize_current_account_round(default_status):
    if state.temporary_purchase_mode:
        return True
    if not state.account_record_loaded and state.account_read_status == "":
        return True
    _freeze_purchase_timer()
    final_status = resolve_shutdown_final_status(default_status)
    result = persist_final_round_snapshot(final_status)
    if result.status == "success":
        return True

    print(f"[账号数据] 最终写回失败：{result.reason}")
    logger.error("[账号数据] 最终写回失败：%s", result.reason)
    return False


def _handle_execution_slot_dispatch(camera):
    try:
        transition = resolve_execution_slot_transition(state.current_execution_slot)
        if transition is None:
            pause_thread6_failure("解析下一目标执行位", f"当前执行位 {state.current_execution_slot} 无效，无法解析下一目标执行位。")
            state.need_switch_server = False
            return "abort"

        ui_print(
            f"线程6调度：执行位 {transition['current_slot']} 本轮结束，下一目标执行位 {transition['next_slot']}。",
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
                f"线程6调度：命中 {transition['current_slot']}->{transition['next_slot']} 自动衔接边界，继续沿用原链路。",
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
                f"线程6调度：命中 {transition['current_slot']}->{transition['next_slot']} 同账号跨区切换，进入真实页面自动切换。",
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

        if not _run_pre_listing_flow(
            camera,
            reset_runtime_before_listing=True,
            reset_reason="换号后预上架前清空当前账号运行态",
            purchase_reset_reason="换号后开始新账号流程",
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
        "SQLite 查看页",
        "账号详情页",
        "页面不存在。",
        "页面渲染失败",
        "提交处理失败",
    )
    return any(marker in body_text for marker in markers)


def _probe_web_view_service(timeout=0.5):
    request = urllib_request.Request(
        f"{config.WEB_VIEW_SERVER_URL}/",
        headers={"User-Agent": "codex-main-web-check"},
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            body_text = response.read().decode("utf-8", errors="ignore")
    except urllib_error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="ignore")
        if _is_web_view_service_response_valid(body_text):
            return True, f"网页服务已可访问，HTTP {exc.code}"
        return False, f"8091 已有其他 HTTP 服务响应，HTTP {exc.code}"
    except Exception as exc:
        return False, f"网页服务不可访问：{exc}"

    if _is_web_view_service_response_valid(body_text):
        return True, "网页服务已可访问"
    return False, "8091 已有其他 HTTP 服务响应"


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

    try:
        process = subprocess.Popen(
            [sys.executable, script_path],
            cwd=config.SCRIPT_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo,
            creationflags=creationflags,
            close_fds=True,
        )
    except Exception as exc:
        message = f"[网页服务] 后台静默启动失败：{exc}"
        print(message)
        logger.error(message)
        return False

    logger.info("[网页服务] 已发起后台静默启动，pid=%s", process.pid)
    print(f"[网页服务] 已发起后台静默启动，pid={process.pid}")

    for _ in range(6):
        time.sleep(0.3)
        if process.poll() is not None:
            message = f"[网页服务] 子进程已退出，returncode={process.returncode}"
            print(message)
            logger.error(message)
            return False
        is_running, reason = _probe_web_view_service(timeout=0.3)
        if is_running:
            logger.info("[网页服务] 后台静默启动完成：%s", reason)
            print(f"[网页服务] 后台静默启动完成：{reason}")
            return True
        if "其他 HTTP 服务" in reason:
            logger.warning("[网页服务] 8091 端口冲突：%s", reason)
            print(f"[网页服务] 8091 端口冲突：{reason}")
            return False

    message = "[网页服务] 已尝试后台静默启动，但暂未确认可访问，主程序继续运行。"
    print(message)
    logger.warning(message)
    return False


def ensure_web_view_server_ready():
    is_running, reason = _probe_web_view_service(timeout=0.4)
    if is_running:
        logger.info("[网页服务] 跳过启动：%s", reason)
        print(f"[网页服务] 跳过启动：{reason}")
        return True

    if "其他 HTTP 服务" in reason:
        logger.warning("[网页服务] 跳过启动：%s", reason)
        print(f"[网页服务] 跳过启动：{reason}")
        return False

    logger.info("[网页服务] 检查未通过，准备后台静默启动：%s", reason)
    print(f"[网页服务] 检查未通过，准备后台静默启动：{reason}")
    return _start_web_view_server_in_background()


def main():
    ensure_web_view_server_ready()
    mode = _prompt_main_mode()
    start_overlay()
    try:
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
                if not _prepare_default_launcher_start(camera):
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
                ):
                    return
            else:
                item_count = _prompt_temporary_item_count()
                ui_print("临时抢购模式将在 1 秒后启动...")
                safe_sleep(1.0)
                _prepare_temporary_purchase_context(item_count)
                ui_print("开始执行预上架流程...")
                execute_listing_routine(camera)
                run_purchase_loop(
                    camera,
                    templates,
                    temp_success,
                    temp_shop,
                    temp_goumai,
                    temp_meihuo,
                    temp_diyici,
                )
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
                    print(f"[账号数据] SQLite 写回失败：{state.account_round_writeback_error}")
                    logger.error("[账号数据] SQLite 写回失败：%s", state.account_round_writeback_error)
                    _finalize_current_account_round("未知异常")
                    return

                if not _finalize_current_account_round("未知异常"):
                    return

                if not state.need_switch_server:
                    break

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
        _finalize_current_account_round("手动结束")
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
