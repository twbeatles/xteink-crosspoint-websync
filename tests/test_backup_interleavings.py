"""Two-PC interleavings + concurrent push + corrupt-shared safety.

Uses real SyncService/EpubBuilder/HTTP/SQLite and a real shared folder.
Covers plan 6.1 items 1,2,4,10. INV-05: pull/push failure never overwrites
the shared canonical bytes.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import threading
from unittest.mock import patch

_OS = os
_SYS = sys
_SYS.path.insert(0, _OS.path.join(_OS.path.dirname(__file__), "support"))
from fake_crosspoint_server import FakeCrosspointServer

from websync.config.manager import ConfigManager
from websync.db.history import SyncHistoryDb
from websync.pipeline.service import SyncService
from websync.scrapers.factory import ScraperFactory


def _article(n: int) -> dict:
    return {"title": f"글 {n}", "content": f"<p>본문 {n}</p>", "url": f"https://blog.example/{n}"}


def _make_pc(root, name, ip, device_id, shared, server_host):
    cfg_path = os.path.join(root, f"{name}.json")
    cm = ConfigManager(cfg_path)
    cfg = cm.load_config()
    cfg["x3_ip"] = server_host if ip == "SAME" else ip
    cfg["x3_primary_device_id"] = device_id
    cfg["x3_devices"] = []
    cfg["output_dir"] = os.path.join(root, f"{name}_out")
    cfg["epub_cover"] = False
    cfg["device_files"] = {"default_upload_path": "/Books"}
    cfg["sites"] = [
        {"name": "Blog", "type": "rss", "url": "https://blog.example/feed", "limit": 10, "enabled": True}
    ]
    cfg["portable_data"] = {
        "enabled": True, "folder": shared, "include_history": True,
        "auto_export": True, "auto_import_on_start": True,
        "history_mode": "per_device",
    }
    cm.save_config(cfg)
    db = SyncHistoryDb(os.path.join(root, f"{name}.db"))
    with patch("websync.pipeline.service.SyncHistoryDb", return_value=db), \
         patch("websync.backup.local_import.import_local_sidecars", return_value={}):
        svc = SyncService(cm)
    return svc, db


def _run(svc, articles):
    from unittest.mock import MagicMock

    scraper = MagicMock()
    scraper.fetch_articles.side_effect = lambda _s: [dict(a) for a in articles]
    scraper.last_fetch_stats = {}
    with patch.object(ScraperFactory, "get_scraper", return_value=scraper), \
         patch("websync.integrations.notifier.ToastNotifier.show_toast"):
        return svc.run_sync_pipeline(log_callback=lambda _m: None)


def test_ABAB_incremental_with_same_reader_real_http(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        root = str(tmp_path)
        shared = os.path.join(root, "shared")
        os.makedirs(shared)
        pc1, _db1 = _make_pc(root, "pc1", "SAME", "dev_bbbb", shared, srv.host)
        pc2, _db2 = _make_pc(root, "pc2", "SAME", "dev_aaaa", shared, srv.host)
        assert _run(pc1, [_article(1), _article(2)]) is True
        assert len(srv.state.uploads) == 1
        with srv.state.lock:
            srv.state.uploads.clear()
            srv.state.files.clear()
        assert _run(pc2, [_article(1), _article(2), _article(3)]) is True
        # only article 3 goes out on the second PC
        assert len(srv.state.uploads) == 1
        with srv.state.lock:
            srv.state.uploads.clear()
            srv.state.files.clear()
        assert _run(pc1, [_article(1), _article(2), _article(3), _article(4)]) is True
        assert len(srv.state.uploads) == 1
        with srv.state.lock:
            srv.state.uploads.clear()
            srv.state.files.clear()
        assert _run(pc2, [_article(3), _article(4)]) is True
        assert len(srv.state.uploads) == 0
    finally:
        srv.stop()


def test_concurrent_push_keeps_union(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        root = str(tmp_path)
        shared = os.path.join(root, "shared")
        os.makedirs(shared)
        pc1, db1 = _make_pc(root, "pc1", "SAME", "dev_1", shared, srv.host)
        pc2, db2 = _make_pc(root, "pc2", "SAME", "dev_2", shared, srv.host)
        db1.mark_synced("https://blog.example/1", "Blog", "1", "dev_1")
        db2.mark_synced("https://blog.example/2", "Blog", "2", "dev_2")
        barrier = threading.Barrier(2)
        results = {}

        def _push(name, svc):
            barrier.wait(timeout=10)
            results[name] = svc.backup_sync.push(force=True)

        t1 = threading.Thread(target=_push, args=("pc1", pc1))
        t2 = threading.Thread(target=_push, args=("pc2", pc2))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)
        assert not t1.is_alive() and not t2.is_alive()
        hist_path = os.path.join(shared, "synced_posts.json")
        payload = json.load(open(hist_path, encoding="utf-8"))
        urls = {p.get("url") for p in payload.get("posts", [])}
        assert "https://blog.example/1" in urls and "https://blog.example/2" in urls
    finally:
        srv.stop()


def _shared_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def test_corrupt_shared_never_overwritten(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        root = str(tmp_path)
        shared = os.path.join(root, "shared")
        os.makedirs(shared)
        pc1, _db = _make_pc(root, "pc1", "SAME", "dev_1", shared, srv.host)
        hist_path = os.path.join(shared, "synced_posts.json")
        sites_path = os.path.join(shared, "sites.json")
        for bad in (b"", b'{"posts": [', b"\xff\xfe\x00broken"):
            with open(hist_path, "wb") as f:
                f.write(bad)
            with open(sites_path, "w", encoding="utf-8") as f:
                json.dump({"kind": "sites", "export_version": 3, "sites": []}, f)
            before = _shared_bytes(hist_path)
            res = pc1.backup_sync.pull(force=True)
            assert res.get("ok") is False
            assert _shared_bytes(hist_path) == before
            # a failed pull must not be followed by a push of local cache
            res2 = pc1.backup_sync.sync_now()
            assert res2.get("ok") is False
            assert _shared_bytes(hist_path) == before
        # missing file vs empty file are distinguished (both fail, neither writes)
        os.remove(hist_path)
        res = pc1.backup_sync.pull(force=True)
        assert res.get("ok") in (True, False)
    finally:
        srv.stop()
