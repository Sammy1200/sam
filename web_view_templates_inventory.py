"""库存语义版网页模板。"""
from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
import re

import web_view_templates as base_templates


_base_page = base_templates._base_page
_build_status_options_html = base_templates._build_status_options_html
_format_balance_wan_display = base_templates._format_balance_wan_display
_format_cooldown_remaining_time = base_templates._format_cooldown_remaining_time
_format_value = base_templates._format_value
_is_active_edit_row = base_templates._is_active_edit_row
_render_edit_result = base_templates._render_edit_result
_render_execution_slot_summary = base_templates._render_execution_slot_summary
_render_field_error = base_templates._render_field_error
_render_health_summary = base_templates._render_health_summary
_render_inline_row_result = base_templates._render_inline_row_result
_render_kv_table = base_templates._render_kv_table
_render_runtime_consistency_summary = base_templates._render_runtime_consistency_summary
_render_source_diagnostics = base_templates._render_source_diagnostics
_render_source_notice = base_templates._render_source_notice
_render_table = base_templates._render_table


def _format_runtime_remaining_text(value):
    text = str(value or "").strip()
    if not text:
        return "-"
    normalized_text = re.sub(r"\d+\s*秒", "", text).strip()
    if not normalized_text:
        normalized_text = "0分钟"
    return escape(normalized_text)


def _format_remote_remaining_text(seconds_value):
    seconds = max(0, int(seconds_value or 0))
    return _format_cooldown_remaining_time(seconds)


def _render_remote_countdown_cell(row, field_name):
    return _format_remote_remaining_text(row.get(field_name))


def _render_local_relative_time(fallback_text, updated_at):
    normalized_updated_at = str(updated_at or "").strip()
    display_text = str(fallback_text or "").strip() or "-"
    if not normalized_updated_at:
        return escape(display_text)

    updated_at_ms = ""
    try:
        updated_at_ms = str(
            int(datetime.fromisoformat(normalized_updated_at.replace(" ", "T")).timestamp() * 1000)
        )
    except ValueError:
        updated_at_ms = ""

    return (
        f'<span class="local-relative-time" '
        f'data-updated-at="{escape(normalized_updated_at, quote=True)}" '
        f'data-updated-at-ms="{escape(updated_at_ms, quote=True)}">{escape(display_text)}</span>'
    )


def _render_local_relative_time_script():
    return """
<script>
(function () {
  function parseUpdatedAtNode(node) {
    if (!node) return NaN;

    var updatedAtMsText = String((node.dataset && node.dataset.updatedAtMs) || "").trim();
    if (updatedAtMsText) {
      var updatedAtMs = Number(updatedAtMsText);
      if (Number.isFinite(updatedAtMs)) return updatedAtMs;
    }

    var updatedAtText = String((node.dataset && node.dataset.updatedAt) || "").trim();
    if (!updatedAtText) return NaN;
    return Date.parse(updatedAtText.replace(" ", "T"));
  }

  function formatRelative(updatedAtMs, nowMs) {
    if (!Number.isFinite(updatedAtMs)) return "-";

    var deltaSeconds = Math.max(0, Math.floor((nowMs - updatedAtMs) / 1000));
    if (deltaSeconds < 60) return "刚刚";

    var totalMinutes = Math.max(1, Math.floor(deltaSeconds / 60));
    if (totalMinutes < 60) return totalMinutes + "分钟前";

    var totalHours = Math.floor(totalMinutes / 60);
    if (totalHours < 24) return totalHours + "小时前";

    return Math.floor(totalHours / 24) + "天前";
  }

  function updateRelativeNodes() {
    var nowMs = Date.now();
    document.querySelectorAll(".local-relative-time").forEach(function (node) {
      var updatedAtMs = parseUpdatedAtNode(node);
      if (!Number.isFinite(updatedAtMs)) return;
      node.textContent = formatRelative(updatedAtMs, nowMs);
    });
  }

  updateRelativeNodes();
  if (window.__localRelativeTimeTimerId) {
    window.clearInterval(window.__localRelativeTimeTimerId);
  }
  window.__refreshLocalRelativeTimeNodes = updateRelativeNodes;
  window.__localRelativeTimeTimerId = window.setInterval(updateRelativeNodes, 60000);
  window.addEventListener("pageshow", updateRelativeNodes);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) updateRelativeNodes();
  });
})();
</script>
"""


