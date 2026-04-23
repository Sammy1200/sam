"""启动页上架模式：独立筛号、进场、批次上架与账号收尾。"""

import re

import config
import state
from account_view_repo import get_account_view_rows
from account_db import (
    CANONICAL_ACCOUNT_STATS_TABLE,
    ROUND_STATUS_LIMITED,
    ROUND_STATUS_READY,
    ensure_canonical_account_stats_table,
    ensure_canonical_execution_slot_seed_records,
    ensure_local_canonical_account_stats_store,
    find_canonical_account_stats_store,
    normalize_canonical_round_status_values,
    read_preferred_canonical_account_stats_record_by_execution_slot,
)
from listing import execute_startup_listing_batch
from overlay import ui_print, update_score_text
from purchase import parse_balance_text_to_value, recognize_latest_balance_at_trade
from purchase import clear_live_listing_count_for_account_switch
from round_persistence import (
    persist_startup_listing_mode_listing_count_clear,
    persist_startup_listing_mode_account_snapshot,
    reset_round_runtime_state,
)
from switch import (
    enter_startup_listing_target_slot,
    exit_to_launcher_for_startup_listing,
    navigate_to_trade,
    refresh_latest_balance_route,
)
from utils import async_push_msg, logger


STARTUP_LISTING_BALANCE_THRESHOLD = 500000000
STARTUP_LISTING_LOW_BALANCE_THRESHOLD = 400000000
STARTUP_LISTING_LOW_BALANCE_TARGET = 99
STARTUP_LISTING_MID_BALANCE_TARGET = 50


def _parse_duration_text_to_total_minutes(raw_text):
    text = str(raw_text or "").strip()
    if not text:
        return None

    hours = 0
    minutes = 0
    seconds = 0
    matched = False

    hour_match = re.search(r"(\d+)\s*小时", text)
    if hour_match:
        hours = int(hour_match.group(1))
        matched = True

    minute_match = re.search(r"(\d+)\s*分", text)
    if minute_match:
        minutes = int(minute_match.group(1))
        matched = True

    second_match = re.search(r"(\d+)\s*秒", text)
    if second_match:
        seconds = int(second_match.group(1))
        matched = True

    if not matched:
        digits_only = "".join(ch for ch in text if ch.isdigit())
        if not digits_only:
            return None
        return int(digits_only)

    total_minutes = hours * 60 + minutes
    if seconds > 0:
        total_minutes += 1
    return total_minutes


def _build_runtime_minutes_candidate(row):
    if not bool(row.get("allow_purchase")):
        return None

    source = str(row.get("runtime_window_source") or "").strip()
    if source == "missing":
        return None

    raw_seconds = row.get("runtime_window_remaining_seconds")
    try:
        if raw_seconds not in (None, ""):
            normalized_seconds = max(0, int(raw_seconds))
            return (normalized_seconds + 59) // 60
    except (TypeError, ValueError):
        pass

    return _parse_duration_text_to_total_minutes(row.get("runtime_window_remaining_text"))


def _build_cooldown_seconds_candidate(row):
    raw_seconds = row.get("cooldown_remaining_seconds")
    try:
        if raw_seconds in (None, ""):
            return None
        return max(0, int(raw_seconds))
    except (TypeError, ValueError):
        return None


