"""X3DeviceClient 단위 테스트 (네트워크 mock)."""
import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from datetime import date

from websync.upload.device_client import (
    X3DeviceClient,
    DeviceClientError,
    normalize_remote_path,
    parent_remote_path,
    join_remote_path,
    format_file_size,
    parse_sync_epub_date,
    filter_old_sync_epubs,
)


def test_normalize_remote_path():
    assert normalize_remote_path("") == "/"
    assert normalize_remote_path("/") == "/"
    assert normalize_remote_path("/Books/") == "/Books"
    assert normalize_remote_path("Books/Sub") == "/Books/Sub"
    assert normalize_remote_path("/a/../b") == "/b"
    assert normalize_remote_path("/a/./b//c") == "/a/b/c"
    assert normalize_remote_path("/../..") == "/"
    assert normalize_remote_path("\\Books\\x") == "/Books/x"


def test_parent_remote_path():
    assert parent_remote_path("/") == "/"
    assert parent_remote_path("/Books") == "/"
    assert parent_remote_path("/Books/Sub") == "/Books"


def test_join_remote_path():
    assert join_remote_path("/", "a.epub") == "/a.epub"
    assert join_remote_path("/Books", "a.epub") == "/Books/a.epub"
    with pytest.raises(ValueError):
        join_remote_path("/", "../x")
    with pytest.raises(ValueError):
        join_remote_path("/", "a/b")


def test_format_file_size():
    assert format_file_size(0) == "0 B"
    assert format_file_size(512) == "512 B"
    assert "KB" in format_file_size(2048)
    assert "MB" in format_file_size(2 * 1024 * 1024)


def test_build_target_list_dedup():
    c = X3DeviceClient(
        "http://10.0.0.1/",
        devices=[{"name": "B", "ip": "10.0.0.2"}, {"name": "dup", "ip": "10.0.0.1"}],
    )
    targets = c._build_target_list()
    ips = [t["ip"] for t in targets]
    assert ips == ["10.0.0.1", "10.0.0.2"]


def test_get_status_success():
    c = X3DeviceClient("192.168.1.10")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "version": "1.2.0",
        "device": "X3",
        "mode": "STA",
        "rssi": -50,
        "freeHeap": 100000,
    }
    with patch("websync.upload.device_client.requests.get", return_value=mock_resp) as mget:
        data = c.get_status()
    assert data["device"] == "X3"
    assert mget.call_args.args[0] == "http://192.168.1.10/api/status"
    assert "192.168.1.10" not in c.last_errors


def test_get_status_http_error():
    c = X3DeviceClient("10.0.0.1")
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "Not Found"
    with patch("websync.upload.device_client.requests.get", return_value=mock_resp):
        with pytest.raises(DeviceClientError) as ei:
            c.get_status()
    assert "404" in str(ei.value)
    assert "10.0.0.1" in c.last_errors


def test_list_files_success_and_sort():
    c = X3DeviceClient("10.0.0.1")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"name": "z.epub", "size": 100, "isDirectory": False, "isEpub": True},
        {"name": "Notes", "size": 0, "isDirectory": True, "isEpub": False},
        {"name": "a.txt", "size": 50, "isDirectory": False, "isEpub": False},
    ]
    with patch("websync.upload.device_client.requests.get", return_value=mock_resp) as mget:
        items = c.list_files("/Books")
    # 폴더 우선
    assert items[0]["name"] == "Notes"
    assert items[0]["path"] == "/Books/Notes"
    assert items[0]["isDirectory"] is True
    names = [i["name"] for i in items]
    assert names[1:] == sorted(names[1:], key=str.lower)
    assert mget.call_args.kwargs["params"]["path"] == "/Books"


def test_list_files_root_path_default():
    c = X3DeviceClient("10.0.0.1")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"name": "book.epub", "size": 1, "isDirectory": False, "isEpub": True},
    ]
    with patch("websync.upload.device_client.requests.get", return_value=mock_resp) as mget:
        items = c.list_files()
    assert items[0]["path"] == "/book.epub"
    assert mget.call_args.kwargs["params"]["path"] == "/"


def test_list_files_network_error():
    import requests as req

    c = X3DeviceClient("10.0.0.1")
    with patch(
        "websync.upload.device_client.requests.get",
        side_effect=req.ConnectionError("refused"),
    ):
        with pytest.raises(DeviceClientError):
            c.list_files("/")
    assert "10.0.0.1" in c.last_errors


def test_delete_paths_single():
    c = X3DeviceClient("10.0.0.1")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"
    with patch("websync.upload.device_client.requests.post", return_value=mock_resp) as mpost:
        assert c.delete_paths(["/Books/old.epub"]) is True
    assert mpost.call_args.kwargs["data"] == {"path": "/Books/old.epub"}
    assert mpost.call_args.args[0] == "http://10.0.0.1/delete"


def test_delete_paths_multi_json():
    c = X3DeviceClient("10.0.0.1")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("websync.upload.device_client.requests.post", return_value=mock_resp) as mpost:
        c.delete_paths(["/a.epub", "/b.epub"])
    data = mpost.call_args.kwargs["data"]
    assert "paths" in data
    assert json.loads(data["paths"]) == ["/a.epub", "/b.epub"]


def test_delete_paths_rejects_empty():
    c = X3DeviceClient("10.0.0.1")
    with pytest.raises(DeviceClientError, match="삭제할 경로"):
        c.delete_paths(["/"])


def test_mkdir():
    c = X3DeviceClient("10.0.0.1")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("websync.upload.device_client.requests.post", return_value=mock_resp) as mpost:
        assert c.mkdir("NewFolder", path="/Books") is True
    assert mpost.call_args.kwargs["data"] == {"name": "NewFolder", "path": "/Books"}
    assert mpost.call_args.args[0] == "http://10.0.0.1/mkdir"