def _build_machine_daily_summary_rows(machine_daily_summaries):
    summary_by_date = {
        str(item.get("stat_date") or "").strip(): item
        for item in (machine_daily_summaries or [])
        if str(item.get("stat_date") or "").strip()
    }
    now = datetime.now()
    target_dates = (
        ("今日", now.strftime("%Y-%m-%d")),
        ("昨日", (now - timedelta(days=1)).strftime("%Y-%m-%d")),
    )
    rows = []
    for label, stat_date in target_dates:
        item = summary_by_date.get(stat_date) or {}
        purchase_success = int(item.get("total_purchase_success_count") or 0)
        listing_success = int(item.get("total_listing_success_count") or 0)
        purchase_fail = int(item.get("total_purchase_fail_count") or 0)
        rows.append(
            (
                label,
                _format_value(purchase_success - listing_success),
                _format_value(purchase_success),
                _format_value(listing_success),
                _format_value(purchase_fail),
            )
        )
    return rows


def _render_machine_daily_summary(machine_daily_summaries):
    return _render_table(
        ("汇总周期", "总道具变化", "总抢购成功", "总上架成功", "总抢购失败"),
        _build_machine_daily_summary_rows(machine_daily_summaries),
    )


def _render_page_notice():
    return """
<div class="readonly-notice">
  <strong>当前页面收口规则：</strong>
  首页保留本机真实数据修改和远端镜像手动刷新；远端写回和公网写回继续关闭。
</div>
"""


def _render_more_info_entry():
    return """
<div class="section">
  <p><a href="/more-info">更多信息</a></p>
</div>
"""


def _render_demo_list_notice():
    return """
<div class="flash-error">
  <strong>当前无真实账号数据：</strong>
  下方仅为演示数据，用于展示页面结构。
</div>
"""


def _build_demo_account_rows():
    return [
        {
            "current_execution_slot": 1,
            "nickname": "演示账号-A",
            "round_status": "运行中",
            "baseline_item_count": 42,
            "inventory_quantity": 42,
            "current_balance_wan": "18.6",
            "updated_at": "2026-04-03 10:15:00",
            "updated_at_relative": "5小时前",
            "allow_purchase": True,
            "cooldown_remaining_seconds": 0,
            "runtime_window_remaining_text": "2小时50分钟",
        },
        {
            "current_execution_slot": 2,
            "nickname": "演示账号-B",
            "round_status": "账号限制",
            "baseline_item_count": 17,
            "inventory_quantity": 17,
            "current_balance_wan": "9.2",
            "updated_at": "2026-04-03 09:48:00",
            "updated_at_relative": "6小时前",
            "allow_purchase": False,
            "cooldown_remaining_seconds": 1280,
            "runtime_window_remaining_text": "1小时26分钟",
        },
    ]


def _render_machine_section_title(title, badge_text):
    return (
        f'<h2>{escape(str(title))} '
        f'<span class="unit-tag">{escape(str(badge_text))}</span></h2>'
    )


def _build_list_form_values(row, edit_result):
    form_values = {
        "nickname": str(row.get("nickname") or "").strip(),
        "baseline_item_count": str(row.get("baseline_item_count") or row.get("inventory_quantity") or 0),
        "round_status": str(row.get("round_status") or "").strip(),
        "current_balance_wan": str(row.get("current_balance_wan") or "").strip(),
    }
    if _is_active_edit_row(row, edit_result):
        form_values.update(edit_result.get("form_values") or {})
    return form_values


def _get_local_edit_result(edit_result):
    if not edit_result:
        return None
    scope = str(edit_result.get("scope") or "local").strip()
    return edit_result if scope == "local" else None


def _render_local_read_only_cells(row):
    inventory_text = _format_value(row.get("inventory_quantity") or row.get("baseline_item_count"))
    update_tip = _render_local_relative_time(
        row.get("updated_at_relative") or "-",
        row.get("updated_at"),
    )
    inventory_cell = (
        f'<div class="inline-field"><div class="readonly-value">{inventory_text}</div>'
        f'<div class="muted-text">更新：{update_tip}</div></div>'
    )
    balance_cell = _format_balance_wan_display(row.get("current_balance_wan"))
    status_cell = _format_value(row.get("round_status"))
    nickname = str(row.get("nickname") or "").strip()
    if nickname:
        action_cell = f'<a href="{escape(f"/account?nickname={nickname}", quote=True)}">查看详情</a>'
    else:
        action_cell = '<span class="muted-text">缺少昵称，无法查看详情</span>'
    return inventory_cell, balance_cell, status_cell, action_cell


