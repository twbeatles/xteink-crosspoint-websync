import os
import io
import tempfile
import urllib.error
import urllib.request

import pytest
import requests


class _Response:
    def __init__(self, response):
        self.status = response.status_code
        self.headers = response.headers
        self._body = response.content

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def _urlopen(request, timeout=3):
    if isinstance(request, urllib.request.Request):
        url, method, data = request.full_url, request.get_method(), request.data
        headers = dict(request.header_items())
    else:
        url, method, data, headers = request, "GET", None, {}
    headers.setdefault("Connection", "close")
    for attempt in range(6):
        try:
            with requests.Session() as session:
                session.trust_env = False
                response = session.request(method, url, data=data, headers=headers, timeout=timeout)
            break
        except requests.RequestException:
            if attempt == 5:
                raise
    if response.status_code >= 400:
        raise urllib.error.HTTPError(
            url, response.status_code, response.reason, response.headers, io.BytesIO(response.content)
        )
    return _Response(response)

from websync.servers.opds import OPDSServer


def _free_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(tmp_output: str, *, require_auth: bool = False, api_key: str = "secret-key") -> OPDSServer:
    srv = OPDSServer(
        output_dir=tmp_output,
        port=0,
        bind_host="127.0.0.1",
        api_key=api_key,
        require_auth=require_auth,
    )
    assert srv.start() is True
    return srv


def test_opds_catalog_localhost_no_auth():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "book_2026-01-01.epub"), "wb") as f:
            f.write(b"epub")
        srv = _start_server(tmp, require_auth=False)
        try:
            url = f"http://127.0.0.1:{srv.port}/opds"
            with _urlopen(url, timeout=3) as resp:
                body = resp.read().decode("utf-8")
            assert "book_2026-01-01.epub" in body
        finally:
            srv.stop()


def test_opds_lan_requires_api_key():
    with tempfile.TemporaryDirectory() as tmp:
        srv = _start_server(tmp, require_auth=True, api_key="mykey")
        try:
            url = f"http://127.0.0.1:{srv.port}/opds"
            with pytest.raises(urllib.error.HTTPError) as exc:
                _urlopen(url, timeout=3)
            assert exc.value.code == 401

            req = urllib.request.Request(url, headers={"X-Api-Key": "mykey"})
            with _urlopen(req, timeout=3) as resp:
                assert resp.status == 200
        finally:
            srv.stop()


def test_opds_download_rejects_non_epub():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "evil.exe"), "wb") as f:
            f.write(b"x")
        srv = _start_server(tmp)
        try:
            url = f"http://127.0.0.1:{srv.port}/opds/download/evil.exe"
            with pytest.raises(urllib.error.HTTPError) as exc:
                _urlopen(url, timeout=3)
            assert exc.value.code == 403
        finally:
            srv.stop()


def test_opds_path_traversal_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        srv = _start_server(tmp)
        try:
            url = f"http://127.0.0.1:{srv.port}/opds/download/..%2F..%2Fetc%2Fpasswd"
            with pytest.raises(urllib.error.HTTPError) as exc:
                _urlopen(url, timeout=3)
            assert exc.value.code in (403, 404)
        finally:
            srv.stop()


def test_opds_unicode_filename_download():
    from urllib.parse import quote

    with tempfile.TemporaryDirectory() as tmp:
        fname = "한글_책_2026-01-01.epub"
        with open(os.path.join(tmp, fname), "wb") as f:
            f.write(b"epub-data")
        srv = _start_server(tmp, require_auth=False)
        try:
            catalog_url = f"http://127.0.0.1:{srv.port}/opds"
            with _urlopen(catalog_url, timeout=3) as resp:
                body = resp.read().decode("utf-8")
            assert quote(fname, safe="") in body or fname in body

            dl = f"http://127.0.0.1:{srv.port}/opds/download/{quote(fname, safe='')}"
            with _urlopen(dl, timeout=3) as resp:
                assert resp.read() == b"epub-data"
        finally:
            srv.stop()


# --- N6: ThreadingHTTPServer 동시 요청 처리 ---

def test_opds_serves_concurrent_requests():
    """대용량 다운로드(느린 요청) 중 카탈로그(빠른 요청)가 동시 처리되는지."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    with tempfile.TemporaryDirectory() as tmp:
        # 1MB 더미 EPUB — 다운로드가 약간의 시간을 갖도록
        with open(os.path.join(tmp, "big_2026-01-01.epub"), "wb") as f:
            f.write(b"X" * (1024 * 1024))
        srv = _start_server(tmp, require_auth=False)
        try:
            catalog_url = f"http://127.0.0.1:{srv.port}/opds"
            dl_url = f"http://127.0.0.1:{srv.port}/opds/download/big_2026-01-01.epub"
            results = {}

            def fetch_catalog():
                with _urlopen(catalog_url, timeout=5) as resp:
                    results["catalog"] = resp.read().decode("utf-8")

            def fetch_download():
                with _urlopen(dl_url, timeout=10) as resp:
                    results["download_size"] = len(resp.read())

            # 다운로드 먼저 시작, 그 사이 카탈로그 요청이 블로킹되지 않아야
            with ThreadPoolExecutor(max_workers=2) as ex:
                futs = [ex.submit(fetch_download), ex.submit(fetch_catalog)]
                for fut in futs:
                    fut.result(timeout=15)

            assert "big_2026-01-01.epub" in results["catalog"]
            assert results["download_size"] == 1024 * 1024
        finally:
            srv.stop()
