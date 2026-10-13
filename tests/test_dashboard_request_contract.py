"""Single-shot mutations and bounded persistent HTTP request framing."""
import pytest
import requests

from websync.servers.dashboard.service import WebDashboard
from websync.servers.dashboard.templates_loader import dashboard_html


def test_single_shot_post_framing_auth_and_cancel():
    calls = []
    server = WebDashboard(port=0, api_token="test-token",
                          sync_callback=lambda: calls.append("sync") or True,
                          cancel_callback=lambda: calls.append("cancel") or True)
    assert server.start()
    try:
        with requests.Session() as session:
            session.trust_env = False
            base = f"http://127.0.0.1:{server.port}"
            headers = {"Authorization": "Bearer test-token"}
            for body in (None, {}, {"payload": "hello"}):
                for _ in range(10):
                    kwargs = {} if body is None else {"json": body}
                    assert session.post(base + "/api/sync", headers=headers, timeout=5, **kwargs).status_code == 202
            assert len(calls) == 30
            assert session.post(base + "/api/sync", json={"discard": True}, timeout=5).status_code == 401
            assert len(calls) == 30
            assert session.get(base + "/api/status", headers=headers, timeout=5).status_code == 200
            assert session.post(base + "/api/cancel", json={}, headers=headers, timeout=5).status_code == 200
            assert calls[-1] == "cancel"
    finally:
        server.stop()


@pytest.mark.parametrize("length", ["-1", "invalid", "65537"])
def test_invalid_post_size_rejected_before_callback(length):
    import http.client
    calls = []
    server = WebDashboard(port=0, api_token="test-token", sync_callback=lambda: calls.append(1))
    assert server.start()
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    try:
        conn.request("POST", "/api/sync", headers={"Content-Length": length, "Authorization": "Bearer test-token"})
        response = conn.getresponse()
        assert response.status == 400
        response.read()
        assert not calls
    finally:
        conn.close()
        server.stop()


def test_dashboard_ui_cancel_and_log_polling():
    html = dashboard_html()
    assert "{{i18n." not in html
    assert "controlSync('/api/cancel')" in html
    assert "Promise.all([refreshStatus(), refreshLog()])" in html
    assert "setInterval(refreshAll, 5000)" in html
    assert "AbortController" in html


def test_dashboard_control_translations_survive_utf8():
    from websync.i18n import init_i18n, t
    init_i18n("ko")
    assert t("dashboard.cancel_sync") == "동기화 취소"
    assert "상태를 새로고침" in t("dashboard.request_error")
    assert "동기화 취소" in dashboard_html()
    init_i18n("en")
    assert t("dashboard.cancel_sync") == "Cancel sync"
    assert "Refresh status" in t("dashboard.request_error")
