"""最小网页只读展示模板。"""
from __future__ import annotations

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
  <strong>当前页面为只读查看页：</strong>
  仅支持 GET 查看，不提供编辑、写入、提交或自动刷新能力。
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


def _base_page(title, body_html):
    style = """
    body { font-family: "Microsoft YaHei", sans-serif; margin: 24px; color: #1f2328; background: #f7f8fa; }
    h1, h2 { margin: 0 0 12px 0; }
    .section { background: #fff; border: 1px solid #d0d7de; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
    .meta { color: #59636e; margin-bottom: 12px; }
    .readonly-notice { background: #ddf4ff; border: 1px solid #54aeff; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; line-height: 1.6; }
    .notice { background: #fff8c5; border: 1px solid #d4a72c; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; line-height: 1.6; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border: 1px solid #d8dee4; padding: 8px 10px; text-align: left; vertical-align: top; }
    th { background: #f3f4f6; }
    a { color: #0969da; text-decoration: none; }
    a:hover { text-decoration: underline; }
    code { background: #f0f2f4; padding: 1px 4px; border-radius: 4px; }
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

    row_items = []
    for row in rows:
        nickname = row.get("nickname")
        slot = row.get("current_execution_slot")
        detail_url = f"/account?nickname={nickname}" if nickname else f"/account?execution_slot={slot}"
        row_items.append(
            (
                _format_value(slot),
                _format_value(nickname),
                _format_value(row.get("round_status")),
                _format_value(row.get("current_balance")),
                _format_value(row.get("updated_at")),
                _format_value(row.get("allow_purchase")),
                f"<a href=\"{escape(detail_url, quote=True)}\">查看详情</a>",
            )
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

    body_html = f"""
<h1>SQLite 只读查看层</h1>
{_render_read_only_notice()}
{_render_source_notice(source_summary)}
<div class="meta">
  canonical 库：<code>{escape(str(view_rows_result.get("database_path") or ""))}</code><br>
  生成时间：{_format_value(view_rows_result.get("generated_at"))}
</div>

<div class="section">
  <h2>Health 体检摘要</h2>
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

<div class="section">
  <h2>账号列表</h2>
  {_render_table(("执行位", "昵称", "状态", "余额", "更新时间", "允许抢购", "详情"), row_items)}
</div>
"""
    return _base_page("SQLite 只读查看层", body_html)


def render_account_detail_page(detail_result, runtime_result):
    record = detail_result.get("record")
    health = detail_result.get("health") or {}
    lookup = detail_result.get("lookup") or {}
    source_summary = detail_result.get("source_summary") or {}

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
        ("余额", record.get("current_balance")),
        ("基线数量", record.get("baseline_item_count")),
        ("抢购成功数", record.get("round_purchase_success_count")),
        ("上架成功数", record.get("round_listing_success_count")),
        ("抢购失败数", record.get("round_purchase_fail_count")),
        ("本轮运行秒数", record.get("purchase_running_seconds")),
        ("最后限制时间", record.get("last_limit_time")),
        ("最后下号时间", record.get("last_account_end_time")),
        ("更新时间", record.get("updated_at")),
    ]
    derived_items = [
        ("允许开始时间", record.get("allow_start_time")),
        ("当前可抢购", record.get("allow_purchase")),
        ("冷却剩余秒数", record.get("cooldown_remaining_seconds")),
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
{_render_read_only_notice()}
{_render_source_notice(source_summary)}
<div class="meta">
  canonical 库：<code>{escape(str(detail_result.get("database_path") or ""))}</code><br>
  查询条件：nickname={_format_value(lookup.get("nickname"))}，
  execution_slot={_format_value(lookup.get("execution_slot"))}
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
  <h2>当前记录 Health</h2>
  <p>这里只展示当前 canonical 记录本身的完整性和可读性摘要，不写回任何数据。</p>
  {_render_kv_table(record_health_items)}
</div>

<div class="section">
  <h2>与 Runtime 的一致性摘要</h2>
  <p>runtime 仅做辅助对照，以下结果用于观察当前快照与 canonical 详情是否一致。</p>
  {_render_runtime_consistency_summary(runtime_result, runtime_consistency)}
</div>
"""
    return _base_page(f"账号详情 - {record.get('nickname')}", body_html)
