import json
import os
import re
import time

import config
from live_paths import (
    log_resolved_live_path,
    resolve_local_switch_account_config_path,
    resolve_nickname_template_dir,
)


_PURCHASE_PRICE_RULE_CONFIG_CACHE = None
_PURCHASE_PRICE_RULE_CONFIG_SOURCE_PATH = ""
_PURCHASE_PRICE_RULE_CONFIG_LOGGED = False
_EQUIPMENT_PRICE_RULE_CONFIG_CACHE = None
_EQUIPMENT_PRICE_RULE_CONFIG_SOURCE_PATH = ""
_EQUIPMENT_PRICE_RULE_CONFIG_LOGGED = False
_EXECUTION_SLOT_CONFIG_CACHE = None
_EXECUTION_SLOT_CONFIG_SOURCE_PATH = ""
STONE_PRICE_MODE_PREFIX = "prefix"
STONE_PRICE_MODE_FIXED_RANGE = "fixed_range"
STONE_PRICE_MODE_LABELS = {
    STONE_PRICE_MODE_PREFIX: "前缀抢购",
    STONE_PRICE_MODE_FIXED_RANGE: "固定上下限抢购",
}


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


def _normalize_optional_bool(value, field_name, default):
    if value in (None, ""):
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)

    raw_value = str(value).strip().lower()
    if raw_value in ("true", "1", "yes", "on", "启用", "开启"):
        return True
    if raw_value in ("false", "0", "no", "off", "禁用", "关闭"):
        return False
    raise ValueError(f"{field_name} 必须是布尔值 true/false，当前值: {value!r}")


def _normalize_optional_price_bound(value, field_name, default):
    if value in (None, ""):
        return int(default)
    raw_value = str(value).strip()
    if not raw_value.isdigit():
        raise ValueError(f"{field_name} 必须为纯数字整数，当前值: {value!r}")
    return int(raw_value)


def _normalize_stone_purchase_price_mode(value):
    if value in (None, ""):
        return STONE_PRICE_MODE_PREFIX
    mode = str(value).strip()
    if mode not in (STONE_PRICE_MODE_PREFIX, STONE_PRICE_MODE_FIXED_RANGE):
        raise ValueError(
            "stone_purchase_price_mode 只能是 prefix 或 fixed_range，"
            f"当前值: {value!r}"
        )
    return mode


def _load_legacy_listing_enabled_preference(source_path):
    legacy_path = os.path.join(os.path.dirname(source_path), "launcher_preferences.json")
    try:
        data = _read_json(legacy_path)
    except FileNotFoundError:
        return True, ""
    except Exception as exc:
        print(f"[启动器] 旧上架勾选记录读取失败：{exc}")
        return True, ""

    if isinstance(data, dict) and isinstance(data.get("listing_enabled"), bool):
        return bool(data["listing_enabled"]), legacy_path
    return True, ""


def _resolve_listing_enabled_setting(data, source_path):
    if "listing_enabled" in data:
        return _normalize_optional_bool(data.get("listing_enabled"), "listing_enabled", True), source_path
    return _load_legacy_listing_enabled_preference(source_path)


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


def _normalize_optional_positive_int(value, field_name, default):
    if value in (None, ""):
        return int(default)
    raw_value = str(value).strip()
    if not raw_value.isdigit():
        raise ValueError(f"{field_name} 必须是正整数，当前值: {value!r}")
    result = int(raw_value)
    if result <= 0:
        raise ValueError(f"{field_name} 必须大于 0，当前值: {value!r}")
    return result


def _normalize_slot_index_sequence(value, field_name, slot_count, default_values):
    if value in (None, ""):
        values = tuple(int(item) for item in default_values)
    else:
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{field_name} 必须是执行位数组")
        values = tuple(int(item) for item in value)

    if len(values) != int(slot_count):
        raise ValueError(f"{field_name} 长度必须等于 execution_slot_count={slot_count}，当前长度: {len(values)}")
    if any(item < 0 for item in values):
        raise ValueError(f"{field_name} 中的大区索引必须大于等于 0")
    return values


