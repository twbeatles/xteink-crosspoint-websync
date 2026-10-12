"""CrossPoint HTTP contract over real loopback HTTP (no requests mock).

INV-01/02/08/09: success only on real 200+stored bytes; download failure
preserves local bytes and cleans .part; destructive paths are refused.
"""
from __future__ import annotations

import hashlib
import os

import pytest
import requests

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "support"))
from fake_crosspoint_server import FakeCrosspointServer
from websync.upload.device_client import X3DeviceClient
from websync.upload.errors import DeviceClientError
from websync.upload.uploader import X3Uploader


@pytest.fixture
def server():
    srv = FakeCrosspointServer().start()
    try:
        yield srv
    finally:
        srv.stop()


def _epub_bytes(marker: str) -> bytes:
    return (f"EPUB-{marker}-" + "x" * 2048).encode("utf-8")


def test_status_contract_ok_and_summary(server, tmp_path):
    client = X3DeviceClient(server.host)
    data = client.get_status()
    assert data["device"] == "X3-Fake"
    assert "X3-Fake" in X3DeviceClient.format_status_summary(data)
    logged = [r for r in server.state.requests if r.get("path") == "/api/status"]
    assert logged, "expected a real GET /api/status"


def test_status_contract_error_and_malformed(server):
    client = X3DeviceClient(server.host)
    server.state.status_code = 500
    with pytest.raises(DeviceClientError):
        client.get_status()
    assert server.host in client.last_errors

    server.state.status_code = 200
    server.state.status_raw = b"not-json{{{"
    with pytest.raises(DeviceClientError):
        client.get_status()

    server.state.status_raw = b'["not", "a", "dict"]'
    with pytest.raises(DeviceClientError):
        client.get_status()


def test_files_listing_korean_names(server):
    server.seed_file("/Books/한글 책.epub", b"abc")
    server.seed_file("/Books/plain.epub", b"def")
    client = X3DeviceClient(server.host)
    items = client.list_files("/Books")
    names = {i["name"] for i in items}
    assert "한글 책.epub" in names and "plain.epub" in names
    assert all(i["path"].startswith("/Books/") for i in items)


def test_uploader_real_multipart_and_sha256(server, tmp_path):
    payload = _epub_bytes("real")
    local = tmp_path / "my book 한 글.epub"
    local.write_bytes(payload)
    uploader = X3Uploader(server.host, remote_dir="/Books")

    ok = uploader._upload_to_ip(
        str(local), server.host,
        uploader._sanitize_filename(str(local)), 30,
    )
    assert ok is True
    assert len(server.state.uploads) == 1
    rec = server.state.uploads[0]
    assert rec["sha256"] == hashlib.sha256(payload).hexdigest()
    assert rec["dest"] == "/Books"
    assert " " not in rec["filename"]
    # stored bytes identical
    with server.state.lock:
        stored = dict(server.state.files)
    assert stored[rec["path"]] == payload


def test_device_client_upload_uses_params_path_style(server, tmp_path):
    payload = _epub_bytes("params")
    local = tmp_path / "a.epub"
    local.write_bytes(payload)
    client = X3DeviceClient(server.host)
    assert client.upload_to_path(str(local), "/Books") is True
    queries = [r.get("query", "") for r in server.state.requests if r.get("path") == "/upload"]
    assert any("path=" in q and "Books" in q for q in queries)


def test_upload_root_omits_path_query(server, tmp_path):
    local = tmp_path / "r.epub"
    local.write_bytes(b"0123456789")
    uploader = X3Uploader(server.host, remote_dir="/")
    assert uploader._upload_to_ip(str(local), server.host, "r.epub", 30) is True
    queries = [r.get("query", "") for r in server.state.requests if r.get("path") == "/upload"]
    assert queries and all(q == "" for q in queries)


def test_mkdir_rename_move_delete_roundtrip(server):
    client = X3DeviceClient(server.host)
    assert client.mkdir("WebSyncTest", path="/") is True
    server.seed_file("/Books/old.epub", b"data-old")
    assert client.rename("/Books/old.epub", "new.epub") is True
    with server.state.lock:
        assert "/Books/new.epub" in server.state.files
        assert "/Books/old.epub" not in server.state.files
    assert client.move("/Books/new.epub", "/") is True
    with server.state.lock:
        assert "/new.epub" in server.state.files
    assert client.delete_paths(["/new.epub"]) is True
    with server.state.lock:
        assert "/new.epub" not in server.state.files


def test_delete_refuses_root(server):
    client = X3DeviceClient(server.host)
    server.seed_file("/Books/keep.epub", b"keep")
    with pytest.raises(DeviceClientError):
        client.delete_paths(["/"])
    with server.state.lock:
        assert "/Books/keep.epub" in server.state.files


def test_download_ok_and_interrupted_preserves_local(server, tmp_path):
    server.seed_file("/Books/book.epub", b"D" * 4096)
    client = X3DeviceClient(server.host)
    dest = tmp_path / "book.epub"
    assert client.download("/Books/book.epub", str(dest)) is True
    assert dest.read_bytes() == b"D" * 4096

    # interrupted download: pre-existing file must be preserved, .part cleaned
    dest.write_bytes(b"ORIGINAL-KEPT")
    server.state.download_disconnect_after = 100
    with pytest.raises(DeviceClientError):
        client.download("/Books/book.epub", str(dest))
    assert dest.read_bytes() == b"ORIGINAL-KEPT"
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".part" or ".part" in p.name]
    assert leftovers == []


def test_raw_http_status_reflects_firmware_shape(server):
    # Independent oracle: raw HTTP shape, not our mock's return_value.
    r = requests.get(f"http://{server.host}/api/status", timeout=5)
    assert r.status_code == 200
    assert r.json()["mode"] == "STA"
