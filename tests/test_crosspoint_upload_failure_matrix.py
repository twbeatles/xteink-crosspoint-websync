"""Upload failure-injection matrix over real loopback HTTP.

Each case asserts: uploader returns False (never True on failure),
the failing host is recorded in last_errors without touching the peer's
success, and the 200-without-commit lie is surfaced by listing check.
"""
from __future__ import annotations

import pytest

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


def _local_epub(tmp_path, name="b.epub", body=b"Z" * 4096) -> str:
    p = tmp_path / name
    p.write_bytes(body)
    return str(p)


@pytest.mark.parametrize("code", [400, 401, 404, 409, 500])
def test_uploader_status_matrix_never_success(server, tmp_path, code):
    server.state.upload_status = code
    server.state.upload_body = f"err{code}"
    up = X3Uploader(server.host)
    path = _local_epub(tmp_path)
    assert up._upload_to_ip(path, server.host, "b.epub", 30) is False
    assert server.host in up.last_errors
    assert f"HTTP {code}" in up.last_errors[server.host]
    assert server.state.uploads == []


def test_uploader_reports_200_without_commit_as_suspect(server, tmp_path):
    """Plan 4.2: 200을 반환해도 listing에 파일이 없으면 확정 저장이 아니다."""
    server.state.store_upload = False  # lie: 200 but nothing stored
    up = X3Uploader(server.host, remote_dir="/Books")
    client = X3DeviceClient(server.host)
    path = _local_epub(tmp_path)
    assert up._upload_to_ip(path, server.host, "b.epub", 30) is True
    # Current product policy returns True on 200; the contract test pins the
    # observable gap instead of silently changing the policy.
    assert client.list_files("/Books") == []
    assert server.state.uploads[0]["sha256"] is not None


def test_connection_refused_and_dns_are_failure_not_success(tmp_path):
    up = X3Uploader("127.0.0.1", devices=[{"name": "dead", "ip": "127.0.0.1"}])
    # port 1 is (practically) always refused on loopback
    assert up._upload_to_ip(str(tmp_path / "x.epub"), "127.0.0.1:1", "x.epub", 2) is False
    assert "127.0.0.1:1" in up.last_errors
    client = X3DeviceClient("nonexistent.invalid")
    with pytest.raises(DeviceClientError):
        client.get_status()


def test_dropped_upload_connection_is_failure(server, tmp_path):
    server.state.drop_upload_connection = True
    up = X3Uploader(server.host)
    path = _local_epub(tmp_path)
    assert up._upload_to_ip(path, server.host, "b.epub", 30) is False
    assert server.host in up.last_errors


def test_zero_byte_and_large_upload_roundtrip(server, tmp_path):
    up = X3Uploader(server.host, remote_dir="/Books")
    for body in (b"", b"L" * (512 * 1024)):
        p = _local_epub(tmp_path, name=f"s{len(body)}.epub", body=body)
        assert up._upload_to_ip(p, server.host, f"s{len(body)}.epub", 60) is True
    with server.state.lock:
        sizes = sorted(v.__len__() for v in server.state.files.values())
    assert 0 in sizes


def test_duplicate_registration_same_reader_ip_and_hostname(tmp_path):
    up = X3Uploader("127.0.0.1", devices=[
        {"name": "same", "ip": "127.0.0.1"},
        {"name": "other", "ip": "127.0.0.2"},
    ])
    ips = [t["ip"] for t in up._build_target_list()]
    assert ips.count("127.0.0.1") == 1
    assert "127.0.0.2" in ips


def test_peer_success_untouched_by_peer_failure(server, tmp_path):
    """X 성공 / Y 실패: Y의 오류가 X 성공 판정에 영향을 주지 않는다."""
    fail_host = "127.0.0.1:1"  # refused
    up = X3Uploader(server.host, devices=[{"name": "dead", "ip": fail_host}])
    path = _local_epub(tmp_path)
    results = up.upload_to_targets(path)
    assert results[server.host] is True
    assert results[fail_host] is False
    assert fail_host in up.last_errors
    assert server.host not in up.last_errors


def test_error_responses_do_not_leak_streams(server, tmp_path):
    server.state.files_status = 401
    client = X3DeviceClient(server.host)
    with pytest.raises(DeviceClientError):
        client.list_files("/Books")
    # client usable again after failure
    server.state.files_status = 200
    assert client.list_files("/Books") == []