def _normalize_slot_template_files(value, field_name, slot_count, default_values):
    if value in (None, ""):
        if len(default_values) == int(slot_count):
            return tuple(str(item or "").strip() for item in default_values)
        return tuple(f"{slot_index}.png" for slot_index in range(1, int(slot_count) + 1))

    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} 必须是模板文件数组")

    files = tuple(str(item or "").strip() for item in value)
    if len(files) != int(slot_count):
        raise ValueError(f"{field_name} 长度必须等于 execution_slot_count={slot_count}，当前长度: {len(files)}")
    if any(not item for item in files):
        raise ValueError(f"{field_name} 不能包含空模板文件名")
    return files


def _normalize_slot_int_map(value, field_name, slot_count, default_map):
    if value in (None, ""):
        return {int(key): int(target) for key, target in default_map.items()}

    if not isinstance(value, dict):
        raise ValueError(f"{field_name} 必须是对象，例如 {{\"8\": 9, \"9\": 1}}")

    result = {}
    for raw_key, raw_target in value.items():
        try:
            key = int(raw_key)
            target = int(raw_target)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} 的键和值都必须是执行位整数") from exc
        if key < 1 or key > int(slot_count) or target < 1 or target > int(slot_count):
            raise ValueError(f"{field_name} 中的执行位必须在 1-{slot_count} 范围内")
        result[key] = target
    return result


def _build_default_next_slot_map(slot_count):
    return {
        slot_index: (slot_index + 1 if slot_index < int(slot_count) else 1)
        for slot_index in range(1, int(slot_count) + 1)
    }


def _build_default_execution_slot_config(source_path=""):
    slot_count = int(config.EXECUTION_SLOT_COUNT)
    return {
        "count": slot_count,
        "nicknames": tuple(config.EXECUTION_SLOT_NICKNAMES),
        "server_coord_indexes": tuple(config.EXECUTION_SLOT_SERVER_COORD_INDEXES),
        "nickname_template_files": tuple(config.EXECUTION_SLOT_NICKNAME_TEMPLATE_FILES),
        "next_slot_map": {int(key): int(value) for key, value in config.EXECUTION_SLOT_NEXT_SLOT_MAP.items()},
        "switch_targets": {int(key): int(value) for key, value in config.EXECUTION_SLOT_SWITCH_TARGETS.items()},
        "source_path": source_path,
    }


def _build_execution_slot_config(data, source_path=""):
    slot_count = _normalize_optional_positive_int(
        data.get("execution_slot_count"),
        "execution_slot_count",
        config.EXECUTION_SLOT_COUNT,
    )
    default_nicknames = tuple(config.EXECUTION_SLOT_NICKNAMES)
    if len(default_nicknames) == slot_count:
        nicknames = default_nicknames
    else:
        nicknames = tuple("" for _ in range(slot_count))

    default_server_indexes = tuple(config.EXECUTION_SLOT_SERVER_COORD_INDEXES)
    default_template_files = tuple(config.EXECUTION_SLOT_NICKNAME_TEMPLATE_FILES)
    default_next_slot_map = (
        {int(key): int(value) for key, value in config.EXECUTION_SLOT_NEXT_SLOT_MAP.items()}
        if slot_count == int(config.EXECUTION_SLOT_COUNT)
        else _build_default_next_slot_map(slot_count)
    )
    default_switch_targets = (
        {int(key): int(value) for key, value in config.EXECUTION_SLOT_SWITCH_TARGETS.items()}
        if slot_count == int(config.EXECUTION_SLOT_COUNT)
        else {}
    )

    server_coord_indexes = _normalize_slot_index_sequence(
        data.get("execution_slot_server_coord_indexes"),
        "execution_slot_server_coord_indexes",
        slot_count,
        default_server_indexes,
    )
    nickname_template_files = _normalize_slot_template_files(
        data.get("execution_slot_nickname_template_files"),
        "execution_slot_nickname_template_files",
        slot_count,
        default_template_files,
    )
    next_slot_map = _normalize_slot_int_map(
        data.get("execution_slot_next_slot_map"),
        "execution_slot_next_slot_map",
        slot_count,
        default_next_slot_map,
    )
    switch_targets = _normalize_slot_int_map(
        data.get("execution_slot_switch_targets"),
        "execution_slot_switch_targets",
        slot_count,
        default_switch_targets,
    )

    missing_next_slots = [
        slot_index
        for slot_index in range(1, int(slot_count) + 1)
        if slot_index not in next_slot_map
    ]
    if missing_next_slots:
        raise ValueError(f"execution_slot_next_slot_map 缺少执行位: {missing_next_slots}")

    return {
        "count": int(slot_count),
        "nicknames": tuple(nicknames),
        "server_coord_indexes": tuple(server_coord_indexes),
        "nickname_template_files": tuple(nickname_template_files),
        "next_slot_map": dict(next_slot_map),
        "switch_targets": dict(switch_targets),
        "source_path": source_path,
    }


