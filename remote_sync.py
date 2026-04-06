"""局域网最小账号快照同步与远端镜像存储。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import os
import sqlite3
from urllib import error as urllib_error
from urllib import request as urllib_request

from account_view_repo import get_account_view_rows
from config import REMOTE_SYNC_MIRROR_DB_PATH, WEB_VIEW_PORT
from machine_sync_config import get_machine_sync_runtime_context


REMOTE_SYNC_SOURCE_TYPE = "remote_sync_mirror"
REMOTE_SYNC_TABLE = "remote_account_snapshots"


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
            machine_display_name TEXT NOT NULL DEFAULT '',
            current_execution_slot INTEGER NOT NULL,
            nickname TEXT NOT NULL DEFAULT '',
            region TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            baseline_item_count INTEGER NOT NULL DEFAULT 0,
            current_balance TEXT NOT NULL DEFAULT '',
            round_status TEXT NOT NULL DEFAULT '',
            updated_at TEXT,
            last_account_end_time TEXT,
            last_limit_time TEXT,
            allow_purchase INTEGER NOT NULL DEFAULT 0,
            cooldown_remaining_seconds INTEGER NOT NULL DEFAULT 0,
            report_time TEXT,
            source_client_ip TEXT NOT NULL DEFAULT '',
            received_at TEXT,
            PRIMARY KEY (machine_id, current_execution_slot)
        )
        """
    )


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
        "current_balance": str(item.get("current_balance") or "").strip(),
        "round_status": str(item.get("round_status") or "").strip(),
        "updated_at": _serialize_datetime(item.get("updated_at")),
        "last_account_end_time": _serialize_datetime(item.get("last_account_end_time")),
        "last_limit_time": _serialize_datetime(item.get("last_limit_time")),
        "allow_purchase": 1 if bool(item.get("allow_purchase")) else 0,
        "cooldown_remaining_seconds": max(
            0,
            _parse_int(item.get("cooldown_remaining_seconds"), default=0),
        ),
        "report_time": _serialize_datetime(item.get("report_time")) or report_time,
    }


