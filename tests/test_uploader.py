import os
import tempfile
from unittest.mock import patch

from websync.upload.uploader import (
    X3Uploader,
    normalize_device_host,
    normalize_upload_remote_dir,
)


def test_gui_make_uploader_passes_primary_device_id():
    from unittest.mock import MagicMock

    from websync.gui.app_core.helpers import AppHelpersMixin

    helper = AppHelpersMixin.__new__(AppHelpersMixin)
    helper.service = MagicMock()
    helper.service.config = {
        "x3_ip": "1.2.3.4",
        "x3_devices": [],
        "device_files": {"default_upload_path": "/books"},
        "x3_primary_device_id": "dev_abc",
    }
    helper.tab_sync = MagicMock()
    helper.tab_sync.ip_entry.get.return_value = ""
    up = helper._make_uploader()
    assert up.primary_device_id == "dev_abc"


def test_normalize_device_host_strips_slash_and_scheme():
    assert normalize_device_host("192.168.31.54/") == "192.168.31.54"
    assert normalize_device_host("http://192.168.31.54/") == "192.168.31.54"
    assert normalize_device_host("https://crosspoint.local/path") == "crosspoint.local"
    assert normalize_device_host("  10.0.0.1  ") == "10.0.0.1"
    assert normalize_device_host("") == ""


def test_sanitize_filename_korean():
    u = X3Uploader("127.0.0.1")
    name = u._sanitize_filename("/tmp/한글 제목 테스트.epub")
    assert " " not in name
    assert name.endswith(".epub")


def test_build_target_list_dedup():
    u = X3Uploader(
        "192.168.1.10/",
        devices=[
            {"name": "추가", "ip": "http://192.168.1.20/"},
            {"name": "dup", "ip": "192.168.1.10"},
        ],
    )
    targets = u._build_target_list()
    ips = [t["ip"] for t in targets]
    assert ips.count("192.168.1.10") == 1
    assert "192.168.1.20" in ips
    assert all(not ip.endswith("/") for ip in ips)


def test_calc_timeout_scales_with_size():
    u = X3Uploader("127.0.0.1")
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"x" * (2 * 1024 * 1024))
        path = f.name
    try:
        assert u._calc_timeout(path) >= 30
    finally:
        os.remove(path)


def test_upload_to_targets_all_success():
    u = X3Uploader("10.0.0.1", devices=[{"name": "B", "ip": "10.0.0.2"}])
    with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as f:
        f.write(b"data")
        path = f.name
    try:
        with patch.object(u, "_upload_to_ip", return_value=True) as mock_up:
            results = u.upload_to_targets(path)
        assert results == {"10.0.0.1": True, "10.0.0.2": True}
        assert mock_up.call_count == 2
    finally:
        os.remove(path)


def test_upload_to_targets_partial_failure():
    u = X3Uploader("10.0.0.1", devices=[{"name": "B", "ip": "10.0.0.2"}])
    with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as f:
        f.write(b"data")
        path = f.name
    try:
        def side_effect(file_path, ip, safe_filename, timeout, remote_dir=None):
            return ip == "10.0.0.1"

        with patch.object(u, "_upload_to_ip", side_effect=side_effect):
            results = u.upload_to_targets(path)
        assert results["10.0.0.1"] is True
        assert results["10.0.0.2"] is False
    finally:
        os.remove(path)


def test_upload_to_targets_only_ips_filter():
    u = X3Uploader("10.0.0.1", devices=[{"name": "B", "ip": "10.0.0.2"}])
    with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as f:
        f.write(b"data")
        path = f.name
    try:
        with patch.object(u, "_upload_to_ip", return_value=True) as mock_up:
            results = u.upload_to_targets(path, only_ips=["10.0.0.2"])
        assert results == {"10.0.0.2": True}
        assert mock_up.call_count == 1
        assert mock_up.call_args.args[1] == "10.0.0.2"
    finally:
        os.remove(path)


def test_upload_to_targets_no_devices():
    u = X3Uploader("")
    results = u.upload_to_targets("/tmp/x.epub")
    assert results == {}


def test_normalize_upload_remote_dir():
    assert normalize_upload_remote_dir("") == "/"
    assert normalize_upload_remote_dir("/Books/") == "/Books"
    assert normalize_upload_remote_dir("Books/Sub") == "/Books/Sub"
    assert normalize_upload_remote_dir("/a/../b") == "/b"


def test_upload_to_ip_includes_remote_path_query():
    u = X3Uploader("10.0.0.1", remote_dir="/Books")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as f:
        f.write(b"data")
        path = f.name
    try:
        mock_resp = type("R", (), {"status_code": 200, "text": "ok"})()
        with patch("websync.upload.uploader.requests.post", return_value=mock_resp) as mpost:
            assert u._upload_to_ip(path, "10.0.0.1", "book.epub", 30) is True
        url = mpost.call_args.args[0]
        assert url.startswith("http://10.0.0.1/upload")
        assert "path=" in url
        assert "Books" in url
    finally:
        os.remove(path)


def test_upload_to_ip_root_no_path_query():
    u = X3Uploader("10.0.0.1", remote_dir="/")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as f:
        f.write(b"data")
        path = f.name
    try:
        mock_resp = type("R", (), {"status_code": 200, "text": "ok"})()
        with patch("websync.upload.uploader.requests.post", return_value=mock_resp) as mpost:
            u._upload_to_ip(path, "10.0.0.1", "book.epub", 30)
        assert mpost.call_args.args[0] == "http://10.0.0.1/upload"
    finally:
        os.remove(path)


def test_test_connection_requires_2xx_status():
    """ISSUE-002: 404/500을 연결 성공으로 오판하지 않는다."""
    from unittest.mock import MagicMock

    u = X3Uploader("127.0.0.1")
    ok = MagicMock()
    ok.status_code = 200
    not_found = MagicMock()
    not_found.status_code = 404
    server_error = MagicMock()
    server_error.status_code = 500
    with patch("websync.upload.uploader.requests.get", return_value=ok):
        assert u.test_connection() is True
    with patch("websync.upload.uploader.requests.get", return_value=not_found):
        assert u.test_connection() is False
    with patch("websync.upload.uploader.requests.get", return_value=server_error):
        assert u.test_connection() is False
    with patch(
        "websync.upload.uploader.requests.get",
        side_effect=ConnectionError("down"),
    ):
        assert u.test_connection() is False

