"""最小网页展示模板。"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from html import escape


def _format_value(value):
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value if str(item).strip()]
        return escape(", ".join(items)) if items else "-"
    if isinstance(value, dict):
        return escape(str(value))
    text = str(value).strip()
    return escape(text) if text else "-"


def _render_table(headers, rows, column_classes=None, table_class=""):
    column_classes = list(column_classes or [])
    table_classes = ["data-table"]
    if table_class:
        table_classes.append(table_class)
    table_class_attr = f' class="{escape(" ".join(table_classes), quote=True)}"'
    header_parts = []
    for index, header in enumerate(headers):
        column_class = column_classes[index] if index < len(column_classes) else ""
        class_attr = f' class="{escape(column_class, quote=True)}"' if column_class else ""
        header_parts.append(f"<th{class_attr}>{escape(str(header))}</th>")
    header_html = "".join(header_parts)
    body_parts = []
    for row in rows:
        cells = []
        for index, cell in enumerate(row):
            column_class = column_classes[index] if index < len(column_classes) else ""
            class_attr = f' class="{escape(column_class, quote=True)}"' if column_class else ""
            cells.append(f"<td{class_attr}>{cell}</td>")
        cell_html = "".join(cells)
        body_parts.append(f"<tr>{cell_html}</tr>")
    body_html = "".join(body_parts) if body_parts else (
        f"<tr><td colspan=\"{len(headers)}\">暂无数据</td></tr>"
    )
    return (
        '<div class="table-wrap">'
        f"<table{table_class_attr}>"
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{body_html}</tbody>"
        "</table>"
        "</div>"
    )


def _display_status_text(value):
    text = str(value or "").strip()
    if text == "抢购时长已到":
        return "时长已到"
    return text


def _render_kv_table(items):
    rows = []
    for key, value in items:
        rows.append((escape(str(key)), _format_value(value)))
    return _render_table(("字段", "值"), rows)


def _render_health_summary(health):
    items = [
        ("存在重复执行位", health.get("has_duplicate_execution_slots")),
        ("存在缺失执行位", health.get("has_missing_execution_slots")),
        ("存在关键字段缺失", health.get("has_missing_critical_fields")),
        ("辅助快照存在", health.get("runtime_snapshot_exists")),
        ("辅助快照命中主记录", health.get("runtime_matched_canonical_record")),
    ]
    if "runtime_consistency" in health:
        runtime_consistency = health.get("runtime_consistency") or {}
        items.extend(
            [
                ("辅助快照明显滞后", runtime_consistency.get("runtime_is_stale")),
                ("辅助快照与主记录一致", runtime_consistency.get("runtime_matches_canonical")),
                ("辅助快照不一致字段", runtime_consistency.get("runtime_mismatch_fields")),
            ]
        )
    return _render_kv_table(items)


def _render_source_notice(source_summary=None):
    source_summary = source_summary or {}
    canonical_table_name = source_summary.get("canonical_table_name") or "-"
    canonical_database_path = escape(str(source_summary.get("canonical_database_path") or ""))
    runtime_database_path = escape(str(source_summary.get("runtime_database_path") or ""))
    runtime_database_exists = _format_value(source_summary.get("runtime_database_exists"))
    return f"""
<div class="notice">
  <strong>数据来源说明：</strong>
  主 SQLite 数据表（表：<code>{escape(str(canonical_table_name))}</code>）是唯一真实数据源；
  辅助快照只用于一致性对照，不参与主展示口径。
  <br>
  主库路径：<code>{canonical_database_path or "-"}</code>
  <br>
  辅助快照路径：<code>{runtime_database_path or "-"}</code>（存在：{runtime_database_exists}）
</div>
"""


def _render_source_diagnostics(source_diagnostics=None):
    source_diagnostics = source_diagnostics or {}
    current_database_path = escape(str(source_diagnostics.get("current_database_path") or ""))
    expected_database_path = escape(str(source_diagnostics.get("expected_database_path") or ""))
    resolved_from_root = escape(str(source_diagnostics.get("resolved_from_root") or ""))
    real_record_count = _format_value(source_diagnostics.get("real_record_count"))
    showing_demo_data = source_diagnostics.get("showing_demo_data")
    demo_tip = "是，下方仅展示演示数据" if showing_demo_data else "否，下方展示真实账号列表"
    return f"""
<div class="section">
  <h2>数据源诊断</h2>
  {_render_kv_table((
      ("当前数据源文件", current_database_path or "-"),
      ("预期默认路径", expected_database_path or "-"),
      ("解析结果", source_diagnostics.get("resolution_label") or "-"),
      ("回退命中的工作树", resolved_from_root or "-"),
      ("真实账号记录数", real_record_count),
      ("当前是否展示演示数据", demo_tip),
  ))}
</div>
"""


def _render_read_only_notice():
    return """
<div class="readonly-notice">
  <strong>当前页面以查看为主：</strong>
  首页支持“单行最小编辑”，其中“当前道具数量”为只读推算值，只能通过“基数增减”调整 <code>baseline_item_count</code>；
  详情页保留“单账号最小编辑”，其中“道具基数”直接对应 <code>baseline_item_count</code>。
</div>
"""


def _render_edit_notice():
    return """
<div class="edit-notice">
  <strong>当前详情页支持最小编辑：</strong>
  仅允许修改 3 个字段：道具基数、账号状态、余额（万）。
  不支持批量编辑，不支持自动刷新，也不会改动辅助快照逻辑。
</div>
"""


def _build_demo_account_rows():
    return [
        {
            "current_execution_slot": 1,
            "nickname": "演示账号-A",
            "round_status": "运行中",
            "item_quantity": 42,
            "current_balance_wan": "18.6",
            "updated_at": "2026-04-03 10:15:00",
            "allow_purchase": True,
            "cooldown_remaining_seconds": 0,
        },
        {
            "current_execution_slot": 2,
            "nickname": "演示账号-B",
            "round_status": "账号限制",
            "item_quantity": 17,
            "current_balance_wan": "9.2",
            "updated_at": "2026-04-03 09:48:00",
            "allow_purchase": False,
            "cooldown_remaining_seconds": 1280,
        },
        {
            "current_execution_slot": 3,
            "nickname": "演示账号-C",
            "round_status": "余额不足",
            "item_quantity": 8,
            "current_balance_wan": "1.4",
            "updated_at": "2026-04-03 08:30:00",
            "allow_purchase": False,
            "cooldown_remaining_seconds": 0,
        },
        {
            "current_execution_slot": 4,
            "nickname": "演示账号-D",
            "round_status": "人工暂停",
            "item_quantity": 26,
            "current_balance_wan": "23",
            "updated_at": "2026-04-03 07:55:00",
            "allow_purchase": True,
            "cooldown_remaining_seconds": 0,
        },
    ]


def _render_demo_list_notice():
    return """
