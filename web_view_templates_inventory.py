"""库存语义版网页模板。"""
from html import escape

import web_view_templates as base_templates


_base_page = base_templates._base_page
_build_detail_form_values = base_templates._build_detail_form_values
_build_status_options_html = base_templates._build_status_options_html
_format_balance_wan_display = base_templates._format_balance_wan_display
_format_cooldown_remaining_time = base_templates._format_cooldown_remaining_time
_format_value = base_templates._format_value
_is_active_edit_row = base_templates._is_active_edit_row
_render_demo_list_notice = base_templates._render_demo_list_notice
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
    return escape(text) if text else "-"


def _format_remote_remaining_text(seconds_value):
    seconds = max(0, int(seconds_value or 0))
    return _format_cooldown_remaining_time(seconds)


def _render_remote_countdown_cell(row, field_name):
    remaining_seconds = max(0, int(row.get(field_name) or 0))
    report_time = str(row.get("report_time") or "").strip()
    initial_text = _format_remote_remaining_text(remaining_seconds)
    if not report_time:
        return initial_text

    return (
        f'<span class="remote-countdown" '
        f'data-remaining-seconds="{escape(str(remaining_seconds), quote=True)}" '
        f'data-report-time="{escape(report_time, quote=True)}">{initial_text}</span>'
    )


def _render_remote_countdown_script():
    return """
<script>
(function () {
  function parseReportTime(text) {
    if (!text) return NaN;
    return Date.parse(String(text).trim().replace(" ", "T"));
  }

  function formatDuration(totalSeconds) {
    totalSeconds = Math.max(0, Math.floor(Number(totalSeconds) || 0));
    var hours = Math.floor(totalSeconds / 3600);
    var minutes = Math.floor((totalSeconds % 3600) / 60);
    var seconds = totalSeconds % 60;
    if (hours > 0) return hours + "小时" + minutes + "分" + seconds + "秒";
    if (minutes > 0) return minutes + "分" + seconds + "秒";
    return seconds + "秒";
  }

  function updateCountdownNodes() {
    var now = Date.now();
    document.querySelectorAll(".remote-countdown").forEach(function (node) {
      var baseSeconds = Number(node.dataset.remainingSeconds || 0);
      var reportTimeMs = parseReportTime(node.dataset.reportTime || "");
      if (!Number.isFinite(reportTimeMs)) {
        node.textContent = formatDuration(baseSeconds);
        return;
      }
      var remainingSeconds = Math.max(0, Math.floor((reportTimeMs + baseSeconds * 1000 - now) / 1000));
      node.textContent = formatDuration(remainingSeconds);
    });
  }

  updateCountdownNodes();
  window.setInterval(updateCountdownNodes, 1000);
})();
</script>
"""


def _render_read_only_notice():
    return """
<div class="readonly-notice">
  <strong>当前首页仍以本机查看为主：</strong>
  本机板块继续支持最小库存/状态/余额编辑；远端板块只展示局域网同步镜像，不允许直接写库。
</div>
"""


def _render_edit_notice():
    return """
<div class="edit-notice">
  <strong>当前详情页支持最小编辑：</strong>
  仅允许修改 3 个字段：道具库存、账号状态、余额（万）。
  提交后只写入本机 canonical 主表，并执行回读确认。
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
        {
            "current_execution_slot": 3,
            "nickname": "演示账号-C",
            "round_status": "余额不足",
            "baseline_item_count": 8,
            "inventory_quantity": 8,
            "current_balance_wan": "1.4",
            "updated_at": "2026-04-03 08:30:00",
            "updated_at_relative": "7小时前",
            "allow_purchase": False,
            "cooldown_remaining_seconds": 0,
            "runtime_window_remaining_text": "0秒",
        },
        {
            "current_execution_slot": 4,
            "nickname": "演示账号-D",
            "round_status": "正常结束",
            "baseline_item_count": 26,
            "inventory_quantity": 26,
            "current_balance_wan": "23",
            "updated_at": "2026-04-03 07:55:00",
            "updated_at_relative": "8小时前",
            "allow_purchase": True,
            "cooldown_remaining_seconds": 0,
            "runtime_window_remaining_text": "48分钟",
        },
    ]


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
    update_tip = escape(str(row.get("updated_at_relative") or "-"))

    inventory_cell = f"""