def load_execution_slot_config(force_reload=False):
    global _EXECUTION_SLOT_CONFIG_CACHE
    global _EXECUTION_SLOT_CONFIG_SOURCE_PATH

    if _EXECUTION_SLOT_CONFIG_CACHE is not None and not force_reload:
        return _EXECUTION_SLOT_CONFIG_CACHE, _EXECUTION_SLOT_CONFIG_SOURCE_PATH

    try:
        data, source_path = _load_local_switch_account_config()
    except FileNotFoundError:
        config_payload = _build_default_execution_slot_config("")
        _EXECUTION_SLOT_CONFIG_CACHE = config_payload
        _EXECUTION_SLOT_CONFIG_SOURCE_PATH = ""
        return config_payload, ""

    config_payload = _build_execution_slot_config(data, source_path)
    _EXECUTION_SLOT_CONFIG_CACHE = config_payload
    _EXECUTION_SLOT_CONFIG_SOURCE_PATH = source_path
    return config_payload, source_path


def get_execution_slot_count():
    execution_slot_config, _ = load_execution_slot_config()
    return int(execution_slot_config["count"])


def get_temporary_account_display_slot():
    return get_execution_slot_count() + 1


def get_execution_slot_nicknames():
    execution_slot_config, _ = load_execution_slot_config()
    return tuple(execution_slot_config["nicknames"])


def get_execution_slot_server_coord_indexes():
    execution_slot_config, _ = load_execution_slot_config()
    return tuple(execution_slot_config["server_coord_indexes"])


def get_execution_slot_nickname_template_files():
    execution_slot_config, _ = load_execution_slot_config()
    return tuple(execution_slot_config["nickname_template_files"])


def resolve_execution_slot_account_index(slot_number):
    try:
        normalized_slot_number = int(slot_number)
    except (TypeError, ValueError):
        return 0

    execution_slot_config, _ = load_execution_slot_config()
    switch_boundaries = sorted(int(slot) for slot in execution_slot_config["switch_targets"])
    account_index = 0
    for boundary_slot in switch_boundaries:
        if normalized_slot_number > boundary_slot:
            account_index += 1
    return account_index


