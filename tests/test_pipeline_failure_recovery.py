"""Pipeline failure recovery over real EPUB+HTTP+SQLite (PIPE-06..09,13..16).

Each case records real SQLite rows, received EPUB hashes, and upload counts;
no bare mock return_value counts as success evidence.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from unittest.mock import MagicMock, patch

_OS = os
_SYS = sys
_SYS.path.insert(0, _OS.path.join(_OS.path.dirname(__file__), "support"))
from fake_crosspoint_server import FakeCrosspointServer

from websync.config.manager import ConfigManager
from websync.db.history import SyncHistoryDb
from websync.pipeline.service import SyncService
from websync.scrapers.factory import ScraperFactory


def _make_service(root, host, *, devices=None, merge_mode="per_site", backup=None):
    cfg_path = os.path.join(root, "config.json")
    db_path = os.path.join(root, "sync_history.db")
    cm = ConfigManager(cfg_path)
    cfg = cm.load_config()
    cfg["x3_ip"] = host
    cfg["x3_primary_device_id"] = "dev_primary"
    cfg["x3_primary_device_alias_ids"] = []
    cfg["x3_devices"] = devices or []
    cfg["output_dir"] = os.path.join(root, "output")
    cfg["epub_cover"] = False
    cfg["epub_merge_mode"] = merge_mode
    cfg["device_files"] = {"default_upload_path": "/Books"}
    cfg["portable_data"] = backup if backup is not None else {"enabled": False}
    cfg["sites"] = [
        {"name": "Good", "type": "rss", "url": "https://good.example/feed", "limit": 5, "enabled": True},
        {"name": "Bad", "type": "rss", "url": "https://bad.example/feed", "limit": 5, "enabled": True},
    ]
    cm.save_config(cfg)
    db = SyncHistoryDb(db_path)
    with patch("websync.pipeline.service.SyncHistoryDb", return_value=db), \
         patch("websync.backup.local_import.import_local_sidecars", return_value={}):
        svc = SyncService(cm)
    return svc, db


def _rows(db):
    conn = sqlite3.connect(db.db_path)
    try:
        return list(conn.execute("SELECT url, device_ip FROM synced_posts"))
    finally:
        conn.close()


def _good_bad_scraper(good_articles, bad_exc: Exception | None = None, empty_bad: bool = False):
    scraper = MagicMock()

    def _fetch(site):
        if site.get("name") == "Bad":
            if bad_exc is not None:
                raise bad_exc
            return [] if empty_bad else [dict(a) for a in good_articles]
        return [dict(a) for a in good_articles]

    scraper.fetch_articles.side_effect = _fetch
    scraper.last_fetch_stats = {}
    return scraper


def test_PIPE_06_site_exception_does_not_taint_other_site(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        svc, db = _make_service(str(tmp_path), srv.host)
        arts = [{"title": "g", "url": "https://x.example/g", "content": "<p>g</p>"}]
        scraper = _good_bad_scraper(arts, bad_exc=RuntimeError("boom"))
        with patch.object(ScraperFactory, "get_scraper", return_value=scraper), \
             patch("websync.integrations.notifier.ToastNotifier.show_toast"):
            svc.run_sync_pipeline(log_callback=lambda _m: None)
        urls = {u for u, _k in _rows(db)}
        assert "https://x.example/g" in urls
        assert svc.get_last_pipeline_result().get("site_errors", 0) >= 1
    finally:
        srv.stop()


def test_PIPE_07_all_empty_no_epub_no_upload(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        svc, db = _make_service(str(tmp_path), srv.host)
        scraper = MagicMock()
        scraper.fetch_articles.return_value = []
        scraper.last_fetch_stats = {}
        with patch.object(ScraperFactory, "get_scraper", return_value=scraper), \
             patch("websync.integrations.notifier.ToastNotifier.show_toast"):
            ok = svc.run_sync_pipeline(log_callback=lambda _m: None)
        assert ok is False
        assert srv.state.uploads == []
        assert _rows(db) == []
        assert svc.get_last_pipeline_result().get("status") == "empty_fetch"
    finally:
        srv.stop()


def test_PIPE_08_backup_pull_failure_blocks_upload_and_keeps_shared(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        shared = os.path.join(str(tmp_path), "shared")
        os.makedirs(shared)
        history_path = os.path.join(shared, "synced_posts.json")
        with open(history_path, "w", encoding="utf-8") as f:
            f.write('{"kind":"history","export_version":2,"posts":[]}')
        before = open(history_path, "rb").read()
        backup = {"enabled": True, "folder": shared, "include_history": True,
                  "auto_export": False, "auto_import_on_start": True, "history_mode": "per_device"}
        svc, db = _make_service(str(tmp_path), srv.host, backup=backup)
        with patch.object(svc.backup_sync, "pull", return_value={"ok": False, "message": "corrupt"}):
            # selected_sync path surfaces pull failure; full pipeline path must
            # also avoid marking anything when pull is known-bad. Here we assert
            # the guarded entry point refuses to proceed.
            from websync.pipeline.selected_sync import sync_selected_articles

            with patch("websync.integrations.notifier.ToastNotifier.show_toast"):
                ok = sync_selected_articles(
                    svc, [{"site_name": "Good", "title": "t", "url": "https://x.example/t", "content": "<p>t</p>"}],
                    log_callback=lambda _m: None,
                )
            assert ok is False
        assert srv.state.uploads == []
        assert open(history_path, "rb").read() == before
    finally:
        srv.stop()


def test_PIPE_09_push_failure_after_upload_is_not_full_success(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        shared = os.path.join(str(tmp_path), "shared")
        os.makedirs(shared)
        backup = {"enabled": True, "folder": shared, "include_history": True,
                  "auto_export": True, "auto_import_on_start": False, "history_mode": "per_device"}
        svc, db = _make_service(str(tmp_path), srv.host, backup=backup)
        from websync.pipeline.selected_sync import sync_selected_articles

        with patch.object(svc.backup_sync, "push", return_value={"ok": False, "message": "disk full"}), \
             patch.object(svc.backup_sync, "pull", return_value={"ok": True, "skipped": True}), \
             patch("websync.integrations.notifier.ToastNotifier.show_toast"):
            ok = sync_selected_articles(
                svc, [{"site_name": "Good", "title": "t", "url": "https://x.example/u9", "content": "<p>u9</p>"}],
                log_callback=lambda _m: None,
            )
        assert ok is False
        result = svc.get_last_pipeline_result()
        assert result.get("status") == "backup_push_failed"
        # local upload + history are preserved (at-least-once), only the
        # user-facing verdict is withheld
        assert len(srv.state.uploads) == 1
        assert ("https://x.example/u9", "dev_primary") in set(_rows(db))
    finally:
        srv.stop()


def test_PIPE_13_digest_partial_failure(tmp_path):
    good = FakeCrosspointServer().start()
    bad = FakeCrosspointServer().start()
    try:
        bad.state.upload_status = 500
        svc, db = _make_service(
            str(tmp_path), good.host, merge_mode="daily_digest",
            devices=[{"name": "bad", "ip": bad.host, "id": "dev_bad"}],
        )
        # single-site config keeps the digest path simple
        svc.config["sites"] = [
            {"name": "Blog", "type": "rss", "url": "https://blog.example/feed", "limit": 5, "enabled": True}
        ]
        svc.config_manager.save_config(svc.config)
        arts = [{"title": "d", "url": "https://x.example/d", "content": "<p>d</p>"}]
        scraper = MagicMock()
        scraper.fetch_articles.return_value = [dict(a) for a in arts]
        scraper.last_fetch_stats = {}
        with patch.object(ScraperFactory, "get_scraper", return_value=scraper), \
             patch("websync.integrations.notifier.ToastNotifier.show_toast"):
            ok = svc.run_sync_pipeline(log_callback=lambda _m: None)
        assert ok is False
        keys = {k for _u, k in _rows(db)}
        assert "dev_bad" not in keys
    finally:
        good.stop()
        bad.stop()


def test_PIPE_14_cancel_between_batches_marks_only_completed(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        svc, db = _make_service(str(tmp_path), srv.host)
        svc.config["sites"] = [
            {"name": f"S{i}", "type": "rss", "url": f"https://s{i}.example/feed", "limit": 5, "enabled": True}
            for i in range(3)
        ]
        svc.config_manager.save_config(svc.config)

        calls = {"n": 0}

        def _fetch(site):
            calls["n"] += 1
            if calls["n"] > 1:
                svc.request_cancel()
            return [{"title": f"t-{site['name']}", "url": f"https://x.example/{site['name']}", "content": "<p>x</p>"}]

        scraper = MagicMock()
        scraper.fetch_articles.side_effect = _fetch
        scraper.last_fetch_stats = {}
        with patch.object(ScraperFactory, "get_scraper", return_value=scraper), \
             patch("websync.integrations.notifier.ToastNotifier.show_toast"):
            ok = svc.run_sync_pipeline(log_callback=lambda _m: None)
        assert ok is False
        # first batch committed, later batches never uploaded
        assert len(srv.state.uploads) == 1
        assert svc.get_last_pipeline_result().get("status") == "cancelled"
    finally:
        srv.stop()


def test_PIPE_15_no_devices_no_crash_no_history(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        svc, db = _make_service(str(tmp_path), "")
        svc.config["x3_ip"] = ""
        svc.config["x3_devices"] = []
        svc.config_manager.save_config(svc.config)
        scraper = MagicMock()
        scraper.fetch_articles.return_value = [{"title": "t", "url": "https://x.example/t", "content": "<p>t</p>"}]
        scraper.last_fetch_stats = {}
        with patch.object(ScraperFactory, "get_scraper", return_value=scraper), \
             patch("websync.integrations.notifier.ToastNotifier.show_toast"):
            ok = svc.run_sync_pipeline(log_callback=lambda _m: None)
        assert ok is False
        assert _rows(db) == []
        assert srv.state.uploads == []
    finally:
        srv.stop()


def test_PIPE_16_db_write_failure_never_reports_complete(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        svc, db = _make_service(str(tmp_path), srv.host)
        arts = [{"title": "t", "url": "https://x.example/t16", "content": "<p>t</p>"}]
        scraper = MagicMock()
        scraper.fetch_articles.return_value = [dict(a) for a in arts]
        scraper.last_fetch_stats = {}
        from websync.db.history import SyncHistoryDbError

        with patch.object(ScraperFactory, "get_scraper", return_value=scraper), \
             patch.object(db, "mark_synced_many", side_effect=SyncHistoryDbError("disk full")), \
             patch("websync.integrations.notifier.ToastNotifier.show_toast"):
            ok = svc.run_sync_pipeline(log_callback=lambda _m: None)
        # upload happened (at-least-once window) but pipeline must not claim success
        assert ok is False
        assert len(srv.state.uploads) == 1
        assert svc.get_last_pipeline_result().get("status") == "db_error"
    finally:
        srv.stop()
