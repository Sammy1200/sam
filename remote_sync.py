"""局域网最小账号快照同步与远端镜像存储。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import os
import sqlite3
import threading
from urllib import error as urllib_error
from urllib import request as urllib_request

from account_db import (
    ACCOUNT_DB_MODE_STONE,
    ROUND_STATUS_VALUES,
    get_account_db_mode_label,
    normalize_account_db_mode,
)
from account_view_repo import get_account_view_rows, update_account_view_record
from config import REMOTE_SYNC_MIRROR_DB_PATH, WEB_VIEW_PORT
from machine_sync_config import get_machine_sync_runtime_context
from round_persistence import mature_all_stone_unlocks


REMOTE_SYNC_SOURCE_TYPE = "remote_sync_mirror"
REMOTE_SYNC_TABLE = "remote_account_snapshots"
REMOTE_SYNC_DAILY_SUMMARY_TABLE = "remote_machine_daily_summaries"
REMOTE_WRITEBACK_ALLOWED_FIELDS = (
    "baseline_item_count",
    "round_status",
    "current_balance_wan",
)
REMOTE_WRITEBACK_BALANCE_INPUT_UNIT = "万"
REMOTE_WRITEBACK_TIMEOUT_SECONDS = 8.0
REMOTE_EVENT_SNAPSHOT_TIMEOUT_SECONDS = 1.5
REMOTE_MANUAL_REFRESH_TIMEOUT_SECONDS = 3.0


def _get_runtime_db_mode(default=ACCOUNT_DB_MODE_STONE):
    try:
        import state
    except Exception:
        return normalize_account_db_mode(default)
    if bool(getattr(state, "accessory_purchase_mode", False)):
        return "accessory"
    return normalize_account_db_mode(default)


def _serialize_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value).strip() or None


def _parse_datetime(raw_value):
    if raw_value in (None, ""):
        return None
    if isinstance(raw_value, datetime):
        return raw_value

    text = str(raw_value).strip()
    if not text:
        return None

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


def _parse_int(raw_value, default=0):
    if raw_value in (None, ""):
        return default
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        return int(raw_value)

    text = "".join(ch for ch in str(raw_value) if ch.isdigit() or ch == "-")
    if not text:
        return default
    return int(text)


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

    wan_text = str(int(wan_value))
    return wan_text


def _ensure_remote_sync_table(conn):
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {REMOTE_SYNC_TABLE} (
            machine_id TEXT NOT NULL,
            db_mode TEXT NOT NULL DEFAULT 'stone',
            machine_display_name TEXT NOT NULL DEFAULT '',
            current_execution_slot INTEGER NOT NULL,
            nickname TEXT NOT NULL DEFAULT '',
            region TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            baseline_item_count INTEGER NOT NULL DEFAULT 0,
            locked_item_count INTEGER NOT NULL DEFAULT 0,
            tradable_item_count INTEGER NOT NULL DEFAULT 0,
            current_balance TEXT NOT NULL DEFAULT '',
            round_status TEXT NOT NULL DEFAULT '',
            updated_at TEXT,
            last_account_end_time TEXT,
            last_limit_time TEXT,
            allow_purchase INTEGER NOT NULL DEFAULT 0,
            runtime_window_remaining_seconds INTEGER NOT NULL DEFAULT 0,
            cooldown_remaining_seconds INTEGER NOT NULL DEFAULT 0,
            report_time TEXT,
            source_client_ip TEXT NOT NULL DEFAULT '',
            received_at TEXT,
            PRIMARY KEY (machine_id, db_mode, current_execution_slot)
        )
        """
    )
    existing_columns = {
        str(row[1]).strip()
        for row in conn.execute(f"PRAGMA table_info({REMOTE_SYNC_TABLE})").fetchall()
        if len(row) > 1 and row[1]
    }
    if "runtime_window_remaining_seconds" not in existing_columns:
        conn.execute(
            f"ALTER TABLE {REMOTE_SYNC_TABLE} "
            "ADD COLUMN runtime_window_remaining_seconds INTEGER NOT NULL DEFAULT 0"
        )
    if "db_mode" not in existing_columns:
        conn.execute(
            f"ALTER TABLE {REMOTE_SYNC_TABLE} "
            "ADD COLUMN db_mode TEXT NOT NULL DEFAULT 'stone'"
        )
    if "locked_item_count" not in existing_columns:
        conn.execute(
            f"ALTER TABLE {REMOTE_SYNC_TABLE} "
            "ADD COLUMN locked_item_count INTEGER NOT NULL DEFAULT 0"
        )
        existing_columns.add("locked_item_count")
    if "tradable_item_count" not in existing_columns:
        conn.execute(
            f"ALTER TABLE {REMOTE_SYNC_TABLE} "
            "ADD COLUMN tradable_item_count INTEGER NOT NULL DEFAULT 0"
        )
        existing_columns.add("tradable_item_count")
    pk_columns = [
        str(row[1]).strip()
        for row in sorted(
            conn.execute(f"PRAGMA table_info({REMOTE_SYNC_TABLE})").fetchall(),
            key=lambda item: int(item[5] or 0),
        )
        if len(row) > 5 and int(row[5] or 0) > 0
    ]
    if pk_columns != ["machine_id", "db_mode", "current_execution_slot"]:
        temp_table = f"{REMOTE_SYNC_TABLE}_mode_migration"
        conn.execute(f"DROP TABLE IF EXISTS {temp_table}")
        conn.execute(
            f"""
            CREATE TABLE {temp_table} (
                machine_id TEXT NOT NULL,
                db_mode TEXT NOT NULL DEFAULT 'stone',
                machine_display_name TEXT NOT NULL DEFAULT '',
                current_execution_slot INTEGER NOT NULL,
                nickname TEXT NOT NULL DEFAULT '',
                region TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                baseline_item_count INTEGER NOT NULL DEFAULT 0,
                locked_item_count INTEGER NOT NULL DEFAULT 0,
                tradable_item_count INTEGER NOT NULL DEFAULT 0,
                current_balance TEXT NOT NULL DEFAULT '',
                round_status TEXT NOT NULL DEFAULT '',
                updated_at TEXT,
                last_account_end_time TEXT,
                last_limit_time TEXT,
                allow_purchase INTEGER NOT NULL DEFAULT 0,
                runtime_window_remaining_seconds INTEGER NOT NULL DEFAULT 0,
                cooldown_remaining_seconds INTEGER NOT NULL DEFAULT 0,
                report_time TEXT,
                source_client_ip TEXT NOT NULL DEFAULT '',
                received_at TEXT,
                PRIMARY KEY (machine_id, db_mode, current_execution_slot)
            )
            """
        )
        conn.execute(
            f"""
            INSERT OR REPLACE INTO {temp_table} (
                machine_id, db_mode, machine_display_name, current_execution_slot,
                nickname, region, sort_order, baseline_item_count, locked_item_count,
                tradable_item_count, current_balance,
                round_status, updated_at, last_account_end_time, last_limit_time,
                allow_purchase, runtime_window_remaining_seconds, cooldown_remaining_seconds,
                report_time, source_client_ip, received_at
            )
            SELECT
                machine_id, COALESCE(NULLIF(db_mode, ''), 'stone'), machine_display_name,
                current_execution_slot, nickname, region, sort_order, baseline_item_count,
                locked_item_count, tradable_item_count, current_balance, round_status, updated_at, last_account_end_time,
                last_limit_time, allow_purchase, runtime_window_remaining_seconds,
                cooldown_remaining_seconds, report_time, source_client_ip, received_at
            FROM {REMOTE_SYNC_TABLE}
            """
        )
        conn.execute(f"DROP TABLE {REMOTE_SYNC_TABLE}")
        conn.execute(f"ALTER TABLE {temp_table} RENAME TO {REMOTE_SYNC_TABLE}")


