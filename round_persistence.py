"""Account round settlement and canonical SQLite write-back."""
from datetime import datetime
import time

import state
from account_db import (
    AccountStatsRecord,
    AccountWriteResult,
    ROUND_STATUS_BALANCE_LOW,
    ROUND_STATUS_LIMITED,
    ROUND_STATUS_MANUAL_END,
    ROUND_STATUS_NORMAL_END,
    ROUND_STATUS_RUNNING,
    ROUND_STATUS_UNKNOWN,
    compute_new_baseline_item_count,
    save_canonical_account_stats_record,
)
from config import ACCOUNT_MAX_PURCHASE_SECONDS
from utils import get_current_elapsed, logger


PLACEHOLDER_BALANCE = "\u83b7\u53d6\u4e2d"
STATUS_NORMAL_SWITCH = "\u5f53\u524d\u8d26\u53f7\u6b63\u5e38\u5b8c\u6210\u5e76\u5207\u5230\u4e0b\u4e00\u4e2a\u8d26\u53f7"


def reset_round_runtime_state(reason):
    """Reset per-round runtime stats after mandatory pre-listing."""
    state.success_count = 0
    state.fail_count = 0
    state.total_listed_count = 0
    state.round_purchase_success_count = 0
    state.round_listing_success_count = 0
    state.round_purchase_fail_count = 0
    state.round_current_balance = ""
    state.round_purchase_running_seconds = 0.0
    state.round_status = ROUND_STATUS_RUNNING
    state.total_running_time = 0.0
    state.last_resume_time = None
    state.purchase_timer_active = False
    state.account_round_end_status = ""
    state.account_round_finalized = False
    state.account_round_writeback_failed = False
    state.account_round_writeback_error = ""
    state.account_limit_reached_at = None
    print(f"[round-settlement] {reason}, round counters reset.")
    logger.info("[round-settlement] %s, round counters reset.", reason)


def resolve_shutdown_final_status(default_status):
    if state.account_round_end_status:
        return state.account_round_end_status
    return default_status


def refresh_account_limit_reached_at():
    """Record the exact wall-clock moment when purchase runtime reaches 2h50m."""
    if state.account_limit_reached_at is not None:
        return state.account_limit_reached_at

    threshold_seconds = ACCOUNT_MAX_PURCHASE_SECONDS
    if state.purchase_timer_active and not state.IS_PAUSED and state.last_resume_time is not None:
        remaining_before_limit = threshold_seconds - state.total_running_time
        if remaining_before_limit <= 0:
            reached_ts = state.last_resume_time
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
    if normalized == "\u624b\u52a8\u7ed3\u675f":
        return ROUND_STATUS_MANUAL_END
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

    refresh_account_limit_reached_at()
    state.round_purchase_running_seconds = float(get_current_elapsed())
    new_baseline_item_count = compute_new_baseline_item_count(
        state.baseline_item_count,
        state.round_purchase_success_count,
        state.round_listing_success_count,
    )
    if new_baseline_item_count < 0:
        return None, AccountWriteResult(
            "invalid_baseline",
            f"new baseline count is negative: {new_baseline_item_count}",
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
    state.round_status = record.round_status
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
        f"nickname={state.current_nickname}, baseline={result.new_baseline_item_count}, "
        f"running_seconds={record.purchase_running_seconds}"
    )
    logger.info(
        "[account-data] lightweight write ok: nickname=%s baseline=%s running_seconds=%s",
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
        f"baseline={result.new_baseline_item_count}"
    )
    logger.info(
        "[account-data] final write ok: nickname=%s status=%s baseline=%s",
        state.current_nickname,
        record.round_status,
        result.new_baseline_item_count,
    )
    return result