<div class="inline-field">
  <input form="{escape(form_id, quote=True)}" type="number" name="baseline_item_count" step="1" min="0" required value="{escape(str(form_values.get('baseline_item_count') or ''), quote=True)}">
  <div class="muted-text">最后入库/更新：{update_tip}</div>
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
            f'<option value="{escape(str(option), quote=True)}"{selected}>{escape(str(option))}</option>'
        )

    return f"""
<div class="section">
  <h2>最小编辑</h2>
  <p>仅开放 3 个字段。余额输入单位固定为“{escape(balance_input_unit)}”，账号状态只能从现有合法枚举中选择。</p>
  <p>字段映射：道具库存 → <code>{escape(str(column_mapping.get("baseline_item_count") or "-"))}</code>，
  账号状态 → <code>{escape(str(column_mapping.get("round_status") or "-"))}</code>，
  余额（{escape(balance_input_unit)}） → <code>{escape(str(column_mapping.get("current_balance_wan") or "-"))}</code>。</p>
  <form method="post" action="/account/update" class="edit-form">
    <input type="hidden" name="nickname" value="{escape(str(record.get("nickname") or ""), quote=True)}">
    <input type="hidden" name="return_to" value="detail">
    <label>
      <span>道具库存</span>
      <input type="number" name="baseline_item_count" step="1" min="0" required value="{escape(str(form_values.get('baseline_item_count') or ''), quote=True)}">
      <small>必须为整数；提交时直接写入底层 <code>baseline_item_count</code>。</small>
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
      <small>页面输入和展示都按“万”为单位；提交时按主库当前存储口径写入。</small>
      {_render_field_error(field_errors, "current_balance_wan")}
    </label>
    <div class="form-actions">
      <button type="submit">保存这 3 个字段</button>
    </div>
  </form>
</div>
"""


def _build_account_list_rows(rows, edit_meta=None, edit_result=None):
    edit_result = _get_local_edit_result(edit_result)
    using_demo_rows = not bool(rows)
    effective_rows = rows if rows else _build_demo_account_rows()

    row_items = []
    for row_index, row in enumerate(effective_rows, start=1):
        nickname = row.get("nickname")
        if using_demo_rows:
            inventory_text = _format_value(row.get("inventory_quantity") or row.get("baseline_item_count"))
            inventory_cell = (
                f'<div class="inline-field"><div class="readonly-value">{inventory_text}</div>'
                f'<div class="muted-text">最后入库/更新：{escape(str(row.get("updated_at_relative") or "-"))}</div></div>'
            )
            balance_cell = _format_balance_wan_display(row.get("current_balance_wan"))
            runtime_cell = _format_runtime_remaining_text(row.get("runtime_window_remaining_text"))
            status_cell = _format_value(row.get("round_status"))
            action_cell = '<span class="muted-text">演示数据，不可操作</span>'
        else:
            inventory_cell, balance_cell, status_cell, action_cell = _render_inline_edit_cells(
                row,
                row_index,
                edit_meta=edit_meta,
                edit_result=edit_result,
            )
            runtime_cell = _format_runtime_remaining_text(row.get("runtime_window_remaining_text"))
        row_items.append(
            (
                _format_value(row.get("current_execution_slot")),
                _format_value(nickname),
                inventory_cell,
                balance_cell,
                runtime_cell,
                status_cell,
                _format_value(row.get("allow_purchase")),
                _format_cooldown_remaining_time(row.get("cooldown_remaining_seconds")),
                action_cell,
            )
        )
    return row_items, using_demo_rows


def _is_active_remote_edit_row(section, row, edit_result):
    if not edit_result or str(edit_result.get("scope") or "").strip() != "remote":
        return False
    form_values = edit_result.get("form_values") or {}
    active_machine_id = str(form_values.get("target_machine_id") or "").strip()
    active_nickname = str(form_values.get("nickname") or "").strip()
    section_machine_id = str(section.get("machine_id") or "").strip()
    row_nickname = str(row.get("nickname") or "").strip()
    return bool(
        active_machine_id
        and active_nickname
        and active_machine_id == section_machine_id
        and active_nickname == row_nickname
    )


def _build_remote_list_form_values(section, row, edit_result):
    form_values = {
        "target_machine_id": str(section.get("machine_id") or "").strip(),
        "nickname": str(row.get("nickname") or "").strip(),
        "baseline_item_count": str(row.get("baseline_item_count") or 0),
        "round_status": str(row.get("round_status") or "").strip(),
        "current_balance_wan": str(row.get("current_balance_wan") or "").strip(),
    }
    if _is_active_remote_edit_row(section, row, edit_result):
        form_values.update(edit_result.get("form_values") or {})
    return form_values


