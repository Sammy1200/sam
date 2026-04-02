import json
import os

import config


def _read_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _normalize_account_id(value, field_name):
    account_id = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not account_id:
        raise ValueError(f"{field_name} \u672a\u914d\u7f6e\u6709\u6548\u767b\u5f55\u53f7")
    return account_id


def load_boundary_switch_accounts():
    source_path = config.LOCAL_SWITCH_ACCOUNT_CONFIG_PATH

    if not os.path.exists(source_path):
        raise FileNotFoundError("\u7f3a\u5c11\u672c\u673a\u771f\u5b9e\u6362\u53f7\u914d\u7f6e\u6587\u4ef6 local_switch_account_config.json")

    data = _read_json(source_path)
    if not isinstance(data, dict):
        raise ValueError("\u672c\u673a\u6362\u53f7\u914d\u7f6e\u6587\u4ef6\u683c\u5f0f\u9519\u8bef\uff0c\u6839\u8282\u70b9\u5fc5\u987b\u662f JSON \u5bf9\u8c61")

    accounts = {
        4: _normalize_account_id(data.get("after_slot_4_account_id"), "after_slot_4_account_id"),
        8: _normalize_account_id(data.get("after_slot_8_account_id"), "after_slot_8_account_id"),
    }
    return accounts, source_path
