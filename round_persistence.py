"""Account round settlement and canonical SQLite write-back."""
from datetime import datetime, timedelta
import time

import state
from account_db import (
    AccountStatsRecord,
    TemporaryAccountSnapshot,
    AccountWriteResult,
    CANONICAL_ACCOUNT_STATS_TABLE,
    MACHINE_DAILY_SUMMARY_EVENT_LISTING_SUCCESS,
    MACHINE_DAILY_SUMMARY_EVENT_PURCHASE_FAIL,
    MACHINE_DAILY_SUMMARY_EVENT_PURCHASE_SUCCESS,
    ROUND_STATUS_BALANCE_LOW,
    ROUND_STATUS_LIMITED,
    ROUND_STATUS_MANUAL_PAUSE,
    ROUND_STATUS_READY,
    ROUND_STATUS_RUNTIME_REACHED,
    ROUND_STATUS_RUNNING,
    ROUND_STATUS_UNKNOWN,
    ACCOUNT_DB_MODE_STONE,
    find_canonical_account_stats_store,
    increment_machine_daily_summary_event,
    mature_all_stone_item_unlock_batches,
    mature_stone_item_unlock_batches,
    read_canonical_account_stats_record,
    read_preferred_canonical_account_stats_record_by_execution_slot,
    record_stone_item_purchase_success,
    record_startup_listing_item_success,
    reset_temporary_account_snapshot,
    save_canonical_account_stats_record,
    save_temporary_account_snapshot,
    clear_canonical_account_round_listing_success_count,
    update_canonical_account_listing_pause_fields,
    update_canonical_account_status_fields,
    update_canonical_account_runtime_fields,
    update_canonical_account_item_balance_fields,
)
from config import ACCOUNT_LIMIT_COOLDOWN_SECONDS, ACCOUNT_MAX_PURCHASE_SECONDS, TEMPORARY_ACCOUNT_NICKNAME
from machine_sync_config import get_machine_sync_runtime_context
from utils import get_current_elapsed, logger


PLACEHOLDER_BALANCE = "\u83b7\u53d6\u4e2d"
STATUS_NORMAL_SWITCH = "\u5f53\u524d\u8d26\u53f7\u6b63\u5e38\u5b8c\u6210\u5e76\u5207\u5230\u4e0b\u4e00\u4e2a\u8d26\u53f7"


def _is_forced_limit_status(round_status):
    return round_status in (ROUND_STATUS_BALANCE_LOW, ROUND_STATUS_LIMITED, ROUND_STATUS_RUNTIME_REACHED)


def _clear_round_counters():
    state.success_count = 0
    state.fail_count = 0
    state.total_listed_count = 0
    state.round_purchase_success_count = 0
    state.round_listing_success_count = 0
    state.round_purchase_fail_count = 0


def _is_stone_inventory_split_active():
    return (
        not bool(getattr(state, "temporary_purchase_mode", False))
        and not bool(getattr(state, "accessory_purchase_mode", False))
        and str(getattr(state, "account_db_mode", ACCOUNT_DB_MODE_STONE) or ACCOUNT_DB_MODE_STONE)
        == ACCOUNT_DB_MODE_STONE
    )


def _apply_stone_inventory_result(result):
    if result is None:
        return
    if result.new_baseline_item_count is not None:
        state.baseline_item_count = max(0, int(result.new_baseline_item_count))
    if result.new_locked_item_count is not None:
        state.locked_item_count = max(0, int(result.new_locked_item_count))
    if result.new_tradable_item_count is not None:
        state.tradable_item_count = max(0, int(result.new_tradable_item_count))
    state.next_tradable_at = result.next_tradable_at


def mature_stone_unlocks_for_current_account(reason=""):
    """低成本触发石头 pending 批次结转；饰品/临时模式跳过。"""
    if not _is_stone_inventory_split_active():
        return AccountWriteResult("skipped", "非石头库存拆分模式")
    if not state.account_record_loaded or not state.account_db_path or not state.current_nickname:
        return AccountWriteResult("skipped", "当前账号未加载")

    next_tradable_at = getattr(state, "next_tradable_at", None)
    now = datetime.now()
    if next_tradable_at is None:
        return AccountWriteResult(
            "skipped",
            "没有待解锁批次",
            int(state.baseline_item_count),
            int(state.locked_item_count),
            int(state.tradable_item_count),
            None,
        )
    if now < next_tradable_at:
        return AccountWriteResult(
            "skipped",
            "未到最早解锁时间",
            int(state.baseline_item_count),
            int(state.locked_item_count),
            int(state.tradable_item_count),
            next_tradable_at,
        )

    result = mature_stone_item_unlock_batches(
        state.account_db_path,
        state.current_nickname,
        table_name=state.account_db_table_name or CANONICAL_ACCOUNT_STATS_TABLE,
        now=now,
    )
    if result.status in ("success", "inventory_mismatch", "skipped"):
        _apply_stone_inventory_result(result)
    if result.status == "success" and result.changed_quantity > 0:
        logger.info(
            "[石头库存] 到期结转完成：reason=%s nickname=%s quantity=%s locked=%s tradable=%s",
            reason,
            state.current_nickname,
            result.changed_quantity,
            state.locked_item_count,
            state.tradable_item_count,
        )
    elif result.status == "inventory_mismatch":
        logger.warning("[石头库存] 到期结转异常：reason=%s nickname=%s %s", reason, state.current_nickname, result.reason)
    elif result.status not in ("success", "skipped"):
        logger.warning("[石头库存] 到期结转失败：reason=%s nickname=%s %s", reason, state.current_nickname, result.reason)
    return result


def mature_all_stone_unlocks(reason=""):
    """触发石头库全账号 pending 批次结转，供启动、F12 和网页刷新使用。"""
    database_path, table_name = find_canonical_account_stats_store()
    if not database_path:
        return AccountWriteResult("skipped", "未找到石头 canonical 主库")

    result = mature_all_stone_item_unlock_batches(
        database_path,
        table_name=table_name or CANONICAL_ACCOUNT_STATS_TABLE,
    )
    if result.status == "success":
        logger.info(
            "[石头库存] 全账号到期结转完成：reason=%s quantity=%s detail=%s",
            reason,
            result.changed_quantity,
            result.reason,
        )
    elif result.status != "skipped":
        logger.warning(
            "[石头库存] 全账号到期结转异常：reason=%s status=%s detail=%s quantity=%s",
            reason,
            result.status,
            result.reason,
            result.changed_quantity,
        )
    return result