def _render_remote_inline_row_result(section, row, edit_result):
    if not _is_active_remote_edit_row(section, row, edit_result):
        return ""
    status = str(edit_result.get("status") or "").strip()
    css_class = "flash-success" if status == "success" else "flash-error"
    message = escape(str(edit_result.get("message") or ""))
    return f'<div class="{css_class} inline-row-result"><strong>回执：</strong>{message}</div>'


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
    can_refresh = bool(section.get("allow_remote_writeback"))
    button_attrs = (
        ' type="submit"'
        ' onclick="this.disabled=true;this.textContent=\'刷新中...\';this.form.submit();"'
    )
    if not can_refresh:
        button_attrs += ' disabled'

    hint_text = "点击后只拉取并刷新当前远端镜像，不会写入对端真源。"
    if not can_refresh:
        hint_text = "当前还没有可回连地址，需先收到一次远端镜像后才能手动刷新。"

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


def _render_remote_inline_edit_cells(section, row, row_index, edit_result=None):
    nickname = str(row.get("nickname") or "").strip()
    if not nickname:
        muted_html = '<span class="muted-text">缺少昵称，暂不可远端写回</span>'
        return muted_html, muted_html, muted_html, muted_html

    if not section.get("allow_remote_writeback"):
        inventory_text = _format_value(row.get("baseline_item_count"))
        balance_text = _format_balance_wan_display(row.get("current_balance_wan"))
        status_text = _format_value(row.get("round_status"))
        action_html = '<span class="muted-text">缺少可回连地址，当前仅镜像只读</span>'
        return inventory_text, balance_text, status_text, action_html

    edit_meta = section.get("edit_meta") or {}
    form_id = f"remote-inline-edit-form-{escape(str(section.get('machine_id') or 'machine'), quote=True)}-{row_index}"
    field_errors = (
        (edit_result or {}).get("field_errors")
        if _is_active_remote_edit_row(section, row, edit_result)
        else {}
    )
    form_values = _build_remote_list_form_values(section, row, edit_result)
    status_options = list(edit_meta.get("status_options") or [])
    balance_input_unit = str(edit_meta.get("balance_input_unit") or "万")
    status_options_html = _build_status_options_html(
        status_options,
        str(form_values.get("round_status") or ""),
    )

    inventory_cell = f"""
<div class="inline-field">
  <input form="{form_id}" type="number" name="baseline_item_count" step="1" min="0" required value="{escape(str(form_values.get('baseline_item_count') or ''), quote=True)}">
  {_render_field_error(field_errors, "baseline_item_count")}
</div>
"""
    balance_cell = f"""
<div class="inline-field">
  <div class="input-with-unit inline-balance">
    <input form="{form_id}" type="text" name="current_balance_wan" inputmode="decimal" required value="{escape(str(form_values.get('current_balance_wan') or ''), quote=True)}">
    <span class="unit-tag">{escape(balance_input_unit)}</span>
  </div>
  {_render_field_error(field_errors, "current_balance_wan")}
</div>
"""
    status_cell = f"""
<div class="inline-field">
  <select form="{form_id}" name="round_status" required>
    {status_options_html}
  </select>
  {_render_field_error(field_errors, "round_status")}
</div>
"""
    action_cell = f"""
<div class="inline-save">
  <form id="{form_id}" method="post" action="/remote-account/update">
    <input type="hidden" name="target_machine_id" value="{escape(str(section.get('machine_id') or ''), quote=True)}">
    <input type="hidden" name="nickname" value="{escape(nickname, quote=True)}">
  </form>
  <button type="submit" form="{form_id}">提交到对端真源</button>
  {_render_remote_inline_row_result(section, row, edit_result)}
</div>
"""
    return inventory_cell, balance_cell, status_cell, action_cell


def _render_machine_section_title(title, badge_text):
    return (
        f'<h2>{escape(str(title))} '
        f'<span class="unit-tag">{escape(str(badge_text))}</span></h2>'
    )


