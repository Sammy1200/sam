"""SQLite account lookup and round write-back helpers."""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import json
import os
import sqlite3

from config import (
    ACCOUNT_LIMIT_COOLDOWN_SECONDS,
    ACCOUNT_STATS_DB_PATH,
    EXECUTION_SLOT_COUNT,
    EXECUTION_SLOT_NICKNAMES,
    SCRIPT_DIR,
    THREAD6_RUNTIME_DB_PATH,
)
from live_paths import log_resolved_live_path, resolve_account_stats_db_path


_DB_SUFFIXES = (".db", ".sqlite", ".sqlite3")
_DB_HINT_NAMES = (
    "accounts",
    "account",
    "account_data",
    "account_stats",
    "stats",
    "data",
    "gameclicker",
)
_TABLE_HINTS = (
    "accounts",
    "account",
    "account_data",
    "account_stats",
    "stats",
    "users",
    "roles",
    "\u8d26\u53f7",
    "\u8d26\u53f7\u6570\u636e",
)
_NICKNAME_ALIASES = {
    "nickname",
    "nick_name",
    "current_nickname",
    "account_nickname",
    "player_nickname",
    "name",
    "\u6635\u79f0",
    "\u8d26\u53f7\u6635\u79f0",
    "\u89d2\u8272\u6635\u79f0",
    "\u8d26\u53f7\u540d",
    "\u89d2\u8272\u540d",
}
_BASELINE_ALIASES = {
    "baseline_initial_count",
    "baseline_count",
    "baseline_item_count",
    "initial_count",
    "item_count",
    "base_count",
    "\u57fa\u7ebf\u521d\u59cb\u6570\u91cf",
    "\u57fa\u7ebf\u6570\u91cf",
    "\u521d\u59cb\u6570\u91cf",
    "\u521d\u59cb\u9053\u5177\u6570\u91cf",
    "\u9053\u5177\u57fa\u7ebf\u6570\u91cf",
}
_LAST_LIMIT_ALIASES = {
    "last_limit_time",
    "last_restricted_time",
    "last_limit_at",
    "last_account_limit_time",
    "limit_time",
    "\u6700\u540e\u4e00\u6b21\u9650\u5236\u65f6\u95f4",
    "\u6700\u540e\u9650\u5236\u65f6\u95f4",
    "\u9650\u5236\u65f6\u95f4",
}
_LAST_ACCOUNT_END_ALIASES = {
    "last_account_end_time",
    "last_logout_time",
    "last_sign_out_time",
    "last_exit_time",
    "last_end_time",
    "\u6700\u540e\u4e0b\u53f7\u65f6\u95f4",
    "\u6700\u540e\u4e00\u6b21\u4e0b\u53f7\u65f6\u95f4",
    "\u6700\u540e\u79bb\u53f7\u65f6\u95f4",
}
_UPDATED_AT_ALIASES = {
    "updated_at",
    "update_time",
    "updated_time",
    "last_update_time",
    "modified_at",
    "\u66f4\u65b0\u65f6\u95f4",
    "\u6700\u8fd1\u66f4\u65b0\u65f6\u95f4",
}
_CURRENT_EXECUTION_SLOT_ALIASES = {
    "current_execution_slot",
    "execution_slot",
    "slot_index",
    "current_slot",
    "run_slot",
    "\u5f53\u524d\u6267\u884c\u4f4d",
    "\u6267\u884c\u4f4d",
}
_ROUND_PURCHASE_SUCCESS_ALIASES = {
    "round_purchase_success_count",
    "round_purchase_success",
    "purchase_success_count",
    "round_success_count",
    "\u672c\u8f6e\u62a2\u8d2d\u6210\u529f\u6570",
    "\u672c\u8f6e\u6210\u529f\u6570",
    "\u62a2\u8d2d\u6210\u529f\u6570",
}
_ROUND_LISTING_SUCCESS_ALIASES = {
    "round_listing_success_count",
    "round_listing_success",
    "listing_success_count",
    "round_list_success_count",
    "\u672c\u8f6e\u4e0a\u67b6\u6210\u529f\u6570",
    "\u672c\u8f6e\u4e0a\u67b6\u6570",
    "\u4e0a\u67b6\u6210\u529f\u6570",
}
_ROUND_PURCHASE_FAIL_ALIASES = {
    "round_purchase_fail_count",
    "round_purchase_fail",
    "purchase_fail_count",
    "round_fail_count",
    "\u672c\u8f6e\u62a2\u8d2d\u5931\u8d25\u6570",
    "\u672c\u8f6e\u5931\u8d25\u6570",
    "\u62a2\u8d2d\u5931\u8d25\u6570",
}
_CURRENT_BALANCE_ALIASES = {
    "round_current_balance",
    "current_balance",
    "balance",
    "account_balance",
    "\u5f53\u524d\u4f59\u989d",
    "\u4f59\u989d",
}
_PURCHASE_RUNNING_SECONDS_ALIASES = {
    "round_purchase_running_seconds",
    "purchase_running_seconds",
    "round_running_seconds",
    "running_seconds",
    "\u62a2\u8d2d\u8fd0\u884c\u65f6\u95f4",
    "\u672c\u8f6e\u8fd0\u884c\u65f6\u95f4",
    "\u8fd0\u884c\u65f6\u95f4",
}
_ROUND_STATUS_ALIASES = {
    "round_status",
    "current_round_status",
    "status",
    "\u672c\u8f6e\u72b6\u6001",
    "\u72b6\u6001",
}

ROUND_STATUS_RUNNING = "\u8fd0\u884c\u4e2d"
ROUND_STATUS_LIMITED = "\u8d26\u53f7\u9650\u5236"
ROUND_STATUS_BALANCE_LOW = "\u4f59\u989d\u4e0d\u8db3"
ROUND_STATUS_RUNTIME_REACHED = "\u62a2\u8d2d\u65f6\u957f\u5df2\u5230"
ROUND_STATUS_READY = "\u5df2\u51c6\u5907"
ROUND_STATUS_NORMAL_END = "\u6b63\u5e38\u7ed3\u675f"
ROUND_STATUS_UNKNOWN = "\u672a\u77e5\u5f02\u5e38"
ROUND_STATUS_MANUAL_PAUSE = "\u4eba\u5de5\u6682\u505c"
ROUND_STATUS_LEGACY_MANUAL_END = "\u624b\u52a8\u7ed3\u675f"

ROUND_STATUS_VALUES = (
    ROUND_STATUS_RUNNING,
    ROUND_STATUS_LIMITED,
    ROUND_STATUS_BALANCE_LOW,
    ROUND_STATUS_RUNTIME_REACHED,
    ROUND_STATUS_READY,
    ROUND_STATUS_UNKNOWN,
    ROUND_STATUS_MANUAL_PAUSE,
)
ROUND_STATUS_VALUE_ALIASES = {
    ROUND_STATUS_RUNNING: ROUND_STATUS_RUNNING,
    ROUND_STATUS_LIMITED: ROUND_STATUS_LIMITED,
    ROUND_STATUS_BALANCE_LOW: ROUND_STATUS_BALANCE_LOW,
    ROUND_STATUS_RUNTIME_REACHED: ROUND_STATUS_RUNTIME_REACHED,
    ROUND_STATUS_READY: ROUND_STATUS_READY,
    ROUND_STATUS_NORMAL_END: ROUND_STATUS_MANUAL_PAUSE,
    ROUND_STATUS_UNKNOWN: ROUND_STATUS_UNKNOWN,
    ROUND_STATUS_MANUAL_PAUSE: ROUND_STATUS_MANUAL_PAUSE,
    ROUND_STATUS_LEGACY_MANUAL_END: ROUND_STATUS_MANUAL_PAUSE,
    "\u62a2\u8d2d\u4e2d": ROUND_STATUS_RUNNING,
    "running": ROUND_STATUS_RUNNING,
    "account_limited": ROUND_STATUS_LIMITED,
    "limited": ROUND_STATUS_LIMITED,
    "balance_low": ROUND_STATUS_BALANCE_LOW,
    "insufficient_balance": ROUND_STATUS_BALANCE_LOW,
    "runtime_reached": ROUND_STATUS_RUNTIME_REACHED,
    "ready": ROUND_STATUS_READY,
    "normal_end": ROUND_STATUS_MANUAL_PAUSE,
    "unknown": ROUND_STATUS_UNKNOWN,
    "unknown_error": ROUND_STATUS_UNKNOWN,
    "manual_end": ROUND_STATUS_MANUAL_PAUSE,
    "manual_pause": ROUND_STATUS_MANUAL_PAUSE,
}

