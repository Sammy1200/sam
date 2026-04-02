"""SQLite 数据查看层最小只读查询接口。"""
from __future__ import annotations

from datetime import datetime, timedelta
import os
import sqlite3

from account_db import (
    CANONICAL_ACCOUNT_STATS_COLUMNS,
    CANONICAL_ACCOUNT_STATS_TABLE,
    find_canonical_account_stats_store,
    read_runtime_execution_state,
)
from config import ACCOUNT_LIMIT_COOLDOWN_SECONDS, EXECUTION_SLOT_COUNT, THREAD6_RUNTIME_DB_PATH


CANONICAL_SOURCE_TYPE = "canonical_account_stats"
RUNTIME_SOURCE_TYPE = "runtime_snapshot_auxiliary"
CRITICAL_VIEW_FIELDS = (
    "nickname",
    "current_execution_slot",
    "updated_at",
    "round_status",
)


def _quote_identifier(name):
    return '"' + str(name).replace('"', '""') + '"'


def _parse_datetime(raw_value):
    if raw_value in (None, ""):
        return None

    if isinstance(raw_value, datetime):
        return raw_value

    if isinstance(raw_value, (int, float)):
        timestamp = float(raw_value)
        if timestamp > 10**12:
            timestamp /= 1000.0
        return datetime.fromtimestamp(timestamp)

    text = str(raw_value).strip()
    if not text:
        return None

    if text.isdigit():
        timestamp = float(text)
        if timestamp > 10**12:
            timestamp /= 1000.0
        return datetime.fromtimestamp(timestamp)

    normalized = text.replace("T", " ").replace("Z", "")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
    ):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue

    return None


def _parse_int(raw_value):
    if raw_value in (None, ""):
        return 0
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        return int(raw_value)

    text = "".join(ch for ch in str(raw_value) if ch.isdigit() or ch == "-")
    if not text:
        return 0
    return int(text)


def _serialize_datetime(value):
    if value is None:
        return None
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _build_cooldown_fields(last_limit_time, now):
    if last_limit_time is None:
        return {
            "allow_start_time": None,
            "allow_purchase": True,
            "cooldown_remaining_seconds": 0,
        }

    allow_start_time = last_limit_time + timedelta(seconds=ACCOUNT_LIMIT_COOLDOWN_SECONDS)
    cooldown_remaining_seconds = max(int((allow_start_time - now).total_seconds()), 0)
    return {
        "allow_start_time": _serialize_datetime(allow_start_time),
        "allow_purchase": cooldown_remaining_seconds == 0,
        "cooldown_remaining_seconds": cooldown_remaining_seconds,
    }


def _is_missing_value(value):
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def _collect_missing_fields(record):
    missing_fields = []
    for field_name in CRITICAL_VIEW_FIELDS:
        if _is_missing_value(record.get(field_name)):
            missing_fields.append(field_name)
    return missing_fields


def _build_record_health(record):
    missing_fields = _collect_missing_fields(record)
    return {
        "has_missing_critical_fields": bool(missing_fields),
        "missing_critical_fields": missing_fields,
    }


def _build_duplicate_slot_health(rows):
    slot_map = {}
    for row in rows:
        slot_value = row.get("current_execution_slot")
        if slot_value is None:
            continue
        slot_map.setdefault(slot_value, []).append(str(row.get("nickname") or "").strip())

    duplicate_items = []
    for slot_value in sorted(slot_map):
        nicknames = [nickname for nickname in slot_map[slot_value] if nickname]
        if len(nicknames) > 1:
            duplicate_items.append(
                {
                    "execution_slot": slot_value,
                    "nicknames": nicknames,
                }
            )

    return {
        "has_duplicate_execution_slots": bool(duplicate_items),
        "duplicate_execution_slots": duplicate_items,
    }


def _build_expected_slot_health(rows):
    present_slots = sorted(
        {
            row.get("current_execution_slot")
            for row in rows
            if row.get("current_execution_slot") is not None
        }
    )
    expected_slots = list(range(1, int(EXECUTION_SLOT_COUNT) + 1))
    missing_slots = [slot for slot in expected_slots if slot not in present_slots]
    return {
        "expected_execution_slots": expected_slots,
        "present_execution_slots": present_slots,
        "has_missing_execution_slots": bool(missing_slots),
        "missing_execution_slots": missing_slots,
    }


def _build_missing_field_health(rows):
    issues = []
    for row in rows:
        missing_fields = _collect_missing_fields(row)
        if not missing_fields:
            continue
        issues.append(
            {
                "nickname": row.get("nickname"),
                "current_execution_slot": row.get("current_execution_slot"),
                "missing_fields": missing_fields,
            }
        )
    return {
        "has_missing_critical_fields": bool(issues),
        "missing_critical_field_records": issues,
    }


