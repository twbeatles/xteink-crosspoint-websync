"""웹 대시보드 HTTP 요청 핸들러."""
from __future__ import annotations

import json
import os
import http.cookies
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING

from websync.servers.dashboard.session import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SEC,
    session_value,
    session_valid,
    token_matches,
)
from websync.servers.dashboard.templates_loader import login_html, dashboard_html
from websync.i18n import t

if TYPE_CHECKING:
    from websync.servers.dashboard.http_server import DashboardHTTPServer


class DashboardHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    timeout = 2

    @property
    def _ctx(self) -> "DashboardHTTPServer":
        return self.server  # type: ignore[return-value]

    def log_message(self, format, *args):
        pass

    def _get_cookie(self, name: str) -> str | None:
        raw = self.headers.get("Cookie", "")
        if not raw:
            return None
        jar = http.cookies.SimpleCookie()
        jar.load(raw)
        if name in jar:
            return jar[name].value
        return None

    def _is_authenticated(self) -> bool:
        token = self._ctx.api_token
        if not token:
            return False
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and token_matches(auth[7:].strip(), token):
            return True
        session = self._get_cookie(SESSION_COOKIE_NAME)
        return session_valid(token, session)

    def _require_auth(self) -> bool:
        if self._is_authenticated():
            return True
        self._send_json(401, {"error": "Unauthorized"})
        return False

    def _send_json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def _send_html(self, html: str):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def do_GET(self):
        if self.path in ("/", "/login"):
            self._send_html(login_html())
        elif self.path in ("/dashboard",):
            if not self._require_auth():
                return
            self._send_html(dashboard_html())
        elif self.path == "/api/log":
            if not self._require_auth():
                return
            log_text = ""
            if self._ctx.get_log_callback:
                log_text = self._ctx.get_log_callback() or ""
            else:
                from websync.core.paths import PROJECT_ROOT
                log_dir = os.path.join(PROJECT_ROOT, "logs")
                if os.path.isdir(log_dir):
                    matching_files = [
                        f for f in os.listdir(log_dir)
                        if f.startswith("sync_") and f.endswith(".log")
                    ]
                    if not matching_files:
                        matching_files = os.listdir(log_dir)
                    if matching_files:
                        matching_files.sort(
                            key=lambda fname: os.path.getmtime(os.path.join(log_dir, fname)),
                            reverse=True,
                        )
                        try:
                            with open(os.path.join(log_dir, matching_files[0]), "r", encoding="utf-8") as f:
                                lines = f.readlines()
                                log_text = "".join(lines[-100:])
                        except Exception:
                            pass
            self._send_json(200, {"log": log_text})
        elif self.path == "/api/status":
            if not self._require_auth():
                return
            status = {"running": False, "last_result": {}}
            if self._ctx.pipeline_busy_callback:
                status["running"] = self._ctx.pipeline_busy_callback()
            if self._ctx.get_status_callback:
                status["last_result"] = self._ctx.get_status_callback()
            self._send_json(200, status)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/login":
            token = self._ctx.api_token
            if not token:
                self._send_json(503, {"error": t("dashboard.no_token")})
                return
            auth = self.headers.get("Authorization", "")
            token_ok = auth.startswith("Bearer ") and token_matches(auth[7:].strip(), token)
            if not token_ok:
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length).decode("utf-8") if length else "{}"
                    data = json.loads(body or "{}")
                    token_ok = token_matches(str(data.get("token") or ""), token)
                except Exception:
                    token_ok = False
            if not token_ok:
                self._send_json(401, {"error": t("dashboard.bad_token")})
                return
            session_val = session_value(token)
            cookie_flags = (
                f"Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_MAX_AGE_SEC}"
            )
            if self._ctx.allow_lan:
                cookie_flags += "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE_NAME}={session_val}; {cookie_flags}",
            )
            body = b'{"ok": true}'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        elif self.path == "/api/sync":
            if not self._require_auth():
                return
            busy_cb = self._ctx.pipeline_busy_callback
            if busy_cb and busy_cb():
                self._send_json(409, {"ok": False, "message": t("dashboard.already_running")})
                return
            sync_cb = self._ctx.sync_callback
            if not sync_cb:
                self._send_json(503, {"ok": False, "message": t("dashboard.no_sync_cb")})
                return

            # 기동 직전 재확인 (TOCTOU 완화)
            if busy_cb and busy_cb():
                self._send_json(409, {"ok": False, "message": t("dashboard.already_running")})
                return

            # sync_callback 계약:
            # - True / None: 기동 수락 (None 은 하위 호환 — 호출 자체가 수락으로 간주)
            # - False: 락 실패 등으로 거부 → 409
            # 콜백이 동기 블로킹 파이프라인이면 요청 스레드가 오래 점유될 수 있으므로
            # begin_sync_pipeline_async 처럼 "수락 여부만 즉시 반환"하는 형태를 권장한다.
            try:
                result = sync_cb()
            except Exception as e:
                self._send_json(
                    500,
                    {"ok": False, "message": t("dashboard.start_failed", error=e)},
                )
                return

            if result is False:
                self._send_json(
                    409,
                    {
                        "ok": False,
                        "started": False,
                        "message": t("dashboard.cannot_start"),
                    },
                )
                return

            self._send_json(
                202,
                {
                    "ok": True,
                    "started": True,
                    "message": t("dashboard.started"),
                },
            )
        elif self.path == "/api/cancel":
            if not self._require_auth():
                return
            cancel_cb = self._ctx.cancel_callback
            if not cancel_cb:
                self._send_json(503, {"ok": False, "message": t("dashboard.no_cancel_cb")})
                return
            try:
                cancel_cb()
            except Exception as e:
                self._send_json(500, {"ok": False, "message": t("dashboard.cancel_failed", error=e)})
                return
            self._send_json(200, {"ok": True, "message": t("dashboard.cancel_requested")})
        else:
            self.send_error(404)