def record_stone_purchase_success_for_current_account():
    """石头抢购成功：锁定库存 +1，并生成 72 小时 pending 批次。"""
    if not _is_stone_inventory_split_active():
        state.baseline_item_count += 1
        return AccountWriteResult("skipped", "非石头库存拆分模式", int(state.baseline_item_count))
    if not state.account_record_loaded or not state.account_db_path or not state.current_nickname:
        return AccountWriteResult("skipped", "当前账号未加载")

    result = record_stone_item_purchase_success(
        state.account_db_path,
        state.current_nickname,
        table_name=state.account_db_table_name or CANONICAL_ACCOUNT_STATS_TABLE,
    )
    if result.status == "success":
        _apply_stone_inventory_result(result)
    else:
        logger.warning("[石头库存] 抢购成功入锁定库存失败：nickname=%s reason=%s", state.current_nickname, result.reason)
    return result


def record_stone_listing_success_for_current_account():
    """石头上架成功：只扣可交易库存，不允许用不可交易库存抵扣。"""
    if not _is_stone_inventory_split_active():
        if state.baseline_item_count > 0:
            state.baseline_item_count -= 1
        else:
            state.baseline_item_count = 0
        return AccountWriteResult("skipped", "非石头库存拆分模式", int(state.baseline_item_count))

    mature_stone_unlocks_for_current_account("上架扣库存前")
    if int(state.tradable_item_count) <= 0:
        logger.warning(
            "[石头库存] 可交易库存不足，禁止扣不可交易库存：nickname=%s locked=%s tradable=%s",
            state.current_nickname,
            state.locked_item_count,
            state.tradable_item_count,
        )
        return AccountWriteResult(
            "insufficient_tradable",
            "可交易库存不足",
            int(state.baseline_item_count),
            int(state.locked_item_count),
            int(state.tradable_item_count),
            state.next_tradable_at,
        )

    state.tradable_item_count = max(0, int(state.tradable_item_count) - 1)
    state.baseline_item_count = int(state.locked_item_count) + int(state.tradable_item_count)
    return AccountWriteResult(
        "success",
        "",
        int(state.baseline_item_count),
        int(state.locked_item_count),
        int(state.tradable_item_count),
        state.next_tradable_at,
        1,
    )


def record_startup_listing_success_for_current_account():
    """启动页上架成功：可交易优先，不足时扣最近到期的不可交易 pending。"""
    if not _is_stone_inventory_split_active():
        if state.baseline_item_count > 0:
            state.baseline_item_count -= 1
        else:
            state.baseline_item_count = 0
        return AccountWriteResult("skipped", "非石头库存拆分模式", int(state.baseline_item_count))
    if not state.account_record_loaded or not state.account_db_path or not state.current_nickname:
        return AccountWriteResult("skipped", "当前账号未加载")

    mature_stone_unlocks_for_current_account("启动页上架扣库存前")
    result = record_startup_listing_item_success(
        state.account_db_path,
        state.current_nickname,
        table_name=state.account_db_table_name or CANONICAL_ACCOUNT_STATS_TABLE,
    )
    if result.status == "success":
        _apply_stone_inventory_result(result)
    else:
        logger.warning("[石头库存] 启动页上架扣库存失败：nickname=%s reason=%s", state.current_nickname, result.reason)
    return result


def record_stone_unlist_recovered_for_current_account():
    """石头下架回补库存：回到可交易库存，不生成 pending。"""
    if not _is_stone_inventory_split_active():
        state.baseline_item_count += 1
        return AccountWriteResult("skipped", "非石头库存拆分模式", int(state.baseline_item_count))

    mature_stone_unlocks_for_current_account("下架回补库存前")
    state.tradable_item_count = max(0, int(state.tradable_item_count) + 1)
    state.baseline_item_count = int(state.locked_item_count) + int(state.tradable_item_count)
    return AccountWriteResult(
        "success",
        "",
        int(state.baseline_item_count),
        int(state.locked_item_count),
        int(state.tradable_item_count),
        state.next_tradable_at,
        1,
    )


def has_tradable_inventory_for_listing():
    """上架前守卫：石头只看可交易库存，饰品/旧逻辑仍看总库存。"""
    if _is_stone_inventory_split_active():
        mature_stone_unlocks_for_current_account("上架前")
        return int(state.tradable_item_count) > 0
    return int(state.baseline_item_count) > 0


def _resolve_current_canonical_target():
    nickname = (state.current_nickname or "").strip()
    database_path = str(state.account_db_path or "").strip()
    table_name = state.account_db_table_name or CANONICAL_ACCOUNT_STATS_TABLE
    slot_value = state.current_execution_slot
    record = None

    if database_path:
        try:
            if slot_value not in (None, ""):
                record = read_preferred_canonical_account_stats_record_by_execution_slot(
                    database_path,
                    slot_value,
                    table_name,
                )
        except Exception:
            record = None
        if record is None and nickname:
            record = read_canonical_account_stats_record(database_path, nickname, table_name)

    resolved_nickname = str((record.nickname if record is not None else nickname) or "").strip()
    if record is not None and resolved_nickname and nickname and resolved_nickname != nickname:
        logger.warning(
            "[账号数据] 当前执行位与内存昵称不一致，已改用执行位对应账号：执行位=%s 内存昵称=%s 解析昵称=%s",
            slot_value,
            nickname,
            resolved_nickname,
        )
    if resolved_nickname:
        state.current_nickname = resolved_nickname
    return {
        "nickname": resolved_nickname,
        "database_path": database_path,
        "table_name": table_name,
        "record": record,
    }


def _schedule_remote_snapshot_event(event_name, synchronous=False):
    try:
        if synchronous:
            from remote_sync import run_local_snapshot_report_for_event
        else:
            from remote_sync import schedule_local_snapshot_report
    except Exception as exc:
        logger.warning("[网页同步] 事件快照模块加载失败：event=%s error=%s", event_name, exc)
        return

    try:
        if synchronous:
            result = run_local_snapshot_report_for_event(event_name)
        else:
            result = schedule_local_snapshot_report(event_name)
    except Exception as exc:
        logger.warning("[网页同步] 事件快照触发失败：event=%s error=%s", event_name, exc)
        return

    status = str(result.get("status") or "").strip()
    if status == "scheduled":
        logger.info("[网页同步] 已安排事件触发最小快照：%s", event_name)
    elif status == "error":
        logger.warning("[网页同步] 事件触发最小快照失败：event=%s reason=%s", event_name, result.get("message"))