def _find_runtime_match(rows, runtime_snapshot):
    snapshot = runtime_snapshot.get("snapshot") or {}
    runtime_slot = snapshot.get("current_execution_slot")
    runtime_nickname = str(snapshot.get("current_nickname") or "").strip()

    if runtime_nickname:
        for row in rows:
            if str(row.get("nickname") or "").strip() == runtime_nickname:
                return row

    if runtime_slot is not None:
        for row in rows:
            if row.get("current_execution_slot") == runtime_slot:
                return row

    return None


def _build_runtime_consistency_health(runtime_snapshot, canonical_record):
    snapshot = runtime_snapshot.get("snapshot") or {}
    runtime_updated_at = _parse_datetime(snapshot.get("updated_at"))
    canonical_updated_at = None
    if canonical_record is not None:
        canonical_updated_at = _parse_datetime(canonical_record.get("updated_at"))

    lag_seconds = None
    runtime_is_stale = False
    if runtime_updated_at is not None and canonical_updated_at is not None:
        lag_seconds = int((canonical_updated_at - runtime_updated_at).total_seconds())
        runtime_is_stale = lag_seconds > 0

    mismatch_fields = []
    if canonical_record is not None:
        runtime_slot = snapshot.get("current_execution_slot")
        canonical_slot = canonical_record.get("current_execution_slot")
        if runtime_slot is not None and canonical_slot is not None and runtime_slot != canonical_slot:
            mismatch_fields.append("current_execution_slot")

        runtime_nickname = str(snapshot.get("current_nickname") or "").strip()
        canonical_nickname = str(canonical_record.get("nickname") or "").strip()
        if runtime_nickname and canonical_nickname and runtime_nickname != canonical_nickname:
            mismatch_fields.append("current_nickname")

    return {
        "runtime_snapshot_exists": bool(runtime_snapshot.get("database_exists")),
        "runtime_record_updated_at": snapshot.get("updated_at"),
        "canonical_record_updated_at": canonical_record.get("updated_at") if canonical_record else None,
        "runtime_lag_seconds": lag_seconds,
        "runtime_is_stale": runtime_is_stale,
        "runtime_matches_canonical": canonical_record is not None and not mismatch_fields,
        "runtime_mismatch_fields": mismatch_fields,
    }


def _build_runtime_snapshot_health(rows, runtime_snapshot):
    matched_record = _find_runtime_match(rows, runtime_snapshot)
    runtime_consistency = _build_runtime_consistency_health(runtime_snapshot, matched_record)
    return {
        "runtime_snapshot_exists": runtime_consistency["runtime_snapshot_exists"],
        "runtime_matched_canonical_record": matched_record is not None,
        "runtime_matched_nickname": matched_record.get("nickname") if matched_record else None,
        "runtime_matched_execution_slot": (
            matched_record.get("current_execution_slot") if matched_record else None
        ),
        "runtime_consistency": runtime_consistency,
    }


def _row_to_view_record(row, now):
    last_limit_time = _parse_datetime(row["last_limit_time"])
    last_account_end_time = _parse_datetime(row["last_account_end_time"])
    updated_at = _parse_datetime(row["updated_at"])

    record = {
        "nickname": str(row["nickname"] or "").strip(),
        "baseline_item_count": _parse_int(row["baseline_item_count"]),
        "last_limit_time": _serialize_datetime(last_limit_time),
        "last_account_end_time": _serialize_datetime(last_account_end_time),
        "updated_at": _serialize_datetime(updated_at),
        "current_execution_slot": (
            _parse_int(row["current_execution_slot"])
            if row["current_execution_slot"] not in (None, "")
            else None
        ),
        "round_purchase_success_count": _parse_int(row["round_purchase_success_count"]),
        "round_listing_success_count": _parse_int(row["round_listing_success_count"]),
        "round_purchase_fail_count": _parse_int(row["round_purchase_fail_count"]),
        "current_balance": str(row["current_balance"] or "").strip(),
        "purchase_running_seconds": _parse_int(row["purchase_running_seconds"]),
        "round_status": str(row["round_status"] or "").strip(),
    }
    record.update(_build_cooldown_fields(last_limit_time, now))
    return record


def _build_canonical_result(database_path, table_name, rows, generated_at):
    return {
        "source_type": CANONICAL_SOURCE_TYPE,
        "database_path": database_path,
        "table_name": table_name,
        "generated_at": _serialize_datetime(generated_at),
        "rows": rows,
    }


