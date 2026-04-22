import json
import os
import re

import config
from live_paths import (
    log_resolved_live_path,
    resolve_local_switch_account_config_path,
    resolve_nickname_template_dir,
)


_PURCHASE_PRICE_RULE_CONFIG_CACHE = None
_PURCHASE_PRICE_RULE_CONFIG_SOURCE_PATH = ""
_PURCHASE_PRICE_RULE_CONFIG_LOGGED = False


def _read_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _load_local_switch_account_config():
    resolved_source_path = resolve_local_switch_account_config_path()
    source_path = resolved_source_path.path
    log_resolved_live_path("本机换号配置", resolved_source_path)

    if not os.path.exists(source_path):
        raise FileNotFoundError(
            f"缺少本机真实换号配置文件：{source_path}。当前正式口径只认 C:\\py666 下的 local_switch_account_config.json"
        )

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


def _normalize_required_int(value, field_name):
    raw_value = str(value or "").strip()
    if not raw_value:
        raise ValueError(f"{field_name} 未配置有效整数，请在 local_switch_account_config.json 中补充该字段")
    if not raw_value.isdigit():
        raise ValueError(f"{field_name} 必须为纯数字整数，当前值: {value!r}")
    return int(raw_value)


def _normalize_purchase_price_prefixes(value, field_name):
    if value in (None, ""):
        return tuple()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} 必须是前缀数组，格式示例: [\"3\", \"16\"]")

    normalized_prefixes = []
    seen_prefixes = set()
    for item in value:
        prefix_text = str(item or "").strip()
        if not re.fullmatch(r"\d{1,2}", prefix_text):
            raise ValueError(f"{field_name} 中的前缀必须是 1 位或 2 位数字字符串，当前值: {item!r}")
        if prefix_text in seen_prefixes:
            raise ValueError(f"{field_name} 中存在重复前缀: {prefix_text}")
        seen_prefixes.add(prefix_text)
        normalized_prefixes.append(prefix_text)
    return tuple(normalized_prefixes)


def _split_purchase_price_prefixes_by_length(prefixes):
    one_digit_prefixes = []
    two_digit_prefixes = []
    for prefix_text in prefixes:
        if len(prefix_text) == 1:
            one_digit_prefixes.append(prefix_text)
        elif len(prefix_text) == 2:
            two_digit_prefixes.append(prefix_text)
    return tuple(one_digit_prefixes), tuple(two_digit_prefixes)


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


