"""OPDS 카탈로그 HTTP 서버"""
import os
import re
import secrets
import sys
import threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Optional
from urllib.parse import quote, unquote, urlparse, parse_qs


class _OPDSHTTPServer(ThreadingHTTPServer):
    """핸들러에 OPDS 설정을 주입하는 HTTP 서버 (ThreadingHTTPServer — 동시 요청 처리, N6)."""

    daemon_threads = False

    def __init__(
        self,
        server_address,
        output_dir: str,
        api_key: str,
        require_auth: bool,
    ):
        self.output_dir = output_dir
        self.api_key = api_key or ""
        self.require_auth = require_auth
        super().__init__(server_address, OPDSHandler)

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


class OPDSHandler(BaseHTTPRequestHandler):
    """OPDS XML 카탈로그 및 파일 다운로드를 처리하는 HTTP 핸들러"""

    protocol_version = "HTTP/1.0"
    timeout = 2

    @property
    def _ctx(self) -> _OPDSHTTPServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, format, *args):
        pass

    def _token_ok(self, provided: str | None) -> bool:
        expected = self._ctx.api_key or ""
        if not provided or not expected:
            return False
        return secrets.compare_digest(provided, expected)

    def _check_auth(self) -> bool:
        ctx = self._ctx
        if not ctx.require_auth:
            return True
        if not ctx.api_key:
            return False
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and self._token_ok(auth[7:].strip()):
            return True
        api_header = self.headers.get("X-Api-Key", "")
        if self._token_ok(api_header):
            return True
        # 쿼리 api_key 는 로그 유출 위험으로 기본 비활성.
        # 환경변수 X3_OPDS_ALLOW_QUERY_API_KEY=1 일 때만 하위 호환 허용.
        if os.environ.get("X3_OPDS_ALLOW_QUERY_API_KEY", "").strip() in ("1", "true", "yes"):
            qs = parse_qs(urlparse(self.path).query)
            if self._token_ok(qs.get("api_key", [None])[0]):
                return True
        self.send_error(401, "Unauthorized")
        return False

    def do_GET(self):
        if not self._check_auth():
            return
        path = self.path.split("?", 1)[0]
        if path in ("/", "/opds", "/opds/"):
            self._serve_catalog()
        elif path.startswith("/opds/download/"):
            self._serve_file()
        else:
            self.send_error(404)

    def _serve_catalog(self):
        output_dir = self._ctx.output_dir
        epub_files = []
        if os.path.isdir(output_dir):
            epub_files = sorted(
                [f for f in os.listdir(output_dir) if f.lower().endswith(".epub")],
                reverse=True,
            )

        entries = ""
        for fname in epub_files:
            fpath = os.path.join(output_dir, fname)
            size = os.path.getsize(fpath) if os.path.exists(fpath) else 0
            safe_name = fname.replace("&", "&amp;").replace("<", "&lt;")
            title = re.sub(r"_\d{4}-\d{2}-\d{2}\.epub$", "", fname.replace("_", " ")).strip()
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%Y-%m-%dT%H:%M:%SZ")
            href = f"/opds/download/{quote(fname, safe='')}"
            entries += f"""
  <entry>
    <title>{safe_name}</title>
    <id>urn:x3sync:{safe_name}</id>
    <updated>{mtime}</updated>
    <summary>{title} ({size // 1024} KB)</summary>
    <link rel="http://opds-spec.org/acquisition" href="{href}" type="application/epub+zip"/>
  </entry>"""

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opds="http://opds-spec.org/2010/catalog">
  <title>X3 WebSync OPDS 카탈로그</title>
  <id>urn:x3sync:root</id>
  <updated>{now_utc}</updated>
  <link rel="self" href="/opds" type="application/atom+xml;profile=opds-catalog"/>{entries}
</feed>"""
        body = xml.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/atom+xml;profile=opds-catalog; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def _serve_file(self):
        path = self.path.split("?", 1)[0]
        raw = path[len("/opds/download/"):]
        fname = os.path.basename(unquote(raw))
        if not fname.lower().endswith(".epub"):
            self.send_error(403)
            return
        fpath = os.path.join(self._ctx.output_dir, fname)
        # output_dir 밖 탈출 방지 (Windows 드라이브 대소문자 차이 방어를 위해 normcase 적용)
        try:
            real_out = os.path.normcase(os.path.realpath(self._ctx.output_dir))
            real_file = os.path.normcase(os.path.realpath(fpath))
            sep = os.path.normcase(os.sep)
            if not real_file.startswith(real_out + sep) and real_file != real_out:
                self.send_error(403)
                return
        except OSError:
            self.send_error(404)
            return
        if not os.path.isfile(fpath):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/epub+zip")
        # HTTP 헤더는 latin-1 — 비ASCII 파일명은 RFC 5987 filename* 사용
        ascii_name = "".join(c if ord(c) < 128 else "_" for c in fname) or "book.epub"
        disp = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(fname, safe='')}"
        self.send_header("Content-Disposition", disp)
        self.send_header("Content-Length", str(os.path.getsize(fpath)))
        self.end_headers()
        # 청크 단위 전송 (대용량 EPUB 메모리 부족 방지)
        _CHUNK_SIZE = 64 * 1024  # 64KB
        with open(fpath, "rb") as f:
            while True:
                chunk = f.read(_CHUNK_SIZE)
                if not chunk:
                    break
                self.wfile.write(chunk)
        self.wfile.flush()


class OPDSServer:
    """OPDS HTTP 서버를 백그라운드 스레드로 실행·관리하는 클래스"""

    def __init__(
        self,
        output_dir: str = "./output",
        port: int = 8765,
        bind_host: str = "127.0.0.1",
        api_key: str = "",
        require_auth: bool = False,
    ):
        self.output_dir = output_dir
        self.port = port
        self.bind_host = bind_host
        self.api_key = api_key
        self.require_auth = require_auth
        self._server: Optional[_OPDSHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> bool:
        if self._running:
            return True
        if self.require_auth and not self.api_key:
            print("❌ OPDS: LAN 공개 모드에는 api_key가 필요합니다.")
            return False
        if self.bind_host not in ("127.0.0.1", "localhost"):
            print(f"⚠️ [OPDS] LAN 공개 모드 활성화 ({self.bind_host}:{self.port}) — 평문 HTTP 통신이므로 보안 토큰 사용을 권장합니다.")
        try:
            self._server = _OPDSHTTPServer(
                (self.bind_host, self.port),
                self.output_dir,
                self.api_key,
                self.require_auth,
            )
            self.port = self._server.server_port
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            self._running = True
            return True
        except Exception as e:
            print(f"❌ OPDS 서버 시작 실패: {e}")
            return False

    def stop(self):
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        self._running = False
        if server:
            server.shutdown()
            server.server_close()
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    @property
    def is_running(self) -> bool:
        return self._running

    def get_url(self) -> str:
        host = "localhost" if self.bind_host in ("127.0.0.1", "localhost") else self.bind_host
        return f"http://{host}:{self.port}/opds"
