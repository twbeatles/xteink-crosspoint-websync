"""요약·번역 루프 안에서의 취소, load_config 보강 저장의 revision (2026-11-02 감사 후속)."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "support"))
from fake_crosspoint_server import FakeCrosspointServer

from websync.config.exceptions import ConfigConflictError
from websync.config.manager import ConfigManager
from websync.db.history import SyncHistoryDb
from websync.pipeline.service import SyncService
from websync.scrapers.factory import ScraperFactory


def _service(root, host):
    cm = ConfigManager(os.path.join(root, "config.json"))
    cfg = cm.load_config()
    cfg["x3_ip"] = host
    cfg["x3_primary_device_id"] = "dev_primary"
    cfg["x3_devices"] = []
    cfg["output_dir"] = os.path.join(root, "output")
    cfg["epub_cover"] = False
    cfg["portable_data"] = {"enabled": False}
    cfg["sites"] = [
        {
            "name": "S",
            "type": "rss",
            "url": "https://s.example/feed",
            "limit": 10,
            "enabled": True,
        }
    ]
    cm.save_config(cfg)
    db = SyncHistoryDb(os.path.join(root, "sync_history.db"))
    return SyncService(cm, db=db, sidecar_root=root), db


def _articles(n):
    return [
        {"title": f"t{i}", "url": f"https://s.example/{i}", "content": "<p>x</p>"}
        for i in range(n)
    ]


class _CancellingSummarizer:
    """두 번째 기사 요약 중 취소가 요청되는 느린 요약기 대역."""

    service = None
    calls = 0

    def __init__(self, config, logger=None):
        pass

    def is_available(self):
        return True

    def summarize(self, title, content):
        type(self).calls += 1
        if type(self).calls == 2:
            type(self).service.request_cancel()
        return "<p>요약</p>"


def _rows(db):
    conn = sqlite3.connect(db.db_path)
    try:
        return list(conn.execute("SELECT url FROM synced_posts"))
    finally:
        conn.close()


def test_full_sync_cancels_inside_summary_loop(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        svc, db = _service(str(tmp_path), srv.host)
        _CancellingSummarizer.service = svc
        _CancellingSummarizer.calls = 0
        scraper = MagicMock()
        scraper.fetch_articles.side_effect = lambda site: _articles(10)
        scraper.last_fetch_stats = {}
        with (
            patch.object(ScraperFactory, "get_scraper", return_value=scraper),
            patch("websync.pipeline.sync_pipeline.Summarizer", _CancellingSummarizer),
            patch("websync.integrations.notifier.ToastNotifier.show_toast"),
        ):
            assert svc.run_sync_pipeline(log_callback=lambda _m: None) is False
        # 10개를 끝까지 요약하지 않고 다음 기사 직전에 멈춘다
        assert _CancellingSummarizer.calls == 2
        assert svc.get_last_pipeline_result()["status"] == "cancelled"
        assert srv.state.uploads == [] or len(srv.state.uploads) == 0
        assert _rows(db) == []
        assert not svc.is_pipeline_running()
    finally:
        srv.stop()


def test_selected_sync_cancels_inside_summary_loop(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        svc, db = _service(str(tmp_path), srv.host)
        _CancellingSummarizer.service = svc
        _CancellingSummarizer.calls = 0
        selected = [dict(a, site_name="S") for a in _articles(5)]
        with patch("websync.pipeline.selected_sync.Summarizer", _CancellingSummarizer):
            assert (
                svc.sync_selected_articles(selected, log_callback=lambda _m: None)
                is False
            )
        assert _CancellingSummarizer.calls == 2
        assert svc.get_last_pipeline_result()["status"] == "cancelled"
        assert len(srv.state.uploads) == 0
        assert _rows(db) == []
    finally:
        srv.stop()


def test_load_config_normalize_save_bumps_revision(tmp_path):
    """자동 보강(새 기기 ID)이 저장되면 그보다 오래된 revision의 CAS 저장은 충돌한다."""
    path = tmp_path / "config.json"
    cm = ConfigManager(str(path))
    cfg = cm.load_config()
    cfg["x3_devices"] = [{"name": "침실", "ip": "192.168.1.20", "id": ""}]
    cm.save_config(cfg)
    raw = json.loads(path.read_text(encoding="utf-8"))
    stale_rev = raw["_config_revision"]
    raw["x3_devices"][0]["id"] = (
        ""  # ID 없는 장치가 디스크에 있는 상태(수동 편집·구버전)
    )
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    loaded = ConfigManager(str(path)).load_config()  # 다른 프로세스가 ID를 부여·저장
    assigned = loaded["x3_devices"][0]["id"]
    assert assigned.startswith("dev_")
    assert loaded["_config_revision"] > stale_rev

    stale = dict(raw)
    try:
        cm.save_config(stale, expected_revision=stale_rev)
    except ConfigConflictError:
        pass
    else:  # pragma: no cover - 회귀 시 메시지
        raise AssertionError("stale writer overwrote the assigned device id")
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["x3_devices"][0]["id"] == assigned