def get_account_view_rows():
    """读取 canonical 账号视图列表，并补出冷却派生字段。"""
    database_path, table_name = find_canonical_account_stats_store()
    generated_at = datetime.now()
    if not database_path or not os.path.isfile(database_path):
        result = _build_canonical_result("", table_name, [], generated_at)
        empty_runtime_snapshot = get_runtime_snapshot()
        result["health"] = {
            **_build_duplicate_slot_health([]),
            **_build_expected_slot_health([]),
            **_build_missing_field_health([]),
            **_build_runtime_snapshot_health([], empty_runtime_snapshot),
        }
        return result

    conn = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        order_by_sql = (
            f"CASE WHEN {_quote_identifier('current_execution_slot')} IS NULL THEN 1 ELSE 0 END, "
            f"{_quote_identifier('current_execution_slot')}, "
            f"{_quote_identifier('nickname')}"
        )
        rows = conn.execute(
            f"SELECT {', '.join(_quote_identifier(name) for name in CANONICAL_ACCOUNT_STATS_COLUMNS)} "
            f"FROM {_quote_identifier(table_name or CANONICAL_ACCOUNT_STATS_TABLE)} "
            f"ORDER BY {order_by_sql}"
        ).fetchall()
        view_rows = [_row_to_view_record(row, generated_at) for row in rows]
        result = _build_canonical_result(database_path, table_name, view_rows, generated_at)
        runtime_snapshot = get_runtime_snapshot()
        result["health"] = {
            **_build_duplicate_slot_health(view_rows),
            **_build_expected_slot_health(view_rows),
            **_build_missing_field_health(view_rows),
            **_build_runtime_snapshot_health(view_rows, runtime_snapshot),
        }
        return result
    finally:
        conn.close()


def get_account_view_detail(nickname=None, execution_slot=None):
    """按昵称或执行位读取单条 canonical 账号视图。"""
    database_path, table_name = find_canonical_account_stats_store()
    generated_at = datetime.now()
    result = {
        "source_type": CANONICAL_SOURCE_TYPE,
        "database_path": database_path or "",
        "table_name": table_name,
        "generated_at": _serialize_datetime(generated_at),
        "lookup": {
            "nickname": (nickname or "").strip() or None,
            "execution_slot": execution_slot,
        },
        "record": None,
        "health": {
            "has_missing_critical_fields": False,
            "missing_critical_fields": [],
            "runtime_consistency": _build_runtime_consistency_health(get_runtime_snapshot(), None),
        },
    }
    if not database_path or not os.path.isfile(database_path):
        return result

    normalized_nickname = (nickname or "").strip()
    try:
        slot_value = int(execution_slot) if execution_slot is not None else None
    except (TypeError, ValueError):
        slot_value = None

    conn = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        base_sql = (
            f"SELECT {', '.join(_quote_identifier(name) for name in CANONICAL_ACCOUNT_STATS_COLUMNS)} "
            f"FROM {_quote_identifier(table_name or CANONICAL_ACCOUNT_STATS_TABLE)} "
        )
        row = None
        if normalized_nickname:
            row = conn.execute(
                base_sql
                + f"WHERE {_quote_identifier('nickname')} = ? "
                "LIMIT 1",
                (normalized_nickname,),
            ).fetchone()
        if row is None and slot_value is not None:
            row = conn.execute(
                base_sql
                + f"WHERE {_quote_identifier('current_execution_slot')} = ? "
                "LIMIT 1",
                (slot_value,),
            ).fetchone()
        if row is not None:
            record = _row_to_view_record(row, generated_at)
            result["record"] = record
            result["health"] = {
                **_build_record_health(record),
                "runtime_consistency": _build_runtime_consistency_health(
                    get_runtime_snapshot(),
                    record,
                ),
            }
        return result
    finally:
        conn.close()


def get_runtime_snapshot():
    """读取 runtime 辅助快照，不与 canonical 账号数据混用。"""
    snapshot = read_runtime_execution_state()
    generated_at = datetime.now()
    runtime_db_exists = bool(THREAD6_RUNTIME_DB_PATH and os.path.isfile(THREAD6_RUNTIME_DB_PATH))
    result = {
        "source_type": RUNTIME_SOURCE_TYPE,
        "is_auxiliary_snapshot": True,
        "database_path": THREAD6_RUNTIME_DB_PATH,
        "database_exists": runtime_db_exists,
        "generated_at": _serialize_datetime(generated_at),
        "snapshot": {
            "current_execution_slot": snapshot.current_execution_slot,
            "current_nickname": str(snapshot.current_nickname or "").strip(),
            "current_account_index": snapshot.current_account_index,
            "current_server_index": snapshot.current_server_index,
            "slot_nicknames": snapshot.slot_nicknames or {},
            "updated_at": _serialize_datetime(snapshot.updated_at),
        },
    }
    result["health"] = _build_runtime_consistency_health(result, None)
    return result
