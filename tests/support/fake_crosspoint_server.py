"""Local loopback CrossPoint emulator for contract tests.

Stdlib only. Binds 127.0.0.1 on an OS-assigned port, serves in a daemon
thread, shuts down cleanly. Emulates a reader's File Transfer webserver;
touches no real network/SD card.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class FakeCrosspointState:
    def __init__(self):
        self.lock = threading.Lock()
        # remote full path -> bytes
        self.files: dict[str, bytes] = {}
        # request log: list of dicts
        self.requests: list[dict] = []
        # upload records: list of dicts {path, filename, sha256, size}
        self.uploads: list[dict] = []
        # failure injection knobs
        self.upload_status = 200
        self.upload_body = "OK"
        self.store_upload = True
        self.drop_upload_connection = False
        self.status_code = 200
        self.status_payload: dict = {
            "device": "X3-Fake",
            "version": "9.9-test",
            "mode": "STA",
        }
        self.status_raw: bytes | None = None  # when set, served verbatim
        self.files_status = 200
        self.files_raw: bytes | None = None
        self.download_disconnect_after: int | None = None
        self.slow_upload_sec = 0.0
        self.delete_status = 200
        self.mkdir_status = 200
        self.rename_status = 200
        self.move_status = 200


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def _state(self) -> FakeCrosspointState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, *args):
        pass

    def end_headers(self):
        # Each request owns its connection. requests' short-lived upload clients
        # otherwise reset idle HTTP/1.1 sockets on Windows, hiding useful errors
        # under unrelated server-thread tracebacks during failure tests.
        self.send_header("Connection", "close")
        super().end_headers()

    def _log(self, **kw):
        with self._state.lock:
            self._state.requests.append(kw)

    def _send_json(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, code: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path == "/api/status":
            self._log(method="GET", path="/api/status")
            st = self._state
            if st.status_raw is not None:
                body = st.status_raw
                self.send_response(st.status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if st.status_code != 200:
                self._send_text(st.status_code, "status error")
                return
            self._send_json(200, st.status_payload)
            return
        if parsed.path == "/api/files":
            self._log(method="GET", path="/api/files", query=parsed.query)
            st = self._state
            if st.files_raw is not None:
                body = st.files_raw
                self.send_response(st.files_status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if st.files_status != 200:
                self._send_text(st.files_status, "files error")
                return
            want = (qs.get("path", ["/"])[0] or "/")
            if not want.startswith("/"):
                want = "/" + want
            items = []
            with st.lock:
                snapshot = dict(st.files)
            prefix = want if want.endswith("/") else want + "/"
            for full, data in snapshot.items():
                if want == "/":
                    # top-level only
                    rest = full.lstrip("/")
                    if "/" in rest:
                        continue
                    items.append({"name": rest, "size": len(data),
                                  "isDirectory": False, "isEpub": rest.endswith(".epub")})
                else:
                    if full == want or full.startswith(prefix):
                        rest = full[len(prefix):]
                        if not rest or "/" in rest:
                            continue
                        items.append({"name": rest, "size": len(data),
                                      "isDirectory": False, "isEpub": rest.endswith(".epub")})
            self._send_json(200, items)
            return
        if parsed.path == "/download":
            want = (qs.get("path", [""])[0] or "")
            self._log(method="GET", path="/download", query=parsed.query)
            with self._state.lock:
                data = self._state.files.get(want)
                cut = self._state.download_disconnect_after
            if data is None:
                self._send_text(404, "not found")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if cut is not None:
                # simulate mid-stream disconnect: send prefix then break
                try:
                    self.wfile.write(data[:cut])
                    self.wfile.flush()
                finally:
                    try:
                        self.connection.shutdown(1)
                    except OSError:
                        pass
                return
            self.wfile.write(data)
            return
        if parsed.path == "/":
            self._log(method="GET", path="/")
            self._send_text(200, "crosspoint fake")
            return
        self._send_text(404, "not found")

    def _parse_form(self):
        ctype = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if "multipart/form-data" in ctype:
            m = re.search(r"boundary=([^;]+)", ctype)
            fields: dict[str, str] = {}
            file_field = None
            filename = None
            filebytes = None
            if m:
                boundary = m.group(1).strip().strip('"').encode("latin-1")
                parts = raw.split(b"--" + boundary)
                for part in parts:
                    if not part or part in (b"--", b"--\r\n", b"\r\n"):
                        continue
                    if b"\r\n\r\n" not in part:
                        continue
                    head, body = part.split(b"\r\n\r\n", 1)
                    if body.endswith(b"\r\n"):
                        body = body[:-2]
                    try:
                        head_s = head.decode("utf-8", "replace")
                    except Exception:
                        continue
                    name_m = re.search(r'name="([^"]*)"', head_s)
                    file_m = re.search(r'filename="([^"]*)"', head_s)
                    if not name_m:
                        continue
                    name = name_m.group(1)
                    if file_m:
                        file_field = name
                        filename = file_m.group(1).split("/")[-1].split("\\")[-1]
                        filebytes = body
                    else:
                        fields[name] = body.decode("utf-8", "replace")
            return fields, file_field, filename, filebytes, raw
        # urlencoded
        fields = {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}
        return fields, None, None, None, raw

    def do_POST(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path == "/upload":
            import time as _time

            st = self._state
            if st.slow_upload_sec:
                _time.sleep(st.slow_upload_sec)
            fields, file_field, filename, filebytes, _raw = self._parse_form()
            dest = (qs.get("path", [""])[0] or "/")
            if not dest.startswith("/"):
                dest = "/" + dest
            if dest != "/" and dest.endswith("/"):
                dest = dest.rstrip("/") or "/"
            self._log(method="POST", path="/upload", query=parsed.query,
                      filename=filename, size=len(filebytes or b""))
            if st.drop_upload_connection:
                try:
                    self.connection.shutdown(1)
                except OSError:
                    pass
                return
            if st.upload_status != 200:
                self._send_text(st.upload_status, st.upload_body)
                return
            if file_field != "file" or filename is None or filebytes is None:
                self._send_text(400, "missing file field")
                return
            # path traversal guard on the fake side mirrors firmware expectations
            segs = [s for s in filename.split("/") if s not in ("", ".", "..")]
            clean = segs[-1] if segs else filename
            full = clean if dest == "/" else dest + "/" + clean
            if st.store_upload:
                with st.lock:
                    st.files[full] = filebytes
            with st.lock:
                st.uploads.append({
                    "path": full,
                    "filename": clean,
                    "sha256": hashlib.sha256(filebytes).hexdigest(),
                    "size": len(filebytes),
                    "dest": dest,
                })
            # HTTP/1.1 needs Content-Length so requests doesn't hang
            self._send_text(200, st.upload_body)
            return
        if parsed.path in ("/delete", "/mkdir", "/rename", "/move"):
            fields, _, _, _, _raw = self._parse_form()
            self._log(method="POST", path=parsed.path, fields=fields)
            st = self._state
            want = {
                "/delete": st.delete_status,
                "/mkdir": st.mkdir_status,
                "/rename": st.rename_status,
                "/move": st.move_status,
            }[parsed.path]
            if want != 200:
                self._send_text(want, "rejected")
                return
            with st.lock:
                if parsed.path == "/delete":
                    targets: list[str] = []
                    if "path" in fields and fields["path"]:
                        targets = [fields["path"]]
                    elif "paths" in fields and fields["paths"]:
                        try:
                            decoded = json.loads(fields["paths"])
                            if isinstance(decoded, list):
                                targets = [str(x) for x in decoded]
                        except ValueError:
                            pass
                    # refuse root deletes
                    targets = [p for p in targets if p and p != "/"]
                    for p in targets:
                        st.files.pop(p, None)
                        # prefix delete for dirs
                        for k in [k for k in st.files if k.startswith(p.rstrip("/") + "/")]:
                            st.files.pop(k, None)
                elif parsed.path == "/mkdir":
                    pass  # accept; no dir tracking needed
                elif parsed.path == "/rename":
                    src = fields.get("path", "")
                    new = fields.get("name", "")
                    if src and new and src in st.files and "/" not in new:
                        parent = src.rsplit("/", 1)[0] or "/"
                        dst = ("/" + new) if parent == "/" else parent + "/" + new
                        st.files[dst] = st.files.pop(src)
                elif parsed.path == "/move":
                    src = fields.get("path", "")
                    dst_dir = fields.get("dest", "")
                    if src and dst_dir and src in st.files:
                        base = src.rsplit("/", 1)[-1]
                        if dst_dir == "/":
                            dst = "/" + base
                        else:
                            dst = "/" + (dst_dir.strip("/") + "/" + base)
                        st.files[dst] = st.files.pop(src)
            self._send_text(200, "OK")
            return
        self._send_text(404, "not found")


class FakeCrosspointServer:
    """Test helper: start/stop a loopback CrossPoint emulator."""

    def __init__(self):
        self.state = FakeCrosspointState()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.ready = threading.Event()
        self.port = 0

    def start(self) -> "FakeCrosspointServer":
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        httpd.daemon_threads = True
        httpd.state = self.state  # type: ignore[attr-defined]
        self._httpd = httpd
        self.port = httpd.server_address[1]
        self._thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05})
        self._thread.daemon = True
        self._thread.start()
        self.ready.set()
        return self

    @property
    def host(self) -> str:
        return f"127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
            finally:
                try:
                    self._httpd.server_close()
                except OSError:
                    pass
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._httpd = None
        self._thread = None

    def __enter__(self) -> "FakeCrosspointServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # convenience for tests
    def seed_file(self, remote_path: str, data: bytes) -> None:
        with self.state.lock:
            self.state.files[remote_path] = data