def test_download_writes_file():
    c = X3DeviceClient("10.0.0.1")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_content = lambda chunk_size: [b"epub-bytes"]
    with tempfile.TemporaryDirectory() as td:
        local = os.path.join(td, "out.epub")
        with patch("websync.upload.device_client.requests.get", return_value=mock_resp) as mget:
            assert c.download("/Books/a.epub", local) is True
        assert open(local, "rb").read() == b"epub-bytes"
        assert mget.call_args.kwargs["params"]["path"] == "/Books/a.epub"


def test_download_failure_preserves_existing_file_and_removes_partial():
    import requests as req

    c = X3DeviceClient("10.0.0.1")
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    def interrupted_chunks(chunk_size):
        yield b"partial-new-data"
        raise req.exceptions.ChunkedEncodingError("connection lost")

    mock_resp.iter_content = interrupted_chunks
    with tempfile.TemporaryDirectory() as td:
        local = os.path.join(td, "out.epub")
        with open(local, "wb") as existing:
            existing.write(b"complete-existing-book")
        with patch("websync.upload.device_client.requests.get", return_value=mock_resp):
            with pytest.raises(DeviceClientError):
                c.download("/Books/a.epub", local)

        with open(local, "rb") as existing:
            assert existing.read() == b"complete-existing-book"
        assert not [name for name in os.listdir(td) if name.endswith(".part")]


def test_format_status_summary():
    s = X3DeviceClient.format_status_summary(
        {"device": "X3", "version": "1.0.0", "mode": "STA", "rssi": -40, "freeHeap": 2048}
    )
    assert "X3" in s
    assert "v1.0.0" in s
    assert "STA" in s


def test_rename():
    c = X3DeviceClient("10.0.0.1")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("websync.upload.device_client.requests.post", return_value=mock_resp) as mpost:
        assert c.rename("/Books/old.epub", "new.epub") is True
    assert mpost.call_args.args[0] == "http://10.0.0.1/rename"
    assert mpost.call_args.kwargs["data"] == {"path": "/Books/old.epub", "name": "new.epub"}


def test_move():
    c = X3DeviceClient("10.0.0.1")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("websync.upload.device_client.requests.post", return_value=mock_resp) as mpost:
        assert c.move("/Books/a.epub", "/Read") is True
    assert mpost.call_args.kwargs["data"] == {"path": "/Books/a.epub", "dest": "/Read"}


def test_upload_to_path_with_dir():
    c = X3DeviceClient("10.0.0.1")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as f:
        f.write(b"data")
        path = f.name
    try:
        with patch("websync.upload.device_client.requests.post", return_value=mock_resp) as mpost:
            assert c.upload_to_path(path, remote_dir="/Books") is True
        assert mpost.call_args.args[0] == "http://10.0.0.1/upload"
        assert mpost.call_args.kwargs["params"] == {"path": "/Books"}
    finally:
        os.remove(path)


def test_upload_to_path_root_omits_params():
    c = X3DeviceClient("10.0.0.1")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as f:
        f.write(b"data")
        path = f.name
    try:
        with patch("websync.upload.device_client.requests.post", return_value=mock_resp) as mpost:
            c.upload_to_path(path, remote_dir="/")
        assert mpost.call_args.kwargs["params"] is None
    finally:
        os.remove(path)


def test_remote_file_exists():
    c = X3DeviceClient("10.0.0.1")
    with patch.object(
        c,
        "list_files",
        return_value=[
            {"name": "a.epub", "isDirectory": False, "size": 1, "isEpub": True, "path": "/a.epub"},
            {"name": "Notes", "isDirectory": True, "size": 0, "isEpub": False, "path": "/Notes"},
        ],
    ):
        assert c.remote_file_exists("/", "a.epub") is True
        assert c.remote_file_exists("/", "missing.epub") is False
        assert c.remote_file_exists("/", "Notes") is False


def test_parse_sync_epub_date():
    assert parse_sync_epub_date("MySite_2026-07-01.epub") == date(2026, 7, 1)
    assert parse_sync_epub_date("Daily_Digest_2026-06-15.epub") == date(2026, 6, 15)
    assert parse_sync_epub_date("MySite_2026-07-01_143022.epub") == date(2026, 7, 1)
    assert parse_sync_epub_date("readme.txt") is None
    assert parse_sync_epub_date("no_date.epub") is None


def test_filter_old_sync_epubs():
    items = [
        {"name": "old_2020-01-01.epub", "isDirectory": False, "path": "/old_2020-01-01.epub"},
        {"name": "new_2026-07-10.epub", "isDirectory": False, "path": "/new_2026-07-10.epub"},
        {"name": "folder", "isDirectory": True, "path": "/folder"},
        {"name": "other.epub", "isDirectory": False, "path": "/other.epub"},
    ]
    old = filter_old_sync_epubs(items, older_than_days=7, today=date(2026, 7, 15))
    assert len(old) == 1
    assert old[0]["name"] == "old_2020-01-01.epub"
    assert old[0]["sync_date"] == "2020-01-01"


def test_test_connection_fallback_requires_2xx():
    """ISSUE-002: /api/status 실패 시 GET / 폴백도 2xx를 요구한다."""
    c = X3DeviceClient("127.0.0.1")
    bad = MagicMock()
    bad.status_code = 404
    good = MagicMock()
    good.status_code = 200
    with patch.object(
        X3DeviceClient, "get_status", side_effect=DeviceClientError("no status")
    ):
        with patch(
            "websync.upload.device_client.requests.get", return_value=bad
        ):
            assert c.test_connection() is False
        with patch(
            "websync.upload.device_client.requests.get", return_value=good
        ):
            assert c.test_connection() is True