CANONICAL_ACCOUNT_STATS_TABLE = "account_stats"
CANONICAL_ACCOUNT_STATS_COLUMNS = (
    "nickname",
    "baseline_item_count",
    "last_limit_time",
    "last_account_end_time",
    "updated_at",
    "current_execution_slot",
    "round_purchase_success_count",
    "round_listing_success_count",
    "round_purchase_fail_count",
    "current_balance",
    "purchase_running_seconds",
    "runtime_window_start_time",
    "round_status",
)
CANONICAL_BASELINE_FIELDS = (
    "nickname",
    "baseline_item_count",
    "current_execution_slot",
)
CANONICAL_ROUND_FIELDS = (
    "round_purchase_success_count",
    "round_listing_success_count",
    "round_purchase_fail_count",
    "current_balance",
)
CANONICAL_STATUS_FIELDS = (
    "round_status",
)
CANONICAL_TIME_FIELDS = (
    "purchase_running_seconds",
    "runtime_window_start_time",
    "last_limit_time",
    "last_account_end_time",
    "updated_at",
)
CANONICAL_PRESERVED_FOUNDATION_FIELDS = (
    "nickname",
    "current_execution_slot",
    "baseline_item_count",
    "current_balance",
)
CANONICAL_BOUNDARY_FIELDS = (
)
CANONICAL_RESETTABLE_RUNTIME_FIELDS = (
    "round_purchase_success_count",
    "round_listing_success_count",
    "round_purchase_fail_count",
    "purchase_running_seconds",
    "runtime_window_start_time",
    "round_status",
    "last_limit_time",
    "last_account_end_time",
)
CANONICAL_RESET_MODE_CONSERVATIVE = "conservative"
CANONICAL_RESET_MODE_AGGRESSIVE = "aggressive"
CANONICAL_RESET_MODE_VALUES = (
    CANONICAL_RESET_MODE_CONSERVATIVE,
    CANONICAL_RESET_MODE_AGGRESSIVE,
)
CANONICAL_DB_HINT_PATHS = (
    ACCOUNT_STATS_DB_PATH,
    THREAD6_RUNTIME_DB_PATH,
    os.path.join(SCRIPT_DIR, "account_stats.sqlite3"),
    os.path.join(SCRIPT_DIR, "account_stats.db"),
    os.path.join(SCRIPT_DIR, "account_data.sqlite3"),
    os.path.join(SCRIPT_DIR, "account_data.db"),
)


def _iter_canonical_db_hint_paths():
    resolved_primary = resolve_account_stats_db_path()
    seen = set()
    for db_path in (resolved_primary.path, *CANONICAL_DB_HINT_PATHS):
        normalized = os.path.abspath(str(db_path or "").strip()) if str(db_path or "").strip() else ""
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        yield normalized
MACHINE_DAILY_SUMMARY_TABLE = "machine_daily_summaries"
MACHINE_DAILY_SUMMARY_EVENT_PURCHASE_SUCCESS = "purchase_success"
MACHINE_DAILY_SUMMARY_EVENT_LISTING_SUCCESS = "listing_success"
MACHINE_DAILY_SUMMARY_EVENT_PURCHASE_FAIL = "purchase_fail"
MACHINE_DAILY_SUMMARY_EVENT_VALUES = (
    MACHINE_DAILY_SUMMARY_EVENT_PURCHASE_SUCCESS,
    MACHINE_DAILY_SUMMARY_EVENT_LISTING_SUCCESS,
    MACHINE_DAILY_SUMMARY_EVENT_PURCHASE_FAIL,
)


@dataclass
class AccountRecord:
    nickname: str
    baseline_item_count: int
    last_limit_time: datetime | None
    database_path: str
    table_name: str
    last_account_end_time: datetime | None = None
    updated_at: datetime | None = None
    current_execution_slot: int | None = None


@dataclass
class AccountLookupResult:
    status: str
    reason: str
    record: AccountRecord | None = None


@dataclass
class AccountRoundWritePayload:
    baseline_item_count: int
    round_purchase_success_count: int
    round_listing_success_count: int
    round_purchase_fail_count: int
    current_balance: str
    purchase_running_seconds: int
    round_status: str
    updated_at: datetime
    last_limit_time: datetime | None = None
    update_last_limit_time: bool = False
    last_account_end_time: datetime | None = None
    update_last_account_end_time: bool = False
    current_execution_slot: int | None = None


@dataclass
class AccountStatsRecord:
    nickname: str
    baseline_item_count: int = 0
    last_limit_time: datetime | None = None
    last_account_end_time: datetime | None = None
    updated_at: datetime | None = None
    current_execution_slot: int | None = None
    round_purchase_success_count: int = 0
    round_listing_success_count: int = 0
    round_purchase_fail_count: int = 0
    current_balance: str = ""
    purchase_running_seconds: int = 0
    runtime_window_start_time: datetime | None = None
    round_status: str = ROUND_STATUS_MANUAL_PAUSE


@dataclass
class AccountWriteResult:
    status: str
    reason: str
    new_baseline_item_count: int | None = None


def compute_item_quantity(
    baseline_item_count,
    round_purchase_success_count,
    round_listing_success_count,
):
    """线程 2 当前真实道具库存口径。"""
    return int(baseline_item_count)


def compute_new_baseline_item_count(
    baseline_item_count,
    round_purchase_success_count,
    round_listing_success_count,
):
    """线程 2 当前真实道具库存回写口径。"""
    return compute_item_quantity(
        baseline_item_count,
        round_purchase_success_count,
        round_listing_success_count,
    )


def build_canonical_account_stats_table_sql(table_name=CANONICAL_ACCOUNT_STATS_TABLE):
    """返回线程 2 统一字段表结构。"""
    escaped_status_values = ", ".join(
        "'" + value.replace("'", "''") + "'" for value in ROUND_STATUS_VALUES
    )
    return f"""
        CREATE TABLE IF NOT EXISTS {_quote_identifier(table_name)} (
            nickname TEXT PRIMARY KEY,
            baseline_item_count INTEGER NOT NULL DEFAULT 0,
            last_limit_time TEXT,
            last_account_end_time TEXT,
            updated_at TEXT,
            current_execution_slot INTEGER,
            round_purchase_success_count INTEGER NOT NULL DEFAULT 0,
            round_listing_success_count INTEGER NOT NULL DEFAULT 0,
            round_purchase_fail_count INTEGER NOT NULL DEFAULT 0,
            current_balance TEXT NOT NULL DEFAULT '',
            purchase_running_seconds INTEGER NOT NULL DEFAULT 0,
            runtime_window_start_time TEXT,
            round_status TEXT NOT NULL DEFAULT '{ROUND_STATUS_MANUAL_PAUSE}'
                CHECK (round_status IN ({escaped_status_values}))
        )
    """


def build_machine_daily_summary_table_sql(table_name=MACHINE_DAILY_SUMMARY_TABLE):
    return f"""
        CREATE TABLE IF NOT EXISTS {_quote_identifier(table_name)} (
            machine_id TEXT NOT NULL,
            machine_display_name TEXT NOT NULL DEFAULT '',
            stat_date TEXT NOT NULL,
            total_purchase_success_count INTEGER NOT NULL DEFAULT 0,
            total_listing_success_count INTEGER NOT NULL DEFAULT 0,
            total_purchase_fail_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT,
            PRIMARY KEY (machine_id, stat_date)
        )
    """


@dataclass
class RuntimeExecutionState:
    current_execution_slot: int | None = None
    current_nickname: str = ""
    current_account_index: int | None = None
    current_server_index: int | None = None
    slot_nicknames: dict | None = None
    updated_at: datetime | None = None


def _normalize_name(value):
    if value is None:
        return ""
    return "".join(ch.lower() for ch in str(value) if ch.isalnum())


_TABLE_HINT_NORMALIZED = {_normalize_name(value) for value in _TABLE_HINTS}
_COLUMN_ALIAS_SETS = {
    "nickname": {_normalize_name(value) for value in _NICKNAME_ALIASES},
    "baseline": {_normalize_name(value) for value in _BASELINE_ALIASES},
    "last_limit": {_normalize_name(value) for value in _LAST_LIMIT_ALIASES},
    "last_account_end": {_normalize_name(value) for value in _LAST_ACCOUNT_END_ALIASES},
    "updated_at": {_normalize_name(value) for value in _UPDATED_AT_ALIASES},
    "current_execution_slot": {_normalize_name(value) for value in _CURRENT_EXECUTION_SLOT_ALIASES},
    "round_purchase_success": {_normalize_name(value) for value in _ROUND_PURCHASE_SUCCESS_ALIASES},
    "round_listing_success": {_normalize_name(value) for value in _ROUND_LISTING_SUCCESS_ALIASES},
    "round_purchase_fail": {_normalize_name(value) for value in _ROUND_PURCHASE_FAIL_ALIASES},
    "current_balance": {_normalize_name(value) for value in _CURRENT_BALANCE_ALIASES},
    "purchase_running_seconds": {_normalize_name(value) for value in _PURCHASE_RUNNING_SECONDS_ALIASES},
    "round_status": {_normalize_name(value) for value in _ROUND_STATUS_ALIASES},
}
_WRITE_REQUIRED_KEYS = (
    "nickname",
    "baseline",
    "last_limit",
    "last_account_end",
    "updated_at",
    "round_purchase_success",
    "round_listing_success",
    "round_purchase_fail",
    "current_balance",
    "purchase_running_seconds",
    "round_status",
)


def _quote_identifier(name):
    return '"' + str(name).replace('"', '""') + '"'


def _iter_candidate_db_paths():
    seen = set()

    for name in _DB_HINT_NAMES:
        for suffix in _DB_SUFFIXES:
            path = os.path.join(SCRIPT_DIR, f"{name}{suffix}")
            if os.path.isfile(path) and path not in seen:
                seen.add(path)
                yield path

    for root, _, files in os.walk(SCRIPT_DIR):
        for file_name in files:
            if not file_name.lower().endswith(_DB_SUFFIXES):
                continue
            path = os.path.join(root, file_name)
            if path in seen:
                continue
            seen.add(path)
            yield path


def _resolve_column_mapping(column_names):
    mapping = {}
    for column_name in column_names:
        normalized = _normalize_name(column_name)
        for logical_name, alias_set in _COLUMN_ALIAS_SETS.items():
            if logical_name in mapping:
                continue
            if normalized in alias_set:
                mapping[logical_name] = column_name
                break
    return mapping


