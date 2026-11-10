import time
from unittest.mock import patch
from websync.servers.dashboard.handler import DashboardHandler


class DummyServer:
    def __init__(self):
        self.api_token = "testtoken"
        self.allow_lan = False
        self.get_log_callback = None


def test_dashboard_handler_log_selection_mtime(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    # 알파벳순으로는 먼저 오는 파일이지만 이전 시각에 생성된 old 파일
    old_file = log_dir / "sync_2026-07-01.log"
    old_file.write_text("OLD LOG CONTENT", encoding="utf-8")

    # 다른 파일명이 섞여 있는 상태
    z_file = log_dir / "z_debug.log"
    z_file.write_text("DEBUG LOG CONTENT", encoding="utf-8")

    time.sleep(0.05)

    # 알파벳순으로는 중간이지만 최신 mtime을 가지는 sync 파일
    new_file = log_dir / "sync_2026-07-31.log"
    new_file.write_text("NEWEST LOG CONTENT", encoding="utf-8")

    handler = DashboardHandler.__new__(DashboardHandler)
    handler.path = "/api/log"
    handler.headers = {"Authorization": "Bearer testtoken"}
    handler.server = DummyServer()

    json_payload = {}

    def mock_send_json(code, payload):
        json_payload.update(payload)

    handler._send_json = mock_send_json

    with patch("websync.core.paths.PROJECT_ROOT", str(tmp_path)):
        handler.do_GET()

    assert json_payload.get("log") == "NEWEST LOG CONTENT"