def _render_inline_edit_cells(row, row_index, edit_meta=None, edit_result=None):
    nickname = str(row.get("nickname") or "").strip()
    if not nickname:
        muted_html = '<span class="muted-text">缺少昵称，暂不可编辑</span>'
        return muted_html, muted_html, muted_html, muted_html

    edit_meta = edit_meta or {}
    form_id = f"inline-edit-form-{row_index}"
    field_errors = (edit_result or {}).get("field_errors") if _is_active_edit_row(row, edit_result) else {}
    form_values = _build_list_form_values(row, edit_result)
    status_options = list(edit_meta.get("status_options") or [])
    balance_input_unit = str(edit_meta.get("balance_input_unit") or "万")
    status_options_html = _build_status_options_html(
        status_options,
        str(form_values.get("round_status") or ""),
    )
    update_tip = _render_local_relative_time(
        row.get("updated_at_relative") or "-",
        row.get("updated_at"),
    )

    inventory_cell = f"""
<div class="inline-field">
  <input form="{escape(form_id, quote=True)}" type="number" name="baseline_item_count" step="1" min="0" required value="{escape(str(form_values.get('baseline_item_count') or ''), quote=True)}">
  <div class="muted-text">更新：{update_tip}</div>
  {_render_field_error(field_errors, "baseline_item_count")}
</div>
"""
    balance_cell = f"""
<div class="inline-field">
  <div class="input-with-unit inline-balance">
    <input form="{escape(form_id, quote=True)}" type="text" name="current_balance_wan" inputmode="decimal" required value="{escape(str(form_values.get('current_balance_wan') or ''), quote=True)}">
    <span class="unit-tag">{escape(balance_input_unit)}</span>
  </div>
  {_render_field_error(field_errors, "current_balance_wan")}
</div>
"""
    status_cell = f"""
<div class="inline-field">
  <select form="{escape(form_id, quote=True)}" name="round_status" required>
    {status_options_html}
  </select>
  {_render_field_error(field_errors, "round_status")}
</div>
"""
    action_cell = f"""
<div class="inline-save">
  <form id="{escape(form_id, quote=True)}" method="post" action="/account/update">
    <input type="hidden" name="nickname" value="{escape(nickname, quote=True)}">
    <input type="hidden" name="return_to" value="index">
  </form>
  <a href="{escape(f'/account?nickname={nickname}', quote=True)}">查看详情</a>
  <button type="submit" form="{escape(form_id, quote=True)}">保存</button>
  {_render_inline_row_result(row, edit_result)}
</div>
"""
    return inventory_cell, balance_cell, status_cell, action_cell


def _build_account_list_rows(rows, edit_meta=None, edit_result=None, read_only_mode=False):
    edit_result = _get_local_edit_result(edit_result)
    using_demo_rows = not bool(rows)
    effective_rows = rows if rows else _build_demo_account_rows()

    row_items = []
    for row_index, row in enumerate(effective_rows, start=1):
        if using_demo_rows or read_only_mode:
            inventory_cell, balance_cell, status_cell, action_cell = _render_local_read_only_cells(row)
        else:
            inventory_cell, balance_cell, status_cell, action_cell = _render_inline_edit_cells(
                row,
                row_index,
                edit_meta=edit_meta,
                edit_result=edit_result,
            )

        row_items.append(
            (
                _format_value(row.get("current_execution_slot")),
                _format_value(row.get("nickname")),
                inventory_cell,
                balance_cell,
                _format_runtime_remaining_text(row.get("runtime_window_remaining_text")),
                status_cell,
                _format_value(row.get("allow_purchase")),
                _format_cooldown_remaining_time(row.get("cooldown_remaining_seconds")),
                action_cell,
            )
        )
    return row_items, using_demo_rows


def _render_remote_updated_at_cell(row):
    return _render_local_relative_time(
        row.get("updated_at_relative") or row.get("updated_at") or "-",
        row.get("updated_at"),
    )


def _is_active_remote_refresh_section(section, refresh_result):
    if not refresh_result or str(refresh_result.get("scope") or "").strip() != "remote_refresh":
        return False
    active_machine_id = str(refresh_result.get("target_machine_id") or "").strip()
    section_machine_id = str(section.get("machine_id") or "").strip()
    return bool(active_machine_id and active_machine_id == section_machine_id)