<div class="flash-error">
  <strong>当前无真实账号数据：</strong>
  下方仅为演示数据，用于展示页面效果。这些账号不会写入数据库，也不可查看详情或提交修改。
</div>
"""


def _render_execution_slot_summary(summary):
    items = [
        ("应有执行位列表", summary.get("expected_execution_slots")),
        ("应有执行位数量", summary.get("expected_execution_slot_count")),
        ("已覆盖执行位列表", summary.get("present_execution_slots")),
        ("已覆盖执行位数量", summary.get("present_execution_slot_count")),
        ("缺失执行位列表", summary.get("missing_execution_slots")),
        ("缺失执行位数量", summary.get("missing_execution_slot_count")),
    ]
    return _render_kv_table(items)


def _render_runtime_consistency_summary(runtime_result, runtime_consistency):
    runtime_snapshot = runtime_result.get("snapshot") or {}
    items = [
        ("辅助快照存在", runtime_result.get("database_exists")),
        ("辅助快照当前执行位", runtime_snapshot.get("current_execution_slot")),
        ("辅助快照当前昵称", runtime_snapshot.get("current_nickname")),
        ("辅助快照更新时间", runtime_snapshot.get("updated_at")),
        ("辅助快照明显滞后", runtime_consistency.get("runtime_is_stale")),
        ("辅助快照滞后秒数", runtime_consistency.get("runtime_lag_seconds")),
        ("辅助快照与主记录一致", runtime_consistency.get("runtime_matches_canonical")),
        ("辅助快照不一致字段", runtime_consistency.get("runtime_mismatch_fields")),
    ]
    return _render_kv_table(items)


def _render_edit_result(edit_result):
    if not edit_result:
        return ""

    status = str(edit_result.get("status") or "").strip()
    css_class = "flash-success" if status == "success" else "flash-error"
    title = "提交成功" if status == "success" else "提交失败"
    field_errors = edit_result.get("field_errors") or {}
    error_rows = []
    for field_name, message in field_errors.items():
        error_rows.append((escape(str(field_name)), escape(str(message))))

    field_error_html = ""
    if error_rows:
        field_error_html = f"""
<div class="field-error-block">
  <strong>字段校验：</strong>
  {_render_table(("字段", "错误"), error_rows)}
</div>
"""

    return f"""
<div class="{css_class}">
  <strong>{title}：</strong>{escape(str(edit_result.get("message") or ""))}
  {field_error_html}
</div>
"""


def _render_field_error(field_errors, field_name):
    message = str((field_errors or {}).get(field_name) or "").strip()
    if not message:
        return ""
    return f'<div class="field-error">{escape(message)}</div>'


def _build_detail_form_values(record, edit_meta, edit_result):
    form_values = dict((edit_meta or {}).get("form_defaults") or {})
    if edit_result and edit_result.get("form_values"):
        form_values.update(edit_result.get("form_values") or {})
    if record:
        form_values.setdefault("nickname", record.get("nickname"))
    return form_values


def _is_active_edit_row(row, edit_result):
    if not edit_result:
        return False
    form_values = edit_result.get("form_values") or {}
    active_nickname = str(form_values.get("nickname") or "").strip()
    row_nickname = str(row.get("nickname") or "").strip()
    return bool(active_nickname and active_nickname == row_nickname)


def _build_list_form_values(row, edit_result):
    form_values = {
        "nickname": str(row.get("nickname") or "").strip(),
        "baseline_item_delta": "",
        "round_status": str(row.get("round_status") or "").strip(),
        "current_balance_wan": str(row.get("current_balance_wan") or "").strip(),
    }
    if _is_active_edit_row(row, edit_result):
        form_values.update(edit_result.get("form_values") or {})
    return form_values


def _render_inline_row_result(row, edit_result):
    if not _is_active_edit_row(row, edit_result):
        return ""

    status = str(edit_result.get("status") or "").strip()
    css_class = "inline-result success" if status == "success" else "inline-result error"
    return f'<div class="{css_class}">{escape(str(edit_result.get("message") or ""))}</div>'


def _build_status_options_html(status_options, current_status):
    option_html = []
    for option in status_options:
        selected = " selected" if option == current_status else ""
        option_html.append(
            f'<option value="{escape(str(option), quote=True)}"{selected}>{escape(_display_status_text(option))}</option>'
        )
    return "".join(option_html)


def _render_inline_edit_cells(row, row_index, edit_meta=None, edit_result=None):
    nickname = str(row.get("nickname") or "").strip()
    if not nickname:
        muted_html = '<span class="muted-text">缺少昵称，暂不可编辑</span>'
        return muted_html, muted_html, muted_html, muted_html, muted_html

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

    item_cell = f"""
<div class="inline-field">
  <div class="readonly-value">{_format_value(row.get("item_quantity"))}</div>
  <div class="muted-text">只读推算值</div>
</div>
"""
    baseline_delta_cell = f"""
<div class="inline-field">
  <input form="{escape(form_id, quote=True)}" type="number" name="baseline_item_delta" step="1" required value="{escape(str(form_values.get('baseline_item_delta') or ''), quote=True)}" placeholder="-100 / 50">
  <div class="muted-text">保存时只调整 <code>baseline_item_count</code></div>
  {_render_field_error(field_errors, "baseline_item_delta")}
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
    balance_cell = f"""
<div class="inline-field">
  <div class="input-with-unit inline-balance">
    <input form="{escape(form_id, quote=True)}" type="text" name="current_balance_wan" inputmode="decimal" required value="{escape(str(form_values.get('current_balance_wan') or ''), quote=True)}">
    <span class="unit-tag">{escape(balance_input_unit)}</span>
  </div>
  {_render_field_error(field_errors, "current_balance_wan")}
</div>
"""
    action_cell = f"""
<div class="inline-save">
  <form id="{escape(form_id, quote=True)}" method="post" action="/account/update">
    <input type="hidden" name="nickname" value="{escape(nickname, quote=True)}">
    <input type="hidden" name="return_to" value="index">
  </form>
  <button type="submit" form="{escape(form_id, quote=True)}">保存</button>
  {_render_inline_row_result(row, edit_result)}
</div>
"""
    return item_cell, baseline_delta_cell, status_cell, balance_cell, action_cell