def _select_normal_mode_handoff_target():
    rows_result = get_account_view_rows()
    rows = rows_result.get("rows") or []
    rows_by_slot = {}
    for row in rows:
        try:
            slot_number = int(row.get("current_execution_slot"))
        except (TypeError, ValueError):
            continue
        if 1 <= slot_number <= int(config.EXECUTION_SLOT_COUNT) and slot_number not in rows_by_slot:
            rows_by_slot[slot_number] = row

    runtime_candidates = []
    cooldown_candidates = []
    for slot_number in range(1, int(config.EXECUTION_SLOT_COUNT) + 1):
        row = rows_by_slot.get(slot_number)
        if row is None:
            continue

        runtime_minutes = _build_runtime_minutes_candidate(row)
        if runtime_minutes is not None:
            runtime_candidates.append((runtime_minutes, slot_number, row))

        cooldown_seconds = _build_cooldown_seconds_candidate(row)
        if cooldown_seconds is not None:
            cooldown_candidates.append((cooldown_seconds, slot_number, row))

    if runtime_candidates:
        runtime_minutes, target_slot, row = min(runtime_candidates, key=lambda item: (item[0], item[1]))
        return {
            "target_slot": target_slot,
            "nickname": str(row.get("nickname") or "").strip(),
            "selection_mode": "runtime_minutes",
            "selection_value": runtime_minutes,
        }

    if cooldown_candidates:
        cooldown_seconds, target_slot, row = min(cooldown_candidates, key=lambda item: (item[0], item[1]))
        return {
            "target_slot": target_slot,
            "nickname": str(row.get("nickname") or "").strip(),
            "selection_mode": "cooldown_seconds",
            "selection_value": cooldown_seconds,
        }

    return {
        "target_slot": 1,
        "nickname": "",
        "selection_mode": "fallback_slot_1",
        "selection_value": None,
    }


def _ensure_canonical_store_context():
    if str(state.account_db_path or "").strip():
        return state.account_db_path, state.account_db_table_name or CANONICAL_ACCOUNT_STATS_TABLE

    database_path, table_name = find_canonical_account_stats_store()
    if not database_path:
        database_path, table_name, inserted_seed_records = ensure_local_canonical_account_stats_store()
        if inserted_seed_records:
            inserted_slots = ",".join(str(record.current_execution_slot) for record in inserted_seed_records)
            logger.info("[上架模式] 已初始化 canonical 主库并补齐执行位：%s", inserted_slots)

    ensure_canonical_account_stats_table(database_path, table_name)
    ensure_canonical_execution_slot_seed_records(database_path, table_name)
    normalized_count = normalize_canonical_round_status_values(database_path, table_name)
    if normalized_count > 0:
        logger.info("[上架模式] 已归一旧状态样本：%s 条", normalized_count)

    state.account_db_path = database_path
    state.account_db_table_name = table_name or CANONICAL_ACCOUNT_STATS_TABLE
    return database_path, state.account_db_table_name


def _read_slot_record(slot_number):
    database_path, table_name = _ensure_canonical_store_context()
    return read_preferred_canonical_account_stats_record_by_execution_slot(
        database_path,
        slot_number,
        table_name,
    )


def _is_limited_slot_record(record):
    if record is None:
        return False
    return str(record.round_status or "").strip() == ROUND_STATUS_LIMITED


def _find_next_candidate(processed_slots, skipped_slots=None):
    ignored_slots = set(processed_slots or ())
    ignored_slots.update(skipped_slots or ())
    for slot_number in range(1, int(config.EXECUTION_SLOT_COUNT) + 1):
        if slot_number in ignored_slots:
            continue

        record = _read_slot_record(slot_number)
        if record is None:
            continue

        if _is_limited_slot_record(record):
            continue

        balance_text = str(record.current_balance or "").strip()
        balance_value = parse_balance_text_to_value(balance_text)
        if balance_value is None or balance_value >= STARTUP_LISTING_BALANCE_THRESHOLD:
            continue

        return {
            "slot": slot_number,
            "record": record,
            "balance_text": balance_text,
            "balance_value": balance_value,
        }
    return None