def save_remote_sync_report(payload, client_ip=""):
    if not isinstance(payload, dict):
        raise ValueError("同步上报载荷必须是 JSON 对象")

    machine_id = str(payload.get("machine_id") or "").strip()
    machine_display_name = str(payload.get("machine_display_name") or "").strip()
    report_time = _serialize_datetime(payload.get("report_time")) or _serialize_datetime(datetime.now())
    raw_accounts = payload.get("accounts")

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

    os.makedirs(os.path.dirname(REMOTE_SYNC_MIRROR_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(REMOTE_SYNC_MIRROR_DB_PATH)
    try:
        _ensure_remote_sync_table(conn)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            f"DELETE FROM {REMOTE_SYNC_TABLE} WHERE machine_id = ?",
            (machine_id,),
        )
        for account in normalized_accounts:
            conn.execute(
                f"""
                INSERT INTO {REMOTE_SYNC_TABLE} (
                    machine_id,
                    machine_display_name,
                    current_execution_slot,
                    nickname,
                    region,
                    sort_order,
                    baseline_item_count,
                    current_balance,
                    round_status,
                    updated_at,
                    last_account_end_time,
                    last_limit_time,
                    allow_purchase,
                    cooldown_remaining_seconds,
                    report_time,
                    source_client_ip,
                    received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    machine_id,
                    machine_display_name,
                    account["current_execution_slot"],
                    account["nickname"],
                    account["region"],
                    account["sort_order"],
                    account["baseline_item_count"],
                    account["current_balance"],
                    account["round_status"],
                    account["updated_at"],
                    account["last_account_end_time"],
                    account["last_limit_time"],
                    account["allow_purchase"],
                    account["cooldown_remaining_seconds"],
                    account["report_time"],
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
        "machine_display_name": machine_display_name,
        "snapshot_count": len(normalized_accounts),
        "report_time": report_time,
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


def build_local_snapshot_payload():
    runtime_context = get_machine_sync_runtime_context()
    if runtime_context.get("config_status") != "ready":
        return {
            "status": "error",
            "message": f"本机网页同步配置不可用：{runtime_context.get('config_error')}",
        }

    view_rows_result = get_account_view_rows()
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
                "current_balance": str(row.get("current_balance") or "").strip(),
                "round_status": str(row.get("round_status") or "").strip(),
                "updated_at": _serialize_datetime(row.get("updated_at")),
                "last_account_end_time": _serialize_datetime(row.get("last_account_end_time")),
                "last_limit_time": _serialize_datetime(row.get("last_limit_time")),
                "allow_purchase": bool(row.get("allow_purchase")),
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
            "machine_display_name": runtime_context.get("machine_display_name"),
            "report_time": report_time,
            "accounts": account_snapshots,
        },
    }


def report_local_snapshot_once(timeout=2.0):
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

    build_result = build_local_snapshot_payload()
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


def get_remote_machine_sections(exclude_machine_id=None):
    runtime_context = get_machine_sync_runtime_context()
    expected_remote_machines = runtime_context.get("expected_remote_machines") or []
    generated_at = _serialize_datetime(datetime.now())
    sections = {}

    for expected in expected_remote_machines:
        if expected.machine_id == exclude_machine_id:
            continue
        sections[expected.machine_id] = {
            "machine_id": expected.machine_id,
            "machine_display_name": expected.machine_display_name,
            "source_type": REMOTE_SYNC_SOURCE_TYPE,
            "data_role": "remote_mirror",
            "data_role_label": "远端同步镜像",
            "is_read_only": True,
            "database_path": REMOTE_SYNC_MIRROR_DB_PATH,
            "generated_at": generated_at,
            "rows": [],
            "message": "尚未收到最近一次局域网同步上报。",
            "status": "empty",
            "last_report_time": "",
        }

    if not os.path.isfile(REMOTE_SYNC_MIRROR_DB_PATH):
        return list(sections.values())

    conn = sqlite3.connect(f"file:{REMOTE_SYNC_MIRROR_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            SELECT
                machine_id,
                machine_display_name,
                current_execution_slot,
                nickname,
                region,
                sort_order,
                baseline_item_count,
                current_balance,
                round_status,
                updated_at,
                last_account_end_time,
                last_limit_time,
                allow_purchase,
                cooldown_remaining_seconds,
                report_time
            FROM {REMOTE_SYNC_TABLE}
            ORDER BY machine_display_name, sort_order, current_execution_slot
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

        section = sections.setdefault(
            machine_id,
            {
                "machine_id": machine_id,
                "machine_display_name": str(row["machine_display_name"] or machine_id).strip(),
                "source_type": REMOTE_SYNC_SOURCE_TYPE,
                "data_role": "remote_mirror",
                "data_role_label": "远端同步镜像",
                "is_read_only": True,
                "database_path": REMOTE_SYNC_MIRROR_DB_PATH,
                "generated_at": generated_at,
                "rows": [],
                "message": "",
                "status": "ready",
                "last_report_time": "",
            },
        )

        report_time = _serialize_datetime(row["report_time"]) or ""
        if report_time and report_time > str(section.get("last_report_time") or ""):
            section["last_report_time"] = report_time

        section["rows"].append(
            {
                "current_execution_slot": _parse_int(row["current_execution_slot"]),
                "nickname": str(row["nickname"] or "").strip(),
                "region": str(row["region"] or "").strip(),
                "sort_order": _parse_int(row["sort_order"]),
                "baseline_item_count": _parse_int(row["baseline_item_count"]),
                "current_balance": str(row["current_balance"] or "").strip(),
                "current_balance_wan": _format_balance_for_wan_input(row["current_balance"]),
                "round_status": str(row["round_status"] or "").strip(),
                "updated_at": _serialize_datetime(row["updated_at"]),
                "last_account_end_time": _serialize_datetime(row["last_account_end_time"]),
                "last_limit_time": _serialize_datetime(row["last_limit_time"]),
                "allow_purchase": bool(row["allow_purchase"]),
                "cooldown_remaining_seconds": max(0, _parse_int(row["cooldown_remaining_seconds"])),
                "report_time": report_time,
            }
        )

    sections_list = list(sections.values())
    sections_list.sort(
        key=lambda item: (
            item.get("machine_display_name") or "",
            item.get("machine_id") or "",
        )
    )
    return sections_list