def _inspect_table(conn, table_name):
    pragma_sql = f"PRAGMA table_info({_quote_identifier(table_name)})"
    columns = conn.execute(pragma_sql).fetchall()
    if not columns:
        return None
    return _resolve_column_mapping([column[1] for column in columns])


def _get_table_column_names(conn, table_name):
    pragma_sql = f"PRAGMA table_info({_quote_identifier(table_name)})"
    return [column[1] for column in conn.execute(pragma_sql).fetchall()]


def _find_matching_table(conn):
    cursor = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    candidates = []

    for (table_name,) in cursor.fetchall():
        mapping = _inspect_table(conn, table_name)
        if not mapping:
            continue
        if "nickname" not in mapping or "baseline" not in mapping:
            continue

        score = 0
        if _normalize_name(table_name) in _TABLE_HINT_NORMALIZED:
            score += 2
        score += len(mapping)
        candidates.append((score, table_name, mapping))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    _, table_name, mapping = candidates[0]
    return table_name, mapping


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


def _canonical_table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _ensure_runtime_state_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS thread6_runtime_state (
            state_key TEXT PRIMARY KEY,
            current_execution_slot INTEGER,
            current_nickname TEXT,
            current_account_index INTEGER,
            current_server_index INTEGER,
            slot_nicknames_json TEXT,
            updated_at TEXT
        )
        """
    )


def read_runtime_execution_state():
    if not THREAD6_RUNTIME_DB_PATH or not os.path.isfile(THREAD6_RUNTIME_DB_PATH):
        return RuntimeExecutionState(slot_nicknames={})

    try:
        conn = sqlite3.connect(f"file:{THREAD6_RUNTIME_DB_PATH}?mode=ro", uri=True)
    except sqlite3.Error:
        return RuntimeExecutionState(slot_nicknames={})

    try:
        row = conn.execute(
            """
            SELECT
                current_execution_slot,
                current_nickname,
                current_account_index,
                current_server_index,
                slot_nicknames_json,
                updated_at
            FROM thread6_runtime_state
            WHERE state_key = 'default'
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return RuntimeExecutionState(slot_nicknames={})

        try:
            slot_nicknames = json.loads(row[4]) if row[4] else {}
        except json.JSONDecodeError:
            slot_nicknames = {}

        return RuntimeExecutionState(
            current_execution_slot=_parse_int(row[0]) or None,
            current_nickname=str(row[1] or "").strip(),
            current_account_index=_parse_int(row[2]) if row[2] not in (None, "") else None,
            current_server_index=_parse_int(row[3]) if row[3] not in (None, "") else None,
            slot_nicknames=slot_nicknames,
            updated_at=_parse_datetime(row[5]),
        )
    except sqlite3.Error:
        return RuntimeExecutionState(slot_nicknames={})
    finally:
        conn.close()