def _render_account_edit_form(record, edit_meta=None, edit_result=None):
    if record is None:
        return ""

    edit_meta = edit_meta or {}
    field_errors = (edit_result or {}).get("field_errors") or {}
    form_values = _build_detail_form_values(record, edit_meta, edit_result)
    status_options = list(edit_meta.get("status_options") or [])
    balance_input_unit = str(edit_meta.get("balance_input_unit") or "万")
    column_mapping = edit_meta.get("column_mapping") or {}

    option_html = []
    current_status = str(form_values.get("round_status") or "")
    for option in status_options:
        selected = " selected" if option == current_status else ""
        option_html.append(
            f'<option value="{escape(str(option), quote=True)}"{selected}>{escape(_display_status_text(option))}</option>'
        )

    return f"""
<div class="section">
  <h2>最小编辑</h2>
  <p>仅开放 3 个字段。余额输入单位固定为“{escape(balance_input_unit)}”，账号状态只能从现有合法枚举中选择。</p>
  <p>字段映射：道具基数 → <code>{escape(str(column_mapping.get("baseline_item_count") or "-"))}</code>，
  账号状态 → <code>{escape(str(column_mapping.get("round_status") or "-"))}</code>，
  余额（{escape(balance_input_unit)}） → <code>{escape(str(column_mapping.get("current_balance_wan") or "-"))}</code>。</p>
  <form method="post" action="/account/update" class="edit-form">
    <input type="hidden" name="nickname" value="{escape(str(record.get("nickname") or ""), quote=True)}">
    <input type="hidden" name="return_to" value="detail">
    <label>
      <span>道具基数</span>
      <input type="number" name="baseline_item_count" step="1" min="0" required value="{escape(str(form_values.get('baseline_item_count') or ''), quote=True)}">
      <small>必须为整数；提交时直接写入底层 <code>baseline_item_count</code>，不再按推算值反推。</small>
      {_render_field_error(field_errors, "baseline_item_count")}
    </label>
    <label>
      <span>账号状态</span>
      <select name="round_status" required>
        {"".join(option_html)}
      </select>
      <small>仅允许现有合法状态枚举，不接受自由文本。</small>
      {_render_field_error(field_errors, "round_status")}
    </label>
    <label>
      <span>余额（万）</span>
      <div class="input-with-unit">
        <input type="text" name="current_balance_wan" inputmode="decimal" required value="{escape(str(form_values.get('current_balance_wan') or ''), quote=True)}">
        <span class="unit-tag">{escape(balance_input_unit)}</span>
      </div>
      <small>页面输入和展示都按“万”为单位；提交时会按主库当前存储口径写入。</small>
      {_render_field_error(field_errors, "current_balance_wan")}
    </label>
    <div class="form-actions">
      <button type="submit">保存这 3 个字段</button>
    </div>
  </form>
</div>
"""


def _format_balance_wan_display(balance_wan_text):
    text = str(balance_wan_text or "").strip()
    if not text:
        return "-"
    if text.endswith("万"):
        text = text[:-1].strip()
    try:
        truncated_value = int(Decimal(text))
    except (InvalidOperation, ValueError):
        integer_text = text.split(".", 1)[0].strip()
        if integer_text in ("", "+", "-"):
            integer_text = "0"
        try:
            truncated_value = int(integer_text)
        except ValueError:
            return escape(text)
    return escape(f"{truncated_value}万")


def _format_cooldown_remaining_time(seconds_value):
    try:
        remaining_seconds = max(0, int(seconds_value or 0))
    except (TypeError, ValueError):
        remaining_seconds = 0

    total_minutes = remaining_seconds // 60
    if total_minutes < 60:
        return f"{total_minutes}分钟"

    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours}小时{minutes}分"


def _build_account_list_rows(rows, edit_meta=None, edit_result=None):
    using_demo_rows = not bool(rows)
    effective_rows = rows if rows else _build_demo_account_rows()

    row_items = []
    for row_index, row in enumerate(effective_rows, start=1):
        nickname = row.get("nickname")
        slot = row.get("current_execution_slot")
        if using_demo_rows:
            detail_cell = '<span class="muted-text">演示数据，不可查看/不可编辑</span>'
            item_cell = _format_value(row.get("item_quantity"))
            baseline_delta_cell = '<span class="muted-text">演示数据，不可编辑</span>'
            status_cell = _format_value(row.get("round_status"))
            balance_cell = _format_balance_wan_display(row.get("current_balance_wan"))
            action_cell = '<span class="muted-text">不可保存</span>'
        else:
            detail_url = f"/account?nickname={nickname}" if nickname else f"/account?execution_slot={slot}"
            detail_cell = f"<a href=\"{escape(detail_url, quote=True)}\">查看详情</a>"
            item_cell, baseline_delta_cell, status_cell, balance_cell, action_cell = _render_inline_edit_cells(
                row,
                row_index,
                edit_meta=edit_meta,
                edit_result=edit_result,
            )
        row_items.append(
            (
                _format_value(slot),
                _format_value(nickname),
                item_cell,
                baseline_delta_cell,
                status_cell,
                balance_cell,
                _format_value(row.get("allow_purchase")),
                _format_cooldown_remaining_time(row.get("cooldown_remaining_seconds")),
                detail_cell,
                action_cell,
            )
        )
    return row_items, using_demo_rows