def _render_remote_refresh_result(section, refresh_result):
    if not _is_active_remote_refresh_section(section, refresh_result):
        return ""
    status = str(refresh_result.get("status") or "").strip()
    css_class = "flash-success" if status == "success" else "flash-error"
    message = escape(str(refresh_result.get("message") or ""))
    return f'<div class="{css_class}"><strong>刷新结果：</strong>{message}</div>'


def _render_remote_refresh_toolbar(section, refresh_result=None):
    can_refresh = bool(str(section.get("machine_id") or "").strip())
    button_attrs = (
        ' type="submit"'
        ' onclick="this.disabled=true;this.textContent=\'刷新中...\';this.form.submit();"'
    )
    if not can_refresh:
        button_attrs += ' disabled'

    hint_text = "点击后只拉取并刷新当前远端镜像，不会写入对端真源。"
    if not can_refresh:
        hint_text = "当前缺少远端机器标识，暂时无法手动刷新。"

    last_refresh_time = str(section.get("last_report_time") or "").strip() or "暂无"
    machine_label = str(section.get("machine_display_name") or section.get("machine_id") or "远端").strip()
    machine_label = machine_label.replace("电脑", "").strip() or "远端"
    return f"""
<div class="meta">
  <form method="post" action="/remote-sync/refresh" style="display:inline-block; margin-right:12px;">
    <input type="hidden" name="target_machine_id" value="{escape(str(section.get('machine_id') or ''), quote=True)}">
    <button{button_attrs}>刷新</button>
  </form>
  {escape(machine_label)}最后快照时间：{escape(last_refresh_time)}<br>
  刷新说明：{escape(hint_text)}
</div>
{_render_remote_refresh_result(section, refresh_result)}
"""


def _build_remote_account_list_rows(section):
    row_items = []
    for row in section.get("rows") or []:
        row_items.append(
            (
                _format_value(row.get("nickname")),
                _format_value(row.get("baseline_item_count")),
                _format_balance_wan_display(row.get("current_balance_wan")),
                _render_remote_countdown_cell(row, "runtime_window_remaining_seconds"),
                _render_remote_countdown_cell(row, "cooldown_remaining_seconds"),
                _format_value(row.get("round_status")),
                _render_remote_updated_at_cell(row),
            )
        )
    return row_items


def _render_remote_machine_section(section, refresh_result=None):
    rows = section.get("rows") or []
    row_items = _build_remote_account_list_rows(section)
    summary_html = _render_machine_daily_summary(section.get("machine_daily_summaries"))
    if not rows:
        empty_html = f'<p class="muted-text">{escape(str(section.get("message") or "暂无远端镜像数据。"))}</p>'
    else:
        empty_html = '<p class="muted-text">当前阶段保留远端镜像手动刷新，但不开放远端写回。</p>'

    return f"""
<div class="section">
  {_render_machine_section_title(section.get("machine_display_name") or section.get("machine_id") or "远端机器", "远端镜像 / 手动刷新")}
  {_render_remote_refresh_toolbar(section, refresh_result)}
  {summary_html}
  {empty_html}
  {_render_table(("昵称", "道具库存", "余额（万）", "可运行时间", "冷却剩余时间", "账号状态", "更新时间"), row_items)}
</div>
"""


def _build_public_local_snapshot_rows(rows):
    row_items = []
    for row in rows or []:
        row_items.append(
            (
                _format_value(row.get("current_execution_slot")),
                _format_value(row.get("nickname")),
                _format_value(row.get("baseline_item_count") or row.get("inventory_quantity")),
                _format_balance_wan_display(row.get("current_balance_wan")),
                _format_runtime_remaining_text(row.get("runtime_window_remaining_text")),
                _format_cooldown_remaining_time(row.get("cooldown_remaining_seconds")),
                _format_value(row.get("round_status")),
                _render_local_relative_time(
                    row.get("updated_at_relative") or "-",
                    row.get("updated_at"),
                ),
            )
        )
    return row_items


def _render_public_local_refresh_result(refresh_result):
    if not refresh_result or str(refresh_result.get("scope") or "").strip() != "public_local_refresh":
        return ""
    status = str(refresh_result.get("status") or "").strip()
    css_class = "flash-success" if status == "success" else "flash-error"
    message = escape(str(refresh_result.get("message") or ""))
    return f'<div class="{css_class}"><strong>刷新结果：</strong>{message}</div>'


