"""库存语义版网页模板。"""
from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
import json
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


def _render_strip_year_display_script():
    return """
<script>
(function () {
  function stripYearText(text) {
    return String(text || "")
      .replace(/\\b\\d{4}[-/年]/g, "")
      .replace(/^(\\d{4})年/, "")
      .trim();
  }

  document.querySelectorAll(".summary-card-date").forEach(function (node) {
    node.textContent = stripYearText(node.textContent);
  });

  document.querySelectorAll(".page-shell-home .meta, .page-shell-public .meta").forEach(function (node) {
    node.childNodes.forEach(function (child) {
      if (child.nodeType === 3) {
        child.textContent = stripYearText(child.textContent);
      }
    });
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
  首页保留本机真实数据最小修改；远端镜像与公网快照只提供查看和刷新，不开放其他修改。
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
            "runtime_window_remaining_text": "2小时40分钟",
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
    return f"""
<div class="section-head">
  <div class="section-head-main">
    <div class="section-title-wrap">
      <div class="section-eyebrow">Zone</div>
      <h2 class="section-title">{escape(str(title))}</h2>
    </div>
    <span class="unit-tag">{escape(str(badge_text))}</span>
  </div>
</div>
"""


def _render_page_title(title, lead_text, rule_text="", kicker="Page"):
    lead_html = f'<p class="page-title-lead">{escape(str(lead_text))}</p>' if str(lead_text or "").strip() else ""
    rule_html = f'<p class="page-title-rule">{escape(str(rule_text))}</p>' if str(rule_text or "").strip() else ""
    kicker_html = f'<div class="page-title-kicker">{escape(str(kicker))}</div>' if str(kicker or "").strip() else ""
    return f"""
<header class="page-title-shell">
  {kicker_html}
  <div class="page-title-main">
    <h1>{escape(str(title))}</h1>
    {lead_html}
    {rule_html}
  </div>
</header>
"""


def _render_module_title(title, note=""):
    note_html = f'<p class="module-note">{escape(str(note))}</p>' if str(note or "").strip() else ""
    return f"""
<div class="module-head">
  <div class="module-title-row">
    <span class="module-title-line" aria-hidden="true"></span>
    <h3 class="module-title">{escape(str(title))}</h3>
  </div>
  {note_html}
</div>
"""


def _build_linear_summary_cards(machine_daily_summaries, change_label="总道具变化"):
    summary_rows = _build_machine_daily_summary_rows(machine_daily_summaries)
    cards = []
    for index, row in enumerate(summary_rows):
        label = str(row[0] or "").strip() or ("今日" if index == 0 else "昨日")
        stat_date = (datetime.now() - timedelta(days=index)).strftime("%m-%d")
        card_class = "summary-card summary-card-today" if index == 0 else "summary-card summary-card-yesterday"
        cards.append(
            f"""
<article class="{card_class}">
  <div class="summary-card-head">
    <span class="summary-card-label">{escape(label)}</span>
    <span class="summary-card-date">{escape(stat_date)}</span>
  </div>
  <div class="summary-main">
    <span class="summary-main-label">{escape(str(change_label))}</span>
    <strong class="summary-main-value">{row[1]}</strong>
  </div>
  <div class="summary-subgrid">
    <div class="summary-metric">
      <span class="summary-metric-label">总抢购成功</span>
      <strong class="summary-metric-value">{row[2]}</strong>
    </div>
    <div class="summary-metric">
      <span class="summary-metric-label">总上架成功</span>
      <strong class="summary-metric-value">{row[3]}</strong>
    </div>
    <div class="summary-metric">
      <span class="summary-metric-label">总抢购失败</span>
      <strong class="summary-metric-value">{row[4]}</strong>
    </div>
  </div>
</article>
"""
        )
    return f'<div class="summary-band">{"".join(cards)}</div>'


def _render_linear_page_action(href, label):
    return f'<a class="page-title-action" href="{escape(str(href), quote=True)}">{escape(str(label))}</a>'


def _render_linear_page_title(title, lead_text, rule_text="", kicker="Page", action_html=""):
    lead_html = f'<p class="page-title-lead">{escape(str(lead_text))}</p>' if str(lead_text or "").strip() else ""
    rule_html = f'<p class="page-title-rule">{escape(str(rule_text))}</p>' if str(rule_text or "").strip() else ""
    kicker_html = f'<div class="page-title-kicker">{escape(str(kicker))}</div>' if str(kicker or "").strip() else ""
    action_slot_html = f'<div class="page-title-action-slot">{action_html}</div>' if str(action_html or "").strip() else ""
    return f"""
<header class="page-title-shell">
  <div class="page-title-top">
    {kicker_html}
    {action_slot_html}
  </div>
  <div class="page-title-main">
    <h1>{escape(str(title))}</h1>
    {lead_html}
    {rule_html}
  </div>
</header>
"""


def _render_linear_section_title(title, badge_text, eyebrow="Zone", action_html="", badge_html=""):
    action_block = f'<div class="section-head-actions">{action_html}</div>' if str(action_html or "").strip() else ""
    badge_block = str(badge_html or "").strip()
    if not badge_block and str(badge_text or "").strip():
        badge_block = f'<span class="unit-tag">{escape(str(badge_text))}</span>'
    eyebrow_html = f'<div class="section-eyebrow">{escape(str(eyebrow))}</div>' if str(eyebrow or "").strip() else ""
    return f"""
<div class="section-head">
  <div class="section-head-main">
    <div class="section-head-primary">
      <div class="section-title-wrap">
        {eyebrow_html}
        <h2 class="section-title">{escape(str(title))}</h2>
      </div>
      {badge_block}
    </div>
    {action_block}
  </div>