def _base_page(title, body_html):
    style = """
    :root {
      --bg: #08090a;
      --panel: #0f1011;
      --surface: #131416;
      --surface-elevated: #191a1b;
      --surface-secondary: #202124;
      --line-subtle: rgba(255,255,255,0.05);
      --line-standard: rgba(255,255,255,0.08);
      --line-strong: rgba(255,255,255,0.12);
      --text-primary: #f7f8f8;
      --text-secondary: #d0d6e0;
      --text-tertiary: #8a8f98;
      --text-quaternary: #62666d;
      --accent: #7170ff;
      --accent-bg: #5e6ad2;
      --accent-hover: #828fff;
      --success: #27a644;
      --success-soft: rgba(39,166,68,0.12);
      --danger: #ff7b72;
      --danger-soft: rgba(255,123,114,0.12);
      --warning: #d4a72c;
      --warning-soft: rgba(212,167,44,0.12);
      --radius-sm: 6px;
      --radius-md: 8px;
      --radius-lg: 12px;
      --radius-xl: 22px;
      --shadow-panel: rgba(0,0,0,0.35) 0px 24px 60px -28px, inset 0 1px 0 rgba(255,255,255,0.03);
      --shadow-soft: rgba(0,0,0,0.24) 0px 10px 30px -20px, inset 0 1px 0 rgba(255,255,255,0.02);
    }
    html { background: var(--bg); }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Inter Variable", "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", -apple-system, system-ui, sans-serif;
      font-feature-settings: "cv01", "ss03";
      color: var(--text-primary);
      background:
        radial-gradient(circle at top, rgba(113,112,255,0.12), transparent 28%),
        radial-gradient(circle at 80% 0%, rgba(94,106,210,0.09), transparent 24%),
        linear-gradient(180deg, #0b0c10 0%, #08090a 48%, #090a0d 100%);
      padding: 24px;
    }
    h1, h2, h3, p { margin: 0; }
    .page-shell {
      max-width: 1240px;
      margin: 0 auto;
      display: grid;
      gap: 20px;
    }
    .page-shell-home,
    .page-shell-public {
      gap: 24px;
    }
    .page-grid {
      display: grid;
      gap: 18px;
    }
    .section {
      background: linear-gradient(180deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.02) 100%);
      border: 1px solid var(--line-standard);
      border-radius: var(--radius-xl);
      padding: 22px;
      margin: 0;
      box-shadow: var(--shadow-panel);
    }
    .stage-panel { position: relative; overflow: hidden; }
    .stage-panel::before {
      content: "";
      position: absolute;
      inset: 0 0 auto 0;
      height: 1px;
      background: linear-gradient(90deg, rgba(255,255,255,0.14), rgba(255,255,255,0.02) 55%, transparent);
      pointer-events: none;
    }
    .stage-primary {
      background:
        radial-gradient(circle at top right, rgba(113,112,255,0.12), transparent 36%),
        linear-gradient(180deg, rgba(255,255,255,0.035) 0%, rgba(255,255,255,0.025) 100%);
    }
    .stage-secondary {
      background:
        radial-gradient(circle at top right, rgba(255,255,255,0.05), transparent 34%),
        linear-gradient(180deg, rgba(255,255,255,0.028) 0%, rgba(255,255,255,0.02) 100%);
      border-color: rgba(255,255,255,0.06);
    }
    .meta,
    .muted-text {
      color: var(--text-tertiary);
      font-size: 14px;
      line-height: 1.7;
    }
    .meta { margin-bottom: 0; }
    .readonly-notice, .edit-notice, .notice, .flash-success, .flash-error {
      border-radius: var(--radius-lg);
      padding: 14px 16px;
      margin: 0;
      line-height: 1.65;
      font-size: 14px;
      color: var(--text-secondary);
      border: 1px solid var(--line-standard);
      background: rgba(255,255,255,0.03);
      box-shadow: var(--shadow-soft);
    }
    .readonly-notice {
      background: linear-gradient(180deg, rgba(94,106,210,0.12), rgba(255,255,255,0.025));
      border-color: rgba(113,112,255,0.28);
    }
    .edit-notice,
    .flash-success {
      background: linear-gradient(180deg, rgba(39,166,68,0.12), rgba(255,255,255,0.025));
      border-color: rgba(39,166,68,0.34);
    }
    .notice {
      background: linear-gradient(180deg, rgba(212,167,44,0.12), rgba(255,255,255,0.025));
      border-color: rgba(212,167,44,0.32);
    }
    .flash-error {
      background: linear-gradient(180deg, rgba(255,123,114,0.12), rgba(255,255,255,0.025));
      border-color: rgba(255,123,114,0.34);
    }
    .field-error-block { margin-top: 12px; }
    .field-error { color: #ff9b94; margin-top: 6px; font-size: 13px; }
    a { color: #aab2ff; text-decoration: none; }
    a:hover { color: #d6dbff; text-decoration: none; }
    code {
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.06);
      color: var(--text-secondary);
      padding: 1px 5px;
      border-radius: 4px;
      font-family: "Berkeley Mono", ui-monospace, "SF Mono", Menlo, monospace;
      font-size: 12px;
    }
    .table-wrap {
      width: 100%;
      overflow-x: auto;
      border-radius: 14px;
    }
    table,
    .data-table {
      width: 100%;
      border-collapse: collapse;
    }
    .data-table th,
    .data-table td {
      border-bottom: 1px solid rgba(255,255,255,0.06);
      padding: 12px 14px;
      text-align: left;
      vertical-align: top;
    }
    .data-table th {
      background: rgba(255,255,255,0.03);
      color: var(--text-secondary);
      font-size: 12px;
      line-height: 1.4;
      font-weight: 590;
      letter-spacing: 0.02em;
    }
    .data-table tbody tr:last-child td { border-bottom: none; }
    .data-table td {
      color: var(--text-primary);
      background: transparent;
    }
    .edit-form { display: grid; gap: 14px; }
    .edit-form label { display: grid; gap: 6px; }
    .edit-form span { font-weight: 510; color: var(--text-secondary); }
    .edit-form small { color: var(--text-tertiary); }
    .edit-form input, .edit-form select, .edit-form button { font: inherit; }
    .edit-form input, .edit-form select {
      padding: 8px 10px;
      border: 1px solid var(--line-standard);
      border-radius: var(--radius-sm);
      background: rgba(255,255,255,0.03);
      color: var(--text-primary);
    }
    .inline-field { display: grid; gap: 6px; min-width: 120px; }
    .inline-field input, .inline-field select {
      width: 100%;
      padding: 8px 10px;
      border: 1px solid var(--line-standard);
      border-radius: var(--radius-sm);
      background: rgba(255,255,255,0.03);
      color: var(--text-primary);
      font: inherit;
      box-sizing: border-box;
    }
    .inventory-field { min-width: 0; }
    .inventory-inline-row {
      display: flex;
      align-items: center;
      justify-content: flex-start;
      gap: 8px;
      min-width: 0;
    }
    .inventory-value,
    .inventory-input {
      width: 72px;
      min-width: 72px;
      max-width: 72px;
    }
    .inventory-input {
      text-align: left;
      padding-left: 12px;
      padding-right: 10px;
    }
    .inventory-input::-webkit-outer-spin-button,
    .inventory-input::-webkit-inner-spin-button {
      -webkit-appearance: none;
      margin: 0;
    }
    .inventory-input[type="number"] {
      -moz-appearance: textfield;
      appearance: textfield;
    }
    .inventory-updated {
      white-space: nowrap;
      font-size: 12px;
      line-height: 1.2;
      flex: 0 0 auto;
    }
    .edit-form select,
    .inline-field select,
    select {
      appearance: none;
      -webkit-appearance: none;
      -moz-appearance: none;
      background-color: rgba(255,255,255,0.035);
      background-image:
        linear-gradient(45deg, transparent 50%, var(--text-tertiary) 50%),
        linear-gradient(135deg, var(--text-tertiary) 50%, transparent 50%);
      background-position:
        calc(100% - 18px) calc(50% - 1px),
        calc(100% - 12px) calc(50% - 1px);
      background-size: 6px 6px, 6px 6px;
      background-repeat: no-repeat;
      color: var(--text-primary);
      border-color: var(--line-standard);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.02);
    }
    .edit-form select:hover,
    .inline-field select:hover,
    select:hover {
      background-color: rgba(255,255,255,0.05);
      border-color: var(--line-strong);
    }
    .edit-form select:focus,
    .inline-field select:focus,
    select:focus {
      outline: none;
      border-color: rgba(113,112,255,0.42);
      box-shadow: 0 0 0 3px rgba(113,112,255,0.16);
      background-color: rgba(255,255,255,0.05);
    }
    .edit-form select option,
    .inline-field select option,
    select option {
      background: #17191d;
      color: var(--text-primary);
    }
    .edit-form select option:checked,
    .inline-field select option:checked,
    select option:checked {
      background: #232637;
      color: #ffffff;
    }
    .readonly-value {
      padding: 8px 10px;
      border: 1px solid var(--line-standard);
      border-radius: var(--radius-sm);
      background: rgba(255,255,255,0.03);
      color: var(--text-secondary);
    }
    .input-with-unit { display: flex; align-items: center; gap: 8px; }
    .input-with-unit input { flex: 1; }
    .inline-balance { align-items: stretch; }
    .unit-tag {
      background: rgba(255,255,255,0.03);
      border: 1px solid var(--line-standard);
      border-radius: 999px;
      padding: 6px 10px;
      color: var(--text-secondary);
      font-weight: 510;
      font-size: 12px;
    }
    .form-actions button,
    .inline-save button,
    button {
      padding: 10px 14px;
      border: 1px solid rgba(113,112,255,0.24);
      border-radius: var(--radius-sm);
      background: rgba(255,255,255,0.04);
      color: var(--text-primary);
      cursor: pointer;
      transition: background .18s ease, border-color .18s ease, color .18s ease, transform .18s ease;
    }
    .form-actions button:hover,
    .inline-save button:hover,
    button:hover {
      background: rgba(113,112,255,0.16);
      border-color: rgba(130,143,255,0.42);
      color: #ffffff;
      transform: translateY(-1px);
    }
    .inline-save { display: grid; gap: 6px; min-width: 0; }
    .inline-save-main {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: nowrap;
      min-width: 0;
    }
    .inline-save a {
      white-space: nowrap;
      flex: 0 0 auto;
    }
    .inline-save button {
      padding: 8px 10px;
      min-width: 56px;
      flex: 0 0 auto;
    }
    .inline-save button.is-saved {
      border-color: rgba(39,166,68,0.42);
      background:
        linear-gradient(180deg, rgba(39,166,68,0.2) 0%, rgba(255,255,255,0.05) 100%);
      color: #d7f5de;
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.05),
        0 8px 18px -16px rgba(39,166,68,0.45);
    }
    .inline-save button.is-saved:hover {
      background:
        linear-gradient(180deg, rgba(39,166,68,0.26) 0%, rgba(255,255,255,0.07) 100%);
      border-color: rgba(92,194,114,0.5);
      color: #f4fff6;
    }
    .inline-save button.is-saved:focus {
      outline: none;
      border-color: rgba(92,194,114,0.52);
      box-shadow:
        0 0 0 3px rgba(39,166,68,0.18),
        inset 0 1px 0 rgba(255,255,255,0.05);
    }
    .inline-result { border-radius: 6px; padding: 6px 8px; font-size: 12px; line-height: 1.5; }
    .inline-result.success { background: rgba(39,166,68,0.12); color: #8ad39c; }
    .inline-result.error { background: rgba(255,123,114,0.12); color: #ff9b94; }
    .account-table { table-layout: fixed; }
    .account-table .col-slot { width: 84px; }
    .account-table .col-name { width: 84px; }
    .account-table .col-inventory { width: 132px; }
    .account-table .col-balance { width: 108px; }
    .account-table .col-runtime { width: 140px; }
    .account-table .col-status { width: 140px; }
    .account-table .col-allow { width: 92px; }
    .account-table .col-cooldown { width: 130px; }
    .account-table .col-action { width: 124px; }
    .page-title-shell {
      display: grid;
      gap: 16px;
      padding: 24px 28px 26px;
      border-radius: 24px;
      border: 1px solid var(--line-standard);
      background:
        radial-gradient(circle at top right, rgba(113,112,255,0.16), transparent 32%),
        linear-gradient(180deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.02) 100%);
      box-shadow: var(--shadow-panel);
    }
    .page-title-shell + h1 { display: none; }
    .page-title-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      flex-wrap: wrap;
    }
    .page-title-action-slot { display: inline-flex; align-items: center; }
    .page-title-kicker {
      display: inline-flex;
      align-items: center;
      width: fit-content;
      min-height: 24px;
      padding: 0 10px 0 9px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.09);
      background: rgba(255,255,255,0.03);
      color: var(--text-tertiary);
      font-size: 11px;
      line-height: 1.4;
      font-weight: 510;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    .page-title-action {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 36px;
      padding: 0 14px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(255,255,255,0.03);
      color: var(--text-secondary);
      font-size: 13px;
      font-weight: 510;
      letter-spacing: -0.01em;
      text-decoration: none;
    }
    .page-title-action:hover {
      color: #ffffff;
      background: rgba(113,112,255,0.18);
      border-color: rgba(130,143,255,0.42);
    }
    .page-title-main {
      display: grid;
      gap: 12px;
      max-width: 980px;
      position: relative;
      padding-left: 22px;
    }
    .page-title-main::before {
      content: "";
      position: absolute;
      left: 0;
      top: 6px;
      bottom: 10px;
      width: 4px;
      border-radius: 999px;
      background: linear-gradient(180deg, rgba(130,143,255,0.98) 0%, rgba(94,106,210,0.44) 100%);
      box-shadow: 0 0 28px rgba(113,112,255,0.22);
    }
    .page-title-main h1 {
      margin: 0;
      color: var(--text-primary);
      font-size: 46px;
      line-height: 1.02;
      font-weight: 510;
      letter-spacing: -0.022em;
    }
    .page-title-lead {
      margin: 0;
      color: var(--text-secondary);
      font-size: 17px;
      line-height: 1.6;
      font-weight: 400;
      letter-spacing: -0.01em;
      max-width: 860px;
    }
    .page-title-rule {
      margin: 0;
      color: var(--text-quaternary);
      font-size: 12px;
      line-height: 1.7;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .section-head {
      display: grid;
      gap: 10px;
      margin: 0 0 18px 0;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--line-standard);
    }
    .section-head-main {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }
    .section-head-primary {
      display: flex;
      align-items: flex-end;
      gap: 12px;
      flex-wrap: wrap;
      min-width: 0;
    }
    .section-title-wrap {
      display: grid;
      gap: 7px;
      min-width: 0;
      position: relative;
      padding-left: 18px;
    }
    .section-title-wrap::before {
      content: "";
      position: absolute;
      left: 0;
      top: 5px;
      width: 10px;
      height: 10px;
      border-top: 2px solid rgba(130,143,255,0.72);
      border-left: 2px solid rgba(130,143,255,0.72);
      opacity: 0.9;
    }
    .section-eyebrow {
      color: var(--text-quaternary);
      font-size: 10px;
      line-height: 1.4;
      font-weight: 510;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    .section-title {
      margin: 0;
      color: var(--text-primary);
      font-size: 26px;
      line-height: 1.14;
      font-weight: 400;
      letter-spacing: -0.018em;
    }
    .section-head-actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 10px;
      min-width: 0;
      margin-left: auto;
    }
    .section-action-cluster {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 10px;
      flex-wrap: wrap;
      min-width: 0;
    }
    .section-refresh-form {
      display: inline-flex;
      margin: 0;
    }
    .section-refresh-button {
      padding: 8px 14px;
      min-height: 34px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.1);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.025) 100%);
      color: var(--text-primary);
      font: inherit;
      font-size: 13px;
      font-weight: 510;
      letter-spacing: -0.01em;
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.03),
        0 8px 22px -18px rgba(0,0,0,0.5);
      cursor: pointer;
      transition: background .18s ease, border-color .18s ease, color .18s ease, transform .18s ease;
    }
    .section-refresh-button:hover {
      background:
        linear-gradient(180deg, rgba(113,112,255,0.18) 0%, rgba(255,255,255,0.05) 100%);
      border-color: rgba(130,143,255,0.34);
      color: #ffffff;
      transform: translateY(-1px);
    }
    .section-refresh-button:disabled {
      opacity: 0.45;
      cursor: not-allowed;
      transform: none;
    }
    .section-refresh-meta {
      color: var(--text-tertiary);
      font-size: 13px;
      line-height: 1.5;
      white-space: nowrap;
    }
    .module-head { display: grid; gap: 6px; margin: 0; padding-top: 0; }
    .module-title-row { display: flex; align-items: center; gap: 10px; min-width: 0; }
    .module-title-line { flex: 0 0 26px; height: 1px; background: linear-gradient(90deg, rgba(113,112,255,0.78) 0%, rgba(255,255,255,0.2) 100%); }
    .module-title {
      margin: 0;
      color: var(--text-secondary);
      font-size: 13px;
      line-height: 1.35;
      font-weight: 590;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    .module-note { margin: 0 0 0 36px; color: var(--text-quaternary); font-size: 12px; line-height: 1.6; }
    .summary-band {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin: 0 0 18px 0;
    }
    .summary-card {
      padding: 18px 18px 16px;
      border-radius: 18px;
      border: 1px solid var(--line-standard);
      background: linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.02));
      box-shadow: var(--shadow-soft);
      display: grid;
      gap: 14px;
    }
    .summary-card.summary-card-today {
      background:
        radial-gradient(circle at top right, rgba(113,112,255,0.16), transparent 42%),
        linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.025));
      border-color: rgba(255,255,255,0.1);
    }
    .summary-card.summary-card-yesterday {
      background: linear-gradient(180deg, rgba(255,255,255,0.028), rgba(255,255,255,0.018));
      border-color: rgba(255,255,255,0.06);
    }
    .summary-card-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .summary-card-label {
      color: var(--text-secondary);
      font-size: 12px;
      font-weight: 510;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    .summary-card-date {
      color: var(--text-quaternary);
      font-size: 12px;
      line-height: 1.4;
    }
    .summary-main {
      display: grid;
      gap: 4px;
    }
    .summary-main-label {
      color: var(--text-quaternary);
      font-size: 12px;
      line-height: 1.4;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .summary-main-value {
      color: var(--text-primary);
      font-size: 34px;
      line-height: 1;
      font-weight: 510;
      letter-spacing: -0.03em;
    }
    .summary-subgrid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .summary-metric {
      display: grid;
      gap: 5px;
      padding-top: 10px;
      border-top: 1px solid rgba(255,255,255,0.06);
    }
    .summary-metric-label {
      color: var(--text-quaternary);
      font-size: 11px;
      line-height: 1.45;
    }
    .summary-metric-value {
      color: var(--text-secondary);
      font-size: 18px;
      line-height: 1.1;
      font-weight: 590;
      letter-spacing: -0.02em;
    }
    .data-module {
      display: grid;
      gap: 12px;
      margin-top: 18px;
    }
    .data-module-toolbar {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .toolbar-pill {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 0 10px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(255,255,255,0.03);
      color: var(--text-tertiary);
      font-size: 12px;
      font-weight: 510;
    }
    .data-module-frame {
      border-radius: 18px;
      border: 1px solid rgba(255,255,255,0.08);
      background: linear-gradient(180deg, rgba(0,0,0,0.22), rgba(255,255,255,0.015));
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.03), inset 0 -1px 0 rgba(255,255,255,0.02);
      padding: 10px;
    }
    .data-module-frame .table-wrap {
      border-radius: 12px;
      border: 1px solid rgba(255,255,255,0.06);
      background: rgba(8,9,10,0.72);
    }
    .data-module-frame .data-table th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.025));
      box-shadow: inset 0 -1px 0 rgba(255,255,255,0.05);
    }
    .page-shell-home .stage-primary .data-module {
      gap: 14px;
      margin-top: 16px;
    }
    .page-shell-home .stage-primary .module-head {
      gap: 7px;
    }
    .page-shell-home .stage-primary .module-title-line {
      flex-basis: 30px;
      background: linear-gradient(90deg, rgba(130,143,255,0.88) 0%, rgba(255,255,255,0.22) 100%);
    }
    .page-shell-home .stage-primary .module-title {
      color: var(--text-primary);
      font-size: 14px;
      font-weight: 590;
      letter-spacing: 0.11em;
    }
    .page-shell-home .stage-primary .module-note {
      color: var(--text-tertiary);
      font-size: 12px;
    }
    .page-shell-home .stage-primary .data-module-frame {
      padding: 12px;
      border-color: rgba(255,255,255,0.09);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.015) 100%),
        linear-gradient(180deg, rgba(8,9,10,0.12) 0%, rgba(8,9,10,0.34) 100%);
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.04),
        inset 0 -1px 0 rgba(255,255,255,0.02),
        rgba(0,0,0,0.22) 0px 12px 28px -18px;
    }
    .page-shell-home .stage-primary .data-module-frame .table-wrap {
      border-radius: 14px;
      border: 1px solid rgba(255,255,255,0.08);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.02) 0%, rgba(255,255,255,0.01) 100%),
        #111214;
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.03),
        inset 0 0 0 1px rgba(255,255,255,0.02);
    }
    .page-shell-home .stage-primary .data-table {
      border-collapse: separate;
      border-spacing: 0;
    }
    .page-shell-home .stage-primary .data-table thead tr::after {
      content: "";
      display: table-row;
      height: 0;
    }
    .page-shell-home .stage-primary .account-table-local {
      width: 100%;
      table-layout: fixed;
    }
    .page-shell-home .stage-primary > .table-wrap {
      margin-top: 16px;
      border-radius: 14px;
      border: 1px solid rgba(255,255,255,0.08);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.02) 0%, rgba(255,255,255,0.01) 100%),
        #111214;
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.03),
        inset 0 0 0 1px rgba(255,255,255,0.02);
    }
    .page-shell-home .stage-primary .account-table-local .col-name { width: 9%; }
    .page-shell-home .stage-primary .account-table-local .col-inventory { width: 16%; }
    .page-shell-home .stage-primary .account-table-local .col-balance { width: 13%; }
    .page-shell-home .stage-primary .account-table-local .col-runtime { width: 18%; }
    .page-shell-home .stage-primary .account-table-local .col-status { width: 14%; }
    .page-shell-home .stage-primary .account-table-local .col-cooldown { width: 12%; }
    .page-shell-home .stage-primary .account-table-local .col-action { width: 18%; }
    .page-shell-home .stage-primary .account-table-local th {
      padding: 12px 14px;
      background: rgba(255,255,255,0.028);
      color: var(--text-secondary);
      font-size: 12px;
      font-weight: 590;
      letter-spacing: 0.03em;
      border-bottom: 1px solid rgba(255,255,255,0.08);
      box-shadow: none;
    }
    .page-shell-home .stage-primary .account-table-local td {
      padding: 13px 14px;
      vertical-align: middle;
      background: rgba(255,255,255,0.012);
      color: var(--text-primary);
      border-bottom: 1px solid rgba(255,255,255,0.05);
    }
    .page-shell-home .stage-primary .data-table tbody tr:nth-child(even) td {
      background: rgba(255,255,255,0.015);
    }
    .page-shell-home .stage-primary .data-table tbody tr:hover td {
      background: rgba(255,255,255,0.024);
    }
    .page-shell-home .stage-primary .data-table td.col-name,
    .page-shell-home .stage-primary .data-table td.col-runtime,
    .page-shell-home .stage-primary .data-table td.col-cooldown {
      padding-top: 12px;
      padding-bottom: 12px;
    }
    .page-shell-home .stage-primary .data-table td.col-status {
      color: #e9ecf3;
      font-size: 14px;
      font-weight: 510;
    }
    .page-shell-home .stage-primary .data-table td.col-balance {
      color: #f0f2f7;
      font-size: 15px;
      font-weight: 510;
      letter-spacing: -0.012em;
    }
    .page-shell-home .stage-primary .inventory-value,
    .page-shell-home .stage-primary .inventory-input,
    .page-shell-home .stage-primary .inline-balance input,
    .page-shell-home .stage-primary .inline-field select,
    .page-shell-home .stage-primary .readonly-value {
      min-height: 40px;
      border-color: rgba(255,255,255,0.09);
      background: linear-gradient(180deg, rgba(255,255,255,0.038) 0%, rgba(255,255,255,0.02) 100%);
      color: var(--text-primary);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.025);
    }
    .page-shell-home .stage-primary .inventory-value,
    .page-shell-home .stage-primary .inventory-input,
    .page-shell-home .stage-primary .inline-balance input,
    .page-shell-home .stage-primary .readonly-value {
      font-size: 15px;
      font-weight: 510;
      letter-spacing: -0.01em;
    }
    .page-shell-home .stage-primary .inline-field select {
      font-size: 14px;
      font-weight: 510;
      color: var(--text-secondary);
    }
    .page-shell-home .stage-primary .inline-field,
    .page-shell-home .stage-primary .inline-save,
    .page-shell-home .stage-primary .inline-save-main,
    .page-shell-home .stage-primary .inventory-inline-row,
    .page-shell-home .stage-primary .inline-balance {
      width: 100%;
      min-width: 0;
      align-items: center;
    }
    .page-shell-home .stage-primary .inline-save-main {
      width: auto;
      justify-content: flex-start;
    }
    .page-shell-public .data-module-public,
    .page-shell-home .stage-secondary .data-module-public {
      display: grid;
      gap: 14px;
      margin-top: 16px;
    }
    .page-shell-public .data-module-public > .table-wrap,
    .page-shell-home .stage-secondary .data-module-public > .table-wrap {
      border-radius: 14px;
      border: 1px solid rgba(255,255,255,0.08);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.026) 0%, rgba(255,255,255,0.012) 100%),
        rgba(15,16,17,0.96);
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.03),
        inset 0 0 0 1px rgba(255,255,255,0.018);
    }
    .page-shell-public .data-module-public .data-table,
    .page-shell-home .stage-secondary .data-module-public .data-table {
      border-collapse: separate;
      border-spacing: 0;
    }
    .page-shell-public .data-module-public .data-table th,
    .page-shell-home .stage-secondary .data-module-public .data-table th {
      background: rgba(255,255,255,0.028);
      color: var(--text-secondary);
      border-bottom: 1px solid rgba(255,255,255,0.08);
      box-shadow: none;
    }
    .page-shell-public .data-module-public .data-table td,
    .page-shell-home .stage-secondary .data-module-public .data-table td {
      background: rgba(255,255,255,0.012);
      border-bottom: 1px solid rgba(255,255,255,0.05);
    }
    .page-shell-public .data-module-public .data-table tbody tr:nth-child(even) td,
    .page-shell-home .stage-secondary .data-module-public .data-table tbody tr:nth-child(even) td {
      background: rgba(255,255,255,0.016);
    }
    .page-shell-public .data-module-public .data-table tbody tr:hover td,
    .page-shell-home .stage-secondary .data-module-public .data-table tbody tr:hover td {
      background: rgba(255,255,255,0.024);
    }
    .page-shell-public .summary-card {
      padding: 15px 18px 13px;
      gap: 11px;
    }
    .page-shell-home .summary-card {
      padding: 15px 18px 13px;
      gap: 11px;
    }
    .page-shell-public .summary-subgrid {
      gap: 8px;
    }
    .page-shell-home .summary-subgrid {
      gap: 8px;
    }
    .page-shell-public .summary-metric {
      gap: 4px;
      padding-top: 8px;
    }
    .page-shell-home .summary-metric {
      gap: 4px;
      padding-top: 8px;
    }
    .page-shell-home .stage-primary .display-field {
      display: flex;
      align-items: center;
      width: 100%;
      min-height: 40px;
      padding: 0 12px;
      border: 1px solid rgba(255,255,255,0.09);
      border-radius: 12px;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.038) 0%, rgba(255,255,255,0.02) 100%);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.025);
      box-sizing: border-box;
      color: var(--text-secondary);
      font-size: 14px;
      font-weight: 510;
      letter-spacing: -0.01em;
    }
    .page-shell-home .stage-primary .display-field-name {
      color: var(--text-primary);
      font-size: 15px;
      font-weight: 590;
    }
    .page-shell-home .stage-primary .display-field-meta {
      color: var(--text-secondary);
    }
    .detail-back-link {
      margin: 4px 0 2px;
    }
    .detail-back-link a {
      color: var(--text-secondary);
    }
    .page-shell-home .stage-primary .inventory-updated,
    .page-shell-home .stage-primary .local-relative-time {
      color: var(--text-quaternary);
      font-size: 12px;
      font-weight: 400;
      letter-spacing: -0.01em;
    }
    .page-shell-home .data-module > .module-head,
    .page-shell-home .data-module > .data-module-toolbar {
      display: none;
    }
    .page-shell-home .stage-secondary .flash-success,
    .page-shell-home .stage-secondary .flash-error {
      display: none;
    }
    .page-split-note {
      display: grid;
      gap: 8px;
      margin-bottom: 2px;
    }
    .page-split-note p { margin: 0; }
    @media (max-width: 760px) {
      body { padding: 12px; }
      .page-shell { gap: 16px; }
      .section { padding: 16px; border-radius: 18px; }
      .page-title-shell { padding: 18px 18px 20px; }
      .page-title-main { padding-left: 16px; }
      .page-title-main h1 { font-size: 32px; }
      .page-title-lead { font-size: 15px; }
      .section-title { font-size: 22px; }
      .section-head-actions,
      .section-action-cluster {
        width: 100%;
        justify-content: flex-start;
      }
      .section-refresh-meta {
        white-space: normal;
      }
      .summary-band,
      .summary-subgrid { grid-template-columns: 1fr; }
      .module-note { margin-left: 0; }
      .input-with-unit { flex-direction: column; align-items: stretch; }
      .unit-tag { align-self: flex-start; }
      .account-table { table-layout: auto; }
    }
    """
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>{style}</style>
</head>
<body>
{body_html}
</body>
</html>"""


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
{_render_read_only_notice()}
{_render_source_notice()}
<div class="section">
  <p>{escape(message)}</p>
  <p><a href="{escape(back_href, quote=True)}">{escape(back_label)}</a></p>
</div>
{detail_html}
"""
    return _base_page(title, body_html)