def reset_round_runtime_state(
    reason,
    reset_purchase_runtime=True,
    reset_round_counters=True,
    round_status=ROUND_STATUS_RUNNING,
):
    """Reset per-round runtime stats after mandatory pre-listing."""
    if reset_round_counters:
        _clear_round_counters()
        state.round_current_balance = ""
    state.listing_scan_miss_count = 0
    state.listing_periodic_disabled = False
    state.listing_periodic_disabled_reason = ""
    state.listing_periodic_skip_logged = False
    state.round_status = round_status
    state.last_resume_time = None
    state.purchase_timer_active = False
    state.account_round_end_status = ""
    state.account_round_finalized = False
    state.account_round_writeback_failed = False
    state.account_round_writeback_error = ""
    if reset_purchase_runtime:
        state.round_purchase_running_seconds = 0.0
        state.total_running_time = 0.0
        state.runtime_window_start_time = None
        state.account_limit_reached_at = None
    else:
        state.round_purchase_running_seconds = float(max(0.0, state.total_running_time))
    print(f"[round-settlement] {reason}, round counters reset.")
    logger.info("[round-settlement] %s, round counters reset.", reason)


def _reload_current_account_state_from_canonical():
    """恢复后回灌当前账号关键可回写字段，避免旧内存覆盖网页修改。"""
    target = _resolve_current_canonical_target()
    nickname = str(target.get("nickname") or "").strip()
    database_path = str(target.get("database_path") or "").strip()
    table_name = target.get("table_name") or CANONICAL_ACCOUNT_STATS_TABLE
    if not nickname or not database_path:
        return AccountWriteResult("skipped", "current account context is incomplete")

    record = target.get("record") or read_canonical_account_stats_record(database_path, nickname, table_name)
    if record is None:
        return AccountWriteResult("account_not_found", f"sqlite record not found for nickname: {nickname}")

    state.current_nickname = record.nickname
    state.baseline_item_count = int(record.baseline_item_count)
    state.locked_item_count = int(record.locked_item_count)
    state.tradable_item_count = int(record.tradable_item_count)
    state.next_tradable_at = record.next_tradable_at
    state.last_limit_time = record.last_limit_time
    state.last_account_end_time = record.last_account_end_time
    state.updated_at = record.updated_at
    if record.current_execution_slot is not None:
        state.current_execution_slot = record.current_execution_slot
    state.success_count = int(record.round_purchase_success_count)
    state.total_listed_count = int(record.round_listing_success_count)
    state.fail_count = int(record.round_purchase_fail_count)
    state.round_purchase_success_count = int(record.round_purchase_success_count)
    state.round_listing_success_count = int(record.round_listing_success_count)
    state.round_purchase_fail_count = int(record.round_purchase_fail_count)
    state.round_current_balance = str(record.current_balance or "").strip()
    state.current_balance = state.round_current_balance
    state.last_valid_balance = state.round_current_balance
    state.total_running_time = float(record.purchase_running_seconds)
    state.round_purchase_running_seconds = float(record.purchase_running_seconds)
    state.runtime_window_start_time = record.runtime_window_start_time
    state.round_status = record.round_status
    return AccountWriteResult("success", "")


def resolve_shutdown_final_status(default_status):
    if state.account_round_end_status:
        return state.account_round_end_status
    return default_status


def _runtime_window_seconds():
    return int(ACCOUNT_LIMIT_COOLDOWN_SECONDS)


def _build_runtime_window_result(changed, actions, persist_result=None):
    return {
        "changed": changed,
        "actions": actions,
        "persist_result": persist_result,
    }


def _resolve_machine_daily_summary_database_path():
    database_path = str(state.account_db_path or "").strip()
    if database_path:
        return database_path

    try:
        resolved_database_path, _ = find_canonical_account_stats_store()
    except Exception as exc:
        logger.warning("[机器汇总] 解析机器级汇总数据库路径失败：%s", exc)
        return ""
    return str(resolved_database_path or "").strip()


def _record_machine_daily_summary_event(event_name, occurred_at=None):
    if (not state.temporary_purchase_mode) and (
        state.account_read_status == "account_not_found" or not state.account_record_loaded
    ):
        return AccountWriteResult("skipped", "current account record is unavailable")
    database_path = _resolve_machine_daily_summary_database_path()
    if not database_path:
        return AccountWriteResult("skipped", "machine daily summary database path is empty")

    runtime_context = get_machine_sync_runtime_context()
    machine_id = str(runtime_context.get("machine_id") or "local").strip() or "local"
    machine_display_name = str(runtime_context.get("machine_display_name") or "本机").strip() or machine_id
    result = increment_machine_daily_summary_event(
        database_path,
        machine_id,
        machine_display_name,
        event_name,
        occurred_at=occurred_at,
    )
    if result.status not in ("success", "skipped"):
        logger.warning(
            "[日报汇总] 事件入账失败：event=%s nickname=%s reason=%s",
            event_name,
            state.current_nickname,
            result.reason,
        )
    return result


def _resolve_temporary_round_status():
    status_aliases = {
        "临时抢购中": ROUND_STATUS_RUNNING,
        "抢购中": ROUND_STATUS_RUNNING,
        "临时账号限制": ROUND_STATUS_LIMITED,
    }
    for value in (
        state.account_round_end_status,
        state.round_status,
        state.overlay_status,
    ):
        text = str(value or "").strip()
        if text:
            return status_aliases.get(text, text)
    return ROUND_STATUS_RUNNING


def reset_temporary_account_snapshot_for_new_round():
    result = reset_temporary_account_snapshot()
    if result.status not in ("success", "skipped"):
        logger.warning("[临时号] 重置辅助快照失败：%s", result.reason)
    return result


def persist_temporary_account_snapshot(event_name=None, trigger_remote_snapshot=False):
    if not state.temporary_purchase_mode:
        return AccountWriteResult("skipped", "非临时模式")

    snapshot = TemporaryAccountSnapshot(
        nickname=TEMPORARY_ACCOUNT_NICKNAME,
        baseline_item_count=max(0, int(state.baseline_item_count)),
        round_purchase_success_count=max(0, int(state.round_purchase_success_count)),
        round_listing_success_count=max(0, int(state.round_listing_success_count)),
        round_purchase_fail_count=max(0, int(state.round_purchase_fail_count)),
        current_balance=_get_effective_balance(),
        purchase_running_seconds=max(0, int(get_current_elapsed())),
        round_status=_resolve_temporary_round_status(),
        updated_at=datetime.now(),
    )
    result = save_temporary_account_snapshot(snapshot)
    if result.status != "success":
        logger.warning("[临时号] 辅助快照写入失败：%s", result.reason)
        return result

    if trigger_remote_snapshot:
        _schedule_remote_snapshot_event(event_name or "临时号辅助快照")
    return result


