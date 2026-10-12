"""Crash-consistency: atomic JSON replace + SQLite commit windows (plan 6.1.11).

Real failpoints (not timeouts): write fails before/after os.replace, and
SQLite commit failure. Asserts no torn shared JSON and no false success.
"""
from __future__ import annotations

import json
import os
from unittest.mock import patch

from websync.backup.atomic_io import write_json_atomic
from websync.config.manager import ConfigManager
from websync.db.history import SyncHistoryDb, SyncHistoryDbError
from websync.pipeline.service import SyncService
from websync.scrapers.factory import ScraperFactory


def test_atomic_replace_failure_keeps_prior_bytes(tmp_path):
    target = os.path.join(str(tmp_path), "sites.json")
    write_json_atomic(target, {"kind": "sites", "sites": [{"url": "https://a.example"}]})
    before = open(target, "rb").read()
    with patch("websync.backup.atomic_io.os.replace", side_effect=OSError("power cut")):
        try:
            write_json_atomic(target, {"kind": "sites", "sites": []})
        except OSError:
            pass
    assert open(target, "rb").read() == before
    assert json.load(open(target, encoding="utf-8"))["sites"][0]["url"] == "https://a.example"


def test_sqlite_commit_failure_reports_db_error_not_success(tmp_path):
    import sys as _sys
    import os as _os
    _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "support"))
    from fake_crosspoint_server import FakeCrosspointServer

    srv = FakeCrosspointServer().start()
    try:
        root = str(tmp_path)
        cm = ConfigManager(os.path.join(root, "config.json"))
        cfg = cm.load_config()
        cfg["x3_ip"] = srv.host
        cfg["x3_primary_device_id"] = "dev_primary"
        cfg["x3_devices"] = []
        cfg["output_dir"] = os.path.join(root, "output")
        cfg["epub_cover"] = False
        cfg["device_files"] = {"default_upload_path": "/Books"}
        cfg["portable_data"] = {"enabled": False}
        cfg["sites"] = [
            {"name": "Blog", "type": "rss", "url": "https://blog.example/feed", "limit": 5, "enabled": True}
        ]
        cm.save_config(cfg)
        db = SyncHistoryDb(os.path.join(root, "s.db"))
        with patch("websync.pipeline.service.SyncHistoryDb", return_value=db), \
             patch("websync.backup.local_import.import_local_sidecars", return_value={}):
            svc = SyncService(cm)
        from unittest.mock import MagicMock

        scraper = MagicMock()
        scraper.fetch_articles.return_value = [
            {"title": "t", "url": "https://x.example/crash", "content": "<p>c</p>"}
        ]
        scraper.last_fetch_stats = {}
        with patch.object(ScraperFactory, "get_scraper", return_value=scraper), \
             patch("websync.db.history.sqlite3.connect", side_effect=SyncHistoryDbError("disk full")), \
             patch("websync.integrations.notifier.ToastNotifier.show_toast"):
            ok = svc.run_sync_pipeline(log_callback=lambda _m: None)
        assert ok is False
        assert svc.get_last_pipeline_result().get("success") is False
    finally:
        srv.stop()