def render_index_page(view_rows_result, runtime_result, edit_result=None):
    rows = view_rows_result.get("rows") or []
    health = view_rows_result.get("health") or {}
    source_summary = view_rows_result.get("source_summary") or {}
    source_diagnostics = view_rows_result.get("source_diagnostics") or {}
    execution_slot_summary = view_rows_result.get("execution_slot_summary") or {}
    edit_meta = view_rows_result.get("edit_meta") or {}
    runtime_snapshot = runtime_result.get("snapshot") or {}
    row_items, using_demo_rows = _build_account_list_rows(
        rows,
        edit_meta=edit_meta,
        edit_result=edit_result,
    )

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

    demo_notice_html = _render_demo_list_notice() if using_demo_rows else ""

    body_html = f"""
<h1>账号数据查看页</h1>
{_render_read_only_notice()}
{_render_edit_result(edit_result)}
{_render_source_notice(source_summary)}
{_render_source_diagnostics(source_diagnostics)}
<div class="meta">
  主库路径：<code>{escape(str(view_rows_result.get("database_path") or ""))}</code><br>
  生成时间：{_format_value(view_rows_result.get("generated_at"))}
</div>

<div class="section">
  <h2>账号列表</h2>
  {demo_notice_html}
  {_render_table(("执行位", "昵称", "当前道具数量", "基数增减", "账号状态", "余额（万）", "允许抢购", "冷却剩余时间", "详情", "保存"), row_items)}
</div>

<div class="section">
  <h2>数据健康摘要</h2>
  {_render_health_summary(health)}
</div>

<div class="section">
  <h2>执行位覆盖情况</h2>
  <p>首页明确展示主库视角下已覆盖与缺失的执行位，便于快速判断槽位是否齐全。</p>
  {_render_execution_slot_summary(execution_slot_summary)}
</div>

<div class="section">
  <h2>辅助快照摘要</h2>
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
    return _base_page("账号数据查看页", body_html)


def render_account_detail_page(detail_result, runtime_result, edit_result=None):
    record = detail_result.get("record")
    health = detail_result.get("health") or {}
    lookup = detail_result.get("lookup") or {}
    source_summary = detail_result.get("source_summary") or {}
    edit_meta = detail_result.get("edit_meta") or {}

    if record is None:
        body_html = f"""
