"""SQLite 数据查看层最小只读查询接口。"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import os
import sqlite3
import subprocess

from account_db import (
    AccountStatsRecord,
    CANONICAL_ACCOUNT_STATS_COLUMNS,
    CANONICAL_ACCOUNT_STATS_TABLE,
    ROUND_STATUS_VALUES,
    compute_item_quantity,
    find_canonical_account_stats_store,
    read_canonical_account_stats_record,
    read_runtime_execution_state,
    save_canonical_account_stats_record,
)
from config import (
    ACCOUNT_LIMIT_COOLDOWN_SECONDS,
    ACCOUNT_STATS_DB_PATH,
    EXECUTION_SLOT_COUNT,
    THREAD6_RUNTIME_DB_PATH,
)


CANONICAL_SOURCE_TYPE = "canonical_account_stats"
RUNTIME_SOURCE_TYPE = "runtime_snapshot_auxiliary"
BALANCE_INPUT_UNIT = "万"
BALANCE_STORAGE_SUFFIX = "万"
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


def _normalize_decimal_text(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if "." not in text:
        return text
    text = text.rstrip("0").rstrip(".")
    return text or "0"


def _extract_balance_number(raw_value):
    text = str(raw_value or "").strip()
    if not text:
        return ""
    return "".join(ch for ch in text if ch.isdigit() or ch == ".")


def _format_balance_for_wan_input(raw_balance):
    text = str(raw_balance or "").strip()
    if not text:
        return ""

    numeric_text = _extract_balance_number(text)
    if not numeric_text:
        return ""

    try:
        amount = Decimal(numeric_text)
    except InvalidOperation:
        return ""

    if "亿" in text:
        wan_value = amount * Decimal("10000")
    elif "万" in text:
        wan_value = amount
    else:
        wan_value = amount / Decimal("10000")
    return _normalize_decimal_text(wan_value)


def _normalize_balance_wan_input(balance_wan_text):
    text = str(balance_wan_text or "").strip()
    if not text:
        raise ValueError("余额不能为空")
    if text.endswith(BALANCE_INPUT_UNIT):
        text = text[:-1].strip()
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("余额必须是数字，单位为万") from exc
    if value < 0:
        raise ValueError("余额不能为负数")
    return _normalize_decimal_text(value), f"{_normalize_decimal_text(value)}{BALANCE_STORAGE_SUFFIX}"


def _parse_integer_input(raw_text, field_label):
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError(f"{field_label}不能为空")

    sign = ""
    digits = text
    if text[0] in "+-":
        sign = text[0]
        digits = text[1:].strip()

    if not digits or not digits.isdigit():
        raise ValueError(f"{field_label}必须是整数")
    return int(f"{sign}{digits}" if sign else digits)


def _parse_baseline_item_delta_input(baseline_item_delta_text):
    return _parse_integer_input(baseline_item_delta_text, "基数增减")


def _parse_baseline_item_count_input(baseline_item_count_text):
    value = _parse_integer_input(baseline_item_count_text, "道具基数")
    if value < 0:
        raise ValueError("道具基数不能为负数")
    return value


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


def _build_execution_slot_summary(health):
    expected_slots = list(health.get("expected_execution_slots") or [])
    present_slots = list(health.get("present_execution_slots") or [])
    missing_slots = list(health.get("missing_execution_slots") or [])
    return {
        "expected_execution_slots": expected_slots,
        "expected_execution_slot_count": len(expected_slots),
        "present_execution_slots": present_slots,
        "present_execution_slot_count": len(present_slots),
        "missing_execution_slots": missing_slots,
        "missing_execution_slot_count": len(missing_slots),
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


def _build_source_summary(database_path, table_name, runtime_snapshot):
    runtime_snapshot = runtime_snapshot or {}
    return {
        "canonical_source_type": CANONICAL_SOURCE_TYPE,
        "canonical_is_primary": True,
        "canonical_database_path": database_path or "",
        "canonical_table_name": table_name,
        "runtime_source_type": RUNTIME_SOURCE_TYPE,
        "runtime_is_auxiliary_snapshot": True,
        "runtime_database_path": runtime_snapshot.get("database_path") or "",
        "runtime_database_exists": bool(runtime_snapshot.get("database_exists")),
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
    record["item_quantity"] = compute_item_quantity(
        record["baseline_item_count"],
        record["round_purchase_success_count"],
        record["round_listing_success_count"],
    )
    record["current_balance_wan"] = _format_balance_for_wan_input(record["current_balance"])
    record.update(_build_cooldown_fields(last_limit_time, now))
    return record


def _build_edit_meta(record=None):
    record = record or {}
    return {
        "editable_fields": (
            "baseline_item_delta",
            "baseline_item_count",
            "round_status",
            "current_balance_wan",
        ),
        "status_options": list(ROUND_STATUS_VALUES),
        "balance_input_unit": BALANCE_INPUT_UNIT,
        "column_mapping": {
            "baseline_item_delta": "baseline_item_count",
            "baseline_item_count": "baseline_item_count",
            "round_status": "round_status",
            "current_balance_wan": "current_balance",
        },
        "form_defaults": {
            "baseline_item_delta": "",
            "baseline_item_count": str(record.get("baseline_item_count") or 0),
            "round_status": str(record.get("round_status") or ""),
            "current_balance_wan": str(record.get("current_balance_wan") or ""),
        },
    }


def _sqlite_table_exists(database_path, table_name):
    if not database_path or not os.path.isfile(database_path):
        return False

    try:
        conn = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False

    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
            (table_name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _iter_git_worktree_roots():
    current_root = os.path.dirname(os.path.abspath(__file__))
    try:
        completed = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=current_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError):
        return []

    if completed.returncode != 0:
        return []

    roots = []
    seen = set()
    for line in completed.stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        worktree_root = os.path.abspath(line[len("worktree ") :].strip())
        if not worktree_root or worktree_root in seen:
            continue
        seen.add(worktree_root)
        roots.append(worktree_root)
    return roots


def _resolve_account_view_canonical_store(table_name=CANONICAL_ACCOUNT_STATS_TABLE):
    database_path, resolved_table_name = find_canonical_account_stats_store(table_name)
    expected_database_path = os.path.abspath(ACCOUNT_STATS_DB_PATH)
    current_root = os.path.dirname(os.path.abspath(__file__))

    if database_path and os.path.isfile(database_path):
        return {
            "database_path": database_path,
            "table_name": resolved_table_name,
            "expected_database_path": expected_database_path,
            "resolution_type": "current_search",
            "resolved_from_root": current_root,
            "using_fallback": False,
        }

    database_name = os.path.basename(expected_database_path)
    for worktree_root in _iter_git_worktree_roots():
        candidate_path = os.path.join(worktree_root, database_name)
        if os.path.normcase(candidate_path) == os.path.normcase(expected_database_path):
            continue
        if not _sqlite_table_exists(candidate_path, resolved_table_name):
            continue
        return {
            "database_path": candidate_path,
            "table_name": resolved_table_name,
            "expected_database_path": expected_database_path,
            "resolution_type": "git_worktree_fallback",
            "resolved_from_root": worktree_root,
            "using_fallback": True,
        }

    return {
        "database_path": "",
        "table_name": resolved_table_name,
        "expected_database_path": expected_database_path,
        "resolution_type": "not_found",
        "resolved_from_root": "",
        "using_fallback": False,
    }


def _count_canonical_records(database_path, table_name):
    if not database_path or not os.path.isfile(database_path):
        return 0

    conn = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            f"SELECT COUNT(*) FROM {_quote_identifier(table_name or CANONICAL_ACCOUNT_STATS_TABLE)}"
        ).fetchone()
        return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _build_source_diagnostics(resolved_source, real_record_count):
    resolution_type = resolved_source.get("resolution_type")
    if resolution_type == "git_worktree_fallback":
        resolution_label = "当前工作树未找到库，已回退到 Git 主工作树数据源"
    elif resolution_type == "current_search":
        resolution_label = "当前工作树 canonical 数据源"
    else:
        resolution_label = "未找到 canonical 数据源"

    return {
        "current_database_path": resolved_source.get("database_path") or "",
        "expected_database_path": resolved_source.get("expected_database_path") or "",
        "resolved_from_root": resolved_source.get("resolved_from_root") or "",
        "resolution_type": resolution_type,
        "resolution_label": resolution_label,
        "using_fallback": bool(resolved_source.get("using_fallback")),
        "real_record_count": int(real_record_count or 0),
        "showing_demo_data": int(real_record_count or 0) == 0,
    }


def _build_canonical_result(database_path, table_name, rows, generated_at):
    return {
        "source_type": CANONICAL_SOURCE_TYPE,
        "database_path": database_path,
        "table_name": table_name,
        "generated_at": _serialize_datetime(generated_at),
        "rows": rows,
        "edit_meta": _build_edit_meta(),
    }


def get_account_view_rows():
    """读取 canonical 账号视图列表，并补出冷却派生字段。"""
    resolved_source = _resolve_account_view_canonical_store()
    database_path = resolved_source.get("database_path") or ""
    table_name = resolved_source.get("table_name") or CANONICAL_ACCOUNT_STATS_TABLE
    generated_at = datetime.now()
    runtime_snapshot = get_runtime_snapshot()
    real_record_count = _count_canonical_records(database_path, table_name)
    if not database_path or not os.path.isfile(database_path):
        result = _build_canonical_result("", table_name, [], generated_at)
        result["health"] = {
            **_build_duplicate_slot_health([]),
            **_build_expected_slot_health([]),
            **_build_missing_field_health([]),
            **_build_runtime_snapshot_health([], runtime_snapshot),
        }
        result["execution_slot_summary"] = _build_execution_slot_summary(result["health"])
        result["source_summary"] = _build_source_summary("", table_name, runtime_snapshot)
        result["source_diagnostics"] = _build_source_diagnostics(resolved_source, real_record_count)
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
        result["health"] = {
            **_build_duplicate_slot_health(view_rows),
            **_build_expected_slot_health(view_rows),
            **_build_missing_field_health(view_rows),
            **_build_runtime_snapshot_health(view_rows, runtime_snapshot),
        }
        result["execution_slot_summary"] = _build_execution_slot_summary(result["health"])
        result["source_summary"] = _build_source_summary(database_path, table_name, runtime_snapshot)
        result["source_diagnostics"] = _build_source_diagnostics(resolved_source, real_record_count)
        return result
    finally:
        conn.close()


def get_account_view_detail(nickname=None, execution_slot=None):
    """按昵称或执行位读取单条 canonical 账号视图。"""
    resolved_source = _resolve_account_view_canonical_store()
    database_path = resolved_source.get("database_path") or ""
    table_name = resolved_source.get("table_name") or CANONICAL_ACCOUNT_STATS_TABLE
    generated_at = datetime.now()
    runtime_snapshot = get_runtime_snapshot()
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
        "source_summary": _build_source_summary(database_path, table_name, runtime_snapshot),
        "edit_meta": _build_edit_meta(),
        "health": {
            "has_missing_critical_fields": False,
            "missing_critical_fields": [],
            "runtime_consistency": _build_runtime_consistency_health(runtime_snapshot, None),
        },
        "source_diagnostics": _build_source_diagnostics(
            resolved_source,
            _count_canonical_records(database_path, table_name),
        ),
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
            result["edit_meta"] = _build_edit_meta(record)
            result["health"] = {
                **_build_record_health(record),
                "runtime_consistency": _build_runtime_consistency_health(
                    runtime_snapshot,
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


def update_account_view_record(
    nickname,
    baseline_item_delta_text,
    baseline_item_count_text,
    round_status,
    balance_wan_text,
    baseline_update_mode="detail",
):
    """最小单账号写接口：仅允许更新道具基数、状态和余额。"""
    normalized_nickname = str(nickname or "").strip()
    normalized_update_mode = str(baseline_update_mode or "detail").strip().lower()
    if normalized_update_mode not in ("index", "detail"):
        normalized_update_mode = "detail"
    form_values = {
        "nickname": normalized_nickname,
        "baseline_item_delta": str(baseline_item_delta_text or "").strip(),
        "baseline_item_count": str(baseline_item_count_text or "").strip(),
        "round_status": str(round_status or "").strip(),
        "current_balance_wan": str(balance_wan_text or "").strip(),
    }
    result = {
        "status": "error",
        "message": "",
        "field_errors": {},
        "form_values": form_values,
        "detail_result": None,
    }

    if not normalized_nickname:
        result["message"] = "缺少账号昵称，无法提交修改。"
        return result

    resolved_source = _resolve_account_view_canonical_store()
    database_path = resolved_source.get("database_path") or ""
    table_name = resolved_source.get("table_name") or CANONICAL_ACCOUNT_STATS_TABLE
    if not database_path or not os.path.isfile(database_path):
        result["message"] = "canonical SQLite 不存在，当前无法写入。"
        return result

    current_record = read_canonical_account_stats_record(database_path, normalized_nickname, table_name)
    if current_record is None:
        result["message"] = "未找到对应账号记录，无法写入。"
        result["detail_result"] = get_account_view_detail(nickname=normalized_nickname)
        return result

    recalculated_baseline = None
    if normalized_update_mode == "index":
        try:
            baseline_delta = _parse_baseline_item_delta_input(baseline_item_delta_text)
        except ValueError as exc:
            result["field_errors"]["baseline_item_delta"] = str(exc)
        else:
            recalculated_baseline = _parse_int(current_record.baseline_item_count) + baseline_delta
            if recalculated_baseline < 0:
                result["field_errors"]["baseline_item_delta"] = (
                    "调整后的道具基数不能小于 0。"
                )
    else:
        try:
            recalculated_baseline = _parse_baseline_item_count_input(baseline_item_count_text)
        except ValueError as exc:
            result["field_errors"]["baseline_item_count"] = str(exc)
        else:
            form_values["baseline_item_count"] = str(recalculated_baseline)

    if recalculated_baseline is not None:
        form_values["baseline_item_count"] = str(recalculated_baseline)

    normalized_round_status = str(round_status or "").strip()
    if normalized_round_status not in ROUND_STATUS_VALUES:
        result["field_errors"]["round_status"] = "账号状态必须从下拉枚举中选择。"

    try:
        normalized_balance_wan, storage_balance_text = _normalize_balance_wan_input(balance_wan_text)
    except ValueError as exc:
        result["field_errors"]["current_balance_wan"] = str(exc)
    else:
        form_values["current_balance_wan"] = normalized_balance_wan

    if result["field_errors"]:
        result["message"] = "提交失败，请先修正表单输入。"
        result["detail_result"] = get_account_view_detail(nickname=normalized_nickname)
        return result

    updated_record = AccountStatsRecord(
        nickname=current_record.nickname,
        baseline_item_count=recalculated_baseline,
        last_limit_time=current_record.last_limit_time,
        last_account_end_time=current_record.last_account_end_time,
        updated_at=datetime.now(),
        current_execution_slot=current_record.current_execution_slot,
        round_purchase_success_count=current_record.round_purchase_success_count,
        round_listing_success_count=current_record.round_listing_success_count,
        round_purchase_fail_count=current_record.round_purchase_fail_count,
        current_balance=storage_balance_text,
        purchase_running_seconds=current_record.purchase_running_seconds,
        round_status=normalized_round_status,
    )

    try:
        save_canonical_account_stats_record(database_path, updated_record, table_name)
    except Exception as exc:
        result["message"] = f"写库失败：{exc}"
        result["detail_result"] = get_account_view_detail(nickname=normalized_nickname)
        return result

    reloaded_record = read_canonical_account_stats_record(database_path, normalized_nickname, table_name)
    if reloaded_record is None:
        result["message"] = "写库后回读失败：未找到更新后的账号记录。"
        return result

    if (
        int(reloaded_record.baseline_item_count) != int(updated_record.baseline_item_count)
        or str(reloaded_record.round_status or "").strip() != normalized_round_status
        or str(reloaded_record.current_balance or "").strip() != storage_balance_text
    ):
        result["message"] = "写库后回读校验失败：数据库中的值与提交值不一致。"
        result["detail_result"] = get_account_view_detail(nickname=normalized_nickname)
        return result

    result["status"] = "success"
    result["message"] = "保存成功，已完成写库并回读确认。"
    result["detail_result"] = get_account_view_detail(nickname=normalized_nickname)
    result["form_values"] = {
        "nickname": normalized_nickname,
        "baseline_item_delta": "" if normalized_update_mode == "index" else form_values["baseline_item_delta"],
        "baseline_item_count": str(recalculated_baseline),
        "round_status": normalized_round_status,
        "current_balance_wan": normalized_balance_wan,
    }
    return result