</div>
"""


def _render_linear_module_toolbar(*items):
    pills = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        pills.append(f'<span class="toolbar-pill">{escape(text)}</span>')
    if not pills:
        return ""
    return f'<div class="data-module-toolbar">{"".join(pills)}</div>'


def _render_linear_data_module(title, note, table_html, *toolbar_items):
    return f"""
<div class="data-module">
  {_render_module_title(title, note)}
  {_render_linear_module_toolbar(*toolbar_items)}
  <div class="data-module-frame">
    {table_html}
  </div>
</div>
"""


def _render_linear_frame_only(table_html):
    return f"""
<div class="data-module">
  <div class="data-module-frame">
    {table_html}
  </div>
</div>
"""


def _format_time_without_year(text):
    value = str(text or "").strip()
    if not value:
        return "-"
    value = re.sub(r"^\d{4}[-/]", "", value)
    value = re.sub(r"^\d{4}年", "", value)
    return value


def _build_list_form_values(row, edit_result):
    baseline_value = str(row.get("baseline_item_count") or row.get("inventory_quantity") or 0)
    form_values = {
        "nickname": str(row.get("nickname") or "").strip(),
        "baseline_item_count": baseline_value,
        "locked_item_count": str(row.get("locked_item_count") or 0),
        "tradable_item_count": str(
            row.get("tradable_item_count")
            if row.get("tradable_item_count") not in (None, "")
            else baseline_value
        ),
        "round_status": str(row.get("round_status") or "").strip(),
        "current_balance_wan": str(row.get("current_balance_wan") or "").strip(),
        "db_mode": str(row.get("db_mode") or "stone").strip() or "stone",
    }
    if _is_active_edit_row(row, edit_result):
        form_values.update(edit_result.get("form_values") or {})
    return form_values


def _normalize_db_mode_from_view(source):
    mode = str((source or {}).get("db_mode") or "").strip().lower()
    return "accessory" if mode == "accessory" else "stone"


def _is_stone_mode_value(value):
    return str(value or "").strip().lower() != "accessory"


def _format_int_text(value):
    try:
        return str(max(0, int(value or 0)))
    except (TypeError, ValueError):
        return "0"


def _render_inventory_split_display(row, db_mode="stone"):
    if not _is_stone_mode_value(db_mode):
        return _format_value(row.get("inventory_quantity") or row.get("baseline_item_count"))
    if "locked_item_count" not in (row or {}) and "tradable_item_count" not in (row or {}):
        return _format_value(row.get("inventory_quantity") or row.get("baseline_item_count"))

    locked_text = _format_int_text(row.get("locked_item_count"))
    tradable_text = _format_int_text(row.get("tradable_item_count"))
    baseline_text = _format_int_text(row.get("baseline_item_count") or row.get("inventory_quantity"))
    return (
        '<span class="inventory-locked" style="color:#dc2626;font-weight:700;">'
        f'{escape(locked_text)}</span>'
        '<span class="inventory-op"> + </span>'
        '<span class="inventory-tradable" style="color:#15803d;font-weight:700;">'
        f'{escape(tradable_text)}</span>'
        '<span class="inventory-op"> = </span>'
        f'<span class="inventory-total">{escape(baseline_text)}</span>'
    )


def _render_home_table_layout_style():
    return """