def resolve_account_switch_source_slot_for_execution_slot(slot_number):
    try:
        normalized_slot_number = int(slot_number)
    except (TypeError, ValueError):
        return None

    execution_slot_config, _ = load_execution_slot_config()
    slot_count = int(execution_slot_config["count"])
    if normalized_slot_number < 1 or normalized_slot_number > slot_count:
        return None

    switch_boundaries = sorted(int(slot) for slot in execution_slot_config["switch_targets"])
    if not switch_boundaries:
        return None

    for index, boundary_slot in enumerate(switch_boundaries):
        if normalized_slot_number <= boundary_slot:
            return switch_boundaries[index - 1] if index > 0 else switch_boundaries[-1]
    return switch_boundaries[-1]


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
    fixed_min_inclusive = _normalize_optional_price_bound(
        data.get("stone_fixed_price_min_inclusive"),
        "stone_fixed_price_min_inclusive",
        min_exclusive + 1,
    )
    fixed_max_inclusive = _normalize_optional_price_bound(
        data.get("stone_fixed_price_max_inclusive"),
        "stone_fixed_price_max_inclusive",
        max_exclusive - 1,
    )
    if fixed_min_inclusive > fixed_max_inclusive:
        raise ValueError(
            "stone_fixed_price_min_inclusive 必须小于或等于 stone_fixed_price_max_inclusive，"
            f"当前值: {fixed_min_inclusive} > {fixed_max_inclusive}"
        )

    rule_config = {
        "stone_purchase_price_mode": _normalize_stone_purchase_price_mode(
            data.get("stone_purchase_price_mode")
        ),
        "stone_fixed_price_min_inclusive": fixed_min_inclusive,
        "stone_fixed_price_max_inclusive": fixed_max_inclusive,
        "min_exclusive": min_exclusive,
        "max_exclusive": max_exclusive,
        "direct_accept_prefixes": _normalize_purchase_price_prefixes(
            data.get("purchase_price_direct_accept_prefixes"),
            "purchase_price_direct_accept_prefixes",
        ),
        "skip_item_click_prefixes": _normalize_purchase_price_prefixes(
            data.get("purchase_price_skip_item_click_prefixes"),
            "purchase_price_skip_item_click_prefixes",
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
        "purchase_price_skip_item_click_prefixes": rule_config["skip_item_click_prefixes"],
        "purchase_price_direct_reject_prefixes": rule_config["direct_reject_prefixes"],
        "purchase_price_full_check_prefixes": rule_config["full_check_prefixes"],
    }
    for config_key, field_name in (
        ("direct_accept_prefixes", "purchase_price_direct_accept_prefixes"),
        ("skip_item_click_prefixes", "purchase_price_skip_item_click_prefixes"),
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

    for config_key in (
        "direct_accept_prefixes",
        "skip_item_click_prefixes",
        "direct_reject_prefixes",
        "full_check_prefixes",
    ):
        one_digit_prefixes, two_digit_prefixes = _split_purchase_price_prefixes_by_length(rule_config[config_key])
        rule_config[f"{config_key}_1digit"] = frozenset(one_digit_prefixes)
        rule_config[f"{config_key}_2digit"] = frozenset(two_digit_prefixes)

    rule_config["redundant_prefix_messages"] = tuple(redundant_prefix_messages)

    return rule_config


def _build_equipment_price_rule_config(data):
    min_exclusive = _normalize_optional_price_bound(
        data.get("equipment_price_min_exclusive"),
        "equipment_price_min_exclusive",
        config.EQUIPMENT_PRICE_MIN_EXCLUSIVE,
    )
    max_exclusive = _normalize_optional_price_bound(
        data.get("equipment_price_max_exclusive"),
        "equipment_price_max_exclusive",
        config.EQUIPMENT_PRICE_MAX_EXCLUSIVE,
    )
    if min_exclusive >= max_exclusive:
        raise ValueError(
            "equipment_price_min_exclusive 必须小于 equipment_price_max_exclusive，"
            f"当前值: {min_exclusive} >= {max_exclusive}"
        )
    return {
        "equipment_price_min_exclusive": min_exclusive,
        "equipment_price_max_exclusive": max_exclusive,
    }


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
        mode_label = STONE_PRICE_MODE_LABELS.get(rule_config["stone_purchase_price_mode"], "未知模式")
        if rule_config["stone_purchase_price_mode"] == STONE_PRICE_MODE_FIXED_RANGE:
            print(
                "[抢购价格规则] 已加载："
                f"模式={mode_label}，"
                f"石头价格>={rule_config['stone_fixed_price_min_inclusive']} "
                f"且 <={rule_config['stone_fixed_price_max_inclusive']}，"
                f"来源={source_path}"
            )
        else:
            print(
                "[抢购价格规则] 已加载："
                f"模式={mode_label}，"
                f"完整价格>{rule_config['min_exclusive']} 且 <{rule_config['max_exclusive']}，"
                f"直接抢前缀={_format_prefixes_for_log(rule_config['direct_accept_prefixes'])}，"
                f"跳过商品点击前缀={_format_prefixes_for_log(rule_config['skip_item_click_prefixes'])}，"
                f"直接不抢前缀={_format_prefixes_for_log(rule_config['direct_reject_prefixes'])}，"
                f"指定走完整价格前缀={_format_prefixes_for_log(rule_config['full_check_prefixes'])}，"
                f"来源={source_path}"
            )
        for redundant_message in rule_config["redundant_prefix_messages"]:
            print(f"[抢购价格规则] 冗余提示：{redundant_message}")

    return rule_config, source_path


def load_equipment_price_rule_config(force_reload=False):
    global _EQUIPMENT_PRICE_RULE_CONFIG_CACHE
    global _EQUIPMENT_PRICE_RULE_CONFIG_SOURCE_PATH
    global _EQUIPMENT_PRICE_RULE_CONFIG_LOGGED

    if _EQUIPMENT_PRICE_RULE_CONFIG_CACHE is not None and not force_reload:
        return _EQUIPMENT_PRICE_RULE_CONFIG_CACHE, _EQUIPMENT_PRICE_RULE_CONFIG_SOURCE_PATH

    data, source_path = _load_local_switch_account_config()
    rule_config = _build_equipment_price_rule_config(data)
    _EQUIPMENT_PRICE_RULE_CONFIG_CACHE = rule_config
    _EQUIPMENT_PRICE_RULE_CONFIG_SOURCE_PATH = source_path

    if not _EQUIPMENT_PRICE_RULE_CONFIG_LOGGED or force_reload:
        _EQUIPMENT_PRICE_RULE_CONFIG_LOGGED = True
        print(
            "[装备价格规则] 已加载："
            f"装备价格>{rule_config['equipment_price_min_exclusive']} "
            f"且 <{rule_config['equipment_price_max_exclusive']}，"
            f"来源={source_path}"
        )

    return rule_config, source_path


def load_launcher_settings():
    data, source_path = _load_local_switch_account_config()
    rule_config = _build_purchase_price_rule_config(data)
    equipment_rule_config = _build_equipment_price_rule_config(data)
    listing_enabled, listing_source_path = _resolve_listing_enabled_setting(data, source_path)
    return {
        "listing_enabled": listing_enabled,
        "listing_enabled_source_path": listing_source_path,
        "stone_purchase_price_mode": rule_config["stone_purchase_price_mode"],
        "stone_fixed_price_min_inclusive": rule_config["stone_fixed_price_min_inclusive"],
        "stone_fixed_price_max_inclusive": rule_config["stone_fixed_price_max_inclusive"],
        "equipment_price_min_exclusive": equipment_rule_config["equipment_price_min_exclusive"],
        "equipment_price_max_exclusive": equipment_rule_config["equipment_price_max_exclusive"],
        "source_path": source_path,
    }


def save_launcher_settings(settings):
    global _PURCHASE_PRICE_RULE_CONFIG_CACHE
    global _PURCHASE_PRICE_RULE_CONFIG_SOURCE_PATH
    global _PURCHASE_PRICE_RULE_CONFIG_LOGGED
    global _EQUIPMENT_PRICE_RULE_CONFIG_CACHE
    global _EQUIPMENT_PRICE_RULE_CONFIG_SOURCE_PATH
    global _EQUIPMENT_PRICE_RULE_CONFIG_LOGGED

    resolved_source_path = resolve_local_switch_account_config_path()
    source_path = resolved_source_path.path
    data = _read_json(source_path)
    if not isinstance(data, dict):
        raise ValueError("本机换号配置文件格式错误，根节点必须是 JSON 对象")

    listing_enabled = _normalize_optional_bool(settings.get("listing_enabled"), "listing_enabled", True)
    mode = _normalize_stone_purchase_price_mode(settings.get("stone_purchase_price_mode"))
    min_exclusive = _normalize_required_int(
        data.get("purchase_price_min_exclusive"),
        "purchase_price_min_exclusive",
    )
    max_exclusive = _normalize_required_int(
        data.get("purchase_price_max_exclusive"),
        "purchase_price_max_exclusive",
    )
    fixed_min = _normalize_optional_price_bound(
        settings.get("stone_fixed_price_min_inclusive"),
        "stone_fixed_price_min_inclusive",
        min_exclusive + 1,
    )
    fixed_max = _normalize_optional_price_bound(
        settings.get("stone_fixed_price_max_inclusive"),
        "stone_fixed_price_max_inclusive",
        max_exclusive - 1,
    )
    if fixed_min > fixed_max:
        raise ValueError("固定价格下限不能大于上限")
    equipment_min = _normalize_optional_price_bound(
        settings.get("equipment_price_min_exclusive"),
        "equipment_price_min_exclusive",
        config.EQUIPMENT_PRICE_MIN_EXCLUSIVE,
    )
    equipment_max = _normalize_optional_price_bound(
        settings.get("equipment_price_max_exclusive"),
        "equipment_price_max_exclusive",
        config.EQUIPMENT_PRICE_MAX_EXCLUSIVE,
    )
    if equipment_min >= equipment_max:
        raise ValueError("装备价格下限必须小于上限")

    data["_comment_listing_enabled"] = "启动器参数设置：全局上架总开关。false 时本次启动内所有场景都跳过上架，且上架模式按钮不可点击。"
    data["listing_enabled"] = listing_enabled
    data["_comment_stone_purchase_price_mode"] = "启动器参数设置：石头抢购方式。prefix=前缀抢购；fixed_range=固定上下限抢购。"
    data["stone_purchase_price_mode"] = mode
    data["_comment_stone_fixed_price_min_inclusive"] = "固定上下限抢购：石头价格下限，含等于。"
    data["stone_fixed_price_min_inclusive"] = fixed_min
    data["_comment_stone_fixed_price_max_inclusive"] = "固定上下限抢购：石头价格上限，含等于。"
    data["stone_fixed_price_max_inclusive"] = fixed_max
    data["_comment_equipment_price_min_exclusive"] = "装备设置：装备抢购价格下限，不含等于。"
    data["equipment_price_min_exclusive"] = equipment_min
    data["_comment_equipment_price_max_exclusive"] = "装备设置：装备抢购价格上限，不含等于。"
    data["equipment_price_max_exclusive"] = equipment_max
    data["_comment_launcher_settings_updated_at"] = "启动器参数设置最近保存时间。"
    data["launcher_settings_updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    _build_purchase_price_rule_config(data)
    _build_equipment_price_rule_config(data)
    with open(source_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    _PURCHASE_PRICE_RULE_CONFIG_CACHE = None
    _PURCHASE_PRICE_RULE_CONFIG_SOURCE_PATH = ""
    _PURCHASE_PRICE_RULE_CONFIG_LOGGED = False
    _EQUIPMENT_PRICE_RULE_CONFIG_CACHE = None
    _EQUIPMENT_PRICE_RULE_CONFIG_SOURCE_PATH = ""
    _EQUIPMENT_PRICE_RULE_CONFIG_LOGGED = False
    return load_launcher_settings()


def load_boundary_switch_accounts():
    data, source_path = _load_local_switch_account_config()
    execution_slot_config = _build_execution_slot_config(data, source_path)
    accounts = {}
    for slot_number in sorted(execution_slot_config["switch_targets"]):
        field_name = f"after_slot_{slot_number}_account_id"
        accounts[int(slot_number)] = _normalize_account_id(data.get(field_name), field_name)
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