def _hydrate_state_from_record(record):
    state.current_nickname = record.nickname
    state.baseline_item_count = int(record.baseline_item_count)
    state.last_limit_time = record.last_limit_time
    state.last_account_end_time = record.last_account_end_time
    state.updated_at = record.updated_at
    if record.current_execution_slot is not None:
        state.current_execution_slot = int(record.current_execution_slot)
    state.success_count = int(record.round_purchase_success_count)
    state.total_listed_count = int(record.round_listing_success_count)
    state.fail_count = int(record.round_purchase_fail_count)
    state.round_purchase_success_count = int(record.round_purchase_success_count)
    state.round_listing_success_count = int(record.round_listing_success_count)
    state.round_purchase_fail_count = int(record.round_purchase_fail_count)
    state.round_current_balance = str(record.current_balance or "").strip()
    state.current_balance = state.round_current_balance or "获取中..."
    state.last_valid_balance = state.round_current_balance
    state.total_running_time = float(record.purchase_running_seconds)
    state.round_purchase_running_seconds = float(record.purchase_running_seconds)
    state.runtime_window_start_time = record.runtime_window_start_time
    state.round_status = str(record.round_status or "").strip() or ROUND_STATUS_READY
    state.account_record_loaded = True
    state.account_allow_purchase = True
    state.account_allow_start_time = None
    state.account_read_status = "ready"
    state.account_is_waiting = False
    state.account_read_error = ""
    state.overlay_status = "上架模式"
    if state.overlay_root:
        try:
            state.overlay_root.after(0, update_score_text)
        except Exception:
            pass


def _prepare_listing_account_context(slot_number):
    record = _read_slot_record(slot_number)
    if record is None:
        return None

    _hydrate_state_from_record(record)
    reset_round_runtime_state(
        f"启动页上架模式进入执行位 {slot_number}",
        reset_purchase_runtime=False,
        reset_round_counters=True,
    )
    state.current_nickname = record.nickname
    state.current_execution_slot = int(record.current_execution_slot or slot_number)
    state.current_balance = str(record.current_balance or "").strip() or "获取中..."
    state.last_valid_balance = str(record.current_balance or "").strip()
    state.round_current_balance = ""
    state.round_status = ROUND_STATUS_READY
    state.overlay_status = "上架模式"
    if state.overlay_root:
        try:
            state.overlay_root.after(0, update_score_text)
        except Exception:
            pass
    return record


def _apply_balance_to_state(balance_text):
    normalized_text = str(balance_text or "").strip()
    if not normalized_text:
        return None

    state.current_balance = normalized_text
    state.last_valid_balance = normalized_text
    state.round_current_balance = normalized_text
    if state.overlay_root:
        try:
            state.overlay_root.after(0, update_score_text)
        except Exception:
            pass
    return parse_balance_text_to_value(normalized_text)


def _recognize_trade_balance_with_fallback(camera, fallback_text, log_prefix):
    latest_balance = recognize_latest_balance_at_trade(camera)
    if latest_balance is not None:
        _apply_balance_to_state(latest_balance["text"])
        return {
            "status": "success",
            "text": latest_balance["text"],
            "value": latest_balance["value"],
        }

    normalized_fallback = str(fallback_text or state.last_valid_balance or state.current_balance or "").strip()
    fallback_value = _apply_balance_to_state(normalized_fallback)
    if fallback_value is not None:
        logger.warning("[上架模式] %s未识别到最新余额，沿用旧余额：%s", log_prefix, normalized_fallback)
        ui_print("沿用旧余额", save_log=True)
        return {
            "status": "fallback",
            "text": normalized_fallback,
            "value": fallback_value,
        }

    logger.warning("[上架模式] %s未识别到最新余额，且无可用旧余额。", log_prefix)
    ui_print("余额未识别", save_log=True)
    return {
        "status": "failed",
        "text": "",
        "value": None,
    }


def _read_latest_trade_balance(camera, fallback_text, log_prefix):
    return _recognize_trade_balance_with_fallback(camera, fallback_text, log_prefix)