def record_daily_purchase_success():
    return _record_machine_daily_summary_event(MACHINE_DAILY_SUMMARY_EVENT_PURCHASE_SUCCESS)


def record_daily_listing_success():
    return _record_machine_daily_summary_event(MACHINE_DAILY_SUMMARY_EVENT_LISTING_SUCCESS)


def record_daily_purchase_fail():
    return _record_machine_daily_summary_event(MACHINE_DAILY_SUMMARY_EVENT_PURCHASE_FAIL)


def _persist_runtime_window_fields(reason, update_last_limit_time=False, last_limit_time=None):
    if state.temporary_purchase_mode:
        return AccountWriteResult("skipped", "\u4e34\u65f6\u6a21\u5f0f\u4e0d\u5199\u5165 canonical SQLite")

    nickname = (state.current_nickname or "").strip()
    if state.account_read_status == "account_not_found" or not state.account_record_loaded or not nickname:
        return AccountWriteResult("skipped", f"\u5f53\u524d\u8d26\u53f7\u672a\u52a0\u8f7d SQLite \u8bb0\u5f55: {nickname}")
    if not state.account_db_path:
        return AccountWriteResult("skipped", "canonical database path is empty")

    runtime_seconds = max(0, int(get_current_elapsed()))
    write_time = datetime.now()
    result = update_canonical_account_runtime_fields(
        state.account_db_path,
        nickname,
        runtime_seconds,
        state.runtime_window_start_time,
        table_name=state.account_db_table_name or CANONICAL_ACCOUNT_STATS_TABLE,
        updated_at=write_time,
        last_limit_time=last_limit_time,
        update_last_limit_time=update_last_limit_time,
    )
    if result.status == "success":
        state.updated_at = write_time
        state.round_purchase_running_seconds = float(runtime_seconds)
        if update_last_limit_time:
            state.last_limit_time = last_limit_time
        logger.info(
            "[\u8fd0\u884c\u7a97\u53e3] %s\uff1a\u6635\u79f0=%s\uff0c\u7d2f\u8ba1\u62a2\u8d2d\u79d2\u6570=%s\uff0c\u7a97\u53e3\u8d77\u70b9=%s",
            reason,
            nickname,
            runtime_seconds,
            state.runtime_window_start_time.strftime("%Y-%m-%d %H:%M:%S")
            if state.runtime_window_start_time is not None
            else "\u65e0",
        )
    else:
        logger.warning("[\u8fd0\u884c\u7a97\u53e3] %s\u5199\u5e93\u5931\u8d25\uff1a%s", reason, result.reason)
    return result


