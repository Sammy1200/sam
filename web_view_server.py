"""最小 SQLite 网页查看服务。"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import parse_qs, urlparse

from config import WEB_VIEW_HOST, WEB_VIEW_PORT
from account_view_repo import (
    get_account_view_detail,
    get_account_view_rows,
    get_runtime_snapshot,
    update_account_view_record,
)
from machine_sync_config import resolve_web_bind_host
from remote_sync import (
    get_remote_machine_sections,
    handle_remote_sync_report_payload,
    handle_remote_writeback_payload,
    submit_remote_account_update,
)
from web_view_templates_inventory import (
    render_account_detail_page,
    render_index_page,
    render_message_page,
)


PORT = WEB_VIEW_PORT


class ReadOnlyViewHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path == "/":
                self._handle_index()
                return
            if path == "/account":
                self._handle_account(query)
                return
            self._send_html("<h1>404</h1><p>页面不存在。</p>", status_code=404)
        except Exception as exc:
            print(f"[网页查看页] 请求处理失败：path={path} error={exc}")
            self._send_html(
                f"<h1>500</h1><p>页面渲染失败：{exc}</p>",
                status_code=500,
            )

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            if path == "/account/update":
                self._handle_account_update()
                return
            if path == "/remote-account/update":
                self._handle_remote_account_update()
                return
            if path == "/remote-sync/report":
                self._handle_remote_sync_report()
                return
            if path == "/remote-sync/writeback":
                self._handle_remote_writeback()
                return
            self._send_html("<h1>404</h1><p>页面不存在。</p>", status_code=404)
        except Exception as exc:
            print(f"[网页查看页] 提交处理失败：path={path} error={exc}")
            self._send_html(
                f"<h1>500</h1><p>提交处理失败：{exc}</p>",
                status_code=500,
            )

    def log_message(self, fmt, *args):
        message = fmt % args
        print(f"[网页查看页] {self.address_string()} - {message}")

    def _handle_index(self):
        view_rows_result = get_account_view_rows()
        runtime_result = get_runtime_snapshot()
        remote_machine_sections = get_remote_machine_sections(
            exclude_machine_id=view_rows_result.get("machine_id"),
        )
        html = render_index_page(
            view_rows_result,
            runtime_result,
            remote_machine_sections=remote_machine_sections,
        )
        self._send_html(html)

    def _handle_account(self, query):
        nickname = ((query.get("nickname") or [""])[0] or "").strip()
        execution_slot_raw = ((query.get("execution_slot") or [""])[0] or "").strip()

        if not nickname and not execution_slot_raw:
            html = render_message_page(
                title="账号详情页",
                message="当前访问缺少必要参数，无法定位账号详情。",
                detail_items=[
                    ("访问限制", "需要通过昵称参数或执行位参数指定单个账号"),
                    ("建议访问方式", "请从首页点击“查看详情”，或在地址中传入 ?nickname=昵称 / ?execution_slot=执行位"),
                ],
            )
            self._send_html(html, status_code=400)
            return

        try:
            execution_slot = int(execution_slot_raw) if execution_slot_raw else None
        except ValueError:
            html = render_message_page(
                title="账号详情页",
                message="执行位参数格式不正确，必须是整数。",
                detail_items=[
                    ("昵称参数", nickname or None),
                    ("执行位原始值", execution_slot_raw),
                ],
            )
            self._send_html(html, status_code=400)
            return

        try:
            detail_result = get_account_view_detail(
                nickname=nickname,
                execution_slot=execution_slot,
            )
        except Exception as exc:
            print(
                f"[网页查看页] 账号详情查询失败：nickname={nickname or '-'} "
                f"execution_slot={execution_slot_raw or '-'} error={exc}"
            )
            html = render_message_page(
                title="账号详情页",
                message="账号详情查询失败，请稍后重试。",
                detail_items=[
                    ("昵称参数", nickname or None),
                    ("执行位参数", execution_slot),
                    ("错误信息", str(exc)),
                ],
            )
            self._send_html(html, status_code=500)
            return

        runtime_result = get_runtime_snapshot()
        if detail_result.get("record") is None:
            html = render_message_page(
                title="账号详情页",
                message="未找到对应账号记录，请确认查询参数后重试。",
                detail_items=[
                    ("昵称参数", nickname or None),
                    ("执行位参数", execution_slot),
                    ("提示", "建议优先从首页账号列表进入详情页"),
                ],
            )
            self._send_html(html, status_code=404)
            return

        html = render_account_detail_page(detail_result, runtime_result)
        self._send_html(html)

    def _handle_account_update(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        raw_body = self.rfile.read(content_length) if content_length > 0 else b""
        form = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)

        nickname = ((form.get("nickname") or [""])[0] or "").strip()
        baseline_item_delta = ((form.get("baseline_item_delta") or [""])[0] or "").strip()
        baseline_item_count = ((form.get("baseline_item_count") or [""])[0] or "").strip()
        round_status = ((form.get("round_status") or [""])[0] or "").strip()
        current_balance_wan = ((form.get("current_balance_wan") or [""])[0] or "").strip()
        return_to = ((form.get("return_to") or ["detail"])[0] or "detail").strip().lower()

        update_result = update_account_view_record(
            nickname=nickname,
            baseline_item_delta_text=baseline_item_delta,
            baseline_item_count_text=baseline_item_count,
            round_status=round_status,
            balance_wan_text=current_balance_wan,
            baseline_update_mode=return_to,
        )
        update_result["scope"] = "local"
        status_code = 200 if update_result.get("status") == "success" else 400

        if return_to == "index":
            view_rows_result = get_account_view_rows()
            runtime_result = get_runtime_snapshot()
            remote_machine_sections = get_remote_machine_sections(
                exclude_machine_id=view_rows_result.get("machine_id"),
            )
            html = render_index_page(
                view_rows_result,
                runtime_result,
                remote_machine_sections=remote_machine_sections,
                edit_result=update_result,
            )
            self._send_html(html, status_code=status_code)
            return

        detail_result = update_result.get("detail_result") or get_account_view_detail(nickname=nickname)
        runtime_result = get_runtime_snapshot()

        if detail_result.get("record") is None:
            html = render_message_page(
                title="账号详情页",
                message=update_result.get("message") or "账号修改失败。",
                detail_items=[
                    ("昵称参数", nickname or None),
                    ("提交的道具库存", baseline_item_count or None),
                    ("提交的账号状态", round_status or None),
                    ("提交的余额（万）", current_balance_wan or None),
                ],
            )
            self._send_html(html, status_code=400)
            return

        html = render_account_detail_page(
            detail_result,
            runtime_result,
            edit_result=update_result,
        )
        self._send_html(html, status_code=status_code)

    def _handle_remote_account_update(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        raw_body = self.rfile.read(content_length) if content_length > 0 else b""
        form = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)

        target_machine_id = ((form.get("target_machine_id") or [""])[0] or "").strip()
        nickname = ((form.get("nickname") or [""])[0] or "").strip()
        baseline_item_count = ((form.get("baseline_item_count") or [""])[0] or "").strip()
        round_status = ((form.get("round_status") or [""])[0] or "").strip()
        current_balance_wan = ((form.get("current_balance_wan") or [""])[0] or "").strip()

        update_result = submit_remote_account_update(
            target_machine_id=target_machine_id,
            nickname=nickname,
            baseline_item_count_text=baseline_item_count,
            round_status=round_status,
            balance_wan_text=current_balance_wan,
        )
        update_result["scope"] = "remote"
        status = str(update_result.get("status") or "").strip()
        if status == "success":
            status_code = 200
        elif status == "forbidden":
            status_code = 403
        else:
            status_code = 400

        view_rows_result = get_account_view_rows()
        runtime_result = get_runtime_snapshot()
        remote_machine_sections = get_remote_machine_sections(
            exclude_machine_id=view_rows_result.get("machine_id"),
        )
        html = render_index_page(
            view_rows_result,
            runtime_result,
            remote_machine_sections=remote_machine_sections,
            edit_result=update_result,
        )
        self._send_html(html, status_code=status_code)

    def _handle_remote_sync_report(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        raw_body = self.rfile.read(content_length) if content_length > 0 else b""
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except json.JSONDecodeError as exc:
            self._send_json(
                {
                    "status": "error",
                    "message": f"同步上报 JSON 解析失败：{exc}",
                },
                status_code=400,
            )
            return

        result = handle_remote_sync_report_payload(
            payload,
            client_ip=self.client_address[0] if self.client_address else "",
        )
        status = str(result.get("status") or "").strip()
        if status == "success":
            status_code = 200
        elif status == "forbidden":
            status_code = 403
        else:
            status_code = 400
        self._send_json(result, status_code=status_code)

    def _handle_remote_writeback(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        raw_body = self.rfile.read(content_length) if content_length > 0 else b""
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except json.JSONDecodeError as exc:
            self._send_json(
                {
                    "status": "error",
                    "message": f"远端写回 JSON 解析失败：{exc}",
                },
                status_code=400,
            )
            return

        result = handle_remote_writeback_payload(
            payload,
            client_ip=self.client_address[0] if self.client_address else "",
        )
        status = str(result.get("status") or "").strip()
        if status == "success":
            status_code = 200
        elif status == "forbidden":
            status_code = 403
        else:
            status_code = 400
        self._send_json(result, status_code=status_code)

    def _send_html(self, html, status_code=200):
        body = html.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload, status_code=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(host=None, port=PORT):
    bind_host = host or resolve_web_bind_host() or WEB_VIEW_HOST
    server = ThreadingHTTPServer((bind_host, port), ReadOnlyViewHandler)
    print(f"[网页查看页] 服务已启动：bind={bind_host} local=http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[网页查看页] 收到中断，准备关闭服务。")
    finally:
        server.server_close()
        print("[网页查看页] 服务已关闭。")


if __name__ == "__main__":
    run_server()
