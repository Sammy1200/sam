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


def _render_table(headers, rows):
    header_html = "".join(f"<th>{escape(str(header))}</th>" for header in headers)
    body_parts = []
    for row in rows:
        cell_html = "".join(f"<td>{cell}</td>" for cell in row)
        body_parts.append(f"<tr>{cell_html}</tr>")
    body_html = "".join(body_parts) if body_parts else (
        f"<tr><td colspan=\"{len(headers)}\">暂无数据</td></tr>"
    )
    return (
        "<table>"
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{body_html}</tbody>"
        "</table>"
    )


def _render_kv_table(items):
    rows = []
    for key, value in items:
        rows.append((escape(str(key)), _format_value(value)))
    return _render_table(("字段", "值"), rows)


def _render_health_summary(health):
    items = [
        ("存在重复 execution_slot", health.get("has_duplicate_execution_slots")),
        ("存在缺失 execution_slot", health.get("has_missing_execution_slots")),
        ("存在关键字段缺失", health.get("has_missing_critical_fields")),
        ("runtime 快照存在", health.get("runtime_snapshot_exists")),
        ("runtime 命中 canonical", health.get("runtime_matched_canonical_record")),
    ]
    if "runtime_consistency" in health:
        runtime_consistency = health.get("runtime_consistency") or {}
        items.extend(
            [
                ("runtime 明显滞后", runtime_consistency.get("runtime_is_stale")),
                ("runtime 与 canonical 一致", runtime_consistency.get("runtime_matches_canonical")),
                ("runtime 不一致字段", runtime_consistency.get("runtime_mismatch_fields")),
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
  canonical SQLite（表：<code>{escape(str(canonical_table_name))}</code>）是主数据源；
  runtime 仅为辅助快照，只用于一致性对照，不参与主展示口径。
  <br>
  canonical 库：<code>{canonical_database_path or "-"}</code>
  <br>
  runtime 库：<code>{runtime_database_path or "-"}</code>（存在：{runtime_database_exists}）
</div>
"""


def _render_read_only_notice():
    return """
<div class="readonly-notice">
  <strong>当前页面以只读查看为主：</strong>
  首页仍只支持 GET 查看；账号详情页仅新增“单账号最小编辑”，只允许修改道具数量、账号状态和余额（万）。
</div>
"""


def _render_edit_notice():
    return """
<div class="edit-notice">
  <strong>当前详情页支持最小编辑：</strong>
  仅允许修改 3 个字段：道具数量、账号状态、余额（万）。
  不支持批量编辑，不支持自动刷新，也不会改动 runtime 逻辑。
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
            "round_status": "正常结束",
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
        ("expected_execution_slots", summary.get("expected_execution_slots")),
        ("expected_execution_slot_count", summary.get("expected_execution_slot_count")),
        ("present_execution_slots", summary.get("present_execution_slots")),
        ("present_execution_slot_count", summary.get("present_execution_slot_count")),
        ("missing_execution_slots", summary.get("missing_execution_slots")),
        ("missing_execution_slot_count", summary.get("missing_execution_slot_count")),
    ]
    return _render_kv_table(items)


def _render_runtime_consistency_summary(runtime_result, runtime_consistency):
    runtime_snapshot = runtime_result.get("snapshot") or {}
    items = [
        ("runtime 快照存在", runtime_result.get("database_exists")),
        ("runtime 当前执行位", runtime_snapshot.get("current_execution_slot")),
        ("runtime 当前昵称", runtime_snapshot.get("current_nickname")),
        ("runtime 快照更新时间", runtime_snapshot.get("updated_at")),
        ("runtime 明显滞后", runtime_consistency.get("runtime_is_stale")),
        ("runtime 滞后秒数", runtime_consistency.get("runtime_lag_seconds")),
        ("runtime 与 canonical 一致", runtime_consistency.get("runtime_matches_canonical")),
        ("runtime 不一致字段", runtime_consistency.get("runtime_mismatch_fields")),
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
  <p>字段映射：道具数量 → <code>{escape(str(column_mapping.get("item_quantity") or "-"))}</code>，
  账号状态 → <code>{escape(str(column_mapping.get("round_status") or "-"))}</code>，
  余额（{escape(balance_input_unit)}） → <code>{escape(str(column_mapping.get("current_balance_wan") or "-"))}</code>。</p>
  <form method="post" action="/account/update" class="edit-form">
    <input type="hidden" name="nickname" value="{escape(str(record.get("nickname") or ""), quote=True)}">
    <label>
      <span>道具数量</span>
      <input type="number" name="item_quantity" step="1" min="0" required value="{escape(str(form_values.get('item_quantity') or ''), quote=True)}">
      <small>必须为整数；提交时会换算写入底层 <code>baseline_item_count</code>。</small>
      {_render_field_error(field_errors, "item_quantity")}
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


def _build_account_list_rows(rows):
    using_demo_rows = not bool(rows)
    effective_rows = rows if rows else _build_demo_account_rows()

    row_items = []
    for row in effective_rows:
        nickname = row.get("nickname")
        slot = row.get("current_execution_slot")
        if using_demo_rows:
            detail_cell = '<span class="muted-text">演示数据，不可查看/不可编辑</span>'
        else:
            detail_url = f"/account?nickname={nickname}" if nickname else f"/account?execution_slot={slot}"
            detail_cell = f"<a href=\"{escape(detail_url, quote=True)}\">查看详情</a>"
        row_items.append(
            (
                _format_value(slot),
                _format_value(nickname),
                _format_value(row.get("round_status")),
                _format_value(row.get("item_quantity")),
                _format_balance_wan_display(row.get("current_balance_wan")),
                _format_value(row.get("allow_purchase")),
                _format_cooldown_remaining_time(row.get("cooldown_remaining_seconds")),
                detail_cell,
            )
        )
    return row_items, using_demo_rows


def _base_page(title, body_html):
    style = """
    body { font-family: "Microsoft YaHei", sans-serif; margin: 24px; color: #1f2328; background: #f7f8fa; }
    h1, h2 { margin: 0 0 12px 0; }
    .section { background: #fff; border: 1px solid #d0d7de; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
    .meta { color: #59636e; margin-bottom: 12px; }
    .readonly-notice, .edit-notice, .notice, .flash-success, .flash-error { border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; line-height: 1.6; }
    .readonly-notice { background: #ddf4ff; border: 1px solid #54aeff; }
    .edit-notice { background: #dafbe1; border: 1px solid #4ac26b; }
    .notice { background: #fff8c5; border: 1px solid #d4a72c; }
    .flash-success { background: #dafbe1; border: 1px solid #4ac26b; }
    .flash-error { background: #ffebe9; border: 1px solid #ff8182; }
    .field-error-block { margin-top: 12px; }
    .field-error { color: #cf222e; margin-top: 6px; font-size: 13px; }
    .muted-text { color: #59636e; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border: 1px solid #d8dee4; padding: 8px 10px; text-align: left; vertical-align: top; }
    th { background: #f3f4f6; }
    a { color: #0969da; text-decoration: none; }
    a:hover { text-decoration: underline; }
    code { background: #f0f2f4; padding: 1px 4px; border-radius: 4px; }
    .edit-form { display: grid; gap: 14px; }
    .edit-form label { display: grid; gap: 6px; }
    .edit-form span { font-weight: 600; }
    .edit-form small { color: #59636e; }
    .edit-form input, .edit-form select, .edit-form button { font: inherit; }
    .edit-form input, .edit-form select { padding: 8px 10px; border: 1px solid #d0d7de; border-radius: 6px; background: #fff; }
    .input-with-unit { display: flex; align-items: center; gap: 8px; }
    .input-with-unit input { flex: 1; }
    .unit-tag { background: #f3f4f6; border: 1px solid #d0d7de; border-radius: 999px; padding: 6px 10px; font-weight: 600; }
    .form-actions button { padding: 10px 14px; border: 1px solid #1f6feb; border-radius: 6px; background: #1f6feb; color: #fff; cursor: pointer; }
    .form-actions button:hover { background: #1759b8; }
    @media (max-width: 760px) {
      body { margin: 12px; }
      .section { padding: 12px; }
      .input-with-unit { flex-direction: column; align-items: stretch; }
      .unit-tag { align-self: flex-start; }
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


def render_index_page(view_rows_result, runtime_result):
    rows = view_rows_result.get("rows") or []
    health = view_rows_result.get("health") or {}
    source_summary = view_rows_result.get("source_summary") or {}
    execution_slot_summary = view_rows_result.get("execution_slot_summary") or {}
    runtime_snapshot = runtime_result.get("snapshot") or {}
    row_items, using_demo_rows = _build_account_list_rows(rows)

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
{_render_source_notice(source_summary)}
<div class="meta">
  canonical 库：<code>{escape(str(view_rows_result.get("database_path") or ""))}</code><br>
  生成时间：{_format_value(view_rows_result.get("generated_at"))}
</div>

<div class="section">
  <h2>账号列表</h2>
  {demo_notice_html}
  {_render_table(("执行位", "昵称", "状态", "道具数量", "余额（万）", "允许抢购", "冷却剩余时间", "详情"), row_items)}
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
        ("状态", record.get("round_status")),
        ("余额（万）", _format_balance_wan_display(record.get("current_balance_wan"))),
        ("余额原始存储", record.get("current_balance")),
        ("道具数量（推算）", record.get("item_quantity")),
        ("baseline_item_count", record.get("baseline_item_count")),
        ("本轮抢购成功数", record.get("round_purchase_success_count")),
        ("本轮上架成功数", record.get("round_listing_success_count")),
        ("本轮抢购失败数", record.get("round_purchase_fail_count")),
        ("本轮运行秒数", record.get("purchase_running_seconds")),
        ("最后限制时间", record.get("last_limit_time")),
        ("最后下号时间", record.get("last_account_end_time")),
        ("更新时间", record.get("updated_at")),
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
