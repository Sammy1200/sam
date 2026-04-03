"""库存实时语义覆盖模板。"""
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


def _render_read_only_notice():
    return """
<div class="readonly-notice">
  <strong>当前页面以查看为主：</strong>
  首页支持直接编辑“道具库存”，详情页也直接对应底层 <code>baseline_item_count</code>。
  页面不再展示旧的推算库存口径，也不再提供“基数增减”入口。
</div>
"""


def _render_edit_notice():
    return """
<div class="edit-notice">
  <strong>当前详情页支持最小编辑：</strong>
  仅允许修改 3 个字段：道具库存、账号状态、余额（万）。
  提交后会直接写入 canonical SQLite，并执行回读确认。
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
      <small>必须为整数；提交时直接写入底层 <code>baseline_item_count</code>，不再按旧公式反推。</small>
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
      <small>页面输入和展示都按“万”为单位；提交时会按 canonical 当前存储口径写入。</small>
      {_render_field_error(field_errors, "current_balance_wan")}
    </label>
    <div class="form-actions">
      <button type="submit">保存这 3 个字段</button>
    </div>
  </form>
</div>
"""


def _build_account_list_rows(rows, edit_meta=None, edit_result=None):
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
            status_cell = _format_value(row.get("round_status"))
            action_cell = '<span class="muted-text">演示数据，不可操作</span>'
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
                _format_value(nickname),
                inventory_cell,
                balance_cell,
                status_cell,
                _format_value(row.get("allow_purchase")),
                _format_cooldown_remaining_time(row.get("cooldown_remaining_seconds")),
                action_cell,
            )
        )
    return row_items, using_demo_rows


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
<h1>SQLite 查看页</h1>
{_render_read_only_notice()}
{_render_edit_result(edit_result)}
{_render_source_notice(source_summary)}
{_render_source_diagnostics(source_diagnostics)}
<div class="meta">
  canonical 库：<code>{escape(str(view_rows_result.get("database_path") or ""))}</code><br>
  生成时间：{_format_value(view_rows_result.get("generated_at"))}
</div>

<div class="section">
  <h2>账号列表</h2>
  {demo_notice_html}
  {_render_table(("执行位", "昵称", "道具库存", "余额（万）", "账号状态", "允许抢购", "冷却剩余时间", "详情保存"), row_items)}
</div>

<div class="section">
  <h2>Health 摘要</h2>
  {_render_health_summary(health)}
</div>

<div class="section">
  <h2>execution_slot 覆盖情况</h2>
  <p>首页明确展示 canonical 视角下已覆盖与缺失的执行位，便于快速判断槽位是否齐全。</p>
  {_render_execution_slot_summary(execution_slot_summary)}
</div>

<div class="section">
  <h2>Runtime 辅助快照摘要</h2>
  {_render_kv_table(runtime_items)}
</div>

<div class="section">
  <h2>重复 execution_slot</h2>
  {_render_table(("执行位", "昵称列表"), duplicate_rows)}
</div>

<div class="section">
  <h2>关键字段缺失</h2>
  {_render_table(("昵称", "执行位", "缺失字段"), missing_rows)}
</div>
"""
    return _base_page("SQLite 查看页", body_html)


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
  查询条件：nickname={_format_value(lookup.get("nickname"))}，
  execution_slot={_format_value(lookup.get("execution_slot"))}
</div>
<div class="section">
  <p>未根据当前查询条件找到对应账号记录。</p>
  <p>请返回首页重新选择，或确认 nickname / execution_slot 是否填写正确。</p>
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
        ("冷却剩余时间", _format_cooldown_remaining_time(record.get("cooldown_remaining_seconds"))),
    ]

    record_health_items = [
        ("存在关键字段缺失", health.get("has_missing_critical_fields")),
        ("缺失字段", health.get("missing_critical_fields")),
        ("canonical 更新时间", record.get("updated_at")),
        ("runtime 快照存在", runtime_result.get("database_exists")),
    ]

    runtime_consistency = health.get("runtime_consistency") or {}

    body_html = f"""
<h1>账号详情</h1>
{_render_edit_notice()}
{_render_edit_result(edit_result)}
{_render_source_notice(source_summary)}
<div class="meta">
  canonical 库：<code>{escape(str(detail_result.get("database_path") or ""))}</code><br>
  查询条件：nickname={_format_value(lookup.get("nickname"))}，
  execution_slot={_format_value(lookup.get("execution_slot"))}
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
  <h2>当前记录 Health</h2>
  <p>这里只展示当前 canonical 记录本身的完整性和可读性摘要，不写回任何额外数据。</p>
  {_render_kv_table(record_health_items)}
</div>

<div class="section">
  <h2>与 Runtime 的一致性摘要</h2>
  <p>runtime 仅做辅助对照，以下结果用于观察当前快照与 canonical 详情是否一致。</p>
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