def _refresh_balance_after_batch(camera, fallback_text):
    result = refresh_latest_balance_route(camera)
    if result["status"] == "success":
        return _read_latest_trade_balance(camera, fallback_text, "补领金币后")

    if result["status"] == "no_gold":
        if not navigate_to_trade(camera):
            logger.warning("[上架模式] 未识别到金币入口，且返回交易行失败。")
            return _recognize_trade_balance_with_fallback(camera, fallback_text, "无金币可领后")
        return _read_latest_trade_balance(camera, fallback_text, "无金币可领后")

    logger.warning("[上架模式] 批次后余额刷新失败：%s", result["detail"])
    return _recognize_trade_balance_with_fallback(camera, fallback_text, "批次刷新失败后")


def _resolve_batch_target(balance_value):
    if balance_value is None:
        return 0
    if balance_value < STARTUP_LISTING_LOW_BALANCE_THRESHOLD:
        return STARTUP_LISTING_LOW_BALANCE_TARGET
    if balance_value <= STARTUP_LISTING_BALANCE_THRESHOLD:
        return STARTUP_LISTING_MID_BALANCE_TARGET
    return 0


def _append_summary_entry(
    summary_entries,
    slot_number,
    reason_text,
    latest_balance_text,
    listing_count,
    item_inventory,
):
    summary_entries.append(
        {
            "execution_slot": int(slot_number),
            "end_reason": str(reason_text or "").strip() or "未说明",
            "latest_balance_text": str(latest_balance_text or "").strip() or "未识别",
            "listing_count": int(listing_count),
            "item_inventory": int(item_inventory),
        }
    )


def _finalize_account(
    summary_entries,
    slot_number,
    reason_text,
    latest_balance_text,
    limit_account=False,
    round_status_override=None,
    preserve_existing_status=False,
):
    update_last_limit_time = bool(limit_account)
    listing_count_snapshot = int(state.round_listing_success_count)
    item_inventory_snapshot = int(state.baseline_item_count)
    if latest_balance_text:
        _apply_balance_to_state(latest_balance_text)
    if round_status_override is not None:
        save_status = str(round_status_override or "").strip() or ROUND_STATUS_READY
    else:
        save_status = ROUND_STATUS_LIMITED if limit_account else ROUND_STATUS_READY
    persist_result = persist_startup_listing_mode_account_snapshot(
        save_status,
        update_last_limit_time=update_last_limit_time,
        preserve_existing_status=preserve_existing_status,
    )
    if persist_result.status not in ("success", "skipped"):
        logger.warning("[上架模式] 执行位 %s 收尾写库失败：%s", slot_number, persist_result.reason)
    _append_summary_entry(
        summary_entries,
        slot_number,
        reason_text,
        latest_balance_text,
        listing_count_snapshot,
        item_inventory_snapshot,
    )


def _push_final_summary(summary_entries, skipped_limited_slots=None):
    skipped_limited_slots = set(skipped_limited_slots or ())
    if summary_entries:
        lines = []
        for entry in sorted(summary_entries, key=lambda item: item["execution_slot"]):
            lines.append(
                "\n".join(
                    (
                        f"执行位：{entry['execution_slot']}",
                        f"结束原因：{entry['end_reason']}",
                        f"最新余额：{entry['latest_balance_text']}",
                        f"上架次数：{entry['listing_count']}",
                        f"道具库存：{entry['item_inventory']}",
                    )
                )
            )
        content = "\n\n".join(lines)
    else:
        content = "本轮未找到符合条件的账号。"
    if skipped_limited_slots:
        skipped_slots_text = ",".join(str(slot) for slot in sorted(skipped_limited_slots))
        content += f"\n跳过限制执行位：{skipped_slots_text}"
    async_push_msg("【上架汇总】执行完成", content)


def _best_effort_exit_after_fatal(camera, slot_number, failure_detail):
    """已进游戏后遇到致命错误时，尽量先正常下号，避免停在中间页面。"""
    try:
        exit_result = exit_to_launcher_for_startup_listing(camera)
    except Exception as exc:
        logger.warning("[上架模式] 执行位 %s 致命错误后补下号异常：%s", slot_number, exc)
        return

    if exit_result["status"] != "success":
        logger.warning(
            "[上架模式] 执行位 %s 致命错误后补下号失败：%s（原错误：%s）",
            slot_number,
            exit_result["detail"],
            failure_detail,
        )