<style>
.page-shell-home .stage-primary .account-table-local {
  table-layout: fixed;
  width: 100%;
  min-width: 0;
}
.page-shell-home .stage-primary .account-table-local .col-name { width: 6%; }
.page-shell-home .stage-primary .account-table-local .col-inventory { width: 29%; }
.page-shell-home .stage-primary .account-table-local .col-balance { width: 12%; }
.page-shell-home .stage-primary .account-table-local .col-runtime { width: 12%; }
.page-shell-home .stage-primary .account-table-local .col-status { width: 11%; }
.page-shell-home .stage-primary .account-table-local .col-cooldown { width: 12%; }
.page-shell-home .stage-primary .account-table-local .col-action { width: 18%; }
.page-shell-home .stage-primary .account-table-local th,
.page-shell-home .stage-primary .account-table-local td {
  padding: 8px;
}
.page-shell-home .stage-primary .account-table-local th {
  text-align: center;
}
.page-shell-home .stage-primary .account-table-local th.col-inventory {
  text-align: left;
  padding-left: calc(8px + 7ch + 22px);
}
.page-shell-home .stage-primary .account-table-local .display-field {
  min-width: 0;
  width: 100%;
  white-space: nowrap;
}
.page-shell-home .stage-primary .account-table-local .col-name .display-field {
  width: 6ch;
  min-width: 6ch;
  max-width: 6ch;
  justify-content: center;
  margin: 0 auto;
  padding-left: 0;
  padding-right: 0;
  text-align: center;
}
.page-shell-home .stage-primary .account-table-local .col-inventory .inventory-inline-row {
  justify-content: flex-start;
}
.page-shell-home .stage-primary .account-table-local .display-field,
.page-shell-home .stage-primary .account-table-local .inventory-input,
.page-shell-home .stage-primary .account-table-local .inventory-value,
.page-shell-home .stage-primary .account-table-local .readonly-value,
.page-shell-home .stage-primary .account-table-local .inline-balance input,
.page-shell-home .stage-primary .account-table-local .inline-field select,
.page-shell-home .stage-primary .account-table-local .unit-tag,
.page-shell-home .stage-primary .account-table-local .inline-save button {
  height: 36px;
  min-height: 36px;
  line-height: 1;
  border-radius: var(--radius-sm);
  box-sizing: border-box;
}
.page-shell-home .stage-primary .account-table-local .display-field,
.page-shell-home .stage-primary .account-table-local .inventory-value,
.page-shell-home .stage-primary .account-table-local .readonly-value,
.page-shell-home .stage-primary .account-table-local .unit-tag,
.page-shell-home .stage-primary .account-table-local .inline-save button {
  display: flex;
  align-items: center;
  justify-content: center;
}
.page-shell-home .stage-primary .account-table-local .display-field {
  justify-content: flex-start;
  padding-top: 0;
  padding-bottom: 0;
}
.page-shell-home .stage-primary .account-table-local .inventory-input,
.page-shell-home .stage-primary .account-table-local .inline-balance input,
.page-shell-home .stage-primary .account-table-local .inline-field select {
  padding-top: 0;
  padding-bottom: 0;
}
.page-shell-home .stage-primary .account-table-local .inventory-split-row {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  white-space: nowrap;
  width: 100%;
  min-width: 0;
}
.page-shell-home .stage-primary .account-table-local .inventory-split-row .inventory-input,
.page-shell-home .stage-primary .account-table-local .inventory-split-row .inventory-value {
  width: 7ch;
  min-width: 7ch;
  max-width: 7ch;
  flex: 0 0 7ch;
  padding-left: 7px;
  padding-right: 7px;
  text-align: center;
}
.page-shell-home .stage-primary .account-table-local .inventory-split-row .inventory-op {
  flex: 0 0 auto;
  color: var(--text-tertiary);
  font-weight: 590;
}
.page-shell-home .stage-primary .account-table-local .inventory-split-display {
  width: auto;
  min-width: 0;
  max-width: none;
  padding-left: 8px;
  padding-right: 8px;
  white-space: nowrap;
}
.page-shell-home .stage-primary .account-table-local .inventory-field .inventory-updated {
  margin-top: 0;
  margin-left: 2px;
  height: 36px;
  display: flex;
  align-items: center;
  line-height: 1;
}
.page-shell-home .stage-primary .account-table-local .col-balance .inline-balance {
  justify-content: center;
  gap: 6px;
  white-space: nowrap;
}
.page-shell-home .stage-primary .account-table-local .col-balance .inline-balance input {
  width: 8ch;
  min-width: 8ch;
  max-width: 8ch;
  padding-left: 8px;
  padding-right: 8px;
}
.page-shell-home .stage-primary .account-table-local .col-runtime,
.page-shell-home .stage-primary .account-table-local .col-cooldown,
.page-shell-home .stage-primary .account-table-local .col-status {
  white-space: nowrap;
}
.page-shell-home .stage-primary .account-table-local .col-runtime .display-field,
.page-shell-home .stage-primary .account-table-local .col-cooldown .display-field,
.page-shell-home .stage-primary .account-table-local .col-status .display-field {
  justify-content: center;
  padding-left: 10px;
  padding-right: 10px;
}
.page-shell-home .stage-primary .account-table-local .col-action .inline-save-main {
  gap: 8px;
  justify-content: center;
  flex-wrap: nowrap;
}
.page-shell-home .stage-primary .account-table-local .col-action .inline-save button {
  min-width: 54px;
  padding-left: 9px;
  padding-right: 9px;
}
.page-shell-home .stage-primary .account-table-local .col-action .inline-save a {
  height: 36px;
  display: inline-flex;
  align-items: center;
  line-height: 1;
}
</style>
"""


def _render_kv_table_html(items):
    rows = []
    for key, value in items:
        if isinstance(value, dict) and "html" in value:
            rendered_value = str(value.get("html") or "-")
        else:
            rendered_value = _format_value(value)
        rows.append((escape(str(key)), rendered_value))
    return _render_table(("字段", "值"), rows)


def _db_mode_labels(db_mode):
    normalized = "accessory" if str(db_mode or "").strip().lower() == "accessory" else "stone"
    if normalized == "accessory":
        return {
            "db_mode": "accessory",
            "db_label": "饰品库",
            "alternate_db_mode": "stone",
            "alternate_db_label": "石头库",
            "inventory_label": "饰品库存",
            "balance_label": "金币（万）",
            "summary_change_label": "总饰品变化",
        }
    return {
        "db_mode": "stone",
        "db_label": "石头库",
        "alternate_db_mode": "accessory",
        "alternate_db_label": "饰品库",
        "inventory_label": "道具库存",
        "balance_label": "余额（万）",
        "summary_change_label": "总道具变化",
    }


def _build_db_mode_toggle(path, labels):
    target = labels["alternate_db_mode"]
    label = labels["db_label"]
    separator = "&" if "?" in path else "?"
    href = f"{path}{separator}db={target}"
    return f'<a class="unit-tag db-mode-badge-toggle" href="{escape(href, quote=True)}">{escape(label)}</a>'


def _get_local_edit_result(edit_result):
    if not edit_result:
        return None
    scope = str(edit_result.get("scope") or "local").strip()
    return edit_result if scope == "local" else None


def _render_inline_row_result(row, edit_result):
    if not _is_active_edit_row(row, edit_result):
        return ""

    if str(edit_result.get("status") or "").strip() == "success":
        return ""

    return f'<div class="inline-result error">{escape(str(edit_result.get("message") or ""))}</div>'


def _build_restore_scroll_script(edit_result):
    if not edit_result:
        return ""

    scroll_x = edit_result.get("scroll_x")
    scroll_y = edit_result.get("scroll_y")
    if scroll_x is None and scroll_y is None:
        return ""

    try:
        target_x = max(0, int(scroll_x or 0))
        target_y = max(0, int(scroll_y or 0))
    except (TypeError, ValueError):
        return ""

    return f"""
<script>
(function () {{
  var targetX = {target_x};
  var targetY = {target_y};
  function restoreScrollPosition() {{
    window.scrollTo(targetX, targetY);
  }}
  if (document.readyState === "loading") {{
    document.addEventListener("DOMContentLoaded", restoreScrollPosition, {{ once: true }});
  }} else {{
    restoreScrollPosition();
  }}
  window.requestAnimationFrame(restoreScrollPosition);
  window.setTimeout(restoreScrollPosition, 0);
}})();
</script>
"""


def _build_inline_save_scroll_script():
    return """
