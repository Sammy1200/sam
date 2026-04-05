import json
import os

import config


def _read_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _load_local_switch_account_config():
    source_path = config.LOCAL_SWITCH_ACCOUNT_CONFIG_PATH

    if not os.path.exists(source_path):
        raise FileNotFoundError("缺少本机真实换号配置文件 local_switch_account_config.json")

    data = _read_json(source_path)
    if not isinstance(data, dict):
        raise ValueError("本机换号配置文件格式错误，根节点必须是 JSON 对象")

    return data, source_path


def _normalize_account_id(value, field_name):
    account_id = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not account_id:
        raise ValueError(f"{field_name} \u672a\u914d\u7f6e\u6709\u6548\u767b\u5f55\u53f7")
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
