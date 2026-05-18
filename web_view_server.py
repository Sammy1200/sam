"""最小 SQLite 网页查看服务。"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from urllib.parse import parse_qs, urlencode, urlparse

from account_view_repo import (
    get_account_view_detail,
    get_account_view_rows,
    get_runtime_snapshot,
    update_account_view_record,
)
from account_db import normalize_account_db_mode
from config import (
    WEB_VIEW_HOST,
    WEB_VIEW_PORT,
    WEB_VIEW_PORT_FALLBACK_END,
    WEB_VIEW_PORT_FALLBACK_START,
    WEB_VIEW_SERVER_PORT_FILE,
)
from machine_sync_config import resolve_web_bind_host
from remote_sync import (
    get_remote_machine_sections,
    handle_remote_snapshot_request,
    handle_remote_sync_report_payload,
    refresh_remote_machine_snapshot,
)
from round_persistence import mature_all_stone_unlocks
from web_view_templates_inventory import (
    render_account_detail_page,
    render_index_page,
    render_message_page,
    render_more_info_page,
    render_public_snapshot_page,
)


PORT = WEB_VIEW_PORT


def _iter_web_view_candidate_ports(preferred_port):
    ports = []

    def add_port(value):
        try:
            port = int(value)
        except (TypeError, ValueError):
            return
        if 1 <= port <= 65535 and port not in ports:
            ports.append(port)

    add_port(preferred_port)
    for fallback_port in range(WEB_VIEW_PORT_FALLBACK_START, WEB_VIEW_PORT_FALLBACK_END + 1):
        add_port(fallback_port)
    return ports


def _write_web_view_bound_port(port):
    try:
        os.makedirs(os.path.dirname(WEB_VIEW_SERVER_PORT_FILE), exist_ok=True)
        with open(WEB_VIEW_SERVER_PORT_FILE, "w", encoding="utf-8") as file:
            file.write(str(int(port)))
    except Exception:
        pass


class ReadOnlyViewHandler(BaseHTTPRequestHandler):
    @staticmethod
    def _parse_scroll_value(raw_value):
        text = str(raw_value or "").strip()
        if not text:
            return None
        try:
            value = int(text)
        except (TypeError, ValueError):
            return None
        return max(0, value)

    @staticmethod
    def _parse_db_mode(query_or_form):
        return normalize_account_db_mode(((query_or_form.get("db") or query_or_form.get("db_mode") or ["stone"])[0] or "stone"))

    @staticmethod
    def _build_local_flash_edit_result(query):
        status = str(((query.get("flash_status") or [""])[0] or "")).strip().lower()
        scope = str(((query.get("flash_scope") or [""])[0] or "")).strip().lower()
        nickname = str(((query.get("flash_nickname") or [""])[0] or "")).strip()
        if status != "success" or scope != "local" or not nickname:
            return None
        result = {
            "status": "success",
            "message": "保存成功，已完成写库并回读确认。",
            "scope": "local",
            "form_values": {
                "nickname": nickname,
            },
            "field_errors": {},
        }
        scroll_x = ReadOnlyViewHandler._parse_scroll_value((query.get("flash_scroll_x") or [""])[0])
        scroll_y = ReadOnlyViewHandler._parse_scroll_value((query.get("flash_scroll_y") or [""])[0])
        if scroll_x is not None:
            result["scroll_x"] = scroll_x
        if scroll_y is not None:
            result["scroll_y"] = scroll_y
        return result

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path == "/":
                self._handle_index(query)
                return
            if path == "/public-snapshot":
                self._handle_public_snapshot(query=query)
                return
            if path == "/more-info":
                self._handle_more_info(query)
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
            if path == "/public-snapshot/refresh":
                self._handle_public_snapshot_refresh()
                return
            if path == "/remote-account/update":
                self._send_read_only_html("公网只开放查看与刷新，不开放远端修改。")
                return
            if path == "/remote-sync/refresh":
                self._handle_remote_sync_refresh()
                return
            if path == "/remote-sync/report":
                self._handle_remote_sync_report()
                return
            if path == "/remote-sync/snapshot":
                self._handle_remote_sync_snapshot()
                return
            if path == "/remote-sync/writeback":
                self._send_json(
                    {
                        "status": "forbidden",
                        "message": "公网只开放查看与刷新，不开放其他修改。",
                    },
                    status_code=403,
                )
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

    def _send_read_only_html(self, message, status_code=403):
        html = render_message_page(
            title="网页只读模式",
            message=message,
            detail_items=[
                ("当前阶段", "公网只查看与刷新"),
                ("处理结果", "本次请求未执行被关闭的写入能力"),
            ],
        )
        self._send_html(html, status_code=status_code)

    def _handle_index(self, query=None):
        query = query or {}
        db_mode = self._parse_db_mode(query)
        view_rows_result = get_account_view_rows(db_mode=db_mode)
        runtime_result = get_runtime_snapshot()
        remote_machine_sections = get_remote_machine_sections(
            exclude_machine_id=view_rows_result.get("machine_id"),
            db_mode=db_mode,
        )
        edit_result = self._build_local_flash_edit_result(parse_qs(urlparse(self.path).query))
        html = render_index_page(
            view_rows_result,
            runtime_result,
            remote_machine_sections=remote_machine_sections,
            edit_result=edit_result,
            refresh_result=None,
            read_only_mode=False,
        )
        self._send_html(html)

    def _handle_public_snapshot(self, refresh_result=None, query=None):
        query = query or {}
        db_mode = self._parse_db_mode(query)
        view_rows_result = get_account_view_rows(db_mode=db_mode)
        remote_machine_sections = get_remote_machine_sections(
            exclude_machine_id=view_rows_result.get("machine_id"),
            db_mode=db_mode,
        )
        html = render_public_snapshot_page(
            view_rows_result,
            remote_machine_sections=remote_machine_sections,
            refresh_result=refresh_result,
        )
        self._send_html(html)

    def _handle_more_info(self, query=None):
        query = query or {}
        db_mode = self._parse_db_mode(query)
        view_rows_result = get_account_view_rows(db_mode=db_mode)
        runtime_result = get_runtime_snapshot()
        html = render_more_info_page(view_rows_result, runtime_result)
        self._send_html(html)

    def _handle_account(self, query):
        nickname = ((query.get("nickname") or [""])[0] or "").strip()
        execution_slot_raw = ((query.get("execution_slot") or [""])[0] or "").strip()
        db_mode = self._parse_db_mode(query)

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
                db_mode=db_mode,
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

        html = render_account_detail_page(
            detail_result,
            runtime_result,
            edit_result=None,
            read_only_mode=True,
        )
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
        locked_item_count = ((form.get("locked_item_count") or [""])[0] or "").strip()
        tradable_item_count = ((form.get("tradable_item_count") or [""])[0] or "").strip()
        round_status = ((form.get("round_status") or [""])[0] or "").strip()
        current_balance_wan = ((form.get("current_balance_wan") or [""])[0] or "").strip()
        db_mode = self._parse_db_mode(form)
        return_to = ((form.get("return_to") or ["detail"])[0] or "detail").strip().lower()
        scroll_x = self._parse_scroll_value((form.get("scroll_x") or [""])[0])
        scroll_y = self._parse_scroll_value((form.get("scroll_y") or [""])[0])

        update_result = update_account_view_record(
            nickname=nickname,
            baseline_item_delta_text=baseline_item_delta,
            baseline_item_count_text=baseline_item_count,
            round_status=round_status,
            balance_wan_text=current_balance_wan,
            baseline_update_mode=return_to,
            db_mode=db_mode,
            locked_item_count_text=locked_item_count,
            tradable_item_count_text=tradable_item_count,
        )
        update_result["scope"] = "local"
        status_code = 200 if update_result.get("status") == "success" else 400

        if update_result.get("status") == "success":
            redirect_payload = {
                "flash_status": "success",
                "flash_scope": "local",
                "flash_nickname": nickname,
                "db": db_mode,
            }
            if scroll_x is not None:
                redirect_payload["flash_scroll_x"] = str(scroll_x)
            if scroll_y is not None:
                redirect_payload["flash_scroll_y"] = str(scroll_y)
            redirect_query = urlencode(redirect_payload)
            self._send_redirect(f"/?{redirect_query}")
            return

        if scroll_x is not None:
            update_result["scroll_x"] = scroll_x
        if scroll_y is not None:
            update_result["scroll_y"] = scroll_y

        view_rows_result = get_account_view_rows(db_mode=db_mode)
        runtime_result = get_runtime_snapshot()
        remote_machine_sections = get_remote_machine_sections(
            exclude_machine_id=view_rows_result.get("machine_id"),
            db_mode=db_mode,
        )
        html = render_index_page(
            view_rows_result,
            runtime_result,
            remote_machine_sections=remote_machine_sections,
            edit_result=update_result,
            refresh_result=None,
            read_only_mode=False,
        )
        self._send_html(html, status_code=status_code)

    def _handle_remote_sync_refresh(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        raw_body = self.rfile.read(content_length) if content_length > 0 else b""
        form = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)
        target_machine_id = ((form.get("target_machine_id") or [""])[0] or "").strip()
        db_mode = self._parse_db_mode(form)

        refresh_result = refresh_remote_machine_snapshot(machine_id=target_machine_id, db_mode=db_mode)
        refresh_result["scope"] = "remote_refresh"
        refresh_result["target_machine_id"] = target_machine_id
        refresh_result["db_mode"] = db_mode
        status = str(refresh_result.get("status") or "").strip()
        if status == "success":
            status_code = 200
        elif status == "forbidden":
            status_code = 403
        else:
            status_code = 400

        view_rows_result = get_account_view_rows(db_mode=db_mode)
        runtime_result = get_runtime_snapshot()
        remote_machine_sections = get_remote_machine_sections(
            exclude_machine_id=view_rows_result.get("machine_id"),
            db_mode=db_mode,
        )
        html = render_index_page(
            view_rows_result,
            runtime_result,
            remote_machine_sections=remote_machine_sections,
            edit_result=None,
            refresh_result=refresh_result,
            read_only_mode=False,
        )
        self._send_html(html, status_code=status_code)

    def _handle_public_snapshot_refresh(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        raw_body = self.rfile.read(content_length) if content_length > 0 else b""
        form = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)
        target_scope = ((form.get("target_scope") or [""])[0] or "").strip().lower()
        target_machine_id = ((form.get("target_machine_id") or [""])[0] or "").strip()
        db_mode = self._parse_db_mode(form)

        if target_scope == "local":
            mature_result = None
            refresh_result = {
                "status": "success",
                "scope": "public_local_refresh",
                "db_mode": db_mode,
                "message": "已刷新 1号快照显示。",
            }
            if normalize_account_db_mode(db_mode) == "stone":
                mature_result = mature_all_stone_unlocks("公网快照页本机刷新")
                refresh_result["message"] = f"已刷新 1号快照显示，到期结转 {mature_result.changed_quantity} 个。"
                if mature_result.status not in ("success", "skipped"):
                    refresh_result["status"] = "error"
                    refresh_result["message"] = f"刷新前全账号结转异常：{mature_result.reason}"
            self._handle_public_snapshot(refresh_result=refresh_result, query={"db": [db_mode]})
            return

        if target_scope == "remote":
            refresh_result = refresh_remote_machine_snapshot(machine_id=target_machine_id, db_mode=db_mode)
            refresh_result["scope"] = "remote_refresh"
            refresh_result["target_machine_id"] = target_machine_id
            refresh_result["db_mode"] = db_mode
            status = str(refresh_result.get("status") or "").strip()
            if status == "success":
                self._handle_public_snapshot(refresh_result=refresh_result, query={"db": [db_mode]})
                return
            view_rows_result = get_account_view_rows(db_mode=db_mode)
            remote_machine_sections = get_remote_machine_sections(
                exclude_machine_id=view_rows_result.get("machine_id"),
                db_mode=db_mode,
            )
            html = render_public_snapshot_page(
                view_rows_result,
                remote_machine_sections=remote_machine_sections,
                refresh_result=refresh_result,
            )
            self._send_html(html, status_code=403 if status == "forbidden" else 400)
            return

        self._send_read_only_html("公网快照页刷新请求缺少合法目标。", status_code=400)

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

    def _handle_remote_sync_snapshot(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        raw_body = self.rfile.read(content_length) if content_length > 0 else b""
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except json.JSONDecodeError:
            payload = {}
        db_mode = normalize_account_db_mode(payload.get("db_mode"))
        result = handle_remote_snapshot_request(
            client_ip=self.client_address[0] if self.client_address else "",
            db_mode=db_mode,
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

    def _send_redirect(self, location, status_code=303):
        self.send_response(status_code)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()


def run_server(host=None, port=PORT):
    bind_host = host or resolve_web_bind_host() or WEB_VIEW_HOST
    server = None
    actual_host = bind_host
    actual_port = port
    last_error = None

    for candidate_port in _iter_web_view_candidate_ports(port):
        candidate_hosts = [bind_host]
        if bind_host != WEB_VIEW_HOST:
            candidate_hosts.append(WEB_VIEW_HOST)
        for candidate_host in candidate_hosts:
            try:
                server = ThreadingHTTPServer((candidate_host, candidate_port), ReadOnlyViewHandler)
                actual_host = candidate_host
                actual_port = candidate_port
                break
            except OSError as exc:
                last_error = exc
                print(f"[网页查看页] 绑定 {candidate_host}:{candidate_port} 失败：{exc}")
        if server is not None:
            break

    if server is None:
        if last_error is not None:
            raise last_error
        raise OSError("网页服务没有可用端口")

    _write_web_view_bound_port(actual_port)
    print(f"[网页查看页] 服务已启动：bind={actual_host} local=http://127.0.0.1:{actual_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[网页查看页] 收到中断，准备关闭服务。")
    finally:
        server.server_close()
        print("[网页查看页] 服务已关闭。")


if __name__ == "__main__":
    run_server()