def _render_public_local_refresh_toolbar(machine_display_name, refresh_result=None):
    label = str(machine_display_name or "1号电脑").strip() or "1号电脑"
    return f"""
<div class="meta">
  <form method="post" action="/public-snapshot/refresh" style="display:inline-block; margin-right:12px;">
    <input type="hidden" name="target_scope" value="local">
    <button type="submit" onclick="this.disabled=true;this.textContent='刷新中...';this.form.submit();">刷新 1号快照</button>
  </form>
  当前卡片展示 {escape(label)} 的只读快照视图。
</div>
{_render_public_local_refresh_result(refresh_result)}
"""


def _render_public_remote_refresh_toolbar(section, refresh_result=None):
    machine_id = str(section.get("machine_id") or "").strip()
    machine_label = str(section.get("machine_display_name") or machine_id or "2号电脑").strip() or "2号电脑"
    button_attrs = (
        ' type="submit"'
        ' onclick="this.disabled=true;this.textContent=\'刷新中...\';this.form.submit();"'
    )
    if not machine_id:
        button_attrs += " disabled"
    return f"""
<div class="meta">
  <form method="post" action="/public-snapshot/refresh" style="display:inline-block; margin-right:12px;">
    <input type="hidden" name="target_scope" value="remote">
    <input type="hidden" name="target_machine_id" value="{escape(machine_id, quote=True)}">
    <button{button_attrs}>刷新 2号快照</button>
  </form>
  当前卡片展示 {escape(machine_label)} 的只读快照视图。
</div>
{_render_remote_refresh_result(section, refresh_result)}
"""


def render_public_snapshot_page(view_rows_result, remote_machine_sections=None, refresh_result=None):
    rows = list(view_rows_result.get("rows") or [])
    local_machine_display_name = view_rows_result.get("machine_display_name") or "1号电脑"
    local_summary_html = _render_machine_daily_summary(view_rows_result.get("machine_daily_summaries"))
    local_row_items = _build_public_local_snapshot_rows(rows)

    remote_machine_sections = list(remote_machine_sections or [])
    remote_section = remote_machine_sections[0] if remote_machine_sections else {
        "machine_id": "",
        "machine_display_name": "2号电脑",
        "rows": [],
        "machine_daily_summaries": [],
        "message": "暂无 2号快照数据。",
        "last_report_time": "",
    }
    remote_row_items = _build_remote_account_list_rows(remote_section)
    remote_summary_html = _render_machine_daily_summary(remote_section.get("machine_daily_summaries"))
    remote_empty_html = (
        f'<p class="muted-text">{escape(str(remote_section.get("message") or "暂无 2号快照数据。"))}</p>'
        if not (remote_section.get("rows") or [])
        else '<p class="muted-text">该卡片只读展示 2号最新快照，不开放修改或远端写回。</p>'
    )

    body_html = f"""
<h1>公网快照页</h1>
<div class="readonly-notice">
  <strong>当前页面仅允许查看与刷新快照：</strong>
  不显示任何修改控件，不显示编辑表单，不开放本机修改、远端修改或远端写回。
</div>

<div class="section">
  {_render_machine_section_title(local_machine_display_name, "1号快照 / 只读")}
  {_render_public_local_refresh_toolbar(local_machine_display_name, refresh_result)}
  {local_summary_html}
  {_render_table(("执行位", "昵称", "道具库存", "余额（万）", "可运行时间", "冷却剩余时间", "账号状态", "更新时间"), local_row_items)}
</div>

<div class="section">
  {_render_machine_section_title(remote_section.get("machine_display_name") or "2号电脑", "2号快照 / 只读")}
  {_render_public_remote_refresh_toolbar(remote_section, refresh_result)}
  {remote_summary_html}
  {remote_empty_html}
  {_render_table(("昵称", "道具库存", "余额（万）", "可运行时间", "冷却剩余时间", "账号状态", "更新时间"), remote_row_items)}
</div>

{_render_local_relative_time_script() if (rows or remote_section.get("rows")) else ""}
"""
    return _base_page("公网快照页", body_html)