def _build_purchase_price_rule_config(data):
    min_exclusive = _normalize_required_int(
        data.get("purchase_price_min_exclusive"),
        "purchase_price_min_exclusive",
    )
    max_exclusive = _normalize_required_int(
        data.get("purchase_price_max_exclusive"),
        "purchase_price_max_exclusive",
    )
    if min_exclusive >= max_exclusive:
        raise ValueError(
            "purchase_price_min_exclusive 必须小于 purchase_price_max_exclusive，"
            f"当前值: {min_exclusive} >= {max_exclusive}"
        )

    rule_config = {
        "min_exclusive": min_exclusive,
        "max_exclusive": max_exclusive,
        "direct_accept_prefixes": _normalize_purchase_price_prefixes(
            data.get("purchase_price_direct_accept_prefixes"),
            "purchase_price_direct_accept_prefixes",
        ),
        "direct_reject_prefixes": _normalize_purchase_price_prefixes(
            data.get("purchase_price_direct_reject_prefixes"),
            "purchase_price_direct_reject_prefixes",
        ),
        "full_check_prefixes": _normalize_purchase_price_prefixes(
            data.get("purchase_price_full_check_prefixes"),
            "purchase_price_full_check_prefixes",
        ),
    }

    prefix_owner_map = {}
    action_prefix_map = {
        "purchase_price_direct_accept_prefixes": rule_config["direct_accept_prefixes"],
        "purchase_price_direct_reject_prefixes": rule_config["direct_reject_prefixes"],
        "purchase_price_full_check_prefixes": rule_config["full_check_prefixes"],
    }
    for config_key, field_name in (
        ("direct_accept_prefixes", "purchase_price_direct_accept_prefixes"),
        ("direct_reject_prefixes", "purchase_price_direct_reject_prefixes"),
        ("full_check_prefixes", "purchase_price_full_check_prefixes"),
    ):
        for prefix_text in rule_config[config_key]:
            previous_owner = prefix_owner_map.get(prefix_text)
            if previous_owner is not None:
                raise ValueError(
                    f"抢购价格前缀 {prefix_text} 同时出现在 {previous_owner} 和 {field_name} 中，请保持三类前缀互斥"
                )
            prefix_owner_map[prefix_text] = field_name

    redundant_prefix_messages = []
    for field_name, prefixes in action_prefix_map.items():
        one_digit_prefixes, two_digit_prefixes = _split_purchase_price_prefixes_by_length(prefixes)
        one_digit_set = set(one_digit_prefixes)
        redundant_two_digit_prefixes = [prefix_text for prefix_text in two_digit_prefixes if prefix_text[0] in one_digit_set]
        if redundant_two_digit_prefixes:
            redundant_prefix_messages.append(
                f"{field_name} 中的 {', '.join(redundant_two_digit_prefixes)} 与同动作的一位前缀重复，属于冗余配置"
            )

    for field_name, prefixes in action_prefix_map.items():
        current_one_digit_prefixes, _ = _split_purchase_price_prefixes_by_length(prefixes)
        for one_digit_prefix in current_one_digit_prefixes:
            for other_field_name, other_prefixes in action_prefix_map.items():
                if other_field_name == field_name:
                    continue
                conflicting_two_digit_prefixes = [
                    prefix_text for prefix_text in other_prefixes
                    if len(prefix_text) == 2 and prefix_text.startswith(one_digit_prefix)
                ]
                if conflicting_two_digit_prefixes:
                    raise ValueError(
                        f"一位前缀 {one_digit_prefix} 出现在 {field_name} 中，但其下的两位前缀 "
                        f"{', '.join(conflicting_two_digit_prefixes)} 出现在 {other_field_name} 中，"
                        "会产生跨动作覆盖冲突，请保持动作一致或删除冗余配置"
                    )

    for config_key in ("direct_accept_prefixes", "direct_reject_prefixes", "full_check_prefixes"):
        one_digit_prefixes, two_digit_prefixes = _split_purchase_price_prefixes_by_length(rule_config[config_key])
        rule_config[f"{config_key}_1digit"] = frozenset(one_digit_prefixes)
        rule_config[f"{config_key}_2digit"] = frozenset(two_digit_prefixes)

    rule_config["redundant_prefix_messages"] = tuple(redundant_prefix_messages)

    return rule_config


def _format_prefixes_for_log(prefixes):
    return "无" if not prefixes else "/".join(prefixes)


def load_purchase_price_rule_config(force_reload=False):
    global _PURCHASE_PRICE_RULE_CONFIG_CACHE
    global _PURCHASE_PRICE_RULE_CONFIG_SOURCE_PATH
    global _PURCHASE_PRICE_RULE_CONFIG_LOGGED

    if _PURCHASE_PRICE_RULE_CONFIG_CACHE is not None and not force_reload:
        return _PURCHASE_PRICE_RULE_CONFIG_CACHE, _PURCHASE_PRICE_RULE_CONFIG_SOURCE_PATH

    data, source_path = _load_local_switch_account_config()
    rule_config = _build_purchase_price_rule_config(data)
    _PURCHASE_PRICE_RULE_CONFIG_CACHE = rule_config
    _PURCHASE_PRICE_RULE_CONFIG_SOURCE_PATH = source_path

    if not _PURCHASE_PRICE_RULE_CONFIG_LOGGED or force_reload:
        _PURCHASE_PRICE_RULE_CONFIG_LOGGED = True
        print(
            "[抢购价格规则] 已加载："
            f"完整价格>{rule_config['min_exclusive']} 且 <{rule_config['max_exclusive']}，"
            f"直接抢前缀={_format_prefixes_for_log(rule_config['direct_accept_prefixes'])}，"
            f"直接不抢前缀={_format_prefixes_for_log(rule_config['direct_reject_prefixes'])}，"
            f"指定走完整价格前缀={_format_prefixes_for_log(rule_config['full_check_prefixes'])}，"
            f"来源={source_path}"
        )
        for redundant_message in rule_config["redundant_prefix_messages"]:
            print(f"[抢购价格规则] 冗余提示：{redundant_message}")

    return rule_config, source_path


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


def save_listing_target_price(new_price_str):
    """将新的上架价格写回 JSON 配置文件。"""
    normalized_price = _normalize_listing_price(new_price_str, "listing_price")
    resolved_source_path = resolve_local_switch_account_config_path()
    source_path = resolved_source_path.path
    data = _read_json(source_path)
    if not isinstance(data, dict):
        raise ValueError("本机换号配置文件格式错误，根节点必须是 JSON 对象")
    data["listing_price"] = str(normalized_price)
    with open(source_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