<script>
(function () {
  function writeScrollPosition(form) {
    if (!form) return;
    var scrollXInput = form.querySelector('input[name="scroll_x"]');
    var scrollYInput = form.querySelector('input[name="scroll_y"]');
    if (scrollXInput) scrollXInput.value = String(window.scrollX || window.pageXOffset || 0);
    if (scrollYInput) scrollYInput.value = String(window.scrollY || window.pageYOffset || 0);
  }

  document.querySelectorAll('form[data-preserve-scroll="true"]').forEach(function (form) {
    form.addEventListener("submit", function () {
      writeScrollPosition(form);
    });
  });
})();
</script>
"""


def _build_refresh_scroll_script():
    return """
<script>
(function () {
  var storagePrefix = "web-view-refresh-scroll:";

  function getFormStorageKey(form) {
    try {
      var actionUrl = new URL(form.getAttribute("action") || window.location.pathname, window.location.href);
      return storagePrefix + actionUrl.pathname;
    } catch (error) {
      return storagePrefix + window.location.pathname;
    }
  }

  function preserveRefreshScroll(form) {
    if (!form) return;
    try {
      window.sessionStorage.setItem(
        getFormStorageKey(form),
        JSON.stringify({
          x: window.scrollX || window.pageXOffset || 0,
          y: window.scrollY || window.pageYOffset || 0
        })
      );
    } catch (error) {
      // 浏览器禁用 sessionStorage 时，刷新仍按原流程提交。
    }
  }

  function restoreRefreshScroll() {
    var key = storagePrefix + window.location.pathname;
    var rawValue = "";
    try {
      rawValue = window.sessionStorage.getItem(key) || "";
      window.sessionStorage.removeItem(key);
    } catch (error) {
      rawValue = "";
    }
    if (!rawValue) return;

    var payload;
    try {
      payload = JSON.parse(rawValue);
    } catch (error) {
      return;
    }

    var targetX = Math.max(0, Number(payload.x) || 0);
    var targetY = Math.max(0, Number(payload.y) || 0);
    function restore() {
      window.scrollTo(targetX, targetY);
    }

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", restore, { once: true });
    } else {
      restore();
    }
    window.requestAnimationFrame(restore);
    window.setTimeout(restore, 0);
  }

  window.__preserveRefreshScroll = preserveRefreshScroll;
  restoreRefreshScroll();
  document.querySelectorAll('form[data-refresh-preserve-scroll="true"]').forEach(function (form) {
    form.addEventListener("submit", function () {
      preserveRefreshScroll(form);
    });
  });
})();
</script>
"""


def _build_flash_cleanup_script(edit_result):
    if not edit_result or str(edit_result.get("status") or "").strip() != "success":
        return ""

    return """
<script>
(function () {
  var url = new URL(window.location.href);
  var changed = false;
  ["flash_status", "flash_scope", "flash_nickname", "flash_scroll_x", "flash_scroll_y"].forEach(function (key) {
    if (url.searchParams.has(key)) {
      url.searchParams.delete(key);
      changed = true;
    }
  });
  if (changed && window.history && typeof window.history.replaceState === "function") {
    window.history.replaceState({}, document.title, url.pathname + url.search + url.hash);
  }
})();
</script>
"""


def _build_saved_button_state_script(edit_result):
    if not edit_result or str(edit_result.get("status") or "").strip() != "success":
        return ""

    nickname = str(((edit_result.get("form_values") or {}).get("nickname") or "")).strip()
    if not nickname:
        return ""

    return f"""
<script>
(function () {{
  var targetNickname = {nickname!r};
  document.querySelectorAll('form[data-preserve-scroll="true"]').forEach(function (form) {{
    var nicknameInput = form.querySelector('input[name="nickname"]');
    if (!nicknameInput || String(nicknameInput.value || "").trim() !== targetNickname) {{
      return;
    }}
    var submitButton = document.querySelector('button[form="' + form.id + '"]');
    if (submitButton) {{
      submitButton.classList.add("is-saved");
    }}
  }});
}})();
</script>
"""


def _build_refresh_button_state_script(refresh_result):
    if not refresh_result or str(refresh_result.get("status") or "").strip() != "success":
        return ""

    scope = str(refresh_result.get("scope") or "").strip()
    target_machine_id = str(refresh_result.get("target_machine_id") or "").strip()
    if scope not in ("public_local_refresh", "remote_refresh"):
        return ""
    if scope == "remote_refresh" and not target_machine_id:
        return ""

    return f"""