def _remote_table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _ensure_remote_daily_summary_table(conn):
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {REMOTE_SYNC_DAILY_SUMMARY_TABLE} (
            machine_id TEXT NOT NULL,
            db_mode TEXT NOT NULL DEFAULT 'stone',
            machine_display_name TEXT NOT NULL DEFAULT '',
            stat_date TEXT NOT NULL,
            total_purchase_success_count INTEGER NOT NULL DEFAULT 0,
            total_listing_success_count INTEGER NOT NULL DEFAULT 0,
            total_purchase_fail_count INTEGER NOT NULL DEFAULT 0,
            report_time TEXT,
            source_client_ip TEXT NOT NULL DEFAULT '',
            received_at TEXT,
            PRIMARY KEY (machine_id, db_mode, stat_date)
        )
        """
    )
    existing_columns = {
        str(row[1]).strip()
        for row in conn.execute(f"PRAGMA table_info({REMOTE_SYNC_DAILY_SUMMARY_TABLE})").fetchall()
        if len(row) > 1 and row[1]
    }
    if "db_mode" not in existing_columns:
        conn.execute(
            f"ALTER TABLE {REMOTE_SYNC_DAILY_SUMMARY_TABLE} "
            "ADD COLUMN db_mode TEXT NOT NULL DEFAULT 'stone'"
        )
    pk_columns = [
        str(row[1]).strip()
        for row in sorted(
            conn.execute(f"PRAGMA table_info({REMOTE_SYNC_DAILY_SUMMARY_TABLE})").fetchall(),
            key=lambda item: int(item[5] or 0),
        )
        if len(row) > 5 and int(row[5] or 0) > 0
    ]
    if pk_columns != ["machine_id", "db_mode", "stat_date"]:
        temp_table = f"{REMOTE_SYNC_DAILY_SUMMARY_TABLE}_mode_migration"
        conn.execute(f"DROP TABLE IF EXISTS {temp_table}")
        conn.execute(
            f"""
            CREATE TABLE {temp_table} (
                machine_id TEXT NOT NULL,
                db_mode TEXT NOT NULL DEFAULT 'stone',
                machine_display_name TEXT NOT NULL DEFAULT '',
                stat_date TEXT NOT NULL,
                total_purchase_success_count INTEGER NOT NULL DEFAULT 0,
                total_listing_success_count INTEGER NOT NULL DEFAULT 0,
                total_purchase_fail_count INTEGER NOT NULL DEFAULT 0,
                report_time TEXT,
                source_client_ip TEXT NOT NULL DEFAULT '',
                received_at TEXT,
                PRIMARY KEY (machine_id, db_mode, stat_date)
            )
            """
        )
        conn.execute(
            f"""
            INSERT OR REPLACE INTO {temp_table} (
                machine_id, db_mode, machine_display_name, stat_date,
                total_purchase_success_count, total_listing_success_count,
                total_purchase_fail_count, report_time, source_client_ip, received_at
            )
            SELECT
                machine_id, COALESCE(NULLIF(db_mode, ''), 'stone'), machine_display_name,
                stat_date, total_purchase_success_count, total_listing_success_count,
                total_purchase_fail_count, report_time, source_client_ip, received_at
            FROM {REMOTE_SYNC_DAILY_SUMMARY_TABLE}
            """
        )
        conn.execute(f"DROP TABLE {REMOTE_SYNC_DAILY_SUMMARY_TABLE}")
        conn.execute(f"ALTER TABLE {temp_table} RENAME TO {REMOTE_SYNC_DAILY_SUMMARY_TABLE}")


def _normalize_snapshot_entry(item, report_time):
    if not isinstance(item, dict):
        raise ValueError("accounts 中存在非对象项")

    execution_slot = _parse_int(item.get("current_execution_slot"), default=0)
    if execution_slot <= 0:
        raise ValueError("current_execution_slot 必须是大于 0 的整数")

    sort_order = _parse_int(item.get("sort_order"), default=execution_slot)
    if sort_order <= 0:
        sort_order = execution_slot

    return {
        "current_execution_slot": execution_slot,
        "nickname": str(item.get("nickname") or "").strip(),
        "region": str(item.get("region") or item.get("server") or "").strip(),
        "sort_order": sort_order,
        "baseline_item_count": max(0, _parse_int(item.get("baseline_item_count"), default=0)),
        "locked_item_count": max(0, _parse_int(item.get("locked_item_count"), default=0)),
        "tradable_item_count": max(0, _parse_int(item.get("tradable_item_count"), default=0)),
        "current_balance": str(item.get("current_balance") or "").strip(),
        "round_status": str(item.get("round_status") or "").strip(),
        "updated_at": _serialize_datetime(item.get("updated_at")),
        "last_account_end_time": _serialize_datetime(item.get("last_account_end_time")),
        "last_limit_time": _serialize_datetime(item.get("last_limit_time")),
        "allow_purchase": 1 if bool(item.get("allow_purchase")) else 0,
        "runtime_window_remaining_seconds": max(
            0,
            _parse_int(item.get("runtime_window_remaining_seconds"), default=0),
        ),
        "cooldown_remaining_seconds": max(
            0,
            _parse_int(item.get("cooldown_remaining_seconds"), default=0),
        ),
        "report_time": _serialize_datetime(item.get("report_time")) or report_time,
    }


def _normalize_machine_daily_summary_entry(item):
    if not isinstance(item, dict):
        raise ValueError("machine_daily_summaries 中存在非对象项")

    stat_date = str(item.get("stat_date") or "").strip()
    if len(stat_date) != 10:
        raise ValueError("machine_daily_summaries.stat_date 格式无效")

    return {
        "stat_date": stat_date,
        "total_purchase_success_count": max(
            0,
            _parse_int(item.get("total_purchase_success_count"), default=0),
        ),
        "total_listing_success_count": max(
            0,
            _parse_int(item.get("total_listing_success_count"), default=0),
        ),
        "total_purchase_fail_count": max(
            0,
            _parse_int(item.get("total_purchase_fail_count"), default=0),
        ),
    }


def save_remote_sync_report(payload, client_ip=""):
    if not isinstance(payload, dict):
        raise ValueError("同步上报载荷必须是 JSON 对象")

    machine_id = str(payload.get("machine_id") or "").strip()
    db_mode = normalize_account_db_mode(payload.get("db_mode"))
    machine_display_name = str(payload.get("machine_display_name") or "").strip()
    report_time = _serialize_datetime(payload.get("report_time")) or _serialize_datetime(datetime.now())
    raw_accounts = payload.get("accounts")
    raw_machine_daily_summaries = payload.get("machine_daily_summaries")

    if not machine_id:
        raise ValueError("machine_id 不能为空")
    if not machine_display_name:
        raise ValueError("machine_display_name 不能为空")
    if not isinstance(raw_accounts, list):
        raise ValueError("accounts 必须是数组")

    normalized_accounts = [
        _normalize_snapshot_entry(item, report_time)
        for item in raw_accounts
    ]
    if raw_machine_daily_summaries is None:
        raw_machine_daily_summaries = []
    elif not isinstance(raw_machine_daily_summaries, list):
        raise ValueError("machine_daily_summaries 必须是数组")
    normalized_machine_daily_summaries = [
        _normalize_machine_daily_summary_entry(item)
        for item in raw_machine_daily_summaries
    ]

    os.makedirs(os.path.dirname(REMOTE_SYNC_MIRROR_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(REMOTE_SYNC_MIRROR_DB_PATH)
    try:
        _ensure_remote_sync_table(conn)
        _ensure_remote_daily_summary_table(conn)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            f"DELETE FROM {REMOTE_SYNC_TABLE} WHERE machine_id = ? AND db_mode = ?",
            (machine_id, db_mode),
        )
        conn.execute(
            f"DELETE FROM {REMOTE_SYNC_DAILY_SUMMARY_TABLE} WHERE machine_id = ? AND db_mode = ?",
            (machine_id, db_mode),
        )
        for account in normalized_accounts:
            conn.execute(
                f"""
                INSERT INTO {REMOTE_SYNC_TABLE} (
                    machine_id,
                    db_mode,
                    machine_display_name,
                    current_execution_slot,
                    nickname,
                    region,
                    sort_order,
                    baseline_item_count,
                    locked_item_count,
                    tradable_item_count,
                    current_balance,
                    round_status,
                    updated_at,
                    last_account_end_time,
                    last_limit_time,
                    allow_purchase,
                    runtime_window_remaining_seconds,
                    cooldown_remaining_seconds,
                    report_time,
                    source_client_ip,
                    received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    machine_id,
                    db_mode,
                    machine_display_name,
                    account["current_execution_slot"],
                    account["nickname"],
                    account["region"],
                    account["sort_order"],
                    account["baseline_item_count"],
                    account["locked_item_count"],
                    account["tradable_item_count"],
                    account["current_balance"],
                    account["round_status"],
                    account["updated_at"],
                    account["last_account_end_time"],
                    account["last_limit_time"],
                    account["allow_purchase"],
                    account["runtime_window_remaining_seconds"],
                    account["cooldown_remaining_seconds"],
                    account["report_time"],
                    str(client_ip or "").strip(),
                    _serialize_datetime(datetime.now()),
                ),
            )
        for summary in normalized_machine_daily_summaries:
            conn.execute(
                f"""
                INSERT INTO {REMOTE_SYNC_DAILY_SUMMARY_TABLE} (
                    machine_id,
                    db_mode,
                    machine_display_name,
                    stat_date,
                    total_purchase_success_count,
                    total_listing_success_count,
                    total_purchase_fail_count,
                    report_time,
                    source_client_ip,
                    received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    machine_id,
                    db_mode,
                    machine_display_name,
                    summary["stat_date"],
                    summary["total_purchase_success_count"],
                    summary["total_listing_success_count"],
                    summary["total_purchase_fail_count"],
                    report_time,
                    str(client_ip or "").strip(),
                    _serialize_datetime(datetime.now()),
                ),
            )
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "status": "success",
            "machine_id": machine_id,
            "db_mode": db_mode,
            "db_label": get_account_db_mode_label(db_mode),
            "machine_display_name": machine_display_name,
        "snapshot_count": len(normalized_accounts),
        "report_time": report_time,
    }


def _build_remote_edit_meta():
    return {
        "editable_fields": REMOTE_WRITEBACK_ALLOWED_FIELDS,
        "status_options": list(ROUND_STATUS_VALUES),
        "balance_input_unit": REMOTE_WRITEBACK_BALANCE_INPUT_UNIT,
    }


def _build_remote_update_form_values(
    machine_id,
    nickname,
    baseline_item_count_text,
    round_status,
    balance_wan_text,
):
    return {
        "target_machine_id": str(machine_id or "").strip(),
        "nickname": str(nickname or "").strip(),
        "baseline_item_count": str(baseline_item_count_text or "").strip(),
        "round_status": str(round_status or "").strip(),
        "current_balance_wan": str(balance_wan_text or "").strip(),
    }


def _read_remote_machine_writeback_target(machine_id, db_mode=ACCOUNT_DB_MODE_STONE):
    normalized_machine_id = str(machine_id or "").strip()
    normalized_mode = normalize_account_db_mode(db_mode)
    if not normalized_machine_id:
        return None
    if not os.path.isfile(REMOTE_SYNC_MIRROR_DB_PATH):
        return None
    init_conn = None
    try:
        init_conn = sqlite3.connect(REMOTE_SYNC_MIRROR_DB_PATH)
        _ensure_remote_sync_table(init_conn)
        init_conn.commit()
    except sqlite3.Error:
        return None
    finally:
        try:
            if init_conn is not None:
                init_conn.close()
        except Exception:
            pass

    conn = sqlite3.connect(f"file:{REMOTE_SYNC_MIRROR_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            f"""
            SELECT
                machine_id,
                db_mode,
                machine_display_name,
                source_client_ip,
                report_time,
                received_at
            FROM {REMOTE_SYNC_TABLE}
            WHERE machine_id = ? AND db_mode = ?
            ORDER BY report_time DESC, received_at DESC
            LIMIT 1
            """,
            (normalized_machine_id, normalized_mode),
        ).fetchone()
        if row is None and normalized_mode != ACCOUNT_DB_MODE_STONE:
            row = conn.execute(
                f"""
                SELECT
                    machine_id,
                    db_mode,
                    machine_display_name,
                    source_client_ip,
                    report_time,
                    received_at
                FROM {REMOTE_SYNC_TABLE}
                WHERE machine_id = ?
                ORDER BY CASE WHEN db_mode = 'stone' THEN 0 ELSE 1 END, report_time DESC, received_at DESC
                LIMIT 1
                """,
                (normalized_machine_id,),
            ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()

    if row is None:
        return None

    source_client_ip = str(row["source_client_ip"] or "").strip()
    if not source_client_ip:
        return {
            "machine_id": normalized_machine_id,
            "db_mode": normalized_mode,
            "machine_display_name": str(row["machine_display_name"] or normalized_machine_id).strip(),
            "source_client_ip": "",
            "base_url": "",
            "report_time": _serialize_datetime(row["report_time"]) or "",
        }

    return {
        "machine_id": normalized_machine_id,
        "db_mode": normalized_mode,
        "machine_display_name": str(row["machine_display_name"] or normalized_machine_id).strip(),
        "source_client_ip": source_client_ip,
        "base_url": f"http://{source_client_ip}:{WEB_VIEW_PORT}",
        "report_time": _serialize_datetime(row["report_time"]) or "",
    }


def handle_remote_sync_report_payload(payload, client_ip=""):
    runtime_context = get_machine_sync_runtime_context()
    if runtime_context.get("config_status") != "ready":
        return {
            "status": "error",
            "message": f"本机网页同步配置不可用：{runtime_context.get('config_error')}",
        }

    if not runtime_context.get("receive_remote_sync"):
        return {
            "status": "forbidden",
            "message": "当前机器未开启 receive_remote_sync，拒绝接收远端同步。",
        }

    payload_machine_id = str((payload or {}).get("machine_id") or "").strip()
    if payload_machine_id and payload_machine_id == runtime_context.get("machine_id"):
        return {
            "status": "error",
            "message": "远端同步 machine_id 与本机 machine_id 相同，已拒绝写入镜像层。",
        }

    try:
        return save_remote_sync_report(payload, client_ip=client_ip)
    except Exception as exc:
        return {
            "status": "error",
            "message": f"写入远端同步镜像失败：{exc}",
        }


def handle_remote_writeback_payload(payload, client_ip=""):
    runtime_context = get_machine_sync_runtime_context()
    if runtime_context.get("config_status") != "ready":
        return {
            "status": "error",
            "message": f"本机网页同步配置不可用：{runtime_context.get('config_error')}",
        }

    if not runtime_context.get("receive_remote_writeback"):
        return {
            "status": "forbidden",
            "message": "当前机器未开启 receive_remote_writeback，拒绝远端最小写回。",
        }

    if not isinstance(payload, dict):
        return {
            "status": "error",
            "message": "远端写回载荷必须是 JSON 对象。",
        }

    operator_machine_id = str(payload.get("operator_machine_id") or "").strip()
    target_machine_id = str(payload.get("target_machine_id") or "").strip()
    db_mode = normalize_account_db_mode(payload.get("db_mode"))
    nickname = str(payload.get("nickname") or "").strip()
    raw_fields = payload.get("fields")

    if not target_machine_id:
        return {
            "status": "error",
            "message": "target_machine_id 不能为空。",
        }
    if target_machine_id != str(runtime_context.get("machine_id") or "").strip():
        return {
            "status": "forbidden",
            "message": "target_machine_id 与当前机器不匹配，拒绝写回。",
        }
    if operator_machine_id and operator_machine_id == target_machine_id:
        return {
            "status": "error",
            "message": "operator_machine_id 与 target_machine_id 相同，拒绝自回写。",
        }
    if not nickname:
        return {
            "status": "error",
            "message": "nickname 不能为空。",
        }
    if not isinstance(raw_fields, dict):
        return {
            "status": "error",
            "message": "fields 必须是对象，且仅允许提交 3 个最小字段。",
        }

    unknown_fields = sorted(
        field_name
        for field_name in raw_fields.keys()
        if field_name not in REMOTE_WRITEBACK_ALLOWED_FIELDS
    )
    missing_fields = [
        field_name
        for field_name in REMOTE_WRITEBACK_ALLOWED_FIELDS
        if field_name not in raw_fields
    ]
    if unknown_fields or missing_fields:
        problems = []
        if unknown_fields:
            problems.append(f"存在非法字段：{', '.join(unknown_fields)}")
        if missing_fields:
            problems.append(f"缺少必填字段：{', '.join(missing_fields)}")
        return {
            "status": "error",
            "message": "；".join(problems),
            "field_errors": {
                field_name: "该字段不允许远端写回。"
                for field_name in unknown_fields
            },
            "form_values": _build_remote_update_form_values(
                target_machine_id,
                nickname,
                raw_fields.get("baseline_item_count"),
                raw_fields.get("round_status"),
                raw_fields.get("current_balance_wan"),
            ),
        }

    update_result = update_account_view_record(
        nickname=nickname,
        baseline_item_delta_text="",
        baseline_item_count_text=raw_fields.get("baseline_item_count"),
        round_status=raw_fields.get("round_status"),
        balance_wan_text=raw_fields.get("current_balance_wan"),
        baseline_update_mode="detail",
        db_mode=db_mode,
    )
    if update_result.get("status") != "success":
        return {
            "status": "error",
            "message": update_result.get("message") or "远端真源写回失败。",
            "field_errors": dict(update_result.get("field_errors") or {}),
            "form_values": _build_remote_update_form_values(
                target_machine_id,
                nickname,
                raw_fields.get("baseline_item_count"),
                raw_fields.get("round_status"),
                raw_fields.get("current_balance_wan"),
            ),
            "canonical_confirmed": False,
        }

    snapshot_result = build_local_snapshot_payload(db_mode=db_mode)
    if snapshot_result.get("status") != "success":
        return {
            "status": "error",
            "message": (
                "远端真源已写入并回读确认，但构建镜像刷新快照失败："
                f"{snapshot_result.get('message') or '未知错误'}"
            ),
            "field_errors": {},
            "form_values": _build_remote_update_form_values(
                target_machine_id,
                nickname,
                raw_fields.get("baseline_item_count"),
                raw_fields.get("round_status"),
                raw_fields.get("current_balance_wan"),
            ),
            "canonical_confirmed": True,
        }

    return {
        "status": "success",
        "message": "远端真源写入成功，已完成本机回读确认并生成最新镜像快照。",
        "field_errors": {},
        "form_values": _build_remote_update_form_values(
            target_machine_id,
            nickname,
            raw_fields.get("baseline_item_count"),
            raw_fields.get("round_status"),
            raw_fields.get("current_balance_wan"),
        ),
        "canonical_confirmed": True,
        "target_machine_id": target_machine_id,
        "target_machine_display_name": runtime_context.get("machine_display_name") or target_machine_id,
        "source_client_ip": str(client_ip or "").strip(),
        "snapshot_payload": snapshot_result.get("payload"),
    }


def submit_remote_account_update(
    target_machine_id,
    nickname,
    baseline_item_count_text,
    round_status,
    balance_wan_text,
    timeout=REMOTE_WRITEBACK_TIMEOUT_SECONDS,
    db_mode=ACCOUNT_DB_MODE_STONE,
):
    normalized_mode = normalize_account_db_mode(db_mode)
    form_values = _build_remote_update_form_values(
        target_machine_id,
        nickname,
        baseline_item_count_text,
        round_status,
        balance_wan_text,
    )
    result = {
        "status": "error",
        "scope": "remote",
        "message": "",
        "field_errors": {},
        "form_values": form_values,
    }

    normalized_machine_id = str(target_machine_id or "").strip()
    normalized_nickname = str(nickname or "").strip()
    if not normalized_machine_id:
        result["message"] = "缺少目标机器标识，无法提交远端写回。"
        return result
    if not normalized_nickname:
        result["message"] = "缺少账号昵称，无法提交远端写回。"
        return result

    writeback_target = _read_remote_machine_writeback_target(normalized_machine_id, db_mode=normalized_mode)
    if writeback_target is None:
        result["message"] = "未找到对应远端机器的最近镜像记录，暂时无法路由写回。"
        return result

    base_url = str(writeback_target.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        result["message"] = "远端机器最近镜像缺少可回连地址，暂时无法路由写回。"
        return result

    runtime_context = get_machine_sync_runtime_context()
    payload = {
        "operator_machine_id": runtime_context.get("machine_id") or "local",
        "operator_machine_display_name": runtime_context.get("machine_display_name") or "本机",
        "target_machine_id": normalized_machine_id,
        "db_mode": normalized_mode,
        "nickname": normalized_nickname,
        "fields": {
            "baseline_item_count": form_values["baseline_item_count"],
            "round_status": form_values["round_status"],
            "current_balance_wan": form_values["current_balance_wan"],
        },
    }
    request = urllib_request.Request(
        f"{base_url}/remote-sync/writeback",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "codex-remote-writeback-proxy",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            response_text = response.read().decode("utf-8", errors="ignore")
            response_payload = json.loads(response_text) if response_text else {}
            http_status = getattr(response, "status", 200)
    except urllib_error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="ignore")
        try:
            response_payload = json.loads(error_text) if error_text else {}
        except json.JSONDecodeError:
            response_payload = {"message": error_text or exc.reason}
        http_status = exc.code
    except Exception as exc:
        result["message"] = f"远端写回请求失败：{exc}"
        return result

    remote_status = str(response_payload.get("status") or "").strip()
    if http_status == 403 or remote_status == "forbidden":
        result["status"] = "forbidden"
        result["message"] = str(response_payload.get("message") or "远端机器拒绝写回。")
        return result

    result["field_errors"] = dict(response_payload.get("field_errors") or {})
    if remote_status != "success":
        result["message"] = str(response_payload.get("message") or "远端机器未返回 success。")
        return result

    snapshot_payload = response_payload.get("snapshot_payload")
    if not isinstance(snapshot_payload, dict):
        result["message"] = "远端真源已写入，但未返回可用于刷新镜像的快照载荷。"
        return result

    try:
        save_remote_sync_report(
            snapshot_payload,
            client_ip=str(writeback_target.get("source_client_ip") or "").strip(),
        )
    except Exception as exc:
        result["message"] = f"远端真源已写入，但刷新本地镜像失败：{exc}"
        return result

    result["status"] = "success"
    result["message"] = (
        f"已写入 {writeback_target.get('machine_display_name') or normalized_machine_id} 的本机真源，"
        "并刷新当前镜像。"
    )
    return result


def build_local_snapshot_payload(db_mode=None):
    normalized_mode = _get_runtime_db_mode() if db_mode is None else normalize_account_db_mode(db_mode)
    runtime_context = get_machine_sync_runtime_context()
    if runtime_context.get("config_status") != "ready":
        return {
            "status": "error",
            "message": f"本机网页同步配置不可用：{runtime_context.get('config_error')}",
        }

    if normalized_mode == ACCOUNT_DB_MODE_STONE:
        mature_result = mature_all_stone_unlocks("远端快照刷新")
        if mature_result.status not in ("success", "skipped"):
            return {
                "status": "error",
                "message": f"生成快照前全账号结转异常：{mature_result.reason}",
            }

    view_rows_result = get_account_view_rows(db_mode=normalized_mode)
    rows = view_rows_result.get("rows") or []
    if not view_rows_result.get("database_path"):
        return {
            "status": "error",
            "message": "未找到本机 canonical 主库，无法构建最小账号快照。",
        }
    if not rows:
        return {
            "status": "error",
            "message": "本机 canonical 主库当前无账号行，已跳过空上报。",
        }

    report_time = _serialize_datetime(datetime.now())
    slot_overrides = runtime_context.get("execution_slot_overrides") or {}
    account_snapshots = []
    for row in rows:
        execution_slot = _parse_int(row.get("current_execution_slot"), default=0)
        if execution_slot <= 0:
            continue

        override = slot_overrides.get(execution_slot)
        nickname = str(row.get("nickname") or "").strip()
        region = ""
        sort_order = execution_slot
        if override is not None:
            nickname = override.nickname or nickname
            region = override.region or region
            sort_order = override.sort_order or sort_order

        account_snapshots.append(
            {
                "machine_id": runtime_context.get("machine_id"),
                "current_execution_slot": execution_slot,
                "nickname": nickname,
                "region": region,
                "sort_order": sort_order,
                "baseline_item_count": max(0, _parse_int(row.get("baseline_item_count"), default=0)),
                "locked_item_count": max(0, _parse_int(row.get("locked_item_count"), default=0)),
                "tradable_item_count": max(0, _parse_int(row.get("tradable_item_count"), default=0)),
                "current_balance": str(row.get("current_balance") or "").strip(),
                "round_status": str(row.get("round_status") or "").strip(),
                "updated_at": _serialize_datetime(row.get("updated_at")),
                "last_account_end_time": _serialize_datetime(row.get("last_account_end_time")),
                "last_limit_time": _serialize_datetime(row.get("last_limit_time")),
                "allow_purchase": bool(row.get("allow_purchase")),
                "runtime_window_remaining_seconds": max(
                    0,
                    _parse_int(row.get("runtime_window_remaining_seconds"), default=0),
                ),
                "cooldown_remaining_seconds": max(
                    0,
                    _parse_int(row.get("cooldown_remaining_seconds"), default=0),
                ),
                "report_time": report_time,
            }
        )

    if not account_snapshots:
        return {
            "status": "error",
            "message": "本机账号列表缺少有效执行位，无法构建最小账号快照。",
        }

    account_snapshots.sort(
        key=lambda item: (
            int(item.get("sort_order") or 0),
            int(item.get("current_execution_slot") or 0),
        )
    )
    return {
        "status": "success",
        "payload": {
            "machine_id": runtime_context.get("machine_id"),
            "db_mode": normalized_mode,
            "db_label": get_account_db_mode_label(normalized_mode),
            "machine_display_name": runtime_context.get("machine_display_name"),
            "report_time": report_time,
            "machine_daily_summaries": list(view_rows_result.get("machine_daily_summaries") or []),
            "accounts": account_snapshots,
        },
    }


def report_local_snapshot_once(timeout=2.0, db_mode=None):
    runtime_context = get_machine_sync_runtime_context()
    if runtime_context.get("config_status") != "ready":
        return {
            "status": "skipped",
            "message": f"网页同步配置不可用：{runtime_context.get('config_error')}",
        }

    if not runtime_context.get("sync_enabled"):
        return {
            "status": "skipped",
            "message": "当前机器未开启 sync_enabled，跳过最小账号快照上报。",
        }

    aggregator_url = str(runtime_context.get("aggregator_url") or "").strip().rstrip("/")
    if not aggregator_url:
        aggregator_host = str(runtime_context.get("aggregator_host") or "").strip()
        if aggregator_host:
            aggregator_url = f"http://{aggregator_host}:{WEB_VIEW_PORT}"
        else:
            return {
                "status": "skipped",
                "message": "未配置 aggregator_url 或 aggregator_host，无法执行最小账号快照上报。",
            }

    build_result = build_local_snapshot_payload(db_mode=db_mode)
    if build_result.get("status") != "success":
        return build_result

    payload = build_result.get("payload") or {}
    request = urllib_request.Request(
        f"{aggregator_url}/remote-sync/report",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "codex-remote-sync",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            response_text = response.read().decode("utf-8", errors="ignore")
            try:
                response_payload = json.loads(response_text) if response_text else {}
            except json.JSONDecodeError:
                response_payload = {"message": response_text}
    except urllib_error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="ignore")
        return {
            "status": "error",
            "message": f"上报失败，HTTP {exc.code}：{error_text or exc.reason}",
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"上报失败：{exc}",
        }

    response_status = str(response_payload.get("status") or "").strip()
    if response_status != "success":
        return {
            "status": "error",
            "message": str(response_payload.get("message") or "汇总节点未返回 success"),
        }

    return {
        "status": "success",
        "message": (
            f"最小账号快照上报成功：机器={payload.get('machine_display_name')} "
            f"数量={len(payload.get('accounts') or [])}"
        ),
    }


def schedule_local_snapshot_report(event_name, timeout=REMOTE_EVENT_SNAPSHOT_TIMEOUT_SECONDS):
    runtime_context = get_machine_sync_runtime_context()
    if runtime_context.get("config_status") != "ready":
        return {
            "status": "skipped",
            "message": f"网页同步配置不可用：{runtime_context.get('config_error')}",
        }
    if not runtime_context.get("sync_enabled"):
        return {
            "status": "skipped",
            "message": "当前机器未开启 sync_enabled，跳过事件触发最小快照。",
        }

    normalized_event_name = str(event_name or "").strip() or "未命名事件"

    def _run_once():
        result = report_local_snapshot_once(timeout=timeout)
        status = str(result.get("status") or "").strip()
        message = str(result.get("message") or "").strip()
        prefix = f"[网页同步] 事件触发最小快照：{normalized_event_name}"
        if status == "success":
            print(f"{prefix}，{message}")
        elif status == "error":
            print(f"{prefix}失败：{message}")
        return result

    def _worker():
        _run_once()

    thread = threading.Thread(
        target=_worker,
        name=f"remote-sync-event-{normalized_event_name[:16]}",
        daemon=True,
    )
    thread.start()
    return {
        "status": "scheduled",
        "message": f"已安排事件触发最小快照：{normalized_event_name}",
    }


def run_local_snapshot_report_for_event(
    event_name,
    timeout=REMOTE_EVENT_SNAPSHOT_TIMEOUT_SECONDS,
):
    runtime_context = get_machine_sync_runtime_context()
    if runtime_context.get("config_status") != "ready":
        return {
            "status": "skipped",
            "message": f"网页同步配置不可用：{runtime_context.get('config_error')}",
        }
    if not runtime_context.get("sync_enabled"):
        return {
            "status": "skipped",
            "message": "当前机器未开启 sync_enabled，跳过事件触发最小快照。",
        }

    normalized_event_name = str(event_name or "").strip() or "未命名事件"
    result = report_local_snapshot_once(timeout=timeout)
    status = str(result.get("status") or "").strip()
    message = str(result.get("message") or "").strip()
    prefix = f"[网页同步] 事件触发最小快照：{normalized_event_name}"
    if status == "success":
        print(f"{prefix}，{message}")
    elif status == "error":
        print(f"{prefix}失败：{message}")
    return result


def handle_remote_snapshot_request(client_ip="", db_mode=None):
    runtime_context = get_machine_sync_runtime_context()
    if runtime_context.get("config_status") != "ready":
        return {
            "status": "error",
            "message": f"本机网页同步配置不可用：{runtime_context.get('config_error')}",
        }
    if not runtime_context.get("sync_enabled"):
        return {
            "status": "forbidden",
            "message": "当前机器未开启 sync_enabled，拒绝导出最小快照。",
        }

    build_result = build_local_snapshot_payload(db_mode=db_mode)
    if build_result.get("status") != "success":
        return build_result

    payload = build_result.get("payload") or {}
    return {
        "status": "success",
        "message": "已基于本机 canonical 真源生成最新最小快照。",
        "source_client_ip": str(client_ip or "").strip(),
        "snapshot_payload": payload,
    }


def refresh_remote_machine_snapshot(
    machine_id,
    timeout=REMOTE_MANUAL_REFRESH_TIMEOUT_SECONDS,
    refresh_reason="manual",
    db_mode=ACCOUNT_DB_MODE_STONE,
):
    normalized_machine_id = str(machine_id or "").strip()
    normalized_mode = normalize_account_db_mode(db_mode)
    result = {
        "status": "error",
        "scope": "remote_refresh",
        "target_machine_id": normalized_machine_id,
        "db_mode": normalized_mode,
        "message": "",
        "refresh_reason": str(refresh_reason or "").strip() or "manual",
    }
    if not normalized_machine_id:
        result["message"] = "缺少目标机器标识，无法刷新远端镜像。"
        return result

    refresh_target = _read_remote_machine_writeback_target(normalized_machine_id, db_mode=normalized_mode)
    if refresh_target is None:
        result["message"] = "未找到对应远端机器的最近镜像记录，暂时无法发起刷新。"
        return result

    base_url = str(refresh_target.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        result["message"] = "远端机器最近镜像缺少可回连地址，暂时无法发起刷新。"
        return result

    request = urllib_request.Request(
        f"{base_url}/remote-sync/snapshot",
        data=json.dumps(
            {
                "request_type": "manual_refresh",
                "target_machine_id": normalized_machine_id,
                "refresh_reason": result["refresh_reason"],
                "db_mode": normalized_mode,
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "codex-remote-mirror-refresh",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            response_text = response.read().decode("utf-8", errors="ignore")
            response_payload = json.loads(response_text) if response_text else {}
            http_status = getattr(response, "status", 200)
    except urllib_error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="ignore")
        try:
            response_payload = json.loads(error_text) if error_text else {}
        except json.JSONDecodeError:
            response_payload = {"message": error_text or exc.reason}
        http_status = exc.code
    except Exception as exc:
        result["message"] = f"刷新失败，远端无响应：{exc}"
        return result

    remote_status = str(response_payload.get("status") or "").strip()
    if http_status == 403 or remote_status == "forbidden":
        result["status"] = "forbidden"
        result["message"] = str(response_payload.get("message") or "远端机器拒绝导出最小快照。")
        return result
    if remote_status != "success":
        result["message"] = str(response_payload.get("message") or "远端机器未返回 success。")
        return result

    snapshot_payload = response_payload.get("snapshot_payload")
    if not isinstance(snapshot_payload, dict):
        result["message"] = "远端机器未返回有效最小快照。"
        return result

    try:
        save_remote_sync_report(
            snapshot_payload,
            client_ip=str(refresh_target.get("source_client_ip") or "").strip(),
        )
    except Exception as exc:
        result["message"] = f"已拿到远端最新快照，但刷新本地镜像失败：{exc}"
        return result

    refreshed_sections = get_remote_machine_sections(db_mode=normalized_mode)
    refreshed_section = next(
        (
            section
            for section in refreshed_sections
            if str(section.get("machine_id") or "").strip() == normalized_machine_id
        ),
        None,
    )
    result["status"] = "success"
    result["message"] = (
        f"已刷新 {refresh_target.get('machine_display_name') or normalized_machine_id} 的远端镜像显示。"
    )
    result["last_refresh_time"] = (
        str((refreshed_section or {}).get("last_report_time") or "").strip()
    )
    return result


def run_remote_snapshot_report_loop(stop_event=None):
    runtime_context = get_machine_sync_runtime_context()
    interval_seconds = int(runtime_context.get("report_interval_seconds") or 30)
    if interval_seconds <= 0:
        interval_seconds = 30

    while True:
        if stop_event is not None and stop_event.is_set():
            return

        result = report_local_snapshot_once()
        message = str(result.get("message") or "").strip()
        status = str(result.get("status") or "").strip()
        if status == "success":
            print(f"[网页同步] {message}")
        elif status == "error":
            print(f"[网页同步] {message}")

        if stop_event is not None:
            if stop_event.wait(interval_seconds):
                return
        else:
            import time
            time.sleep(interval_seconds)


def get_remote_machine_sections(exclude_machine_id=None, db_mode=ACCOUNT_DB_MODE_STONE):
    normalized_mode = normalize_account_db_mode(db_mode)
    runtime_context = get_machine_sync_runtime_context()
    expected_remote_machines = runtime_context.get("expected_remote_machines") or []
    generated_at = _serialize_datetime(datetime.now())
    sections = {}

    for expected in expected_remote_machines:
        if expected.machine_id == exclude_machine_id:
            continue
        sections[expected.machine_id] = {
            "machine_id": expected.machine_id,
            "db_mode": normalized_mode,
            "db_label": get_account_db_mode_label(normalized_mode),
            "machine_display_name": expected.machine_display_name,
            "source_type": REMOTE_SYNC_SOURCE_TYPE,
            "data_role": "remote_mirror",
            "data_role_label": "远端同步镜像",
            "is_read_only": False,
            "database_path": REMOTE_SYNC_MIRROR_DB_PATH,
            "generated_at": generated_at,
            "rows": [],
            "machine_daily_summaries": [],
            "message": "尚未收到最近一次局域网同步上报。",
            "status": "empty",
            "last_report_time": "",
            "source_client_ip": "",
            "allow_remote_writeback": False,
            "edit_meta": _build_remote_edit_meta(),
        }

    if not os.path.isfile(REMOTE_SYNC_MIRROR_DB_PATH):
        return list(sections.values())

    init_conn = None
    try:
        init_conn = sqlite3.connect(REMOTE_SYNC_MIRROR_DB_PATH)
        _ensure_remote_sync_table(init_conn)
        _ensure_remote_daily_summary_table(init_conn)
        init_conn.commit()
    except sqlite3.Error:
        return list(sections.values())
    finally:
        try:
            if init_conn is not None:
                init_conn.close()
        except Exception:
            pass

    conn = sqlite3.connect(f"file:{REMOTE_SYNC_MIRROR_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            SELECT
                machine_id,
                db_mode,
                machine_display_name,
                current_execution_slot,
                nickname,
                region,
                sort_order,
                baseline_item_count,
                locked_item_count,
                tradable_item_count,
                current_balance,
                round_status,
                updated_at,
                last_account_end_time,
                last_limit_time,
                allow_purchase,
                runtime_window_remaining_seconds,
                cooldown_remaining_seconds,
                report_time,
                source_client_ip
            FROM {REMOTE_SYNC_TABLE}
            ORDER BY machine_display_name, sort_order, current_execution_slot
            """
        ).fetchall()
        summary_rows = []
        if _remote_table_exists(conn, REMOTE_SYNC_DAILY_SUMMARY_TABLE):
            summary_rows = conn.execute(
                f"""
                SELECT
                machine_id,
                db_mode,
                machine_display_name,
                    stat_date,
                    total_purchase_success_count,
                    total_listing_success_count,
                    total_purchase_fail_count
            FROM {REMOTE_SYNC_DAILY_SUMMARY_TABLE}
            ORDER BY machine_display_name, stat_date DESC
                """
            ).fetchall()
    except sqlite3.Error:
        return list(sections.values())
    finally:
        conn.close()

    for row in rows:
        machine_id = str(row["machine_id"] or "").strip()
        if not machine_id or machine_id == exclude_machine_id:
            continue
        row_db_mode = normalize_account_db_mode(row["db_mode"])
        if row_db_mode != normalized_mode:
            continue

        section = sections.setdefault(
            machine_id,
            {
                "machine_id": machine_id,
                "db_mode": normalized_mode,
                "db_label": get_account_db_mode_label(normalized_mode),
                "machine_display_name": str(row["machine_display_name"] or machine_id).strip(),
                "source_type": REMOTE_SYNC_SOURCE_TYPE,
                "data_role": "remote_mirror",
                "data_role_label": "远端同步镜像",
                "is_read_only": False,
                "database_path": REMOTE_SYNC_MIRROR_DB_PATH,
                "generated_at": generated_at,
                "rows": [],
                "machine_daily_summaries": [],
                "message": "",
                "status": "ready",
                "last_report_time": "",
                "source_client_ip": "",
                "allow_remote_writeback": False,
                "edit_meta": _build_remote_edit_meta(),
            },
        )

        report_time = _serialize_datetime(row["report_time"]) or ""
        if report_time and report_time > str(section.get("last_report_time") or ""):
            section["last_report_time"] = report_time
        source_client_ip = str(row["source_client_ip"] or "").strip()
        if source_client_ip:
            section["source_client_ip"] = source_client_ip
            section["allow_remote_writeback"] = True

        section["rows"].append(
            {
                "current_execution_slot": _parse_int(row["current_execution_slot"]),
                "nickname": str(row["nickname"] or "").strip(),
                "region": str(row["region"] or "").strip(),
                "sort_order": _parse_int(row["sort_order"]),
                "baseline_item_count": _parse_int(row["baseline_item_count"]),
                "locked_item_count": _parse_int(row["locked_item_count"]),
                "tradable_item_count": _parse_int(row["tradable_item_count"]),
                "current_balance": str(row["current_balance"] or "").strip(),
                "current_balance_wan": _format_balance_for_wan_input(row["current_balance"]),
                "round_status": str(row["round_status"] or "").strip(),
                "updated_at": _serialize_datetime(row["updated_at"]),
                "last_account_end_time": _serialize_datetime(row["last_account_end_time"]),
                "last_limit_time": _serialize_datetime(row["last_limit_time"]),
                "allow_purchase": bool(row["allow_purchase"]),
                "runtime_window_remaining_seconds": max(
                    0,
                    _parse_int(row["runtime_window_remaining_seconds"]),
                ),
                "cooldown_remaining_seconds": max(0, _parse_int(row["cooldown_remaining_seconds"])),
                "report_time": report_time,
            }
        )

    for summary_row in summary_rows:
        machine_id = str(summary_row["machine_id"] or "").strip()
        if not machine_id or machine_id == exclude_machine_id:
            continue
        row_db_mode = normalize_account_db_mode(summary_row["db_mode"])
        if row_db_mode != normalized_mode:
            continue
        section = sections.setdefault(
            machine_id,
            {
                "machine_id": machine_id,
                "db_mode": normalized_mode,
                "db_label": get_account_db_mode_label(normalized_mode),
                "machine_display_name": str(summary_row["machine_display_name"] or machine_id).strip(),
                "source_type": REMOTE_SYNC_SOURCE_TYPE,
                "data_role": "remote_mirror",
                "data_role_label": "远端同步镜像",
                "is_read_only": False,
                "database_path": REMOTE_SYNC_MIRROR_DB_PATH,
                "generated_at": generated_at,
                "rows": [],
                "machine_daily_summaries": [],
                "message": "",
                "status": "ready",
                "last_report_time": "",
                "source_client_ip": "",
                "allow_remote_writeback": False,
                "edit_meta": _build_remote_edit_meta(),
            },
        )
        section["machine_daily_summaries"].append(
            {
                "stat_date": str(summary_row["stat_date"] or "").strip(),
                "total_purchase_success_count": max(0, _parse_int(summary_row["total_purchase_success_count"])),
                "total_listing_success_count": max(0, _parse_int(summary_row["total_listing_success_count"])),
                "total_purchase_fail_count": max(0, _parse_int(summary_row["total_purchase_fail_count"])),
            }
        )

    for section in sections.values():
        section["machine_daily_summaries"] = sorted(
            list(section.get("machine_daily_summaries") or []),
            key=lambda item: str(item.get("stat_date") or ""),
            reverse=True,
        )
        if section.get("rows") and section.get("allow_remote_writeback"):
            section["message"] = "镜像来自远端最近一次上报；提交修改时会转发到远端本机 canonical 真源。"
        elif section.get("rows"):
            section["message"] = "当前只拿到远端镜像内容，但缺少可回连地址，暂不可提交最小写回。"

    sections_list = list(sections.values())
    sections_list.sort(
        key=lambda item: (
            item.get("machine_display_name") or "",
            item.get("machine_id") or "",
        )
    )
    return sections_list