<h1>账号详情</h1>
{_render_read_only_notice()}
{_render_source_notice(source_summary)}
<div class="meta">
  查询条件：昵称={_format_value(lookup.get("nickname"))}，
  执行位={_format_value(lookup.get("execution_slot"))}
</div>
<div class="section">
  <p>未根据当前查询条件找到对应账号记录。</p>
  <p>请返回首页重新选择，或确认昵称参数 / 执行位参数是否填写正确。</p>
  <p><a href="/">返回首页</a></p>
</div>
"""
        return _base_page("账号详情", body_html)

    base_items = [
        ("昵称", record.get("nickname")),
        ("执行位", record.get("current_execution_slot")),
        ("状态", record.get("round_status")),
        ("余额（万）", _format_balance_wan_display(record.get("current_balance_wan"))),
        ("余额原始存储", record.get("current_balance")),
        ("道具基数", record.get("baseline_item_count")),
        ("本轮抢购成功数", record.get("round_purchase_success_count")),
        ("本轮上架成功数", record.get("round_listing_success_count")),
        ("本轮抢购失败数", record.get("round_purchase_fail_count")),
        ("本轮运行秒数", record.get("purchase_running_seconds")),
        ("最后限制时间", record.get("last_limit_time")),
        ("最后下号时间", record.get("last_account_end_time")),
        ("更新时间", record.get("updated_at")),
    ]
    derived_items = [
        ("当前道具数量（推算）", record.get("item_quantity")),
        ("允许开始时间", record.get("allow_start_time")),
        ("当前可抢购", record.get("allow_purchase")),
        ("冷却剩余时间", _format_cooldown_remaining_time(record.get("cooldown_remaining_seconds"))),
    ]

    record_health_items = [
        ("存在关键字段缺失", health.get("has_missing_critical_fields")),
        ("缺失字段", health.get("missing_critical_fields")),
        ("主库更新时间", record.get("updated_at")),
        ("辅助快照存在", runtime_result.get("database_exists")),
    ]

    runtime_consistency = health.get("runtime_consistency") or {}

    body_html = f"""
<h1>账号详情</h1>
{_render_edit_notice()}
{_render_edit_result(edit_result)}
{_render_source_notice(source_summary)}
<div class="meta">
  主库路径：<code>{escape(str(detail_result.get("database_path") or ""))}</code><br>
  查询条件：昵称={_format_value(lookup.get("nickname"))}，
  执行位={_format_value(lookup.get("execution_slot"))}
</div>

<div class="section">
  <p><a href="/">返回首页</a></p>
</div>

{_render_account_edit_form(record, edit_meta, edit_result)}

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
  <p>这里只展示当前主库记录本身的完整性和可读性摘要，不写回任何额外数据。</p>
  {_render_kv_table(record_health_items)}
</div>

<div class="section">
  <h2>与辅助快照的一致性摘要</h2>
  <p>辅助快照仅做对照，以下结果用于观察当前快照与主库详情是否一致。</p>
  {_render_runtime_consistency_summary(runtime_result, runtime_consistency)}
</div>
"""
    return _base_page(f"账号详情 - {record.get('nickname')}", body_html)
