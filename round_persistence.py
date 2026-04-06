"""Account round settlement and canonical SQLite write-back."""
from datetime import datetime, timedelta
import time

import state
from account_db import (
    AccountStatsRecord,
    AccountWriteResult,
    CANONICAL_ACCOUNT_STATS_TABLE,
    ROUND_STATUS_BALANCE_LOW,
    ROUND_STATUS_LIMITED,
    ROUND_STATUS_MANUAL_PAUSE,
    ROUND_STATUS_NORMAL_END,
    ROUND_STATUS_RUNTIME_REACHED,
    ROUND_STATUS_RUNNING,
    ROUND_STATUS_UNKNOWN,
    read_canonical_account_stats_record,
    save_canonical_account_stats_record,
    update_canonical_account_status_fields,
    update_canonical_account_runtime_fields,
    update_canonical_account_item_balance_fields,
)
from config import ACCOUNT_LIMIT_COOLDOWN_SECONDS, ACCOUNT_MAX_PURCHASE_SECONDS
from utils import get_current_elapsed, logger


PLACEHOLDER_BALANCE = "\u83b7\u53d6\u4e2d"
STATUS_NORMAL_SWITCH = "\u5f53\u524d\u8d26\u53f7\u6b63\u5e38\u5b8c\u6210\u5e76\u5207\u5230\u4e0b\u4e00\u4e2a\u8d26\u53f7"


def reset_round_runtime_state(reason, reset_purchase_runtime=True):
    """Reset per-round runtime stats after mandatory pre-listing."""
    state.success_count = 0
    state.fail_count = 0
    state.total_listed_count = 0
    state.round_purchase_success_count = 0
    state.round_listing_success_count = 0
    state.round_purchase_fail_count = 0
    state.round_current_balance = ""
    state.listing_scan_miss_count = 0
    state.listing_periodic_disabled = False
    state.listing_periodic_disabled_reason = ""
    state.listing_periodic_skip_logged = False
    state.round_status = ROUND_STATUS_RUNNING
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
    nickname = (state.current_nickname or "").strip()
    database_path = str(state.account_db_path or "").strip()
    table_name = state.account_db_table_name or CANONICAL_ACCOUNT_STATS_TABLE
    if not nickname or not database_path:
        return AccountWriteResult("skipped", "current account context is incomplete")

    record = read_canonical_account_stats_record(database_path, nickname, table_name)
    if record is None:
        return AccountWriteResult("account_not_found", f"sqlite record not found for nickname: {nickname}")

    state.current_nickname = record.nickname
    state.baseline_item_count = int(record.baseline_item_count)
    state.last_limit_time = record.last_limit_time
    state.last_account_end_time = record.last_account_end_time
    state.updated_at = record.updated_at
    if record.current_execution_slot is not None:
        state.current_execution_slot = record.current_execution_slot
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
    """\u540c\u6b65 24 \u5c0f\u65f6 05 \u5206\u8fd0\u884c\u7a97\u53e3\u72b6\u6001\u3002"""
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
            f"24\u5c0f\u65f605\u5206\u8fd0\u884c\u7a97\u53e3\u5df2\u6eda\u52a8\u5230 {new_window_start.strftime('%Y-%m-%d %H:%M:%S')}"
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
    """\u5728\u8fbe\u5230 2 \u5c0f\u65f6 50 \u5206\u9608\u503c\u65f6\u7acb\u5373\u843d\u5e93 last_limit_time\u3002"""
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
    """Record the exact wall-clock moment when purchase runtime reaches 2h50m."""
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
    if normalized in ("\u624b\u52a8\u7ed3\u675f", "\u4eba\u5de5\u6682\u505c"):
        return ROUND_STATUS_MANUAL_PAUSE
    if normalized == "\u672a\u77e5\u5f02\u5e38":
        return ROUND_STATUS_UNKNOWN
    if normalized == STATUS_NORMAL_SWITCH:
        return ROUND_STATUS_NORMAL_END
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
    record = AccountStatsRecord(
        nickname=nickname,
        baseline_item_count=new_baseline_item_count,
        last_limit_time=last_limit_time,
        last_account_end_time=last_account_end_time,
        updated_at=updated_at,
        current_execution_slot=state.current_execution_slot,
        round_purchase_success_count=int(state.round_purchase_success_count),
        round_listing_success_count=int(state.round_listing_success_count),
        round_purchase_fail_count=int(state.round_purchase_fail_count),
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
    )

    balance_log_text = effective_balance or "保持原值"
    if result.status == "success":
        state.updated_at = write_time
        state.round_purchase_running_seconds = float(runtime_seconds)
        if reached_time is not None:
            state.last_limit_time = reached_time
        print(
            "[账号数据] 实时库存同步完成："
            f"昵称={nickname}，道具库存={runtime_item_quantity}，"
            f"余额={balance_log_text}，累计抢购秒数={runtime_seconds}"
        )
        logger.info(
            "[账号数据] 实时库存同步完成：昵称=%s 道具库存=%s 余额=%s 累计抢购秒数=%s 运行窗口起点=%s",
            nickname,
            runtime_item_quantity,
            balance_log_text,
            runtime_seconds,
            state.runtime_window_start_time.strftime("%Y-%m-%d %H:%M:%S")
            if state.runtime_window_start_time is not None
            else "无",
        )
    elif result.status != "skipped":
        logger.warning("[账号数据] 实时库存同步失败：昵称=%s 原因=%s", nickname, result.reason)

    return result


def persist_pause_snapshot():
    """F12 暂停后只补当前账号最小必要字段，并写入人工暂停状态。"""
    if state.temporary_purchase_mode:
        return AccountWriteResult("skipped", "临时模式不写入 canonical SQLite")

    nickname = (state.current_nickname or "").strip()
    if state.account_read_status == "account_not_found" or not state.account_record_loaded or not nickname:
        return AccountWriteResult("skipped", f"当前账号未加载 SQLite 记录: {nickname}")

    runtime_item_quantity = int(state.baseline_item_count)
    if runtime_item_quantity < 0:
        return AccountWriteResult(
            "invalid_item_quantity",
            f"运行中道具库存为负数: {runtime_item_quantity}",
        )

    table_name = state.account_db_table_name or CANONICAL_ACCOUNT_STATS_TABLE
    sync_runtime_window_state(
        persist_if_changed=False,
        initialize_if_missing=False,
        allow_legacy_fallback=False,
    )
    effective_balance = _get_effective_balance()
    write_time = datetime.now()
    result = update_canonical_account_status_fields(
        state.account_db_path,
        nickname,
        ROUND_STATUS_MANUAL_PAUSE,
        table_name=table_name,
        updated_at=write_time,
        item_quantity=runtime_item_quantity,
        current_balance=effective_balance or None,
    )
    if result.status == "success":
        state.updated_at = write_time
        state.round_purchase_running_seconds = float(max(0, int(get_current_elapsed())))
        state.round_status = ROUND_STATUS_MANUAL_PAUSE
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
    if state.temporary_purchase_mode:
        return AccountWriteResult("skipped", "临时模式不写入 canonical SQLite")

    nickname = (state.current_nickname or "").strip()
    if state.account_read_status == "account_not_found" or not state.account_record_loaded or not nickname:
        return AccountWriteResult("skipped", f"当前账号未加载 SQLite 记录: {nickname}")

    table_name = state.account_db_table_name or CANONICAL_ACCOUNT_STATS_TABLE
    write_time = datetime.now()
    result = update_canonical_account_status_fields(
        state.account_db_path,
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
