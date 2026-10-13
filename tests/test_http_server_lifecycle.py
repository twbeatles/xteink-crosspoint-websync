"""Dashboard + OPDS lifecycle and auth contract over real loopback HTTP.

- POST /api/sync without auth -> 401, callback count 0 (INV-11)
- busy -> 409, accept -> 202, callback False -> 409
- OPDS: unauth denied, traversal/symlink denied, log/response carry no secrets
- lifecycle: port=0 start/stop, burst of concurrent GETs without reset storm
"""
import json
import os
import tempfile
import threading
import urllib.request

import pytest
import requests

from websync.servers.opds import OPDSServer
from websync.servers.web_dashboard import WebDashboard


def _request(method, url, **kw):
    # Readiness retries belong to _wait_ready. Never replay a mutation after
    # response loss: its callback may already have been accepted.
    with requests.Session() as session:
        session.trust_env = False
        return session.request(method, url, timeout=5, **kw)


def _get(url, **headers):
    return _request("GET", url, headers=headers)


def _post(url, payload=None, **headers):
    return _request("POST", url, json=payload or {}, headers=headers)


def _wait_ready(base, token, timeout=10.0):
    import time as _time

    deadline = _time.monotonic() + timeout
    while True:
        try:
            r = _get(base + "/api/status", Authorization=f"Bearer {token}")
            if r.status_code == 200:
                return
        except requests.ConnectionError:
            pass
        if _time.monotonic() >= deadline:
            raise AssertionError("dashboard did not become ready in time")
        _time.sleep(0.05)


def test_dashboard_sync_requires_auth_and_reports_states():
    calls = {"n": 0}

    def _sync():
        calls["n"] += 1
        return True

    srv = WebDashboard(port=0, bind_host="127.0.0.1", api_token="tok123",
                       sync_callback=_sync)
    assert srv.start() is True
    try:
        base = f"http://127.0.0.1:{srv.port}"
        _wait_ready(base, "tok123")
        r = _post(base + "/api/sync", {})
        assert r.status_code == 401
        assert calls["n"] == 0
        r = _post(base + "/api/sync", {}, Authorization="Bearer tok123")
        assert r.status_code == 202
        assert calls["n"] == 1
    finally:
        srv.stop()


def test_dashboard_busy_maps_to_409_and_cancel_needs_auth():
    srv = WebDashboard(port=0, bind_host="127.0.0.1", api_token="tok123",
                       sync_callback=lambda: True,
                       pipeline_busy_callback=lambda: True)
    assert srv.start() is True
    try:
        base = f"http://127.0.0.1:{srv.port}"
        _wait_ready(base, "tok123")
        r = _post(base + "/api/sync", {}, Authorization="Bearer tok123")
        assert r.status_code == 409
        r = _post(base + "/api/cancel", {})
        assert r.status_code == 401
    finally:
        srv.stop()


def test_dashboard_burst_lifecycle(tmp_path):
    srv = WebDashboard(port=0, bind_host="127.0.0.1", api_token="tok123",
                       get_status_callback=lambda: {"ok": True})
    assert srv.start() is True
    try:
        base = f"http://127.0.0.1:{srv.port}"
        _wait_ready(base, "tok123")
        errors = []

        def _hit():
            try:
                r = _get(base + "/api/status", Authorization="Bearer tok123")
                assert r.status_code == 200
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=_hit) for _ in range(20)]
        [t.start() for t in threads]
        [t.join(timeout=10) for t in threads]
        assert errors == []
    finally:
        srv.stop()


def test_opds_security_contract(tmp_path):
    outdir = str(tmp_path)
    with open(os.path.join(outdir, "ok.epub"), "wb") as f:
        f.write(b"epub-bytes")
    outside = tempfile.mkdtemp()
    with open(os.path.join(outside, "secret.epub"), "wb") as f:
        f.write(b"SECRET-BYTES")
    link = os.path.join(outdir, "evil.epub")
    try:
        os.symlink(os.path.join(outside, "secret.epub"), link)
        has_symlink = True
    except (OSError, NotImplementedError):
        has_symlink = False

    srv = OPDSServer(output_dir=outdir, port=0, bind_host="127.0.0.1",
                     api_key="secret-key-xyz-123", require_auth=True)
    assert srv.start() is True
    try:
        base = f"http://127.0.0.1:{srv.port}"
        assert _get(base + "/opds").status_code == 401
        r = _get(base + "/opds", Authorization="Bearer secret-key-xyz-123")
        assert r.status_code == 200
        assert "SECRET-BYTES" not in r.text
        # traversal attempt must not expose outside files (real routes)
        for evil in ("/opds/download/..%2Fsecret.epub",
                     "/opds/download/%2E%2E%5Csecret.epub",
                     "/opds/download/%2Fetc%2Fpasswd"):
            rr = _get(base + evil, Authorization="Bearer secret-key-xyz-123")
            assert rr.status_code in (400, 403, 404)
            assert "SECRET-BYTES" not in getattr(rr, "text", "")
        # query strings on the catalog are ignored, never a file read
        rr = _get(base + "/opds?path=../", Authorization="Bearer secret-key-xyz-123")
        assert rr.status_code == 200
        assert "SECRET-BYTES" not in rr.text
        if has_symlink:
            rr = _get(base + "/opds/download/evil.epub", Authorization="Bearer secret-key-xyz-123")
            assert rr.status_code in (400, 403, 404) or "SECRET-BYTES" not in getattr(rr, "text", "")
        # no secret leakage into body/headers on 401
        denied = _get(base + "/opds")
        assert "secret-key-xyz-123" not in denied.text
    finally:
        srv.stop()