def sync_runtime_window_state(
    persist_if_changed=False,
    initialize_if_missing=False,
    allow_legacy_fallback=False,
):
    """同步 24 小时 01 分运行窗口状态。"""
    if state.temporary_purchase_mode:
        return _build_runtime_window_result(False, [])

    actions = []
    changed = False
    persist_result = None
    now_ts = time.time()
    now_dt = datetime.fromtimestamp(now_ts)
    current_elapsed_seconds = max(0.0, float(get_current_elapsed()))

    if state.runtime_window_start_time is None:
        if allow_legacy_fallback and current_elapsed_seconds > 0:
            restored_start = state.updated_at or state.last_account_end_time or now_dt
            state.runtime_window_start_time = restored_start
            changed = True
            actions.append(
                f"\u8865\u9f50\u8fd0\u884c\u7a97\u53e3\u8d77\u70b9\u4e3a {restored_start.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        elif initialize_if_missing:
            state.runtime_window_start_time = now_dt
            changed = True
            actions.append(
                f"\u521d\u59cb\u5316\u8fd0\u884c\u7a97\u53e3\u8d77\u70b9\u4e3a {now_dt.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        else:
            state.round_purchase_running_seconds = 0.0
            return _build_runtime_window_result(False, actions)

    window_start_time = state.runtime_window_start_time
    window_seconds = _runtime_window_seconds()
    elapsed_since_window_start = (now_dt - window_start_time).total_seconds()
    if elapsed_since_window_start >= window_seconds:
        window_step_count = int(elapsed_since_window_start // window_seconds)
        new_window_start = window_start_time + timedelta(seconds=window_step_count * window_seconds)
        is_active = (
            state.purchase_timer_active
            and not state.IS_PAUSED
            and state.last_resume_time is not None
        )
        if is_active and state.last_resume_time < new_window_start.timestamp():
            state.last_resume_time = new_window_start.timestamp()
        state.total_running_time = 0.0
        state.round_purchase_running_seconds = 0.0
        state.runtime_window_start_time = new_window_start
        state.account_limit_reached_at = None
        changed = True
        actions.append(
            f"24小时01分运行窗口已滚动到 {new_window_start.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    else:
        state.round_purchase_running_seconds = current_elapsed_seconds

    if changed and persist_if_changed:
        persist_result = _persist_runtime_window_fields("\u540c\u6b65\u8fd0\u884c\u7a97\u53e3")

    return _build_runtime_window_result(changed, actions, persist_result)


def restore_runtime_window_state():
    """\u8d26\u53f7\u8f7d\u5165\u540e\u6062\u590d\u8fd0\u884c\u7a97\u53e3\u72b6\u6001\uff0c\u4fdd\u8bc1\u91cd\u542f\u540e\u53ef\u7ee7\u7eed\u8ba1\u7b97\u5269\u4f59\u65f6\u957f\u3002"""
    return sync_runtime_window_state(
        persist_if_changed=True,
        initialize_if_missing=False,
        allow_legacy_fallback=True,
    )


def ensure_active_runtime_window_state():
    """\u8fdb\u5165\u771f\u5b9e\u62a2\u8d2d\u5faa\u73af\u524d\uff0c\u786e\u4fdd\u5f53\u524d\u8d26\u53f7\u5df2\u6709\u8fd0\u884c\u7a97\u53e3\u8d77\u70b9\u3002"""
    return sync_runtime_window_state(
        persist_if_changed=True,
        initialize_if_missing=True,
        allow_legacy_fallback=False,
    )


def get_runtime_window_remaining_seconds():
    sync_runtime_window_state(
        persist_if_changed=False,
        initialize_if_missing=False,
        allow_legacy_fallback=False,
    )
    used_seconds = max(0, int(get_current_elapsed()))
    remaining_seconds = ACCOUNT_MAX_PURCHASE_SECONDS - min(ACCOUNT_MAX_PURCHASE_SECONDS, used_seconds)
    return max(0, remaining_seconds)


def persist_account_limit_reached_if_needed():
    """\u5728\u8fbe\u5230 2 \u5c0f\u65f6 40 \u5206\u9608\u503c\u65f6\u7acb\u5373\u843d\u5e93 last_limit_time\u3002"""
    previous_limit_time = state.account_limit_reached_at
    reached_time = refresh_account_limit_reached_at()
    if reached_time is None or previous_limit_time is not None:
        return AccountWriteResult("skipped", "limit time unchanged")
    if state.last_limit_time is not None and state.last_limit_time == reached_time:
        return AccountWriteResult("skipped", "last_limit_time already persisted")
    return _persist_runtime_window_fields(
        "\u5230\u8fbe\u62a2\u8d2d\u65f6\u957f\u9608\u503c",
        update_last_limit_time=True,
        last_limit_time=reached_time,
    )


def refresh_account_limit_reached_at():
    """Record the exact wall-clock moment when purchase runtime reaches 2h45m."""
    if state.account_limit_reached_at is not None:
        return state.account_limit_reached_at

    threshold_seconds = ACCOUNT_MAX_PURCHASE_SECONDS
    if state.purchase_timer_active and not state.IS_PAUSED and state.last_resume_time is not None:
        remaining_before_limit = threshold_seconds - state.total_running_time
        if remaining_before_limit <= 0:
            if state.last_limit_time is not None:
                state.account_limit_reached_at = state.last_limit_time
            return state.account_limit_reached_at
        else:
            current_segment_elapsed = time.time() - state.last_resume_time
            if current_segment_elapsed < remaining_before_limit:
                return None
            reached_ts = state.last_resume_time + remaining_before_limit
        state.account_limit_reached_at = datetime.fromtimestamp(reached_ts)
        return state.account_limit_reached_at

    return state.account_limit_reached_at


def _get_effective_balance():
    balance_text = str(state.round_current_balance or "").strip()
    if balance_text:
        return balance_text

    current_text = str(state.last_valid_balance or state.current_balance or "").strip()
    if current_text and PLACEHOLDER_BALANCE not in current_text:
        return current_text
    return ""


def _normalize_round_status(raw_status, is_final):
    normalized = (raw_status or "").strip()
    if normalized in ("", "\u62a2\u8d2d\u4e2d", "\u8fd0\u884c\u4e2d"):
        return ROUND_STATUS_RUNNING if not is_final else ROUND_STATUS_UNKNOWN
    if normalized == "\u8d26\u53f7\u9650\u5236":
        return ROUND_STATUS_LIMITED
    if normalized == "\u4f59\u989d\u4e0d\u8db3":
        return ROUND_STATUS_BALANCE_LOW
    if normalized == "\u62a2\u8d2d\u65f6\u957f\u5df2\u5230":
        return ROUND_STATUS_RUNTIME_REACHED
    if normalized == ROUND_STATUS_READY:
        return ROUND_STATUS_READY
    if normalized in ("\u624b\u52a8\u7ed3\u675f", "\u4eba\u5de5\u6682\u505c"):
        return ROUND_STATUS_MANUAL_PAUSE
    if normalized == "\u672a\u77e5\u5f02\u5e38":
        return ROUND_STATUS_UNKNOWN
    if normalized == STATUS_NORMAL_SWITCH:
        return ROUND_STATUS_MANUAL_PAUSE
    return ROUND_STATUS_UNKNOWN if is_final else ROUND_STATUS_RUNNING


def _build_record(is_final, round_status):
    nickname = (state.current_nickname or "").strip()
    if state.account_read_status == "account_not_found" or not state.account_record_loaded:
        return None, AccountWriteResult(
            "account_not_found",
            f"sqlite record not found for nickname: {nickname}",
        )

    sync_runtime_window_state(
        persist_if_changed=False,
        initialize_if_missing=False,
        allow_legacy_fallback=False,
    )
    refresh_account_limit_reached_at()
    mature_stone_unlocks_for_current_account("写回前")
    state.round_purchase_running_seconds = float(get_current_elapsed())
    new_baseline_item_count = int(state.baseline_item_count)
    if new_baseline_item_count < 0:
        return None, AccountWriteResult(
            "invalid_baseline",
            f"current inventory is negative: {new_baseline_item_count}",
        )

    effective_round_status = _normalize_round_status(round_status, is_final)
    last_limit_time = state.last_limit_time
    if state.account_limit_reached_at is not None:
        last_limit_time = state.account_limit_reached_at

    last_account_end_time = state.last_account_end_time
    if is_final:
        last_account_end_time = datetime.now()

    updated_at = datetime.now()
    reset_round_counters_after_finalize = is_final and _is_forced_limit_status(effective_round_status)
    if _is_forced_limit_status(effective_round_status):
        if effective_round_status == ROUND_STATUS_RUNTIME_REACHED and state.account_limit_reached_at is not None:
            last_limit_time = state.account_limit_reached_at
        else:
            last_limit_time = updated_at
        state.round_purchase_running_seconds = 0.0
        state.runtime_window_start_time = None
    record = AccountStatsRecord(
        nickname=nickname,
        baseline_item_count=new_baseline_item_count,
        locked_item_count=int(getattr(state, "locked_item_count", 0)),
        tradable_item_count=int(getattr(state, "tradable_item_count", new_baseline_item_count)),
        next_tradable_at=getattr(state, "next_tradable_at", None),
        last_limit_time=last_limit_time,
        last_account_end_time=last_account_end_time,
        updated_at=updated_at,
        current_execution_slot=state.current_execution_slot,
        round_purchase_success_count=0 if reset_round_counters_after_finalize else int(state.round_purchase_success_count),
        round_listing_success_count=0 if reset_round_counters_after_finalize else int(state.round_listing_success_count),
        round_purchase_fail_count=0 if reset_round_counters_after_finalize else int(state.round_purchase_fail_count),
        current_balance=_get_effective_balance(),
        purchase_running_seconds=int(state.round_purchase_running_seconds),
        runtime_window_start_time=state.runtime_window_start_time,
        round_status=effective_round_status,
    )
    return record, None


def _save_record(record):
    if not state.account_db_path:
        return AccountWriteResult("db_unavailable", "canonical database path is empty")

    try:
        result = save_canonical_account_stats_record(state.account_db_path, record)
    except Exception as exc:
        return AccountWriteResult("write_failed", str(exc))

    state.last_limit_time = record.last_limit_time
    state.last_account_end_time = record.last_account_end_time
    state.updated_at = record.updated_at
    state.runtime_window_start_time = record.runtime_window_start_time
    state.round_status = record.round_status
    state.locked_item_count = int(record.locked_item_count)
    state.tradable_item_count = int(record.tradable_item_count)
    state.next_tradable_at = record.next_tradable_at
    return result


def persist_minimal_item_balance_sync():
    """库存变化时最小同步库存、余额和运行时间字段。"""
    if state.temporary_purchase_mode:
        return AccountWriteResult("skipped", "临时模式不写入 canonical SQLite")

    nickname = (state.current_nickname or "").strip()
    if state.account_read_status == "account_not_found" or not state.account_record_loaded:
        return AccountWriteResult(
            "account_not_found",
            f"未找到昵称为 {nickname} 的账号记录",
        )
    if not nickname:
        return AccountWriteResult("nickname_missing", "当前昵称为空")

    mature_stone_unlocks_for_current_account("实时同步前")
    runtime_item_quantity = int(state.baseline_item_count)
    if runtime_item_quantity < 0:
        return AccountWriteResult(
            "invalid_item_quantity",
            f"运行中道具库存为负数: {runtime_item_quantity}",
        )

    effective_balance = _get_effective_balance()
    table_name = state.account_db_table_name or CANONICAL_ACCOUNT_STATS_TABLE
    sync_runtime_window_state(
        persist_if_changed=False,
        initialize_if_missing=False,
        allow_legacy_fallback=False,
    )
    reached_time = refresh_account_limit_reached_at()
    runtime_seconds = max(0, int(get_current_elapsed()))
    write_time = datetime.now()
    result = update_canonical_account_item_balance_fields(
        state.account_db_path,
        nickname,
        runtime_item_quantity,
        effective_balance,
        table_name=table_name,
        updated_at=write_time,
        purchase_running_seconds=runtime_seconds,
        runtime_window_start_time=state.runtime_window_start_time,
        last_limit_time=reached_time,
        update_last_limit_time=(
            reached_time is not None and state.last_limit_time != reached_time
        ),
        locked_item_count=(
            int(state.locked_item_count) if _is_stone_inventory_split_active() else None
        ),
        tradable_item_count=(
            int(state.tradable_item_count) if _is_stone_inventory_split_active() else None
        ),
        next_tradable_at=(
            state.next_tradable_at if _is_stone_inventory_split_active() else None
        ),
    )

    balance_log_text = effective_balance or "保持原值"
    if result.status == "success":
        state.updated_at = write_time
        state.round_purchase_running_seconds = float(runtime_seconds)
        if reached_time is not None:
            state.last_limit_time = reached_time
        logger.info(
            "[账号数据] 实时库存同步完成：昵称=%s 道具库存=%s 余额=%s 累计抢购秒数=%s 运行窗口起点=%s",
            nickname,
            runtime_item_quantity,
            balance_log_text,
            runtime_seconds,
            state.runtime_window_start_time.strftime("%Y-%m-%d %H:%M:%S")
            if state.runtime_window_start_time is not None
            else "无",
            extra={"show_console": False},
        )
    elif result.status != "skipped":
        logger.warning("[账号数据] 实时库存同步失败：昵称=%s 原因=%s", nickname, result.reason)

    return result


def persist_item_balance_and_schedule_snapshot(event_name):
    """写入最新余额/库存后，补触发一次最小快照。"""
    result = persist_minimal_item_balance_sync()
    if result.status in ("success", "skipped"):
        _schedule_remote_snapshot_event(event_name)
    return result


def persist_startup_listing_mode_account_snapshot(
    round_status,
    update_last_limit_time=False,
    last_limit_time=None,
    preserve_existing_status=False,
):
    """启动页上架模式专用：写回当前账号的上架轮次结果。"""
    if state.temporary_purchase_mode:
        return AccountWriteResult("skipped", "临时模式不写入 canonical SQLite")

    target = _resolve_current_canonical_target()
    nickname = str(target.get("nickname") or "").strip()
    database_path = str(target.get("database_path") or "").strip()
    table_name = target.get("table_name") or CANONICAL_ACCOUNT_STATS_TABLE
    if state.account_read_status == "account_not_found" or not state.account_record_loaded or not nickname:
        return AccountWriteResult("skipped", f"当前账号未加载 SQLite 记录: {nickname}")
    if not database_path:
        return AccountWriteResult("db_unavailable", "canonical database path is empty")

    existing_record = target.get("record") or read_canonical_account_stats_record(database_path, nickname, table_name)
    if existing_record is None:
        return AccountWriteResult("account_not_found", f"sqlite record not found for nickname: {nickname}")

    if preserve_existing_status:
        normalized_status = str(existing_record.round_status or "").strip() or ROUND_STATUS_READY
    else:
        normalized_status = _normalize_round_status(round_status, True)
    write_time = datetime.now()
    normalized_limit_time = existing_record.last_limit_time
    if update_last_limit_time:
        normalized_limit_time = last_limit_time or write_time

    mature_stone_unlocks_for_current_account("启动页上架收尾前")
    effective_balance = _get_effective_balance()
    record = AccountStatsRecord(
        nickname=existing_record.nickname,
        baseline_item_count=int(state.baseline_item_count),
        locked_item_count=int(getattr(state, "locked_item_count", existing_record.locked_item_count)),
        tradable_item_count=int(getattr(state, "tradable_item_count", existing_record.tradable_item_count)),
        next_tradable_at=getattr(state, "next_tradable_at", existing_record.next_tradable_at),
        last_limit_time=normalized_limit_time,
        last_account_end_time=write_time,
        updated_at=write_time,
        current_execution_slot=existing_record.current_execution_slot or state.current_execution_slot,
        round_purchase_success_count=int(state.round_purchase_success_count),
        round_listing_success_count=int(state.round_listing_success_count),
        round_purchase_fail_count=int(state.round_purchase_fail_count),
        current_balance=effective_balance,
        purchase_running_seconds=int(state.round_purchase_running_seconds),
        runtime_window_start_time=state.runtime_window_start_time,
        round_status=normalized_status,
    )
    result = save_canonical_account_stats_record(database_path, record, table_name)
    if result.status == "success":
        state.round_status = normalized_status
        state.updated_at = write_time
        state.last_limit_time = normalized_limit_time
        state.last_account_end_time = write_time
        _schedule_remote_snapshot_event("启动页上架模式账号收尾")
        logger.info(
            "[账号数据] 启动页上架模式写库完成：昵称=%s 状态=%s 上架=%s 余额=%s",
            nickname,
            normalized_status,
            state.round_listing_success_count,
            effective_balance or "保持原值",
        )
    elif result.status != "skipped":
        logger.warning("[账号数据] 启动页上架模式写库失败：昵称=%s 原因=%s", nickname, result.reason)
    return result


def persist_startup_listing_mode_listing_count_clear():
    """启动页上架模式下号成功后，只清当前账号已写库的本轮上架成功数。"""
    if state.temporary_purchase_mode:
        return AccountWriteResult("skipped", "临时模式不写入 canonical SQLite")

    target = _resolve_current_canonical_target()
    nickname = str(target.get("nickname") or "").strip()
    database_path = str(target.get("database_path") or "").strip()
    table_name = target.get("table_name") or CANONICAL_ACCOUNT_STATS_TABLE
    if state.account_read_status == "account_not_found" or not state.account_record_loaded or not nickname:
        return AccountWriteResult("skipped", f"当前账号未加载 SQLite 记录: {nickname}")
    if not database_path:
        return AccountWriteResult("db_unavailable", "canonical database path is empty")

    write_time = datetime.now()
    result = clear_canonical_account_round_listing_success_count(
        database_path,
        nickname,
        table_name=table_name,
        updated_at=write_time,
    )
    if result.status == "success":
        state.updated_at = write_time
        logger.info("[账号数据] 启动页上架模式下号后已清空上架成功写库值：昵称=%s", nickname)
    elif result.status != "skipped":
        logger.warning("[账号数据] 启动页上架模式清空上架成功写库值失败：昵称=%s 原因=%s", nickname, result.reason)
    return result


def _persist_startup_listing_mode_pause_resume_snapshot(event_name):
    """启动页上架模式 F12 专用：只写库存、余额、本轮上架成功数。"""
    if state.temporary_purchase_mode:
        return AccountWriteResult("skipped", "临时模式不写入 canonical SQLite")

    target = _resolve_current_canonical_target()
    nickname = str(target.get("nickname") or "").strip()
    database_path = str(target.get("database_path") or "").strip()
    table_name = target.get("table_name") or CANONICAL_ACCOUNT_STATS_TABLE
    if state.account_read_status == "account_not_found" or not state.account_record_loaded or not nickname:
        return AccountWriteResult("skipped", f"当前账号未加载 SQLite 记录: {nickname}")
    if not database_path:
        return AccountWriteResult("skipped", "canonical database path is empty")

    mature_stone_unlocks_for_current_account(f"{event_name}前")
    effective_balance = _get_effective_balance()
    result = update_canonical_account_listing_pause_fields(
        database_path,
        nickname,
        int(state.baseline_item_count),
        current_balance=effective_balance,
        round_listing_success_count=int(state.round_listing_success_count),
        table_name=table_name,
        locked_item_count=(
            int(state.locked_item_count) if _is_stone_inventory_split_active() else None
        ),
        tradable_item_count=(
            int(state.tradable_item_count) if _is_stone_inventory_split_active() else None
        ),
        next_tradable_at=(
            state.next_tradable_at if _is_stone_inventory_split_active() else None
        ),
    )
    if result.status == "success":
        _schedule_remote_snapshot_event(event_name)
        logger.info(
            "[账号数据] 启动页上架模式 F12 最小写库完成：昵称=%s 上架=%s 余额=%s 库存=%s",
            nickname,
            int(state.round_listing_success_count),
            effective_balance or "保持原值",
            int(state.baseline_item_count),
        )
    elif result.status != "skipped":
        logger.warning("[账号数据] 启动页上架模式 F12 最小写库失败：昵称=%s 原因=%s", nickname, result.reason)
    return result


def persist_pause_snapshot():
    """F12 暂停后只补当前账号最小必要字段，并写入人工暂停状态。"""
    if state.brutal_purchase_mode:
        return AccountWriteResult("skipped", "暴力模式不写入任何持久化数据")
    mature_all_stone_unlocks("F12暂停全账号")
    if state.temporary_purchase_mode:
        return AccountWriteResult("skipped", "临时模式不写入 canonical SQLite")
    if state.startup_listing_mode_active:
        return _persist_startup_listing_mode_pause_resume_snapshot("启动页上架模式F12暂停时")

    target = _resolve_current_canonical_target()
    nickname = str(target.get("nickname") or "").strip()
    database_path = str(target.get("database_path") or "").strip()
    if state.account_read_status == "account_not_found" or not state.account_record_loaded or not nickname:
        return AccountWriteResult("skipped", f"当前账号未加载 SQLite 记录: {nickname}")

    runtime_item_quantity = int(state.baseline_item_count)
    if runtime_item_quantity < 0:
        return AccountWriteResult(
            "invalid_item_quantity",
            f"运行中道具库存为负数: {runtime_item_quantity}",
        )
    if not database_path:
        return AccountWriteResult("skipped", "canonical database path is empty")

    table_name = target.get("table_name") or CANONICAL_ACCOUNT_STATS_TABLE
    mature_stone_unlocks_for_current_account("F12暂停前")
    sync_runtime_window_state(
        persist_if_changed=False,
        initialize_if_missing=False,
        allow_legacy_fallback=False,
    )
    effective_balance = _get_effective_balance()
    runtime_seconds = max(0, int(get_current_elapsed()))
    write_time = datetime.now()
    result = update_canonical_account_status_fields(
        database_path,
        nickname,
        ROUND_STATUS_MANUAL_PAUSE,
        table_name=table_name,
        updated_at=write_time,
        item_quantity=runtime_item_quantity,
        current_balance=effective_balance or None,
        purchase_running_seconds=runtime_seconds,
        runtime_window_start_time=state.runtime_window_start_time,
        round_purchase_success_count=state.round_purchase_success_count,
        round_listing_success_count=state.round_listing_success_count,
        round_purchase_fail_count=state.round_purchase_fail_count,
        locked_item_count=(
            int(state.locked_item_count) if _is_stone_inventory_split_active() else None
        ),
        tradable_item_count=(
            int(state.tradable_item_count) if _is_stone_inventory_split_active() else None
        ),
        next_tradable_at=(
            state.next_tradable_at if _is_stone_inventory_split_active() else None
        ),
    )
    if result.status == "success":
        state.updated_at = write_time
        state.round_purchase_running_seconds = float(runtime_seconds)
        state.round_status = ROUND_STATUS_MANUAL_PAUSE
        _schedule_remote_snapshot_event("F12暂停时")
        logger.info(
            "[账号数据] F12 暂停最小写库完成：昵称=%s 状态=%s 道具库存=%s 余额=%s",
            nickname,
            ROUND_STATUS_MANUAL_PAUSE,
            runtime_item_quantity,
            effective_balance or "保持原值",
        )
    elif result.status != "skipped":
        logger.warning("[账号数据] F12 暂停最小写库失败：昵称=%s 原因=%s", nickname, result.reason)
    return result


def persist_resume_snapshot():
    """F12 恢复后仅在库内当前状态为人工暂停时恢复为运行中。"""
    if state.brutal_purchase_mode:
        return AccountWriteResult("skipped", "暴力模式不写入任何持久化数据")
    if state.temporary_purchase_mode:
        return AccountWriteResult("skipped", "临时模式不写入 canonical SQLite")
    if state.startup_listing_mode_active:
        return _persist_startup_listing_mode_pause_resume_snapshot("启动页上架模式F12恢复时")

    nickname = (state.current_nickname or "").strip()
    if state.account_read_status == "account_not_found" or not state.account_record_loaded or not nickname:
        return AccountWriteResult("skipped", f"当前账号未加载 SQLite 记录: {nickname}")

    target = _resolve_current_canonical_target()
    nickname = str(target.get("nickname") or "").strip()
    database_path = str(target.get("database_path") or "").strip()
    if not database_path:
        return AccountWriteResult("skipped", "canonical database path is empty")

    table_name = target.get("table_name") or CANONICAL_ACCOUNT_STATS_TABLE
    write_time = datetime.now()
    result = update_canonical_account_status_fields(
        database_path,
        nickname,
        ROUND_STATUS_RUNNING,
        table_name=table_name,
        updated_at=write_time,
        expected_current_status=ROUND_STATUS_MANUAL_PAUSE,
    )
    if result.status == "success":
        state.updated_at = write_time
        state.round_status = ROUND_STATUS_RUNNING
        reload_result = _reload_current_account_state_from_canonical()
        if reload_result.status != "success":
            logger.warning("[账号数据] F12 恢复后回灌当前账号数据失败：昵称=%s 原因=%s", nickname, reload_result.reason)
        _schedule_remote_snapshot_event("F12恢复状态变更")
        logger.info("[账号数据] F12 恢复状态写库完成：昵称=%s 状态=%s", nickname, ROUND_STATUS_RUNNING)
    elif result.status == "skipped":
        logger.info("[账号数据] F12 恢复跳过写库：昵称=%s 原因=%s", nickname, result.reason)
    else:
        logger.warning("[账号数据] F12 恢复状态写库失败：昵称=%s 原因=%s", nickname, result.reason)
    return result


def persist_lightweight_round_snapshot():
    round_status = resolve_shutdown_final_status(ROUND_STATUS_RUNNING)
    record, error_result = _build_record(False, round_status)
    if error_result is not None:
        state.account_round_writeback_failed = True
        state.account_round_writeback_error = error_result.reason
        logger.error("[account-data] lightweight write failed: %s", error_result.reason)
        return error_result

    result = _save_record(record)
    if result.status != "success":
        state.account_round_writeback_failed = True
        state.account_round_writeback_error = result.reason
        logger.error("[account-data] lightweight write failed: %s", result.reason)
        return result

    state.account_round_writeback_failed = False
    state.account_round_writeback_error = ""
    print(
        "[account-data] lightweight write ok: "
        f"nickname={state.current_nickname}, inventory={result.new_baseline_item_count}, "
        f"running_seconds={record.purchase_running_seconds}"
    )
    logger.info(
        "[account-data] lightweight write ok: nickname=%s inventory=%s running_seconds=%s",
        state.current_nickname,
        result.new_baseline_item_count,
        record.purchase_running_seconds,
    )
    return result


def persist_final_round_snapshot(default_status):
    if state.account_round_finalized:
        return AccountWriteResult("success", "already finalized")

    round_status = resolve_shutdown_final_status(default_status)
    record, error_result = _build_record(True, round_status)
    if error_result is not None:
        state.account_round_writeback_failed = True
        state.account_round_writeback_error = error_result.reason
        logger.error("[account-data] final write failed: %s", error_result.reason)
        return error_result

    result = _save_record(record)
    if result.status != "success":
        state.account_round_writeback_failed = True
        state.account_round_writeback_error = result.reason
        logger.error("[account-data] final write failed: %s", result.reason)
        return result

    state.account_round_finalized = True
    state.account_round_writeback_failed = False
    state.account_round_writeback_error = ""
    if _is_forced_limit_status(record.round_status):
        _clear_round_counters()
        state.round_purchase_running_seconds = 0.0
    _schedule_remote_snapshot_event("脚本正常收尾/退出时", synchronous=True)
    print(
        "[account-data] final write ok: "
        f"nickname={state.current_nickname}, status={record.round_status}, "
        f"inventory={result.new_baseline_item_count}"
    )
    logger.info(
        "[account-data] final write ok: nickname=%s status=%s inventory=%s",
        state.current_nickname,
        record.round_status,
        result.new_baseline_item_count,
    )
    return result


def persist_accessory_round_status_snapshot(default_status):
    """饰品抢购模式复用正常轮次收尾字段，目标库由 state.account_db_path 隔离。"""
    if state.account_round_finalized:
        return AccountWriteResult("success", "already finalized")

    round_status = resolve_shutdown_final_status(default_status)
    record, error_result = _build_record(True, round_status)
    if error_result is not None:
        state.account_round_writeback_failed = True
        state.account_round_writeback_error = error_result.reason
        logger.error("[饰品抢购] 最终写库失败：%s", error_result.reason)
        return error_result

    result = _save_record(record)
    if result.status != "success":
        state.account_round_writeback_failed = True
        state.account_round_writeback_error = result.reason
        logger.error("[饰品抢购] 最终写库失败：%s", result.reason)
        return result

    state.account_round_finalized = True
    state.account_round_writeback_failed = False
    state.account_round_writeback_error = ""
    if _is_forced_limit_status(record.round_status):
        _clear_round_counters()
        state.round_purchase_running_seconds = 0.0
    _schedule_remote_snapshot_event("饰品抢购收尾", synchronous=True)
    logger.info(
        "[饰品抢购] 最终写库完成：昵称=%s 状态=%s 饰品库存=%s",
        state.current_nickname,
        record.round_status,
        result.new_baseline_item_count,
    )
    return result