def render_index_page(
    view_rows_result,
    runtime_result,
    remote_machine_sections=None,
    edit_result=None,
    refresh_result=None,
    read_only_mode=False,
):
    rows = view_rows_result.get("rows") or []
    edit_meta = view_rows_result.get("edit_meta") or {}
    row_items, using_demo_rows = _build_account_list_rows(
        rows,
        edit_meta=edit_meta,
        edit_result=edit_result,
        read_only_mode=read_only_mode,
    )
    demo_notice_html = _render_demo_list_notice() if using_demo_rows else ""
    account_table_column_classes = (
        "col-slot",
        "col-name",
        "col-inventory",
        "col-balance",
        "col-runtime",
        "col-status",
        "col-allow",
        "col-cooldown",
        "col-action",
    )
    local_machine_display_name = view_rows_result.get("machine_display_name") or "本机"
    local_summary_html = _render_machine_daily_summary(view_rows_result.get("machine_daily_summaries"))
    remote_machine_sections = list(remote_machine_sections or [])
    remote_sections_html = "".join(
        _render_remote_machine_section(section, refresh_result=refresh_result)
        for section in remote_machine_sections
    )

    body_html = f"""
<h1>账号数据查看页</h1>
{_render_page_notice()}
{_render_edit_result(edit_result)}

<div class="section">
  {_render_machine_section_title(local_machine_display_name, "本机真实数据")}
  <p class="muted-text">此卡片展示 1号电脑本机真实数据，保留本机行内保存能力。</p>
  {local_summary_html}
  {demo_notice_html}
  {_render_table(("执行位", "昵称", "道具库存", "余额（万）", "可运行时间", "账号状态", "允许抢购", "冷却剩余时间", "详情 / 保存"), row_items, column_classes=account_table_column_classes, table_class="account-table")}
</div>

{remote_sections_html}
{_render_more_info_entry()}
{_render_local_relative_time_script() if (rows or remote_machine_sections) else ""}
"""
    return _base_page("账号数据查看页", body_html)


def render_more_info_page(view_rows_result, runtime_result):
    health = view_rows_result.get("health") or {}
    source_summary = view_rows_result.get("source_summary") or {}
    source_diagnostics = view_rows_result.get("source_diagnostics") or {}
    execution_slot_summary = view_rows_result.get("execution_slot_summary") or {}
    runtime_snapshot = runtime_result.get("snapshot") or {}

    duplicate_items = health.get("duplicate_execution_slots") or []
    duplicate_rows = [
        (_format_value(item.get("execution_slot")), _format_value(item.get("nicknames")))
        for item in duplicate_items
    ]
    missing_items = health.get("missing_critical_field_records") or []
    missing_rows = [
        (
            _format_value(item.get("nickname")),
            _format_value(item.get("current_execution_slot")),
            _format_value(item.get("missing_fields")),
        )
        for item in missing_items
    ]
    runtime_items = [
        ("辅助快照", runtime_result.get("is_auxiliary_snapshot")),
        ("数据库存在", runtime_result.get("database_exists")),
        ("当前执行位", runtime_snapshot.get("current_execution_slot")),
        ("当前昵称", runtime_snapshot.get("current_nickname")),
        ("当前账号索引", runtime_snapshot.get("current_account_index")),
        ("当前大区索引", runtime_snapshot.get("current_server_index")),
        ("快照更新时间", runtime_snapshot.get("updated_at")),
    ]

    body_html = f"""
<h1>更多信息</h1>
{_render_page_notice()}
<div class="section">
  <p><a href="/">返回首页</a></p>
</div>
{_render_source_notice(source_summary)}
{_render_source_diagnostics(source_diagnostics)}
<div class="meta">
  主库路径：<code>{escape(str(view_rows_result.get("database_path") or ""))}</code><br>
  生成时间：{_format_value(view_rows_result.get("generated_at"))}
</div>

<div class="section">
  <h2>诊断信息</h2>
  {_render_health_summary(health)}
</div>

<div class="section">
  <h2>健康检查</h2>
  <p>这里仅统计本机 canonical 主库，不混入远端镜像。</p>
  {_render_execution_slot_summary(execution_slot_summary)}
</div>

<div class="section">
  <h2>数据源 / 路径说明</h2>
  {_render_kv_table(runtime_items)}
</div>

<div class="section">
  <h2>重复执行位</h2>
  {_render_table(("执行位", "昵称列表"), duplicate_rows)}
</div>

<div class="section">
  <h2>关键字段缺失</h2>
  {_render_table(("昵称", "执行位", "缺失字段"), missing_rows)}
</div>
"""
    return _base_page("更多信息", body_html)