def run_startup_listing_mode(camera):
    processed_slots = set()
    skipped_limited_slots = set()
    summary_entries = []
    current_group = 0
    already_at_launcher = True
    first_entry = True

    state.startup_listing_mode_active = True
    try:
        _ensure_canonical_store_context()
        ui_print("启动页上架", save_log=True)
        logger.info("[上架模式] 启动页上架模式开始。")

        while True:
            candidate = _find_next_candidate(processed_slots, skipped_limited_slots)
            if candidate is None:
                handoff_target = _select_normal_mode_handoff_target()
                _push_final_summary(summary_entries, skipped_limited_slots)
                logger.info(
                    "[上架模式] 无剩余候选执行位，准备切回正常模式：slot=%s mode=%s value=%s",
                    handoff_target["target_slot"],
                    handoff_target["selection_mode"],
                    handoff_target["selection_value"],
                )
                return {
                    "status": "handoff_to_normal",
                    "target_slot": handoff_target["target_slot"],
                    "nickname": handoff_target["nickname"],
                    "selection_mode": handoff_target["selection_mode"],
                    "selection_value": handoff_target["selection_value"],
                }

            slot_number = int(candidate["slot"])
            latest_record = _read_slot_record(slot_number)
            if latest_record is not None and _is_limited_slot_record(latest_record):
                skipped_limited_slots.add(slot_number)
                ui_print(f"限号跳过{slot_number}", save_log=True)
                logger.info("[上架模式] 执行位 %s 当前状态为账号限制，进场前跳过。", slot_number)
                continue

            record = latest_record or candidate["record"]
            expected_balance_text = str(record.current_balance or "").strip() or candidate["balance_text"]
            ui_print(f"候选号{slot_number}", save_log=True)
            logger.info(
                "[上架模式] 命中候选执行位：slot=%s status=%s balance=%s",
                slot_number,
                record.round_status,
                expected_balance_text,
            )

            target_group = 1 if slot_number <= 4 else 2
            force_login = first_entry or current_group != target_group

            enter_result = enter_startup_listing_target_slot(
                camera,
                slot_number,
                force_login=force_login,
                already_at_launcher=already_at_launcher,
            )
            if enter_result["status"] != "success":
                async_push_msg(
                    "【启动页上架】进场失败",
                    f"执行位：{slot_number}\n失败原因：{enter_result['detail']}",
                )
                logger.error("[上架模式] 执行位 %s 进场失败：%s", slot_number, enter_result["detail"])
                return {"status": "failed", "detail": enter_result["detail"], "target_slot": slot_number}

            current_group = target_group
            already_at_launcher = False
            first_entry = False

            try:
                loaded_record = _prepare_listing_account_context(slot_number)
                if loaded_record is None:
                    async_push_msg("【启动页上架】读库失败", f"执行位：{slot_number}\n未能读取 canonical 账号记录。")
                    logger.error("[上架模式] 执行位 %s 读库失败。", slot_number)
                    _best_effort_exit_after_fatal(camera, slot_number, "读库失败")
                    return {"status": "failed", "detail": "读库失败", "target_slot": slot_number}

                if _is_limited_slot_record(loaded_record):
                    skipped_limited_slots.add(slot_number)
                    ui_print(f"限号跳过{slot_number}", save_log=True)
                    logger.info("[上架模式] 执行位 %s 进场后读库命中账号限制，跳过本号上架。", slot_number)
                    exit_result = exit_to_launcher_for_startup_listing(camera)
                    if exit_result["status"] != "success":
                        async_push_msg(
                            "【启动页上架】限号跳过失败",
                            f"执行位：{slot_number}\n结束原因：账号限制后跳过时未能正常下号\n失败原因：{exit_result['detail']}",
                        )
                        return {"status": "failed", "detail": exit_result["detail"], "target_slot": slot_number}
                    already_at_launcher = True
                    continue

                latest_balance_info = _read_latest_trade_balance(camera, expected_balance_text, "进场后")
                latest_balance_text = latest_balance_info["text"]
                latest_balance_value = latest_balance_info["value"]
                if latest_balance_value is None:
                    processed_slots.add(slot_number)
                    _finalize_account(summary_entries, slot_number, "余额未识别", latest_balance_text, limit_account=False)
                else:
                    while True:
                        batch_target = _resolve_batch_target(latest_balance_value)
                        if batch_target <= 0:
                            processed_slots.add(slot_number)
                            _finalize_account(summary_entries, slot_number, "余额超5亿", latest_balance_text, limit_account=False)
                            break

                        ui_print(f"批次{batch_target}", save_log=True)
                        batch_result = execute_startup_listing_batch(camera, batch_target)
                        logger.info(
                            "[上架模式] 执行位 %s 批次完成：status=%s reason=%s listed=%s",
                            slot_number,
                            batch_result["status"],
                            batch_result["reason"],
                            batch_result["listed_count"],
                        )

                        latest_balance_info = _refresh_balance_after_batch(camera, latest_balance_text)
                        latest_balance_text = latest_balance_info["text"]
                        latest_balance_value = latest_balance_info["value"]

                        if batch_result["status"] == "target_reached":
                            if latest_balance_value is not None and latest_balance_value > STARTUP_LISTING_BALANCE_THRESHOLD:
                                processed_slots.add(slot_number)
                                _finalize_account(summary_entries, slot_number, "余额超5亿", latest_balance_text, limit_account=False)
                                break
                            continue

                        if batch_result["status"] == "fail_limit":
                            processed_slots.add(slot_number)
                            _finalize_account(summary_entries, slot_number, "上架失败5次", latest_balance_text, limit_account=True)
                            break

                        if batch_result["status"] == "page_end":
                            processed_slots.add(slot_number)
                            _finalize_account(
                                summary_entries,
                                slot_number,
                                "翻页到底",
                                latest_balance_text,
                                limit_account=False,
                                preserve_existing_status=True,
                            )
                            break

                        processed_slots.add(slot_number)
                        _finalize_account(summary_entries, slot_number, batch_result["reason"], latest_balance_text, limit_account=False)
                        break
            except Exception as exc:
                logger.exception("[上架模式] 执行位 %s 处理异常：%s", slot_number, exc)
                async_push_msg(
                    "【启动页上架】流程异常",
                    f"执行位：{slot_number}\n失败原因：{exc}",
                )
                _best_effort_exit_after_fatal(camera, slot_number, str(exc))
                return {"status": "failed", "detail": str(exc), "target_slot": slot_number}

            exit_result = exit_to_launcher_for_startup_listing(camera)
            if exit_result["status"] != "success":
                async_push_msg(
                    "【启动页上架】下号失败",
                    f"执行位：{slot_number}\n失败原因：{exit_result['detail']}",
                )
                logger.error("[上架模式] 执行位 %s 下号失败：%s", slot_number, exit_result["detail"])
                return {"status": "failed", "detail": exit_result["detail"], "target_slot": slot_number}
            clear_live_listing_count_for_account_switch("启动页上架模式下号成功后")
            clear_persist_result = persist_startup_listing_mode_listing_count_clear()
            if clear_persist_result.status not in ("success", "skipped"):
                logger.warning(
                    "[上架模式] 执行位 %s 下号后清空上架成功写库值失败：%s",
                    slot_number,
                    clear_persist_result.reason,
                )
            already_at_launcher = True
    finally:
        state.startup_listing_mode_active = False