def _build_remote_account_list_rows_with_edit(section, edit_result=None):
    row_items = []
    for row_index, row in enumerate(section.get("rows") or [], start=1):
        inventory_cell, balance_cell, status_cell, action_cell = _render_remote_inline_edit_cells(
            section,
            row,
            row_index,
            edit_result=edit_result,
        )
        row_items.append(
            (
                _format_value(row.get("nickname")),
                inventory_cell,
                balance_cell,
                _render_remote_countdown_cell(row, "runtime_window_remaining_seconds"),
                _render_remote_countdown_cell(row, "cooldown_remaining_seconds"),
                status_cell,
                _format_value(row.get("updated_at")),
                action_cell,
            )
        )
    return row_items


def _render_remote_machine_section(section, edit_result=None, refresh_result=None):
    rows = section.get("rows") or []
    row_items = _build_remote_account_list_rows_with_edit(section, edit_result=edit_result)
    empty_html = ""
    if not rows:
        empty_html = f'<p class="muted-text">{escape(str(section.get("message") or "暂无远端镜像数据。"))}</p>'
    elif section.get("allow_remote_writeback"):
        empty_html = (
            '<p class="muted-text">此板块显示的是远端镜像；提交后会转发到对端本机 canonical 真源，'
            '成功后立即刷新当前镜像显示。</p>'
        )
    else:
        empty_html = f'<p class="muted-text">{escape(str(section.get("message") or "当前仅展示远端镜像。"))}</p>'

    return f"""
<div class="section">
  {_render_machine_section_title(section.get("machine_display_name") or section.get("machine_id") or "远端机器", "远端镜像 / 最小写回")}
  {_render_remote_refresh_toolbar(section, refresh_result)}
  {empty_html}
  {_render_table(("昵称", "道具库存", "余额（万）", "可运行时间", "冷却剩余时间", "账号状态", "最后更新时间", "远端提交"), row_items)}
</div>
"""


def render_index_page(
    view_rows_result,
    runtime_result,
    remote_machine_sections=None,
    edit_result=None,
    refresh_result=None,
):
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
    local_role_label = view_rows_result.get("data_role_label") or "本机真实数据"
    remote_machine_sections = list(remote_machine_sections or [])
    remote_sections_html = "".join(
        _render_remote_machine_section(section, edit_result=edit_result, refresh_result=refresh_result)
        for section in remote_machine_sections
    )

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
  {_render_machine_section_title(local_machine_display_name, local_role_label)}
  <p class="muted-text">此板块对应本机 SQLite canonical 主表，是当前页面唯一可编辑的真实数据区。</p>
  {demo_notice_html}
  {_render_table(("执行位", "昵称", "道具库存", "余额（万）", "可运行时间", "账号状态", "允许抢购", "冷却剩余时间", "详情保存"), row_items, column_classes=account_table_column_classes, table_class="account-table")}
</div>

{remote_sections_html}
{_render_remote_countdown_script() if remote_machine_sections else ""}

<div class="section">
  <h2>本机数据健康摘要</h2>
  {_render_health_summary(health)}
</div>

<div class="section">
  <h2>本机执行位覆盖情况</h2>
  <p>这里只统计本机 canonical 主库，不混入远端同步镜像。</p>
  {_render_execution_slot_summary(execution_slot_summary)}
</div>

<div class="section">
  <h2>本机辅助快照摘要</h2>
  {_render_kv_table(runtime_items)}
</div>

<div class="section">
  <h2>本机重复执行位</h2>
  {_render_table(("执行位", "昵称列表"), duplicate_rows)}
</div>

<div class="section">
  <h2>本机关键字段缺失</h2>
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
        ("账号状态", record.get("round_status")),
        ("余额（万）", _format_balance_wan_display(record.get("current_balance_wan"))),
        ("余额原始存储", record.get("current_balance")),
        ("道具库存", record.get("baseline_item_count")),
        ("最后入库/更新时间", record.get("updated_at_relative")),
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
  <p>这里只展示本机主库记录本身的完整性和可读性摘要，不写回任何额外数据。</p>
  {_render_kv_table(record_health_items)}
</div>

<div class="section">
  <h2>与辅助快照的一致性摘要</h2>
  <p>辅助快照仅做辅助对照，以下结果用于观察当前快照与主库详情是否一致。</p>
  {_render_runtime_consistency_summary(runtime_result, runtime_consistency)}
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
{_render_read_only_notice()}
{_render_source_notice()}
<div class="section">
  <p>{escape(message)}</p>
  <p><a href="{escape(back_href, quote=True)}">{escape(back_label)}</a></p>
</div>
{detail_html}
"""
    return _base_page(title, body_html)
