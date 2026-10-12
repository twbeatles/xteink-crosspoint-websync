"""Device-client branch coverage over real loopback HTTP (INV-08/09/11).

Covers the error/edge branches that core coverage flagged: bad names,
root guards, multi-delete, malformed listings, non-200 on every mutating
route, missing local file, exists-check, and the connection fallback.
"""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "support"))
from fake_crosspoint_server import FakeCrosspointServer

import pytest

from websync.upload.device_client import X3DeviceClient
from websync.upload.errors import DeviceClientError


@pytest.fixture
def server():
    srv = FakeCrosspointServer().start()
    try:
        yield srv
    finally:
        srv.stop()


def test_empty_host_raises(server):
    client = X3DeviceClient("")
    with pytest.raises(DeviceClientError):
        client.get_status("")
    with pytest.raises(DeviceClientError):
        client.list_files("/", ip="")


def test_connection_refused_records_error(server):
    client = X3DeviceClient("127.0.0.1:1")
    with pytest.raises(DeviceClientError):
        client.get_status()
    assert "127.0.0.1:1" in client.last_errors
    with pytest.raises(DeviceClientError):
        client.list_files("/Books")


def test_mkdir_rejects_bad_names(server):
    client = X3DeviceClient(server.host)
    for bad in ("", "a/b", "a\\b"):
        with pytest.raises(DeviceClientError):
            client.mkdir(bad, path="/Books")
    assert client.mkdir("WebSyncTest", path="/Books") is True


def test_mkdir_server_rejection(server):
    server.state.mkdir_status = 409
    with pytest.raises(DeviceClientError):
        X3DeviceClient(server.host).mkdir("New", path="/")


def test_rename_guards_and_rejection(server):
    client = X3DeviceClient(server.host)
    with pytest.raises(DeviceClientError):
        client.rename("/", "new.epub")
    for bad in ("", "a/b", ".", ".."):
        with pytest.raises(DeviceClientError):
            client.rename("/Books/a.epub", bad)
    server.seed_file("/Books/a.epub", b"data")
    server.state.rename_status = 500
    with pytest.raises(DeviceClientError):
        client.rename("/Books/a.epub", "b.epub")


def test_move_guards_and_rejection(server):
    client = X3DeviceClient(server.host)
    with pytest.raises(DeviceClientError):
        client.move("/", "/Books")
    server.seed_file("/Books/a.epub", b"data")
    server.state.move_status = 403
    with pytest.raises(DeviceClientError):
        client.move("/Books/a.epub", "/Books")


def test_delete_multi_and_server_rejection(server):
    client = X3DeviceClient(server.host)
    server.seed_file("/Books/a.epub", b"a")
    server.seed_file("/Books/b.epub", b"b")
    assert client.delete_paths(["/Books/a.epub", "/Books/b.epub"]) is True
    with server.state.lock:
        assert "/Books/a.epub" not in server.state.files
    server.state.delete_status = 500
    with pytest.raises(DeviceClientError):
        client.delete_paths(["/Books/c.epub"])
    with pytest.raises(DeviceClientError):
        client.delete_paths([])


def test_list_skips_malformed_entries(server):
    server.state.files_raw = (
        b'[{"name": "ok.epub", "size": 3}, "junk", {"no_name": 1},'
        b' {"name": ".."}, {"name": "a/b"}, {"name": "bad", "size": "xx"}]'
    )
    items = X3DeviceClient(server.host).list_files("/Books")
    names = {i["name"] for i in items}
    assert "ok.epub" in names and "bad" in names
    assert ".." not in names and "a/b" not in names


def test_list_non_json_and_error_status(server):
    client = X3DeviceClient(server.host)
    server.state.files_raw = b"not json"
    with pytest.raises(DeviceClientError):
        client.list_files("/Books")
    server.state.files_raw = None
    server.state.files_status = 404
    with pytest.raises(DeviceClientError) as exc:
        client.list_files("/Books")
    assert exc.value.status_code == 404


def test_download_guards(server, tmp_path):
    client = X3DeviceClient(server.host)
    with pytest.raises(DeviceClientError):
        client.download("/", str(tmp_path / "x.epub"))
    with pytest.raises(DeviceClientError):
        client.download("/Books/missing.epub", str(tmp_path / "x.epub"))


def test_remote_file_exists(server):
    client = X3DeviceClient(server.host)
    assert client.remote_file_exists("/Books", "") is False
    server.seed_file("/Books/a.epub", b"data")
    assert client.remote_file_exists("/Books", "a.epub") is True
    assert client.remote_file_exists("/Books", "nope.epub") is False


def test_upload_missing_local_file(server):
    with pytest.raises(DeviceClientError):
        X3DeviceClient(server.host).upload_to_path(str(server.host) + "_nope.epub", "/Books")


def test_upload_server_rejection_and_timeout_state(server, tmp_path):
    client = X3DeviceClient(server.host)
    local = tmp_path / "u.epub"
    local.write_bytes(b"data-bytes")
    server.state.upload_status = 500
    with pytest.raises(DeviceClientError):
        client.upload_to_path(str(local), "/Books")
    assert server.host in client.last_errors
    server.state.upload_status = 200
    assert client.upload_to_path(str(local), "/Books") is True
    assert server.host not in client.last_errors


def test_test_connection_fallback_shapes():
    assert X3DeviceClient("").test_connection() is False
    assert X3DeviceClient("127.0.0.1:1").test_connection() is False


def test_test_connection_true_on_loopback(server):
    assert X3DeviceClient(server.host).test_connection() is True
