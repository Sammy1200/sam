"""最小 SQLite 只读网页服务。"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from account_view_repo import (
    get_account_view_detail,
    get_account_view_rows,
    get_runtime_snapshot,
)
from web_view_templates import render_account_detail_page, render_index_page


HOST = "127.0.0.1"
PORT = 8091


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
            print(f"[网页查看层] 请求处理失败：path={path} error={exc}")
            self._send_html(
                f"<h1>500</h1><p>页面渲染失败：{exc}</p>",
                status_code=500,
            )

    def log_message(self, fmt, *args):
        message = fmt % args
        print(f"[网页查看层] {self.address_string()} - {message}")

    def _handle_index(self):
        view_rows_result = get_account_view_rows()
        runtime_result = get_runtime_snapshot()
        html = render_index_page(view_rows_result, runtime_result)
        self._send_html(html)

    def _handle_account(self, query):
        nickname = (query.get("nickname") or [""])[0]
        execution_slot_raw = (query.get("execution_slot") or [""])[0]
        try:
            execution_slot = int(execution_slot_raw) if execution_slot_raw.strip() else None
        except ValueError:
            execution_slot = None

        detail_result = get_account_view_detail(
            nickname=nickname,
            execution_slot=execution_slot,
        )
        runtime_result = get_runtime_snapshot()
        html = render_account_detail_page(detail_result, runtime_result)
        self._send_html(html)

    def _send_html(self, html, status_code=200):
        body = html.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(host=HOST, port=PORT):
    server = ThreadingHTTPServer((host, port), ReadOnlyViewHandler)
    print(f"[网页查看层] 只读服务已启动：http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[网页查看层] 收到中断，准备关闭服务。")
    finally:
        server.server_close()
        print("[网页查看层] 服务已关闭。")


if __name__ == "__main__":
    run_server()
