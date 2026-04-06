"""本机网页汇总同步配置读取。"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os

import config


DEFAULT_REPORT_INTERVAL_SECONDS = 30


@dataclass(frozen=True)
class ExecutionSlotOverride:
    execution_slot: int
    nickname: str
    region: str
    sort_order: int


@dataclass(frozen=True)
class ExpectedRemoteMachine:
    machine_id: str
    machine_display_name: str


@dataclass(frozen=True)
class MachineSyncConfig:
    machine_id: str
    machine_display_name: str
    sync_enabled: bool
    aggregator_host: str
    aggregator_url: str
    receive_remote_sync: bool
    web_bind_host: str
    report_interval_seconds: int
    execution_slot_overrides: dict[int, ExecutionSlotOverride]
    expected_remote_machines: list[ExpectedRemoteMachine]
    source_path: str


def _read_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _normalize_required_text(value, field_name):
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} 未配置有效值")
    return text


def _normalize_bool(value, field_name):
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field_name} 必须是 true 或 false")


def _normalize_positive_int(value, field_name, default=None, min_value=1):
    if value in (None, ""):
        if default is not None:
            return default
        raise ValueError(f"{field_name} 未配置有效整数")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是整数") from exc
    if normalized < min_value:
        raise ValueError(f"{field_name} 必须大于等于 {min_value}")
    return normalized


def _normalize_execution_slot_overrides(raw_value):
    if raw_value in (None, ""):
        return {}
    if not isinstance(raw_value, list):
        raise ValueError("execution_slot_overrides 必须是数组")

    overrides = {}
    for index, item in enumerate(raw_value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"execution_slot_overrides 第 {index} 项必须是对象")

        execution_slot = _normalize_positive_int(
            item.get("execution_slot"),
            f"execution_slot_overrides[{index}].execution_slot",
        )
        nickname = str(item.get("nickname") or "").strip()
        region = str(item.get("region") or "").strip()
        sort_order = _normalize_positive_int(
            item.get("sort_order"),
            f"execution_slot_overrides[{index}].sort_order",
            default=execution_slot,
        )
        overrides[execution_slot] = ExecutionSlotOverride(
            execution_slot=execution_slot,
            nickname=nickname,
            region=region,
            sort_order=sort_order,
        )
    return overrides


def _normalize_expected_remote_machines(raw_value):
    if raw_value in (None, ""):
        return []
    if not isinstance(raw_value, list):
        raise ValueError("expected_remote_machines 必须是数组")

    expected = []
    for index, item in enumerate(raw_value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"expected_remote_machines 第 {index} 项必须是对象")
        expected.append(
            ExpectedRemoteMachine(
                machine_id=_normalize_required_text(
                    item.get("machine_id"),
                    f"expected_remote_machines[{index}].machine_id",
                ),
                machine_display_name=_normalize_required_text(
                    item.get("machine_display_name"),
                    f"expected_remote_machines[{index}].machine_display_name",
                ),
            )
        )
    return expected


def load_machine_sync_config():
    source_path = config.LOCAL_WEB_SYNC_CONFIG_PATH
    if not os.path.exists(source_path):
        raise FileNotFoundError("缺少本机网页同步配置文件 local_web_sync_config.json")

    data = _read_json(source_path)
    if not isinstance(data, dict):
        raise ValueError("本机网页同步配置文件格式错误，根节点必须是 JSON 对象")

    receive_remote_sync = _normalize_bool(data.get("receive_remote_sync"), "receive_remote_sync")
    aggregator_host = str(data.get("aggregator_host") or "").strip()
    aggregator_url = str(data.get("aggregator_url") or "").strip().rstrip("/")
    if not aggregator_url and aggregator_host:
        aggregator_url = f"http://{aggregator_host}:{config.WEB_VIEW_PORT}"

    return MachineSyncConfig(
        machine_id=_normalize_required_text(data.get("machine_id"), "machine_id"),
        machine_display_name=_normalize_required_text(
            data.get("machine_display_name"),
            "machine_display_name",
        ),
        sync_enabled=_normalize_bool(data.get("sync_enabled"), "sync_enabled"),
        aggregator_host=aggregator_host,
        aggregator_url=aggregator_url,
        receive_remote_sync=receive_remote_sync,
        web_bind_host=str(
            data.get("web_bind_host") or ("0.0.0.0" if receive_remote_sync else config.WEB_VIEW_HOST)
        ).strip(),
        report_interval_seconds=_normalize_positive_int(
            data.get("report_interval_seconds"),
            "report_interval_seconds",
            default=DEFAULT_REPORT_INTERVAL_SECONDS,
        ),
        execution_slot_overrides=_normalize_execution_slot_overrides(
            data.get("execution_slot_overrides")
        ),
        expected_remote_machines=_normalize_expected_remote_machines(
            data.get("expected_remote_machines")
        ),
        source_path=source_path,
    )


def get_machine_sync_runtime_context():
    try:
        sync_config = load_machine_sync_config()
    except Exception as exc:
        return {
            "config_status": "error",
            "config_error": str(exc),
            "machine_id": "local",
            "machine_display_name": "本机",
            "sync_enabled": False,
            "aggregator_host": "",
            "aggregator_url": "",
            "receive_remote_sync": False,
            "web_bind_host": config.WEB_VIEW_HOST,
            "report_interval_seconds": DEFAULT_REPORT_INTERVAL_SECONDS,
            "execution_slot_overrides": {},
            "expected_remote_machines": [],
            "source_path": config.LOCAL_WEB_SYNC_CONFIG_PATH,
        }

    return {
        "config_status": "ready",
        "config_error": "",
        "machine_id": sync_config.machine_id,
        "machine_display_name": sync_config.machine_display_name,
        "sync_enabled": sync_config.sync_enabled,
        "aggregator_host": sync_config.aggregator_host,
        "aggregator_url": sync_config.aggregator_url,
        "receive_remote_sync": sync_config.receive_remote_sync,
        "web_bind_host": sync_config.web_bind_host or config.WEB_VIEW_HOST,
        "report_interval_seconds": sync_config.report_interval_seconds,
        "execution_slot_overrides": sync_config.execution_slot_overrides,
        "expected_remote_machines": sync_config.expected_remote_machines,
        "source_path": sync_config.source_path,
    }


def resolve_web_bind_host():
    runtime_context = get_machine_sync_runtime_context()
    return str(runtime_context.get("web_bind_host") or config.WEB_VIEW_HOST).strip() or config.WEB_VIEW_HOST
