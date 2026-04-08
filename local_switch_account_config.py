import json
import os

import config
from live_paths import (
    log_resolved_live_path,
    resolve_local_switch_account_config_path,
    resolve_nickname_template_dir,
)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _load_local_switch_account_config():
    resolved_source_path = resolve_local_switch_account_config_path()
    source_path = resolved_source_path.path
    log_resolved_live_path("本机换号配置", resolved_source_path)

    if not os.path.exists(source_path):
        raise FileNotFoundError("缺少本机真实换号配置文件 local_switch_account_config.json")

    data = _read_json(source_path)
    if not isinstance(data, dict):
        raise ValueError("本机换号配置文件格式错误，根节点必须是 JSON 对象")

    return data, source_path


def _normalize_account_id(value, field_name):
    account_id = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not account_id:
        raise ValueError(f"{field_name} 未配置有效登录号")
    return account_id


def _normalize_listing_price(value, field_name):
    raw_value = str(value or "").strip()
    if not raw_value:
        raise ValueError(
            f"{field_name} 未配置自动上架售价，请在 local_switch_account_config.json 中补充该字段"
        )
    if not raw_value.isdigit():
        raise ValueError(f"{field_name} 必须为纯数字字符串，当前值: {value!r}")
    return raw_value


def _normalize_optional_local_dir(value, source_path):
    return resolve_nickname_template_dir(value, source_path).path


def _normalize_optional_region(value, field_name):
    if value in (None, ""):
        return tuple(config.NICKNAME_VERIFY_REGION)
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{field_name} 必须是长度为 4 的坐标数组，格式示例：[1422, 604, 1441, 624]")

    try:
        region = tuple(int(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须全部为整数坐标，当前值: {value!r}") from exc

    if region[0] >= region[2] or region[1] >= region[3]:
        raise ValueError(f"{field_name} 坐标范围无效，当前值: {value!r}")
    return region


def _normalize_optional_threshold(value, field_name):
    if value in (None, ""):
        return float(config.NICKNAME_MATCH_THRESHOLD)

    try:
        threshold = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是 0 到 1 之间的数字，当前值: {value!r}") from exc

    if threshold <= 0 or threshold > 1:
        raise ValueError(f"{field_name} 必须大于 0 且小于等于 1，当前值: {value!r}")
    return threshold


def load_boundary_switch_accounts():
    data, source_path = _load_local_switch_account_config()
    accounts = {
        4: _normalize_account_id(data.get("after_slot_4_account_id"), "after_slot_4_account_id"),
        8: _normalize_account_id(data.get("after_slot_8_account_id"), "after_slot_8_account_id"),
    }
    return accounts, source_path


def load_listing_target_price():
    data, source_path = _load_local_switch_account_config()
    price = _normalize_listing_price(data.get("listing_price"), "listing_price")
    return price, source_path


def load_local_nickname_match_config():
    data, source_path = _load_local_switch_account_config()
    resolved_template_dir = resolve_nickname_template_dir(data.get("nickname_template_dir"), source_path)
    log_resolved_live_path("昵称模板目录", resolved_template_dir)
    nickname_match_config = {
        "template_dir": _normalize_optional_local_dir(data.get("nickname_template_dir"), source_path),
        "verify_region": _normalize_optional_region(
            data.get("nickname_verify_region"),
            "nickname_verify_region",
        ),
        "match_threshold": _normalize_optional_threshold(
            data.get("nickname_match_threshold"),
            "nickname_match_threshold",
        ),
    }
    return nickname_match_config, source_path