def write_runtime_execution_state(
    current_execution_slot,
    current_nickname,
    current_account_index,
    current_server_index,
    slot_nicknames,
):
    os.makedirs(os.path.dirname(THREAD6_RUNTIME_DB_PATH), exist_ok=True)

    try:
        conn = sqlite3.connect(THREAD6_RUNTIME_DB_PATH)
    except sqlite3.Error as exc:
        return AccountWriteResult("db_unavailable", str(exc))

    try:
        _ensure_runtime_state_table(conn)
        payload = (
            int(current_execution_slot),
            str(current_nickname or "").strip(),
            int(current_account_index),
            int(current_server_index),
            json.dumps(slot_nicknames or {}, ensure_ascii=False),
            _serialize_datetime(datetime.now()),
        )
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO thread6_runtime_state (
                state_key,
                current_execution_slot,
                current_nickname,
                current_account_index,
                current_server_index,
                slot_nicknames_json,
                updated_at
            ) VALUES ('default', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(state_key) DO UPDATE SET
                current_execution_slot = excluded.current_execution_slot,
                current_nickname = excluded.current_nickname,
                current_account_index = excluded.current_account_index,
                current_server_index = excluded.current_server_index,
                slot_nicknames_json = excluded.slot_nicknames_json,
                updated_at = excluded.updated_at
            """,
            payload,
        )
        conn.commit()
        return AccountWriteResult("success", "")
    except sqlite3.Error as exc:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        return AccountWriteResult("write_failed", str(exc))
    finally:
        conn.close()


def read_account_by_nickname(nickname):
    nickname = (nickname or "").strip()
    if not nickname:
        return AccountLookupResult("nickname_missing", "current nickname is empty")

    schema_errors = []
    db_errors = []
    matched_schema = False

    for db_path in _iter_candidate_db_paths():
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        except sqlite3.Error as exc:
            db_errors.append(f"{db_path}: {exc}")
            continue

        try:
            match = _find_matching_table(conn)
            if match is None:
                schema_errors.append(f"{db_path}: schema not found")
                continue

            matched_schema = True
            table_name, columns = match
            select_columns = [
                _quote_identifier(columns["nickname"]),
                _quote_identifier(columns["baseline"]),
            ]
            if "last_limit" in columns:
                select_columns.append(_quote_identifier(columns["last_limit"]))
            else:
                select_columns.append("NULL")
            if "last_account_end" in columns:
                select_columns.append(_quote_identifier(columns["last_account_end"]))
            else:
                select_columns.append("NULL")
            if "updated_at" in columns:
                select_columns.append(_quote_identifier(columns["updated_at"]))
            else:
                select_columns.append("NULL")
            if "current_execution_slot" in columns:
                select_columns.append(_quote_identifier(columns["current_execution_slot"]))
            else:
                select_columns.append("NULL")

            sql = (
                f"SELECT {', '.join(select_columns)} "
                f"FROM {_quote_identifier(table_name)} "
                f"WHERE {_quote_identifier(columns['nickname'])} = ? "
                "LIMIT 1"
            )
            row = conn.execute(sql, (nickname,)).fetchone()
            if row is None:
                continue

            record = AccountRecord(
                nickname=str(row[0]).strip(),
                baseline_item_count=_parse_int(row[1]),
                last_limit_time=_parse_datetime(row[2]),
                database_path=db_path,
                table_name=table_name,
                last_account_end_time=_parse_datetime(row[3]),
                updated_at=_parse_datetime(row[4]),
                current_execution_slot=_parse_int(row[5]) if row[5] not in (None, "") else None,
            )
            return AccountLookupResult("ready", "", record)
        except sqlite3.Error as exc:
            db_errors.append(f"{db_path}: {exc}")
        finally:
            conn.close()

    if matched_schema:
        return AccountLookupResult(
            "account_not_found",
            f"account record not found for nickname: {nickname}",
        )

    if schema_errors:
        return AccountLookupResult("schema_not_found", "; ".join(schema_errors))

    if db_errors:
        return AccountLookupResult("db_unavailable", "; ".join(db_errors))

    return AccountLookupResult("db_unavailable", "no sqlite database file found")


def _validate_round_status(round_status):
    return normalize_round_status_value(round_status) in ROUND_STATUS_VALUES


def normalize_round_status_value(round_status):
    text = str(round_status or "").strip()
    if not text:
        return ""
    return ROUND_STATUS_VALUE_ALIASES.get(text, text)


def _normalize_round_status_for_storage(round_status):
    normalized = normalize_round_status_value(round_status)
    if normalized not in ROUND_STATUS_VALUES:
        return ROUND_STATUS_MANUAL_PAUSE
    return normalized


def _get_round_status_cooldown_remaining_seconds(last_limit_time, now=None):
    if last_limit_time is None:
        return 0

    now_dt = now or datetime.now()
    allow_start_time = last_limit_time + timedelta(seconds=ACCOUNT_LIMIT_COOLDOWN_SECONDS)
    return int((allow_start_time - now_dt).total_seconds())


def restore_ready_account_status_if_needed(
    database_path,
    nickname,
    table_name=CANONICAL_ACCOUNT_STATS_TABLE,
    now=None,
):
    normalized_nickname = str(nickname or "").strip()
    if not normalized_nickname:
        return None, AccountWriteResult("nickname_missing", "current nickname is empty")
    if not database_path or not os.path.isfile(database_path):
        return None, AccountWriteResult("db_unavailable", f"database file not found: {database_path}")

    record = read_canonical_account_stats_record(database_path, normalized_nickname, table_name)
    if record is None:
        return None, AccountWriteResult(
            "account_not_found",
            f"account record not found for nickname: {normalized_nickname}",
        )

    normalized_status = _normalize_round_status_for_storage(record.round_status)
    if normalized_status not in (ROUND_STATUS_LIMITED, ROUND_STATUS_RUNTIME_REACHED):
        return record, AccountWriteResult("skipped", f"current status does not require recovery: {normalized_status}")

    now_dt = now or datetime.now()
    cooldown_remaining_seconds = _get_round_status_cooldown_remaining_seconds(
        record.last_limit_time,
        now=now_dt,
    )
    if cooldown_remaining_seconds > 0:
        return record, AccountWriteResult(
            "skipped",
            f"cooldown_remaining_seconds={cooldown_remaining_seconds}",
        )

    updated_record = replace(
        record,
        purchase_running_seconds=0,
        runtime_window_start_time=None,
        round_status=ROUND_STATUS_READY,
        updated_at=now_dt,
    )
    try:
        save_result = save_canonical_account_stats_record(database_path, updated_record, table_name)
    except Exception as exc:
        return record, AccountWriteResult("write_failed", f"restore ready status failed: {exc}")
    if save_result.status != "success":
        return record, save_result

    reloaded_record = read_canonical_account_stats_record(database_path, normalized_nickname, table_name)
    if reloaded_record is None:
        return updated_record, AccountWriteResult(
            "readback_failed",
            f"readback failed after restoring ready status for nickname: {normalized_nickname}",
        )
    return reloaded_record, save_result


def _row_to_account_stats_record(row):
    if row is None:
        return None

    round_status = normalize_round_status_value(row["round_status"])
    if round_status not in ROUND_STATUS_VALUES:
        round_status = ROUND_STATUS_MANUAL_PAUSE

    return AccountStatsRecord(
        nickname=str(row["nickname"] or "").strip(),
        baseline_item_count=_parse_int(row["baseline_item_count"]),
        last_limit_time=_parse_datetime(row["last_limit_time"]),
        last_account_end_time=_parse_datetime(row["last_account_end_time"]),
        updated_at=_parse_datetime(row["updated_at"]),
        current_execution_slot=(
            _parse_int(row["current_execution_slot"])
            if row["current_execution_slot"] not in (None, "")
            else None
        ),
        round_purchase_success_count=_parse_int(row["round_purchase_success_count"]),
        round_listing_success_count=_parse_int(row["round_listing_success_count"]),
        round_purchase_fail_count=_parse_int(row["round_purchase_fail_count"]),
        current_balance=str(row["current_balance"] or "").strip(),
        purchase_running_seconds=_parse_int(row["purchase_running_seconds"]),
        runtime_window_start_time=_parse_datetime(row["runtime_window_start_time"]),
        round_status=round_status,
    )


def _build_canonical_select_columns_sql(conn, table_name):
    existing_columns = set(_get_table_column_names(conn, table_name))
    select_columns = []
    for column_name in CANONICAL_ACCOUNT_STATS_COLUMNS:
        if column_name in existing_columns:
            select_columns.append(_quote_identifier(column_name))
        else:
            select_columns.append(f"NULL AS {_quote_identifier(column_name)}")
    return ", ".join(select_columns)


def _build_canonical_insert_sql(table_name):
    return (
        f"INSERT INTO {_quote_identifier(table_name)} ("
        f"{', '.join(_quote_identifier(name) for name in CANONICAL_ACCOUNT_STATS_COLUMNS)}"
        f") VALUES ({', '.join('?' for _ in CANONICAL_ACCOUNT_STATS_COLUMNS)})"
    )


def _account_stats_record_to_row_values(record):
    normalized_round_status = _normalize_round_status_for_storage(record.round_status)
    return (
        str(record.nickname).strip(),
        int(record.baseline_item_count),
        _serialize_datetime(record.last_limit_time),
        _serialize_datetime(record.last_account_end_time),
        _serialize_datetime(record.updated_at),
        int(record.current_execution_slot) if record.current_execution_slot is not None else None,
        int(record.round_purchase_success_count),
        int(record.round_listing_success_count),
        int(record.round_purchase_fail_count),
        str(record.current_balance or ""),
        int(record.purchase_running_seconds),
        _serialize_datetime(record.runtime_window_start_time),
        normalized_round_status,
    )


def _fetch_table_sql(conn, table_name):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    if row is None:
        return ""
    if isinstance(row, sqlite3.Row):
        return str(row["sql"] or "")
    return str(row[0] or "")


def _canonical_status_schema_requires_rebuild(conn, table_name):
    create_sql = _fetch_table_sql(conn, table_name)
    if not create_sql:
        return False
    return (
        ROUND_STATUS_LEGACY_MANUAL_END in create_sql
        or ROUND_STATUS_NORMAL_END in create_sql
        or ROUND_STATUS_MANUAL_PAUSE not in create_sql
        or ROUND_STATUS_RUNTIME_REACHED not in create_sql
        or ROUND_STATUS_READY not in create_sql
    )


def _rebuild_canonical_account_stats_table(conn, table_name):
    select_columns_sql = _build_canonical_select_columns_sql(conn, table_name)
    existing_rows = conn.execute(
        f"SELECT {select_columns_sql} FROM {_quote_identifier(table_name)}"
    ).fetchall()

    restored_records = []
    for row in existing_rows:
        record = _row_to_account_stats_record(row)
        if record is None or not record.nickname:
            continue
        record.round_status = _normalize_round_status_for_storage(record.round_status)
        restored_records.append(record)

    legacy_table_name = f"{table_name}__legacy_status_schema"
    if _canonical_table_exists(conn, legacy_table_name):
        conn.execute(f"DROP TABLE {_quote_identifier(legacy_table_name)}")

    conn.execute(f"ALTER TABLE {_quote_identifier(table_name)} RENAME TO {_quote_identifier(legacy_table_name)}")
    conn.execute(build_canonical_account_stats_table_sql(table_name))
    if restored_records:
        conn.executemany(
            _build_canonical_insert_sql(table_name),
            [_account_stats_record_to_row_values(record) for record in restored_records],
        )
    conn.execute(f"DROP TABLE {_quote_identifier(legacy_table_name)}")


def _build_legacy_cleanup_summary(rows):
    status_counts = {}
    legacy_status_count = 0
    invalid_status_count = 0
    round_field_residue_count = 0
    runtime_field_residue_count = 0
    cooldown_present_count = 0
    end_time_present_count = 0
    updated_at_present_count = 0
    preserve_balance_count = 0
    preserve_item_count = 0
    conservative_reset_candidates = 0
    aggressive_reset_candidates = 0

    for row in rows:
        raw_status = str(row["round_status"] or "").strip()
        normalized_status = normalize_round_status_value(raw_status)
        if normalized_status not in ROUND_STATUS_VALUES:
            normalized_status = ROUND_STATUS_MANUAL_PAUSE
            invalid_status_count += 1
        elif normalized_status != raw_status:
            legacy_status_count += 1

        status_counts[normalized_status] = status_counts.get(normalized_status, 0) + 1

        has_round_residue = any(
            _parse_int(row[field_name]) > 0
            for field_name in (
                "round_purchase_success_count",
                "round_listing_success_count",
                "round_purchase_fail_count",
            )
        )
        has_runtime_residue = (
            _parse_int(row["purchase_running_seconds"]) > 0
            or str(row["runtime_window_start_time"] or "").strip() != ""
        )
        if has_round_residue:
            round_field_residue_count += 1
        if has_runtime_residue:
            runtime_field_residue_count += 1
        if str(row["last_limit_time"] or "").strip():
            cooldown_present_count += 1
        if str(row["last_account_end_time"] or "").strip():
            end_time_present_count += 1
        if str(row["updated_at"] or "").strip():
            updated_at_present_count += 1
        if str(row["current_balance"] or "").strip():
            preserve_balance_count += 1
        if _parse_int(row["baseline_item_count"]) > 0:
            preserve_item_count += 1

        if has_round_residue or has_runtime_residue or raw_status != normalized_status or not raw_status:
            conservative_reset_candidates += 1

        if (
            has_round_residue
            or has_runtime_residue
            or raw_status != ROUND_STATUS_MANUAL_PAUSE
            or str(row["last_limit_time"] or "").strip()
            or str(row["last_account_end_time"] or "").strip()
            or str(row["updated_at"] or "").strip()
        ):
            aggressive_reset_candidates += 1

    return {
        "total_records": len(rows),
        "status_counts": status_counts,
        "legacy_status_count": legacy_status_count,
        "invalid_status_count": invalid_status_count,
        "round_field_residue_count": round_field_residue_count,
        "runtime_field_residue_count": runtime_field_residue_count,
        "cooldown_present_count": cooldown_present_count,
        "last_account_end_present_count": end_time_present_count,
        "updated_at_present_count": updated_at_present_count,
        "preserve_balance_count": preserve_balance_count,
        "preserve_item_count": preserve_item_count,
        "conservative_reset_candidates": conservative_reset_candidates,
        "aggressive_reset_candidates": aggressive_reset_candidates,
        "preserved_foundation_fields": CANONICAL_PRESERVED_FOUNDATION_FIELDS,
        "boundary_fields": CANONICAL_BOUNDARY_FIELDS,
        "resettable_runtime_fields": CANONICAL_RESETTABLE_RUNTIME_FIELDS,
    }


def inspect_canonical_account_stats_cleanup_scope(
    database_path,
    table_name=CANONICAL_ACCOUNT_STATS_TABLE,
):
    """盘点当前 canonical 表中受旧规则影响的字段残留。"""
    summary = {
        "database_path": database_path or "",
        "table_name": table_name,
        "database_exists": bool(database_path and os.path.isfile(database_path)),
        "table_exists": False,
        "total_records": 0,
        "status_counts": {},
        "legacy_status_count": 0,
        "invalid_status_count": 0,
        "round_field_residue_count": 0,
        "runtime_field_residue_count": 0,
        "cooldown_present_count": 0,
        "last_account_end_present_count": 0,
        "updated_at_present_count": 0,
        "preserve_balance_count": 0,
        "preserve_item_count": 0,
        "conservative_reset_candidates": 0,
        "aggressive_reset_candidates": 0,
        "preserved_foundation_fields": CANONICAL_PRESERVED_FOUNDATION_FIELDS,
        "boundary_fields": CANONICAL_BOUNDARY_FIELDS,
        "resettable_runtime_fields": CANONICAL_RESETTABLE_RUNTIME_FIELDS,
    }
    if not database_path or not os.path.isfile(database_path):
        return summary

    try:
        conn = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return summary

    conn.row_factory = sqlite3.Row
    try:
        if not _canonical_table_exists(conn, table_name):
            return summary

        summary["table_exists"] = True
        select_columns_sql = _build_canonical_select_columns_sql(conn, table_name)
        rows = conn.execute(
            f"SELECT rowid, {select_columns_sql} "
            f"FROM {_quote_identifier(table_name)}"
        ).fetchall()
        summary.update(_build_legacy_cleanup_summary(rows))
        return summary
    finally:
        conn.close()


def reset_canonical_account_stats_legacy_fields(
    database_path,
    table_name=CANONICAL_ACCOUNT_STATS_TABLE,
    mode=CANONICAL_RESET_MODE_AGGRESSIVE,
):
    """按模式重置旧轮次、旧运行态和旧时间污染字段。"""
    if mode not in CANONICAL_RESET_MODE_VALUES:
        raise ValueError(f"unsupported cleanup mode: {mode}")
    if not database_path or not os.path.isfile(database_path):
        return {
            "status": "skipped",
            "mode": mode,
            "updated_rows": 0,
            "reason": "database file not found",
        }

    ensure_canonical_account_stats_table(database_path, table_name)
    try:
        conn = sqlite3.connect(database_path)
    except sqlite3.Error as exc:
        return {
            "status": "error",
            "mode": mode,
            "updated_rows": 0,
            "reason": str(exc),
        }

    conn.row_factory = sqlite3.Row
    try:
        if not _canonical_table_exists(conn, table_name):
            return {
                "status": "skipped",
                "mode": mode,
                "updated_rows": 0,
                "reason": f"canonical table not found: {table_name}",
            }

        select_columns_sql = _build_canonical_select_columns_sql(conn, table_name)
        rows = conn.execute(
            f"SELECT rowid, {select_columns_sql} "
            f"FROM {_quote_identifier(table_name)}"
        ).fetchall()

        target_rowids = []
        for row in rows:
            raw_status = str(row["round_status"] or "").strip()
            normalized_status = normalize_round_status_value(raw_status)
            has_round_residue = any(
                _parse_int(row[field_name]) > 0
                for field_name in (
                    "round_purchase_success_count",
                    "round_listing_success_count",
                    "round_purchase_fail_count",
                )
            )
            has_runtime_residue = (
                _parse_int(row["purchase_running_seconds"]) > 0
                or str(row["runtime_window_start_time"] or "").strip() != ""
            )
            has_legacy_status = (
                not raw_status
                or normalized_status not in ROUND_STATUS_VALUES
                or raw_status != normalized_status
            )
            if mode == CANONICAL_RESET_MODE_CONSERVATIVE:
                should_reset = has_round_residue or has_runtime_residue or has_legacy_status
            else:
                should_reset = (
                    has_round_residue
                    or has_runtime_residue
                    or raw_status != ROUND_STATUS_MANUAL_PAUSE
                    or str(row["last_limit_time"] or "").strip() != ""
                    or str(row["last_account_end_time"] or "").strip() != ""
                    or str(row["updated_at"] or "").strip() != ""
                )
            if should_reset:
                target_rowids.append(row["rowid"])

        if not target_rowids:
            return {
                "status": "success",
                "mode": mode,
                "updated_rows": 0,
                "reason": "",
            }

        set_clauses = [
            f"{_quote_identifier('round_purchase_success_count')} = 0",
            f"{_quote_identifier('round_listing_success_count')} = 0",
            f"{_quote_identifier('round_purchase_fail_count')} = 0",
            f"{_quote_identifier('purchase_running_seconds')} = 0",
            f"{_quote_identifier('runtime_window_start_time')} = NULL",
            f"{_quote_identifier('round_status')} = ?",
            f"{_quote_identifier('updated_at')} = NULL",
        ]
        params_prefix = [ROUND_STATUS_MANUAL_PAUSE]
        if mode == CANONICAL_RESET_MODE_AGGRESSIVE:
            set_clauses.append(f"{_quote_identifier('last_limit_time')} = NULL")
            set_clauses.append(f"{_quote_identifier('last_account_end_time')} = NULL")

        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            f"UPDATE {_quote_identifier(table_name)} "
            f"SET {', '.join(set_clauses)} "
            "WHERE rowid = ?",
            [tuple(params_prefix + [rowid]) for rowid in target_rowids],
        )
        conn.commit()
        return {
            "status": "success",
            "mode": mode,
            "updated_rows": len(target_rowids),
            "reason": "",
        }
    except sqlite3.Error as exc:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        return {
            "status": "error",
            "mode": mode,
            "updated_rows": 0,
            "reason": str(exc),
        }
    finally:
        conn.close()


def normalize_canonical_round_status_values(
    database_path,
    table_name=CANONICAL_ACCOUNT_STATS_TABLE,
):
    """将测试库中的旧状态值归一为当前正式口径。"""
    if not database_path or not os.path.isfile(database_path):
        return 0

    try:
        conn = sqlite3.connect(database_path)
    except sqlite3.Error:
        return 0

    conn.row_factory = sqlite3.Row
    try:
        if not _canonical_table_exists(conn, table_name):
            return 0

        rows = conn.execute(
            f"SELECT rowid, {_quote_identifier('round_status')} "
            f"FROM {_quote_identifier(table_name)}"
        ).fetchall()

        updates = []
        for row in rows:
            raw_status = str(row["round_status"] or "").strip()
            normalized_status = _normalize_round_status_for_storage(raw_status)
            if normalized_status == raw_status:
                continue
            updates.append((normalized_status, row["rowid"]))

        if not updates:
            return 0

        conn.execute("BEGIN IMMEDIATE")
        conn.executemany(
            f"UPDATE {_quote_identifier(table_name)} "
            f"SET {_quote_identifier('round_status')} = ? "
            "WHERE rowid = ?",
            updates,
        )
        conn.commit()
        return len(updates)
    except sqlite3.Error:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        return 0
    finally:
        conn.close()


def ensure_canonical_account_stats_table(
    database_path,
    table_name=CANONICAL_ACCOUNT_STATS_TABLE,
):
    """创建线程 2 统一字段表结构。"""
    if not database_path:
        raise ValueError("database_path is empty")

    directory = os.path.dirname(database_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(build_canonical_account_stats_table_sql(table_name))
        if _canonical_status_schema_requires_rebuild(conn, table_name):
            conn.execute("BEGIN IMMEDIATE")
            _rebuild_canonical_account_stats_table(conn, table_name)
            conn.commit()
        existing_columns = set(_get_table_column_names(conn, table_name))
        if "runtime_window_start_time" not in existing_columns:
            conn.execute(
                f"ALTER TABLE {_quote_identifier(table_name)} "
                f"ADD COLUMN {_quote_identifier('runtime_window_start_time')} TEXT"
            )
        conn.commit()
    finally:
        conn.close()


def find_canonical_account_stats_store(table_name=CANONICAL_ACCOUNT_STATS_TABLE):
    seen = set()

    resolved_primary = resolve_account_stats_db_path()
    for db_path in _iter_canonical_db_hint_paths():
        if not db_path or not os.path.isfile(db_path) or db_path in seen:
            continue
        seen.add(db_path)
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        except sqlite3.Error:
            continue
        try:
            if _canonical_table_exists(conn, table_name):
                if os.path.normcase(db_path) == os.path.normcase(resolved_primary.path):
                    log_resolved_live_path("SQLite真源", resolved_primary)
                return db_path, table_name
        finally:
            conn.close()

    for db_path in _iter_candidate_db_paths():
        if db_path in seen:
            continue
        seen.add(db_path)
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        except sqlite3.Error:
            continue
        try:
            if _canonical_table_exists(conn, table_name):
                return db_path, table_name
        finally:
            conn.close()

    return None, table_name


def ensure_local_canonical_account_stats_store(
    table_name=CANONICAL_ACCOUNT_STATS_TABLE,
):
    """确保默认本地账号库存在，并补齐 canonical 表与执行位种子记录。"""
    resolved_primary = resolve_account_stats_db_path()
    database_path = resolved_primary.path
    log_resolved_live_path("SQLite真源", resolved_primary)
    inserted_seed_records = ensure_canonical_execution_slot_seed_records(
        database_path,
        table_name,
    )
    return database_path, table_name, inserted_seed_records


def _normalize_machine_daily_summary_date(value):
    if value is None:
        return datetime.now().strftime("%Y-%m-%d")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")

    parsed = _parse_datetime(value)
    if parsed is not None:
        return parsed.strftime("%Y-%m-%d")

    text = str(value or "").strip()
    if len(text) >= 10:
        return text[:10]
    return datetime.now().strftime("%Y-%m-%d")


def ensure_machine_daily_summary_table(
    database_path,
    table_name=MACHINE_DAILY_SUMMARY_TABLE,
):
    if not database_path:
        raise ValueError("database_path is empty")

    directory = os.path.dirname(database_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    conn = sqlite3.connect(database_path)
    try:
        conn.execute(build_machine_daily_summary_table_sql(table_name))
        conn.commit()
    finally:
        conn.close()


def increment_machine_daily_summary_event(
    database_path,
    machine_id,
    machine_display_name,
    event_name,
    occurred_at=None,
    table_name=MACHINE_DAILY_SUMMARY_TABLE,
):
    normalized_machine_id = str(machine_id or "").strip()
    if not normalized_machine_id:
        return AccountWriteResult("machine_id_missing", "machine_id is empty")
    if event_name not in MACHINE_DAILY_SUMMARY_EVENT_VALUES:
        return AccountWriteResult("invalid_event_name", f"unsupported event name: {event_name}")

    normalized_machine_display_name = str(machine_display_name or "").strip() or normalized_machine_id
    occurred_at_value = _parse_datetime(occurred_at) or datetime.now()
    stat_date = _normalize_machine_daily_summary_date(occurred_at_value)
    updated_at = _serialize_datetime(occurred_at_value)
    purchase_success_count = 1 if event_name == MACHINE_DAILY_SUMMARY_EVENT_PURCHASE_SUCCESS else 0
    listing_success_count = 1 if event_name == MACHINE_DAILY_SUMMARY_EVENT_LISTING_SUCCESS else 0
    purchase_fail_count = 1 if event_name == MACHINE_DAILY_SUMMARY_EVENT_PURCHASE_FAIL else 0

    try:
        conn = sqlite3.connect(database_path)
    except sqlite3.Error as exc:
        return AccountWriteResult("db_unavailable", str(exc))

    try:
        conn.execute(build_machine_daily_summary_table_sql(table_name))
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            f"""
            INSERT INTO {_quote_identifier(table_name)} (
                machine_id,
                machine_display_name,
                stat_date,
                total_purchase_success_count,
                total_listing_success_count,
                total_purchase_fail_count,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(machine_id, stat_date) DO UPDATE SET
                machine_display_name = excluded.machine_display_name,
                total_purchase_success_count = total_purchase_success_count + excluded.total_purchase_success_count,
                total_listing_success_count = total_listing_success_count + excluded.total_listing_success_count,
                total_purchase_fail_count = total_purchase_fail_count + excluded.total_purchase_fail_count,
                updated_at = excluded.updated_at
            """,
            (
                normalized_machine_id,
                normalized_machine_display_name,
                stat_date,
                purchase_success_count,
                listing_success_count,
                purchase_fail_count,
                updated_at,
            ),
        )
        conn.commit()
        return AccountWriteResult("success", "")
    except sqlite3.Error as exc:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        return AccountWriteResult("write_failed", str(exc))
    finally:
        conn.close()


def read_machine_daily_summary_records(
    database_path,
    machine_id,
    stat_dates=None,
    table_name=MACHINE_DAILY_SUMMARY_TABLE,
):
    normalized_machine_id = str(machine_id or "").strip()
    if not normalized_machine_id or not database_path or not os.path.isfile(database_path):
        return []

    normalized_dates = [
        _normalize_machine_daily_summary_date(item)
        for item in (stat_dates or [])
        if str(item or "").strip()
    ]
    if not normalized_dates:
        now = datetime.now()
        normalized_dates = [
            _normalize_machine_daily_summary_date(now),
            _normalize_machine_daily_summary_date(now.timestamp() - 86400),
        ]
    normalized_dates = list(dict.fromkeys(normalized_dates))

    try:
        conn = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []

    conn.row_factory = sqlite3.Row
    try:
        if not _canonical_table_exists(conn, table_name):
            return []
        placeholders = ", ".join("?" for _ in normalized_dates)
        rows = conn.execute(
            f"""
            SELECT
                machine_id,
                machine_display_name,
                stat_date,
                total_purchase_success_count,
                total_listing_success_count,
                total_purchase_fail_count,
                updated_at
            FROM {_quote_identifier(table_name)}
            WHERE machine_id = ?
              AND stat_date IN ({placeholders})
            ORDER BY stat_date DESC
            """,
            tuple([normalized_machine_id] + normalized_dates),
        ).fetchall()
        return [
            {
                "machine_id": str(row["machine_id"] or "").strip(),
                "machine_display_name": str(row["machine_display_name"] or "").strip(),
                "stat_date": str(row["stat_date"] or "").strip(),
                "total_purchase_success_count": _parse_int(row["total_purchase_success_count"]),
                "total_listing_success_count": _parse_int(row["total_listing_success_count"]),
                "total_purchase_fail_count": _parse_int(row["total_purchase_fail_count"]),
                "updated_at": _serialize_datetime(_parse_datetime(row["updated_at"])),
            }
            for row in rows
        ]
    finally:
        conn.close()


def read_canonical_account_stats_record(
    database_path,
    nickname,
    table_name=CANONICAL_ACCOUNT_STATS_TABLE,
):
    """读取线程 2 统一字段记录。"""
    if not database_path or not os.path.isfile(database_path):
        return None

    try:
        conn = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None

    conn.row_factory = sqlite3.Row
    try:
        if not _canonical_table_exists(conn, table_name):
            return None
        select_columns_sql = _build_canonical_select_columns_sql(conn, table_name)
        row = conn.execute(
            f"SELECT {select_columns_sql} "
            f"FROM {_quote_identifier(table_name)} "
            f"WHERE {_quote_identifier('nickname')} = ? "
            "LIMIT 1",
            ((nickname or "").strip(),),
        ).fetchone()
        return _row_to_account_stats_record(row)
    finally:
        conn.close()


def read_canonical_account_stats_record_by_execution_slot(
    database_path,
    execution_slot,
    table_name=CANONICAL_ACCOUNT_STATS_TABLE,
):
    """按执行位兼容读取统一账号记录。"""
    if not database_path or not os.path.isfile(database_path):
        return None

    try:
        slot_value = int(execution_slot)
    except (TypeError, ValueError):
        return None

    try:
        conn = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None

    conn.row_factory = sqlite3.Row
    try:
        if not _canonical_table_exists(conn, table_name):
            return None
        select_columns_sql = _build_canonical_select_columns_sql(conn, table_name)
        row = conn.execute(
            f"SELECT {select_columns_sql} "
            f"FROM {_quote_identifier(table_name)} "
            f"WHERE {_quote_identifier('current_execution_slot')} = ? "
            "LIMIT 1",
            (slot_value,),
        ).fetchone()
        return _row_to_account_stats_record(row)
    finally:
        conn.close()


def _is_execution_slot_seed_nickname(nickname, execution_slot):
    """识别执行位自动建档生成的种子昵称，避免误当成真实账号记录。"""
    normalized_nickname = str(nickname or "").strip()
    try:
        slot_value = int(execution_slot)
    except (TypeError, ValueError):
        return False

    if not normalized_nickname:
        return True
    if normalized_nickname == str(slot_value):
        return True
    if normalized_nickname == f"slot_{slot_value}":
        return True
    if normalized_nickname.startswith(f"slot_{slot_value}_"):
        return True
    return False


def read_preferred_canonical_account_stats_record_by_execution_slot(
    database_path,
    execution_slot,
    table_name=CANONICAL_ACCOUNT_STATS_TABLE,
):
    """按执行位优先读取真实账号记录，只有缺失时才回退到执行位种子记录。"""
    if not database_path or not os.path.isfile(database_path):
        return None

    try:
        slot_value = int(execution_slot)
    except (TypeError, ValueError):
        return None

    try:
        conn = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None

    conn.row_factory = sqlite3.Row
    try:
        if not _canonical_table_exists(conn, table_name):
            return None
        select_columns_sql = _build_canonical_select_columns_sql(conn, table_name)
        rows = conn.execute(
            f"SELECT {select_columns_sql} "
            f"FROM {_quote_identifier(table_name)} "
            f"WHERE {_quote_identifier('current_execution_slot')} = ? "
            f"ORDER BY {_quote_identifier('updated_at')} DESC, {_quote_identifier('nickname')}",
            (slot_value,),
        ).fetchall()
        if not rows:
            return None

        seed_fallback_row = None
        for row in rows:
            nickname = str(row["nickname"] or "").strip()
            if _is_execution_slot_seed_nickname(nickname, slot_value):
                if seed_fallback_row is None:
                    seed_fallback_row = row
                continue
            return _row_to_account_stats_record(row)

        return _row_to_account_stats_record(seed_fallback_row)
    finally:
        conn.close()


def save_canonical_account_stats_record(
    database_path,
    record,
    table_name=CANONICAL_ACCOUNT_STATS_TABLE,
):
    """保存线程 2 统一字段记录。"""
    if not isinstance(record, AccountStatsRecord):
        raise TypeError("record must be AccountStatsRecord")
    if not record.nickname or not str(record.nickname).strip():
        raise ValueError("nickname is empty")
    normalized_round_status = _normalize_round_status_for_storage(record.round_status)
    if not _validate_round_status(normalized_round_status):
        raise ValueError(f"invalid round_status: {record.round_status}")

    ensure_canonical_account_stats_table(database_path, table_name)

    sql = f"""
        INSERT INTO {_quote_identifier(table_name)} (
            {', '.join(_quote_identifier(name) for name in CANONICAL_ACCOUNT_STATS_COLUMNS)}
        ) VALUES (
            {', '.join('?' for _ in CANONICAL_ACCOUNT_STATS_COLUMNS)}
        )
        ON CONFLICT({_quote_identifier('nickname')}) DO UPDATE SET
            {_quote_identifier('baseline_item_count')} = excluded.{_quote_identifier('baseline_item_count')},
            {_quote_identifier('last_limit_time')} = excluded.{_quote_identifier('last_limit_time')},
            {_quote_identifier('last_account_end_time')} = excluded.{_quote_identifier('last_account_end_time')},
            {_quote_identifier('updated_at')} = excluded.{_quote_identifier('updated_at')},
            {_quote_identifier('current_execution_slot')} = excluded.{_quote_identifier('current_execution_slot')},
            {_quote_identifier('round_purchase_success_count')} = excluded.{_quote_identifier('round_purchase_success_count')},
            {_quote_identifier('round_listing_success_count')} = excluded.{_quote_identifier('round_listing_success_count')},
            {_quote_identifier('round_purchase_fail_count')} = excluded.{_quote_identifier('round_purchase_fail_count')},
            {_quote_identifier('current_balance')} = excluded.{_quote_identifier('current_balance')},
            {_quote_identifier('purchase_running_seconds')} = excluded.{_quote_identifier('purchase_running_seconds')},
            {_quote_identifier('runtime_window_start_time')} = excluded.{_quote_identifier('runtime_window_start_time')},
            {_quote_identifier('round_status')} = excluded.{_quote_identifier('round_status')}
    """
    values = (
        str(record.nickname).strip(),
        int(record.baseline_item_count),
        _serialize_datetime(record.last_limit_time),
        _serialize_datetime(record.last_account_end_time),
        _serialize_datetime(record.updated_at),
        int(record.current_execution_slot) if record.current_execution_slot is not None else None,
        int(record.round_purchase_success_count),
        int(record.round_listing_success_count),
        int(record.round_purchase_fail_count),
        str(record.current_balance or ""),
        int(record.purchase_running_seconds),
        _serialize_datetime(record.runtime_window_start_time),
        normalized_round_status,
    )

    conn = sqlite3.connect(database_path)
    try:
        conn.execute(sql, values)
        conn.commit()
    finally:
        conn.close()

    return AccountWriteResult(
        "success",
        "",
        int(record.baseline_item_count),
    )


def update_canonical_account_runtime_fields(
    database_path,
    nickname,
    purchase_running_seconds,
    runtime_window_start_time,
    table_name=CANONICAL_ACCOUNT_STATS_TABLE,
    updated_at=None,
    last_limit_time=None,
    update_last_limit_time=False,
):
    """仅更新运行时间窗口相关字段，避免高频全量覆盖写库。"""
    normalized_nickname = str(nickname or "").strip()
    if not normalized_nickname:
        return AccountWriteResult("nickname_missing", "current nickname is empty")

    try:
        normalized_running_seconds = max(0, int(float(purchase_running_seconds)))
    except (TypeError, ValueError):
        return AccountWriteResult(
            "invalid_running_seconds",
            f"invalid purchase_running_seconds: {purchase_running_seconds}",
        )

    ensure_canonical_account_stats_table(database_path, table_name)

    try:
        conn = sqlite3.connect(database_path)
    except sqlite3.Error as exc:
        return AccountWriteResult("db_unavailable", f"database unavailable: {exc}")

    normalized_updated_at = _serialize_datetime(updated_at or datetime.now())
    normalized_window_start_time = _serialize_datetime(runtime_window_start_time)
    normalized_last_limit_time = _serialize_datetime(last_limit_time)
    conn.row_factory = sqlite3.Row
    try:
        if not _canonical_table_exists(conn, table_name):
            return AccountWriteResult("schema_not_found", f"canonical table not found: {table_name}")

        row = conn.execute(
            f"SELECT 1 "
            f"FROM {_quote_identifier(table_name)} "
            f"WHERE {_quote_identifier('nickname')} = ? "
            "LIMIT 1",
            (normalized_nickname,),
        ).fetchone()
        if row is None:
            return AccountWriteResult(
                "account_not_found",
                f"account record not found for nickname: {normalized_nickname}",
            )

        set_clauses = [
            f"{_quote_identifier('purchase_running_seconds')} = ?",
            f"{_quote_identifier('runtime_window_start_time')} = ?",
            f"{_quote_identifier('updated_at')} = ?",
        ]
        params = [
            normalized_running_seconds,
            normalized_window_start_time,
            normalized_updated_at,
        ]
        if update_last_limit_time:
            set_clauses.append(f"{_quote_identifier('last_limit_time')} = ?")
            params.append(normalized_last_limit_time)
        params.append(normalized_nickname)

        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            f"UPDATE {_quote_identifier(table_name)} "
            f"SET {', '.join(set_clauses)} "
            f"WHERE {_quote_identifier('nickname')} = ?",
            params,
        )
        if cursor.rowcount <= 0:
            conn.rollback()
            return AccountWriteResult(
                "account_not_found",
                f"account record not found for nickname: {normalized_nickname}",
            )
        conn.commit()
        return AccountWriteResult("success", "", normalized_running_seconds)
    except sqlite3.Error as exc:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        return AccountWriteResult("write_failed", f"runtime fields write failed: {exc}")
    finally:
        conn.close()


def update_canonical_account_item_balance_fields(
    database_path,
    nickname,
    item_quantity,
    current_balance="",
    table_name=CANONICAL_ACCOUNT_STATS_TABLE,
    updated_at=None,
    purchase_running_seconds=None,
    runtime_window_start_time=None,
    last_limit_time=None,
    update_last_limit_time=False,
):
    """最小高频同步：直接更新真实库存字段与余额。"""
    normalized_nickname = str(nickname or "").strip()
    if not normalized_nickname:
        return AccountWriteResult("nickname_missing", "当前昵称为空")

    try:
        desired_item_quantity = int(item_quantity)
    except (TypeError, ValueError):
        return AccountWriteResult("invalid_item_quantity", f"道具数量无效: {item_quantity}")

    if desired_item_quantity < 0:
        return AccountWriteResult(
            "invalid_item_quantity",
            f"道具数量为负数: {desired_item_quantity}",
        )

    if not database_path or not os.path.isfile(database_path):
        return AccountWriteResult("db_unavailable", f"数据库文件不存在: {database_path}")

    normalized_balance = str(current_balance or "").strip()
    normalized_updated_at = _serialize_datetime(updated_at or datetime.now())
    normalized_running_seconds = None
    if purchase_running_seconds is not None:
        try:
            normalized_running_seconds = max(0, int(float(purchase_running_seconds)))
        except (TypeError, ValueError):
            return AccountWriteResult(
                "invalid_running_seconds",
                f"invalid purchase_running_seconds: {purchase_running_seconds}",
            )
    normalized_window_start_time = _serialize_datetime(runtime_window_start_time)
    normalized_last_limit_time = _serialize_datetime(last_limit_time)

    try:
        conn = sqlite3.connect(database_path)
    except sqlite3.Error as exc:
        return AccountWriteResult("db_unavailable", f"数据库不可用: {exc}")

    conn.row_factory = sqlite3.Row
    try:
        if not _canonical_table_exists(conn, table_name):
            return AccountWriteResult("schema_not_found", f"canonical 表不存在: {table_name}")

        row = conn.execute(
            f"SELECT 1 "
            f"FROM {_quote_identifier(table_name)} "
            f"WHERE {_quote_identifier('nickname')} = ? "
            "LIMIT 1",
            (normalized_nickname,),
        ).fetchone()
        if row is None:
            return AccountWriteResult(
                "account_not_found",
                f"未找到昵称为 {normalized_nickname} 的账号记录",
            )

        set_clauses = [
            f"{_quote_identifier('baseline_item_count')} = ?",
            f"{_quote_identifier('updated_at')} = ?",
        ]
        params = [desired_item_quantity, normalized_updated_at]
        if normalized_running_seconds is not None:
            set_clauses.append(f"{_quote_identifier('purchase_running_seconds')} = ?")
            params.append(normalized_running_seconds)
            set_clauses.append(f"{_quote_identifier('runtime_window_start_time')} = ?")
            params.append(normalized_window_start_time)
        if normalized_balance:
            set_clauses.append(f"{_quote_identifier('current_balance')} = ?")
            params.append(normalized_balance)
        if update_last_limit_time:
            set_clauses.append(f"{_quote_identifier('last_limit_time')} = ?")
            params.append(normalized_last_limit_time)
        params.append(normalized_nickname)

        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            f"UPDATE {_quote_identifier(table_name)} "
            f"SET {', '.join(set_clauses)} "
            f"WHERE {_quote_identifier('nickname')} = ?",
            params,
        )
        if cursor.rowcount <= 0:
            conn.rollback()
            return AccountWriteResult(
                "account_not_found",
                f"未找到昵称为 {normalized_nickname} 的账号记录",
            )
        conn.commit()
        return AccountWriteResult("success", "", desired_item_quantity)
    except sqlite3.Error as exc:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        return AccountWriteResult("write_failed", f"写入失败: {exc}")
    finally:
        conn.close()


def update_canonical_account_status_fields(
    database_path,
    nickname,
    round_status,
    table_name=CANONICAL_ACCOUNT_STATS_TABLE,
    updated_at=None,
    expected_current_status=None,
    item_quantity=None,
    current_balance=None,
    purchase_running_seconds=None,
    runtime_window_start_time=None,
    round_purchase_success_count=None,
    round_listing_success_count=None,
    round_purchase_fail_count=None,
):
    """按昵称最小更新状态相关字段，可选带当前状态前置条件。"""
    normalized_nickname = str(nickname or "").strip()
    if not normalized_nickname:
        return AccountWriteResult("nickname_missing", "当前昵称为空")
    if not database_path or not os.path.isfile(database_path):
        return AccountWriteResult("db_unavailable", f"数据库文件不存在: {database_path}")

    normalized_round_status = _normalize_round_status_for_storage(round_status)
    normalized_expected_status = None
    if expected_current_status is not None:
        normalized_expected_status = _normalize_round_status_for_storage(expected_current_status)

    normalized_updated_at = _serialize_datetime(updated_at or datetime.now())
    normalized_item_quantity = None
    if item_quantity is not None:
        try:
            normalized_item_quantity = int(item_quantity)
        except (TypeError, ValueError):
            return AccountWriteResult("invalid_item_quantity", f"道具数量无效: {item_quantity}")
        if normalized_item_quantity < 0:
            return AccountWriteResult("invalid_item_quantity", f"道具数量为负数: {normalized_item_quantity}")

    normalized_balance = None
    if current_balance is not None:
        normalized_balance = str(current_balance or "").strip()

    normalized_running_seconds = None
    if purchase_running_seconds is not None:
        try:
            normalized_running_seconds = max(0, int(float(purchase_running_seconds)))
        except (TypeError, ValueError):
            return AccountWriteResult(
                "invalid_running_seconds",
                f"invalid purchase_running_seconds: {purchase_running_seconds}",
            )

    normalized_window_start_time = None
    if runtime_window_start_time is not None:
        normalized_window_start_time = _serialize_datetime(runtime_window_start_time)

    normalized_round_purchase_success_count = None
    if round_purchase_success_count is not None:
        try:
            normalized_round_purchase_success_count = max(0, int(round_purchase_success_count))
        except (TypeError, ValueError):
            return AccountWriteResult(
                "invalid_round_purchase_success_count",
                f"invalid round_purchase_success_count: {round_purchase_success_count}",
            )

    normalized_round_listing_success_count = None
    if round_listing_success_count is not None:
        try:
            normalized_round_listing_success_count = max(0, int(round_listing_success_count))
        except (TypeError, ValueError):
            return AccountWriteResult(
                "invalid_round_listing_success_count",
                f"invalid round_listing_success_count: {round_listing_success_count}",
            )

    normalized_round_purchase_fail_count = None
    if round_purchase_fail_count is not None:
        try:
            normalized_round_purchase_fail_count = max(0, int(round_purchase_fail_count))
        except (TypeError, ValueError):
            return AccountWriteResult(
                "invalid_round_purchase_fail_count",
                f"invalid round_purchase_fail_count: {round_purchase_fail_count}",
            )

    try:
        conn = sqlite3.connect(database_path)
    except sqlite3.Error as exc:
        return AccountWriteResult("db_unavailable", f"数据库不可用: {exc}")

    conn.row_factory = sqlite3.Row
    try:
        if not _canonical_table_exists(conn, table_name):
            return AccountWriteResult("schema_not_found", f"canonical 表不存在: {table_name}")

        row = conn.execute(
            f"SELECT {_quote_identifier('round_status')} "
            f"FROM {_quote_identifier(table_name)} "
            f"WHERE {_quote_identifier('nickname')} = ? "
            "LIMIT 1",
            (normalized_nickname,),
        ).fetchone()
        if row is None:
            return AccountWriteResult(
                "account_not_found",
                f"未找到昵称为 {normalized_nickname} 的账号记录",
            )

        current_status = _normalize_round_status_for_storage(row["round_status"])
        if normalized_expected_status is not None and current_status != normalized_expected_status:
            return AccountWriteResult(
                "skipped",
                f"current status mismatch: expected={normalized_expected_status}, actual={current_status}",
            )

        set_clauses = [
            f"{_quote_identifier('round_status')} = ?",
            f"{_quote_identifier('updated_at')} = ?",
        ]
        params = [normalized_round_status, normalized_updated_at]
        if normalized_item_quantity is not None:
            set_clauses.append(f"{_quote_identifier('baseline_item_count')} = ?")
            params.append(normalized_item_quantity)
        if normalized_balance:
            set_clauses.append(f"{_quote_identifier('current_balance')} = ?")
            params.append(normalized_balance)
        if normalized_running_seconds is not None:
            set_clauses.append(f"{_quote_identifier('purchase_running_seconds')} = ?")
            params.append(normalized_running_seconds)
        if runtime_window_start_time is not None:
            set_clauses.append(f"{_quote_identifier('runtime_window_start_time')} = ?")
            params.append(normalized_window_start_time)
        if normalized_round_purchase_success_count is not None:
            set_clauses.append(f"{_quote_identifier('round_purchase_success_count')} = ?")
            params.append(normalized_round_purchase_success_count)
        if normalized_round_listing_success_count is not None:
            set_clauses.append(f"{_quote_identifier('round_listing_success_count')} = ?")
            params.append(normalized_round_listing_success_count)
        if normalized_round_purchase_fail_count is not None:
            set_clauses.append(f"{_quote_identifier('round_purchase_fail_count')} = ?")
            params.append(normalized_round_purchase_fail_count)
        params.append(normalized_nickname)

        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            f"UPDATE {_quote_identifier(table_name)} "
            f"SET {', '.join(set_clauses)} "
            f"WHERE {_quote_identifier('nickname')} = ?",
            params,
        )
        if cursor.rowcount <= 0:
            conn.rollback()
            return AccountWriteResult(
                "account_not_found",
                f"未找到昵称为 {normalized_nickname} 的账号记录",
            )
        conn.commit()
        return AccountWriteResult("success", "", normalized_item_quantity)
    except sqlite3.Error as exc:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        return AccountWriteResult("write_failed", f"写入失败: {exc}")
    finally:
        conn.close()


def ensure_canonical_execution_slot_seed_records(
    database_path,
    table_name=CANONICAL_ACCOUNT_STATS_TABLE,
):
    """补齐缺失执行位的 canonical 建档，仅补不存在的执行位。"""
    if not database_path:
        raise ValueError("database_path is empty")

    ensure_canonical_account_stats_table(database_path, table_name)

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"SELECT {_quote_identifier('nickname')}, {_quote_identifier('current_execution_slot')} "
            f"FROM {_quote_identifier(table_name)}"
        ).fetchall()
    finally:
        conn.close()

    existing_slots = set()
    existing_nicknames = set()
    for row in rows:
        nickname = str(row["nickname"] or "").strip()
        if nickname:
            existing_nicknames.add(nickname)
        slot_value = row["current_execution_slot"]
        if slot_value not in (None, ""):
            existing_slots.add(_parse_int(slot_value))

    inserted_records = []
    for slot_index in range(1, int(EXECUTION_SLOT_COUNT) + 1):
        if slot_index in existing_slots:
            continue

        configured_nickname = ""
        if 0 <= slot_index - 1 < len(EXECUTION_SLOT_NICKNAMES):
            configured_nickname = str(EXECUTION_SLOT_NICKNAMES[slot_index - 1] or "").strip()

        seed_nickname = configured_nickname or str(slot_index)
        if seed_nickname in existing_nicknames:
            seed_nickname = f"slot_{slot_index}"
            suffix = 2
            while seed_nickname in existing_nicknames:
                seed_nickname = f"slot_{slot_index}_{suffix}"
                suffix += 1

        seed_record = AccountStatsRecord(
            nickname=seed_nickname,
            baseline_item_count=0,
            last_limit_time=None,
            last_account_end_time=None,
            updated_at=datetime.now(),
            current_execution_slot=slot_index,
            round_purchase_success_count=0,
            round_listing_success_count=0,
            round_purchase_fail_count=0,
            current_balance="",
            purchase_running_seconds=0,
            runtime_window_start_time=None,
            round_status=ROUND_STATUS_MANUAL_PAUSE,
        )
        save_canonical_account_stats_record(database_path, seed_record, table_name)
        existing_nicknames.add(seed_nickname)
        inserted_records.append(seed_record)

    return inserted_records


def write_account_round_record(database_path, table_name, nickname, payload):
    nickname = (nickname or "").strip()
    if not nickname:
        return AccountWriteResult("nickname_missing", "current nickname is empty")

    if not database_path or not os.path.isfile(database_path):
        return AccountWriteResult("db_unavailable", f"database file not found: {database_path}")

    try:
        conn = sqlite3.connect(database_path)
    except sqlite3.Error as exc:
        return AccountWriteResult("db_unavailable", str(exc))

    try:
        mapping = _inspect_table(conn, table_name)
        if not mapping or "nickname" not in mapping or "baseline" not in mapping:
            return AccountWriteResult("schema_not_found", f"schema not found in table: {table_name}")

        missing_keys = [key for key in _WRITE_REQUIRED_KEYS if key not in mapping]
        if missing_keys:
            return AccountWriteResult(
                "schema_incomplete",
                f"table {table_name} missing columns: {', '.join(missing_keys)}",
            )

        exists_sql = (
            f"SELECT 1 FROM {_quote_identifier(table_name)} "
            f"WHERE {_quote_identifier(mapping['nickname'])} = ? LIMIT 1"
        )
        if conn.execute(exists_sql, (nickname,)).fetchone() is None:
            return AccountWriteResult(
                "account_not_found",
                f"account record not found for nickname: {nickname}",
            )

        assignments = [
            ("baseline", payload.baseline_item_count),
            ("round_purchase_success", payload.round_purchase_success_count),
            ("round_listing_success", payload.round_listing_success_count),
            ("round_purchase_fail", payload.round_purchase_fail_count),
            ("current_balance", payload.current_balance),
            ("purchase_running_seconds", payload.purchase_running_seconds),
            ("round_status", _normalize_round_status_for_storage(payload.round_status)),
            ("updated_at", _serialize_datetime(payload.updated_at)),
        ]

        if payload.update_last_limit_time:
            assignments.append(("last_limit", _serialize_datetime(payload.last_limit_time)))
        if payload.update_last_account_end_time:
            assignments.append(("last_account_end", _serialize_datetime(payload.last_account_end_time)))

        set_clauses = []
        params = []
        for logical_name, value in assignments:
            set_clauses.append(f"{_quote_identifier(mapping[logical_name])} = ?")
            params.append(value)
        params.append(nickname)

        sql = (
            f"UPDATE {_quote_identifier(table_name)} "
            f"SET {', '.join(set_clauses)} "
            f"WHERE {_quote_identifier(mapping['nickname'])} = ?"
        )

        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(sql, params)
        if cursor.rowcount <= 0:
            conn.rollback()
            return AccountWriteResult(
                "account_not_found",
                f"account record not found for nickname: {nickname}",
            )
        conn.commit()
        return AccountWriteResult("success", "", payload.baseline_item_count)
    except sqlite3.Error as exc:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        return AccountWriteResult("write_failed", str(exc))
    finally:
        conn.close()