<script>
(function () {{
  var scope = {json.dumps(scope, ensure_ascii=False)};
  var targetMachineId = {json.dumps(target_machine_id, ensure_ascii=False)};

  function formValue(form, name) {{
    var input = form.querySelector('input[name="' + name + '"]');
    return input ? String(input.value || "").trim() : "";
  }}

  function isTargetRefreshForm(form) {{
    if (scope === "public_local_refresh") {{
      return formValue(form, "target_scope") === "local";
    }}
    if (scope === "remote_refresh") {{
      return formValue(form, "target_machine_id") === targetMachineId;
    }}
    return false;
  }}

  document.querySelectorAll('form[data-refresh-preserve-scroll="true"]').forEach(function (form) {{
    if (!isTargetRefreshForm(form)) {{
      return;
    }}
    var button = form.querySelector(".section-refresh-button");
    if (!button) {{
      return;
    }}
    button.classList.add("is-saved");
    button.textContent = "已刷新";
  }});
}})();
</script>
"""


def _render_local_read_only_cells(row, db_mode="stone"):
    is_split_inventory = not row.get("is_temporary_account") and _is_stone_mode_value(db_mode)
    if row.get("is_temporary_account"):
        inventory_text = _format_value(row.get("inventory_quantity") or row.get("baseline_item_count"))
    else:
        inventory_text = _render_inventory_split_display(row, db_mode)
    update_tip = _render_local_relative_time(
        row.get("updated_at_relative") or "-",
        row.get("updated_at"),
    )
    value_class = "readonly-value inventory-split-display" if is_split_inventory else "readonly-value inventory-value"
    row_class = "inventory-inline-row inventory-split-row" if is_split_inventory else "inventory-inline-row"
    inventory_cell = (
        f'<div class="inline-field inventory-field"><div class="{row_class}">'
        f'<div class="{value_class}">{inventory_text}</div>'
        f'<div class="muted-text inventory-updated">{update_tip}</div>'
        f"</div></div>"
    )
    balance_cell = _format_balance_wan_display(row.get("current_balance_wan"))
    status_cell = _format_value(row.get("round_status"))
    if row.get("is_temporary_account"):
        status_cell = _render_home_display_field(status_cell, "meta")
        action_cell = '<div class="temporary-action-field"><span>临时快照</span></div>'
    else:
        nickname = str(row.get("nickname") or "").strip()
        if nickname:
            action_cell = f'<a href="{escape(f"/account?nickname={nickname}", quote=True)}">查看详情</a>'
        else:
            action_cell = '<span class="muted-text">缺少昵称，无法查看详情</span>'
    return inventory_cell, balance_cell, status_cell, action_cell


def _render_inline_edit_cells(row, row_index, edit_meta=None, edit_result=None):
    if row.get("is_temporary_account"):
        return _render_local_read_only_cells(row, "accessory")

    nickname = str(row.get("nickname") or "").strip()
    if not nickname:
        muted_html = '<span class="muted-text">缺少昵称，暂不可编辑</span>'
        return muted_html, muted_html, muted_html, muted_html

    edit_meta = edit_meta or {}
    db_mode = str(edit_meta.get("db_mode") or "stone").strip() or "stone"
    detail_query = f"/account?nickname={nickname}&db={db_mode}"
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

    if _is_stone_mode_value(db_mode):
        locked_value = str(form_values.get("locked_item_count") or "")
        tradable_value = str(form_values.get("tradable_item_count") or "")
        try:
            total_value = str(max(0, int(locked_value or 0)) + max(0, int(tradable_value or 0)))
        except (TypeError, ValueError):
            total_value = str(form_values.get("baseline_item_count") or row.get("baseline_item_count") or 0)
        inventory_cell = f"""
<div class="inline-field inventory-field">
  <div class="inventory-inline-row inventory-split-row">
    <input class="inventory-input" style="color:#dc2626;font-weight:700;" form="{escape(form_id, quote=True)}" type="number" name="locked_item_count" step="1" min="0" required value="{escape(locked_value, quote=True)}" title="不可交易">
    <span class="inventory-op">+</span>
    <input class="inventory-input" style="color:#15803d;font-weight:700;" form="{escape(form_id, quote=True)}" type="number" name="tradable_item_count" step="1" min="0" required value="{escape(tradable_value, quote=True)}" title="可交易">
    <span class="inventory-op">=</span>
    <div class="readonly-value inventory-value">{escape(total_value)}</div>
    <div class="muted-text inventory-updated">{update_tip}</div>
  </div>
  {_render_field_error(field_errors, "locked_item_count")}
  {_render_field_error(field_errors, "tradable_item_count")}
</div>
"""
    else:
        inventory_cell = f"""
<div class="inline-field inventory-field">
  <div class="inventory-inline-row">
    <input class="inventory-input" form="{escape(form_id, quote=True)}" type="number" name="baseline_item_count" step="1" min="0" required value="{escape(str(form_values.get('baseline_item_count') or ''), quote=True)}">
    <div class="muted-text inventory-updated">{update_tip}</div>
  </div>
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
  <form id="{escape(form_id, quote=True)}" method="post" action="/account/update" data-preserve-scroll="true">
    <input type="hidden" name="nickname" value="{escape(nickname, quote=True)}">
    <input type="hidden" name="db_mode" value="{escape(db_mode, quote=True)}">
    <input type="hidden" name="return_to" value="index">
    <input type="hidden" name="scroll_x" value="">
    <input type="hidden" name="scroll_y" value="">
  </form>
  <div class="inline-save-main">
    <button type="submit" form="{escape(form_id, quote=True)}">保存</button>
    <a href="{escape(detail_query, quote=True)}">查看详情</a>
  </div>
  {_render_inline_row_result(row, edit_result)}