def render_account_detail_page(detail_result, runtime_result, edit_result=None, read_only_mode=True):
    del edit_result, read_only_mode
    record = detail_result.get("record")
    health = detail_result.get("health") or {}
    lookup = detail_result.get("lookup") or {}
    source_summary = detail_result.get("source_summary") or {}

    if record is None:
        body_html = f"""
<h1>账号详情</h1>
{_render_page_notice()}
{_render_source_notice(source_summary)}
<div class="meta">
  查询条件：昵称 {_format_value(lookup.get("nickname"))}，
  执行位 {_format_value(lookup.get("execution_slot"))}
</div>
<div class="section">
  <p>未根据当前查询条件找到对应账号记录。</p>
  <p><a href="/">返回首页</a></p>
</div>
"""
        return _base_page("账号详情", body_html)

    base_items = [
        ("昵称", record.get("nickname")),
        ("执行位", record.get("current_execution_slot")),
        ("账号状态", record.get("round_status")),
        ("余额（万）", _format_balance_wan_display(record.get("current_balance_wan"))),
        ("余额原始存储", record.get("current_balance")),
        ("道具库存", record.get("baseline_item_count")),
        ("更新", record.get("updated_at_relative")),
        ("更新时间原值", record.get("updated_at")),
        ("本轮抢购成功数", record.get("round_purchase_success_count")),
        ("本轮上架成功数", record.get("round_listing_success_count")),
        ("本轮抢购失败数", record.get("round_purchase_fail_count")),
        ("本轮运行秒数", record.get("purchase_running_seconds")),
        ("最后限制时间", record.get("last_limit_time")),
        ("最后下号时间", record.get("last_account_end_time")),
    ]
    derived_items = [
        ("允许开始时间", record.get("allow_start_time")),
        ("当前可抢购", record.get("allow_purchase")),
        ("可运行时间", record.get("runtime_window_remaining_text")),
        ("冷却剩余时间", _format_cooldown_remaining_time(record.get("cooldown_remaining_seconds"))),
    ]
    record_health_items = [
        ("存在关键字段缺失", health.get("has_missing_critical_fields")),
        ("缺失字段", health.get("missing_critical_fields")),
        ("主库更新时间", record.get("updated_at")),
        ("辅助快照存在", runtime_result.get("database_exists")),
    ]

    body_html = f"""
<h1>账号详情</h1>
{_render_page_notice()}
{_render_source_notice(source_summary)}
<div class="meta">
  主库路径：<code>{escape(str(detail_result.get("database_path") or ""))}</code><br>
  查询条件：昵称 {_format_value(lookup.get("nickname"))}，
  执行位 {_format_value(lookup.get("execution_slot"))}
</div>

<div class="section">
  <p><a href="/">返回首页</a></p>
</div>

<div class="section">
  <h2>基础字段</h2>
  {_render_kv_table(base_items)}
</div>

<div class="section">
  <h2>派生字段</h2>
  {_render_kv_table(derived_items)}
</div>

<div class="section">
  <h2>当前记录健康摘要</h2>
  <p>这里只展示本机主库记录本身的完整性和可读性摘要，不执行任何网页写入。</p>
  {_render_kv_table(record_health_items)}
</div>

<div class="section">
  <h2>与辅助快照的一致性摘要</h2>
  <p>辅助快照仅做辅助对照，用于观察当前快照与主库详情是否一致。</p>
  {_render_runtime_consistency_summary(runtime_result, health.get("runtime_consistency") or {})}
</div>
"""
    return _base_page(f"账号详情 - {record.get('nickname')}", body_html)


def render_message_page(title, message, detail_items=None, back_href="/", back_label="返回首页"):
    detail_html = ""
    if detail_items:
        detail_html = f"""
<div class="section">
  <h2>说明</h2>
  {_render_kv_table(detail_items)}
</div>
"""

    body_html = f"""
<h1>{escape(title)}</h1>
{_render_page_notice()}
{_render_source_notice()}
<div class="section">
  <p>{escape(message)}</p>
  <p><a href="{escape(back_href, quote=True)}">{escape(back_label)}</a></p>
</div>
{detail_html}
"""
    return _base_page(title, body_html)