</div>
"""
    return inventory_cell, balance_cell, status_cell, action_cell


def _build_account_list_rows(rows, edit_meta=None, edit_result=None, read_only_mode=False):
    edit_result = _get_local_edit_result(edit_result)
    using_demo_rows = not bool(rows)
    effective_rows = rows if rows else _build_demo_account_rows()

    row_items = []
    db_mode = str((edit_meta or {}).get("db_mode") or "stone").strip() or "stone"
    for row_index, row in enumerate(effective_rows, start=1):
        if using_demo_rows or read_only_mode:
            inventory_cell, balance_cell, status_cell, action_cell = _render_local_read_only_cells(row, db_mode)
        else:
            inventory_cell, balance_cell, status_cell, action_cell = _render_inline_edit_cells(
                row,
                row_index,
                edit_meta=edit_meta,
                edit_result=edit_result,
            )

        cells = (
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
        if row.get("is_temporary_account"):
            row_items.append({"cells": cells, "row_class": "temporary-account-row"})
        else:
            row_items.append(cells)
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


def _build_remote_account_list_rows(section, db_mode=None):
    effective_db_mode = db_mode or section.get("db_mode") or "stone"
    row_items = []
    for row in section.get("rows") or []:
        status_text = str(row.get("round_status") or "").strip()
        cells = (
            _format_value(row.get("nickname")),
            _render_inventory_split_display(row, effective_db_mode),
            _format_balance_wan_display(row.get("current_balance_wan")),
            _render_remote_countdown_cell(row, "runtime_window_remaining_seconds"),
            _render_remote_countdown_cell(row, "cooldown_remaining_seconds"),
            _format_value("时长已到" if status_text == "抢购时长已到" else status_text),
            _render_remote_updated_at_cell(row),
        )
        if str(row.get("nickname") or "").strip() == "临时号":
            row_items.append({"cells": cells, "row_class": "temporary-account-row"})
        else:
            row_items.append(cells)
    return row_items


def _build_public_local_snapshot_rows(rows, db_mode="stone"):
    row_items = []
    for row in rows or []:
        status_text = str(row.get("round_status") or "").strip()
        cells = (
            _format_value(row.get("current_execution_slot")),
            _format_value(row.get("nickname")),
            _render_inventory_split_display(row, db_mode),
            _format_balance_wan_display(row.get("current_balance_wan")),
            _format_runtime_remaining_text(row.get("runtime_window_remaining_text")),
            _format_cooldown_remaining_time(row.get("cooldown_remaining_seconds")),
            _format_value("时长已到" if status_text == "抢购时长已到" else status_text),
            _render_local_relative_time(
                row.get("updated_at_relative") or "-",
                row.get("updated_at"),
            ),
        )
        if row.get("is_temporary_account"):
            row_items.append({"cells": cells, "row_class": "temporary-account-row"})
        else:
            row_items.append(cells)
    return row_items


def _render_public_local_refresh_result(refresh_result):
    if not refresh_result or str(refresh_result.get("scope") or "").strip() != "public_local_refresh":
        return ""
    status = str(refresh_result.get("status") or "").strip()
    css_class = "flash-success" if status == "success" else "flash-error"
    message = escape(str(refresh_result.get("message") or ""))
    return f'<div class="{css_class}"><strong>刷新结果：</strong>{message}</div>'


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
    labels = _db_mode_labels(_normalize_db_mode_from_view(detail_result))
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
  <p><a href="/?db={labels['db_mode']}">返回首页</a></p>
</div>
"""
        return _base_page("账号详情", body_html)

    base_items = [
        ("昵称", record.get("nickname")),
        ("执行位", record.get("current_execution_slot")),
        ("账号状态", record.get("round_status")),
        (labels["balance_label"], _format_balance_wan_display(record.get("current_balance_wan"))),
        (labels["balance_label"].replace("（万）", "原始存储"), record.get("current_balance")),
        (labels["inventory_label"], {"html": _render_inventory_split_display(record, labels["db_mode"])}),
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
  <p><a href="/?db={labels['db_mode']}">返回首页</a></p>
</div>

<div class="section">
  <h2>基础字段</h2>
  {_render_kv_table_html(base_items)}
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


def render_account_detail_page(detail_result, runtime_result, edit_result=None, read_only_mode=True):
    del edit_result, read_only_mode
    labels = _db_mode_labels(_normalize_db_mode_from_view(detail_result))
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
        (labels["inventory_label"], {"html": _render_inventory_split_display(record, labels["db_mode"])}),
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

<p class="detail-back-link"><a href="/">返回首页</a></p>

<div class="section">
  <h2>基础字段</h2>
  {_render_kv_table_html(base_items)}
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


def _render_home_display_field(value, tone="default"):
    tone_class = f" display-field-{escape(str(tone), quote=True)}" if tone else ""
    return f'<div class="display-field{tone_class}">{value}</div>'


def _table_row_cells(row):
    if isinstance(row, dict) and "cells" in row:
        return tuple(row.get("cells") or ())
    return tuple(row or ())


def _table_row_class(row):
    if isinstance(row, dict):
        return str(row.get("row_class") or "").strip()
    return ""


def _with_optional_row_class(cells, row_class):
    row_class = str(row_class or "").strip()
    if not row_class:
        return cells
    return {"cells": cells, "row_class": row_class}


def _format_snapshot_relative_time(value):
    text = str(value or "").strip()
    if not text:
        return "暂无"
    try:
        snapshot_time = datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return text
    now = datetime.now()
    delta_seconds = max(0, int((now - snapshot_time).total_seconds()))
    if delta_seconds < 60:
        return "1分钟前"
    if delta_seconds < 3600:
        return f"{max(1, delta_seconds // 60)}分钟前"
    if delta_seconds < 86400:
        return f"{max(1, delta_seconds // 3600)}小时前"
    return f"{max(1, delta_seconds // 86400)}天前"


# 首页最终生效模板入口
def render_index_page(
    view_rows_result,
    runtime_result,
    remote_machine_sections=None,
    edit_result=None,
    refresh_result=None,
    read_only_mode=False,
):
    del runtime_result
    rows = view_rows_result.get("rows") or []
    edit_meta = view_rows_result.get("edit_meta") or {}
    labels = _db_mode_labels(_normalize_db_mode_from_view(view_rows_result))
    row_items, using_demo_rows = _build_account_list_rows(
        rows,
        edit_meta=edit_meta,
        edit_result=edit_result,
        read_only_mode=read_only_mode,
    )
    demo_notice_html = _render_demo_list_notice() if using_demo_rows else ""
    account_table_column_classes = (
        "col-name",
        "col-inventory",
        "col-balance",
        "col-runtime",
        "col-status",
        "col-cooldown",
        "col-action",
    )
    display_row_items = []
    for raw_row in row_items:
        row = _table_row_cells(raw_row)
        display_row_items.append(
            _with_optional_row_class(
                (
                    _render_home_display_field(row[1], "name"),
                    row[2],
                    row[3],
                    _render_home_display_field(row[4], "meta"),
                    row[5],
                    _render_home_display_field(row[7], "meta"),
                    row[8],
                ),
                _table_row_class(raw_row),
            )
        )
    local_machine_display_name = view_rows_result.get("machine_display_name") or "本机"
    local_summary_html = _build_linear_summary_cards(
        view_rows_result.get("machine_daily_summaries"),
        labels["summary_change_label"],
    )
    remote_machine_sections = list(remote_machine_sections or [])
    remote_sections_html = "".join(
        _render_remote_machine_section(section, refresh_result=refresh_result, labels=labels)
        for section in remote_machine_sections
    )
    local_table_html = _render_table(
        ("昵称", labels["inventory_label"], labels["balance_label"], "可运行时间", "账号状态", "冷却剩余时间", "详情 / 保存"),
        display_row_items,
        column_classes=account_table_column_classes,
        table_class="account-table account-table-local",
    )
    page_edit_result_html = _render_edit_result(edit_result)

    body_html = f"""
<div class="page-shell page-shell-home">
<div class="section stage-panel stage-primary">
  {_render_linear_section_title(
      local_machine_display_name,
      "",
      eyebrow="",
      badge_html=_build_db_mode_toggle("/", labels),
  )}
  {local_summary_html}
  {demo_notice_html}
  {local_table_html}
</div>

{remote_sections_html}
{_render_more_info_entry()}
{page_edit_result_html}
{_render_home_table_layout_style()}
{_build_restore_scroll_script(edit_result)}
{_build_inline_save_scroll_script() if not read_only_mode and not using_demo_rows else ""}
{_build_refresh_scroll_script()}
{_build_saved_button_state_script(edit_result)}
{_build_refresh_button_state_script(refresh_result)}
{_build_flash_cleanup_script(edit_result)}
{_render_local_relative_time_script() if (rows or remote_machine_sections) else ""}
{_render_strip_year_display_script()}
</div>
"""
    return _base_page("首页", body_html)
def _build_section_refresh_action(form_action, hidden_inputs, button_label, meta_text="", disabled=False):
    hidden_html = "".join(
        f'<input type="hidden" name="{escape(str(name), quote=True)}" value="{escape(str(value), quote=True)}">'
        for name, value in hidden_inputs
    )
    button_attrs = (
        ' type="submit"'
        ' class="section-refresh-button"'
        ' onclick="window.__preserveRefreshScroll&&window.__preserveRefreshScroll(this.form);this.disabled=true;this.textContent=\'刷新中...\';this.form.submit();"'
    )
    if disabled:
        button_attrs += " disabled"
    meta_html = f'<div class="section-refresh-meta">{escape(str(meta_text))}</div>' if str(meta_text or "").strip() else ""
    return f"""
<div class="section-action-cluster">
  <form method="post" action="{escape(str(form_action), quote=True)}" class="section-refresh-form" data-refresh-preserve-scroll="true">
    {hidden_html}
    <button{button_attrs}>{escape(str(button_label))}</button>
  </form>
  {meta_html}
</div>
"""


def _build_remote_section_refresh_action(section, labels=None):
    labels = labels or _db_mode_labels(section.get("db_mode"))
    machine_id = str(section.get("machine_id") or "").strip()
    last_refresh_time = _format_snapshot_relative_time(section.get("last_report_time"))
    machine_label = str(section.get("machine_display_name") or section.get("machine_id") or "远端").strip()
    machine_label = machine_label.replace("电脑", "").strip() or "远端"
    return _build_section_refresh_action(
        "/remote-sync/refresh",
        (("target_machine_id", machine_id), ("db_mode", labels["db_mode"])),
        "刷新",
        f"{machine_label}最后快照时间：{last_refresh_time}",
        disabled=not bool(machine_id),
    )


def _render_remote_refresh_toolbar(section, refresh_result=None):
    if _is_active_remote_refresh_section(section, refresh_result):
        if str(refresh_result.get("status") or "").strip() == "success":
            return ""
    return _render_remote_refresh_result(section, refresh_result)


def _render_remote_machine_section(section, refresh_result=None, labels=None):
    labels = labels or _db_mode_labels(section.get("db_mode"))
    rows = section.get("rows") or []
    row_items = _build_remote_account_list_rows(section, labels["db_mode"])
    summary_html = _build_linear_summary_cards(section.get("machine_daily_summaries"), labels["summary_change_label"])
    empty_html = f'<p class="muted-text">{escape(str(section.get("message") or "暂无远端镜像数据。"))}</p>' if not rows else ""

    table_html = _render_table(
        ("昵称", labels["inventory_label"], labels["balance_label"], "可运行时间", "冷却剩余时间", "账号状态", "更新时间"),
        row_items,
    )
    return f"""
<div class="section stage-panel stage-secondary">
  {_render_linear_section_title(
      section.get("machine_display_name") or section.get("machine_id") or "远端机器",
      labels["db_label"],
      eyebrow="Mirror",
      action_html=_build_remote_section_refresh_action(section, labels),
  )}
  {_render_remote_refresh_toolbar(section, refresh_result)}
  {summary_html}
  {empty_html}
  <div class="data-module data-module-public">
    {table_html}
  </div>
</div>
"""


# 公网页最终生效模板入口
def _build_public_local_section_refresh_action(view_rows_result=None, labels=None):
    labels = labels or _db_mode_labels(_normalize_db_mode_from_view(view_rows_result or {}))
    rows = list((view_rows_result or {}).get("rows") or [])
    latest_updated_at = ""
    for row in rows:
        candidate = str((row or {}).get("updated_at") or "").strip()
        if candidate and (not latest_updated_at or candidate > latest_updated_at):
            latest_updated_at = candidate
    last_refresh_time = _format_snapshot_relative_time(latest_updated_at)
    return _build_section_refresh_action(
        "/public-snapshot/refresh",
        (("target_scope", "local"), ("db_mode", labels["db_mode"])),
        "\u5237\u65b0",
        f"1\u53f7\u6700\u540e\u5feb\u7167\u65f6\u95f4\uff1a{last_refresh_time}",
    )


def _build_public_remote_section_refresh_action(section, labels=None):
    labels = labels or _db_mode_labels(section.get("db_mode"))
    machine_id = str(section.get("machine_id") or "").strip()
    last_refresh_time = _format_snapshot_relative_time(section.get("last_report_time"))
    machine_label = str(section.get("machine_display_name") or section.get("machine_id") or "远端").strip()
    machine_label = machine_label.replace("电脑", "").strip() or "远端"
    return _build_section_refresh_action(
        "/public-snapshot/refresh",
        (("target_scope", "remote"), ("target_machine_id", machine_id), ("db_mode", labels["db_mode"])),
        "\u5237\u65b0",
        f"{machine_label}\u6700\u540e\u5feb\u7167\u65f6\u95f4\uff1a{last_refresh_time}",
        disabled=not bool(machine_id),
    )


def _render_public_local_refresh_toolbar(machine_display_name, refresh_result=None):
    del machine_display_name
    if refresh_result and str(refresh_result.get("status") or "").strip() == "success":
        return ""
    return _render_public_local_refresh_result(refresh_result)


def _render_public_remote_refresh_toolbar(section, refresh_result=None):
    return _render_remote_refresh_toolbar(section, refresh_result)


def _render_public_remote_machine_section(section, grid_index, refresh_result=None, labels=None):
    labels = labels or _db_mode_labels(section.get("db_mode"))
    row_items = _build_remote_account_list_rows(section, labels["db_mode"])
    summary_html = _build_linear_summary_cards(section.get("machine_daily_summaries"), labels["summary_change_label"])
    empty_message = str(section.get("message") or "暂无远端快照数据。")
    empty_html = (
        f'<p class="muted-text">{escape(empty_message)}</p>'
        if not (section.get("rows") or [])
        else ""
    )
    display_name = section.get("machine_display_name") or section.get("machine_id") or "远端电脑"
    table_html = _render_table(
        (
            "\u6635\u79f0",
            labels["inventory_label"],
            labels["balance_label"],
            "\u53ef\u8fd0\u884c\u65f6\u95f4",
            "\u51b7\u5374\u5269\u4f59\u65f6\u95f4",
            "\u8d26\u53f7\u72b6\u6001",
            "\u66f4\u65b0\u65f6\u95f4",
        ),
        row_items,
    )
    return f"""
  <div class="section stage-panel stage-secondary">
    {_render_linear_section_title(
        display_name,
        labels["db_label"],
        eyebrow="Snapshot",
        action_html=_build_public_remote_section_refresh_action(section, labels),
    )}
    {_render_public_remote_refresh_toolbar(section, refresh_result)}
    {summary_html}
    {empty_html}
    <div class="data-module data-module-public">
      {_render_module_title(f"Snapshot Grid {grid_index:02d}", "Readonly remote snapshot table for comparison only.")}
      {table_html}
    </div>
  </div>
"""


def render_public_snapshot_page(view_rows_result, remote_machine_sections=None, refresh_result=None):
    labels = _db_mode_labels(_normalize_db_mode_from_view(view_rows_result))
    rows = list(view_rows_result.get("rows") or [])
    local_machine_display_name = view_rows_result.get("machine_display_name") or "1\u53f7\u7535\u8111"
    local_summary_html = _build_linear_summary_cards(
        view_rows_result.get("machine_daily_summaries"),
        labels["summary_change_label"],
    )
    local_row_items = _build_public_local_snapshot_rows(rows, labels["db_mode"])

    remote_machine_sections = list(remote_machine_sections or [])
    if not remote_machine_sections:
        remote_machine_sections = [
            {
                "machine_id": "",
                "machine_display_name": "2\u53f7\u7535\u8111",
                "rows": [],
                "machine_daily_summaries": [],
                "message": "\u6682\u65e0 2\u53f7\u5feb\u7167\u6570\u636e\u3002",
                "last_report_time": "",
            }
        ]
    remote_sections_html = "".join(
        _render_public_remote_machine_section(
            section,
            grid_index=index,
            refresh_result=refresh_result,
            labels=labels,
        )
        for index, section in enumerate(remote_machine_sections, start=2)
    )
    has_remote_rows = any(section.get("rows") for section in remote_machine_sections)
    return_home_label = "\u8fd4\u56de\u9996\u9875"

    local_table_html = _render_table(
        (
            "\u6635\u79f0",
            labels["inventory_label"],
            labels["balance_label"],
            "\u53ef\u8fd0\u884c\u65f6\u95f4",
            "\u51b7\u5374\u5269\u4f59\u65f6\u95f4",
            "\u8d26\u53f7\u72b6\u6001",
            "\u66f4\u65b0\u65f6\u95f4",
        ),
        [
            _with_optional_row_class(_table_row_cells(row)[1:], _table_row_class(row))
            for row in local_row_items
        ],
    )

    body_html = f"""
<div class="page-shell page-shell-public">
  <div class="section stage-panel stage-primary">
    {_render_linear_section_title(
        local_machine_display_name,
        "",
        eyebrow="Snapshot",
        badge_html=_build_db_mode_toggle("/public-snapshot", labels),
        action_html=_build_public_local_section_refresh_action(view_rows_result, labels),
    )}
    {_render_public_local_refresh_toolbar(local_machine_display_name, refresh_result)}
    {local_summary_html}
    <div class="data-module data-module-public">
      {_render_module_title("Snapshot Grid 01", "Readonly local snapshot table for fast scanning.")}
      {local_table_html}
    </div>
  </div>

{remote_sections_html}

  <div class="detail-back-link">
    {_render_linear_page_action(f"/?db={labels['db_mode']}", return_home_label)}
  </div>

  {_build_refresh_scroll_script()}
  {_build_refresh_button_state_script(refresh_result)}
  {_render_local_relative_time_script() if (rows or has_remote_rows) else ""}
  {_render_strip_year_display_script()}
</div>
"""
    return _base_page("\u516c\u7f51\u5feb\u7167\u9875", body_html)
