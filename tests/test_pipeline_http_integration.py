"""End-to-slice: collect -> real EpubBuilder -> real loopback HTTP -> real SQLite.

Independent oracle comes from tests/fixtures/contracts/pipeline_cases.json
(human-fixed article x device x history), never from needs_sync() etc.
Covers PIPE-01..05, PIPE-10..12. Uses tmp_path only.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import zipfile

import pytest
from unittest.mock import patch

_OS = os
_SYS = sys
_SYS.path.insert(0, _OS.path.join(_OS.path.dirname(__file__), "support"))
from fake_crosspoint_server import FakeCrosspointServer

from websync.config.manager import ConfigManager
from websync.db.history import SyncHistoryDb
from websync.pipeline.service import SyncService
from websync.scrapers.factory import ScraperFactory

CASES = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "contracts", "pipeline_cases.json"), encoding="utf-8"))
ARTICLES = CASES["articles"]


def _article(key: str, site: str = "Blog") -> dict:
    a = ARTICLES[key]
    return {"title": a["title"], "url": a["url"], "content": a["content"], "site_name": site}


def _make_service(root, host, *, devices=None, merge_mode="per_site", sites=None):
    cfg_path = os.path.join(root, "config.json")
    db_path = os.path.join(root, "sync_history.db")
    out_dir = os.path.join(root, "output")
    cm = ConfigManager(cfg_path)
    cfg = cm.load_config()
    cfg["x3_ip"] = host
    cfg["x3_primary_device_id"] = "dev_primary"
    cfg["x3_primary_device_alias_ids"] = []
    cfg["x3_devices"] = devices or []
    cfg["output_dir"] = out_dir
    cfg["epub_cover"] = False
    cfg["epub_merge_mode"] = merge_mode
    cfg["device_files"] = {"default_upload_path": "/Books"}
    cfg["portable_data"] = {"enabled": False}
    cfg["sites"] = sites if sites is not None else [
        {"name": "Blog", "type": "rss", "url": "https://blog.example/feed",
         "limit": 10, "enabled": True}
    ]
    cm.save_config(cfg)
    db = SyncHistoryDb(db_path)
    with patch("websync.pipeline.service.SyncHistoryDb", return_value=db), \
         patch("websync.backup.local_import.import_local_sidecars", return_value={}):
        svc = SyncService(cm)
    return svc, db, cm


def _run_with_articles(svc, articles):
    from unittest.mock import MagicMock

    scraper = MagicMock()
    scraper.fetch_articles.side_effect = lambda _site: [dict(a) for a in articles]
    scraper.last_fetch_stats = {}
    with patch.object(ScraperFactory, "get_scraper", return_value=scraper), \
         patch("websync.pipeline.sync_pipeline.ToastNotifier.show_toast"):
        ok = svc.run_sync_pipeline(log_callback=lambda _m: None)
    return ok


def _uploaded_epub_texts(server) -> list[bytes]:
    with server.state.lock:
        blobs = list(server.state.files.values())
    return blobs


def _epub_contains(blobs: list[bytes], needle: str) -> bool:
    for blob in blobs:
        try:
            with zipfile.ZipFile(__import__("io").BytesIO(blob)) as zf:
                for name in zf.namelist():
                    if name.endswith(".xhtml"):
                        if needle in zf.read(name).decode("utf-8", "replace"):
                            return True
        except zipfile.BadZipFile:
            continue
    return False


def _db_rows(db: SyncHistoryDb) -> list[tuple]:
    conn = sqlite3.connect(db.db_path)
    try:
        return list(conn.execute("SELECT url, device_ip FROM synced_posts"))
    finally:
        conn.close()


def test_PIPE_01_success_records_history_and_valid_epub(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        svc, db, _cm = _make_service(str(tmp_path), srv.host)
        arts = [_article("A"), _article("B")]
        assert _run_with_articles(svc, arts) is True
        assert len(srv.state.uploads) == 1
        blobs = _uploaded_epub_texts(srv)
        assert len(blobs) == 1
        assert _epub_contains(blobs, "https://news.example/a") or _epub_contains(blobs, "아침 글 A")
        assert _epub_contains(blobs, "점심 글 B")
        rows = _db_rows(db)
        urls = {u for u, _k in rows}
        assert "https://news.example/a" in urls and "https://news.example/b" in urls
        # INV-01: only the successful device key recorded
        keys = {k for _u, k in rows}
        assert keys == {"dev_primary"}
    finally:
        srv.stop()


def test_PIPE_02_rerun_sends_nothing(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        svc, db, _cm = _make_service(str(tmp_path), srv.host)
        arts = [_article("A"), _article("B")]
        assert _run_with_articles(svc, arts) is True
        n_uploads = len(srv.state.uploads)
        n_rows = len(_db_rows(db))
        assert _run_with_articles(svc, arts) is True
        assert len(srv.state.uploads) == n_uploads
        assert len(_db_rows(db)) == n_rows
    finally:
        srv.stop()


def test_PIPE_03_incremental_only_new(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        svc, db, _cm = _make_service(str(tmp_path), srv.host)
        assert _run_with_articles(svc, [_article("A"), _article("B")]) is True
        with srv.state.lock:
            srv.state.uploads.clear()
            srv.state.files.clear()
        assert _run_with_articles(svc, [_article("A"), _article("B"), _article("C")]) is True
        assert len(srv.state.uploads) == 1
        blobs = _uploaded_epub_texts(srv)
        assert _epub_contains(blobs, "저녁 글 C")
        assert not _epub_contains(blobs, "아침 글 A")
    finally:
        srv.stop()


def test_PIPE_04_partial_failure_only_success_recorded(tmp_path):
    good = FakeCrosspointServer().start()
    bad = FakeCrosspointServer().start()
    try:
        bad.state.upload_status = 500
        svc, db, _cm = _make_service(
            str(tmp_path), good.host,
            devices=[{"name": "bad", "ip": bad.host, "id": "dev_bad"}],
        )
        arts = [_article("A"), _article("B")]
        ok = _run_with_articles(svc, arts)
        assert ok is False  # partial, not full success
        rows = _db_rows(db)
        by_key: dict[str, set[str]] = {}
        for url, key in rows:
            by_key.setdefault(key, set()).add(url)
        assert by_key.get("dev_primary") == {"https://news.example/a", "https://news.example/b"}
        assert "dev_bad" not in by_key
        assert len(good.state.uploads) == 1
        assert len(bad.state.uploads) == 0
    finally:
        good.stop()
        bad.stop()


def test_PIPE_05_recovery_sends_only_missing(tmp_path):
    good = FakeCrosspointServer().start()
    flaky = FakeCrosspointServer().start()
    try:
        flaky.state.upload_status = 500
        svc, db, _cm = _make_service(
            str(tmp_path), good.host,
            devices=[{"name": "flaky", "ip": flaky.host, "id": "dev_flaky"}],
        )
        arts = [_article("A"), _article("B")]
        assert _run_with_articles(svc, arts) is False
        flaky.state.upload_status = 200
        with good.state.lock, flaky.state.lock:
            good.state.uploads.clear()
            flaky.state.uploads.clear()
            flaky.state.files.clear()
        assert _run_with_articles(svc, arts) is True
        # good device already done -> no resend; flaky gets the missing batch
        assert len(good.state.uploads) == 0
        assert len(flaky.state.uploads) == 1
        rows = _db_rows(db)
        keys = {(u, k) for u, k in rows}
        assert keys == {(url, device) for url in ("https://news.example/a", "https://news.example/b")
                        for device in ("dev_primary", "dev_flaky")}
        assert _run_with_articles(svc, arts) is True
        assert len(good.state.uploads) == 0 and len(flaky.state.uploads) == 1
    finally:
        good.stop()
        flaky.stop()


def test_PIPE_10_selected_only_chosen_articles(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        svc, db, _cm = _make_service(str(tmp_path), srv.host)
        from websync.pipeline.selected_sync import sync_selected_articles

        selected = [
            {"site_name": "Blog", "title": "아침 글 A", "url": "https://news.example/a", "content": "<p>A</p>"},
            {"site_name": "Blog", "title": "저녁 글 C", "url": "https://news.example/c", "content": "<p>C</p>"},
        ]
        with patch("websync.integrations.notifier.ToastNotifier.show_toast"):
            ok = sync_selected_articles(svc, selected, log_callback=lambda _m: None)
        assert ok is True
        blobs = _uploaded_epub_texts(srv)
        assert len(blobs) == 1
        assert _epub_contains(blobs, "아침 글 A")
        assert _epub_contains(blobs, "저녁 글 C")
        assert not _epub_contains(blobs, "점심 글 B")
        rows = _db_rows(db)
        urls = {u for u, _k in rows}
        assert "https://news.example/b" not in urls
    finally:
        srv.stop()


def test_PIPE_11_epub_only_no_upload_no_history(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        svc, db, _cm = _make_service(str(tmp_path), srv.host)
        from websync.pipeline.epub_only import build_selected_epubs
        from unittest.mock import MagicMock

        spy_uploader = MagicMock(wraps=svc.uploader)
        svc.uploader = spy_uploader
        selected = [
            {"site_name": "Blog", "title": "a", "url": "https://news.example/a", "content": "<p>a</p>"},
            {"site_name": "Blog", "title": "b", "url": "https://news.example/b", "content": "<p>b</p>"},
        ]
        paths = build_selected_epubs(svc, selected)
        assert len(paths) == 1 and os.path.isfile(paths[0])
        with zipfile.ZipFile(paths[0]) as zf:
            assert "mimetype" in zf.namelist()
        assert len(srv.state.uploads) == 0
        assert _db_rows(db) == []
        spy_uploader.upload_to_targets.assert_not_called()
    finally:
        srv.stop()


def test_PIPE_12_digest_single_bundle_per_device(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        svc, db, _cm = _make_service(str(tmp_path), srv.host, merge_mode="daily_digest")
        arts = [_article("A"), _article("B")]
        assert _run_with_articles(svc, arts) is True
        assert len(srv.state.uploads) == 1
        blobs = _uploaded_epub_texts(srv)
        assert _epub_contains(blobs, "아침 글 A") and _epub_contains(blobs, "점심 글 B")
        rows = _db_rows(db)
        assert len([r for r in rows if r[0] == "https://news.example/a"]) == 1
    finally:
        srv.stop()


# Duplicate display names must never be used as source identity.
def _same_name_sites():
    return [{"name": "same", "type": "rss", "url": f"https://feed.example/{key}",
             "enabled": True, "translate_to": lang, "include_images": images}
            for key, lang, images in [("a", "ko", False), ("b", "en", True)]]


def _source_scraper():
    from unittest.mock import MagicMock
    scraper = MagicMock()
    scraper.last_fetch_stats = {}
    scraper.fetch_articles.side_effect = lambda site: [{
        "title": "Article " + site["url"][-1],
        "url": "https://news.example/" + site["url"][-1],
        "content": "<p>BODY-" + site["url"][-1] + "</p>",
    }]
    return scraper


def _run_same_name(svc):
    with patch.object(ScraperFactory, "get_scraper", return_value=_source_scraper()), \
         patch("websync.pipeline.sync_pipeline.ToastNotifier.show_toast"):
        return svc.run_sync_pipeline(log_callback=lambda _m: None)


def test_same_name_digest_preserves_both_feeds_and_rerun_is_no_new(tmp_path):
    srv = FakeCrosspointServer().start()
    try:
        svc, db, _cm = _make_service(str(tmp_path), srv.host,
            merge_mode="daily_digest", sites=_same_name_sites())
        assert _run_same_name(svc) is True
        blobs = _uploaded_epub_texts(srv)
        assert len(blobs) == 1
        assert _epub_contains(blobs, "BODY-a") and _epub_contains(blobs, "BODY-b")
        assert _epub_contains(blobs, "same")
        assert not _epub_contains(blobs, "source_")
        assert not _epub_contains(blobs, "https://feed.example/")
        assert set(_db_rows(db)) == {("https://news.example/a", "dev_primary"),
                                     ("https://news.example/b", "dev_primary")}
        assert svc.get_last_pipeline_result()["site_count"] == 2
        assert _run_same_name(svc) is True
        assert svc.get_last_pipeline_result()["status"] == "no_new"
        assert len(srv.state.uploads) == 1
    finally:
        srv.stop()


def test_same_name_digest_asymmetric_history_partial_failure_and_retry(tmp_path):
    good, flaky = FakeCrosspointServer().start(), FakeCrosspointServer().start()
    try:
        svc, db, _cm = _make_service(str(tmp_path), good.host,
            merge_mode="daily_digest", sites=_same_name_sites(),
            devices=[{"name": "flaky", "ip": flaky.host, "id": "dev_flaky"}])
        db.mark_synced("https://news.example/a", "same", "a", device_ip="dev_primary")
        db.mark_synced("https://news.example/b", "same", "b", device_ip="dev_flaky")
        flaky.state.upload_status = 500
        assert _run_same_name(svc) is False
        good_blobs = _uploaded_epub_texts(good)
        assert _epub_contains(good_blobs, "BODY-b")
        assert not _epub_contains(good_blobs, "BODY-a")
        assert ("https://news.example/a", "dev_flaky") not in _db_rows(db)
        flaky.state.upload_status = 200
        assert _run_same_name(svc) is True
        assert len(good.state.uploads) == 1
        assert len(flaky.state.uploads) == 1
        flaky_blobs = _uploaded_epub_texts(flaky)
        assert _epub_contains(flaky_blobs, "BODY-a")
        assert not _epub_contains(flaky_blobs, "BODY-b")
        assert len(_db_rows(db)) == 4
        assert _run_same_name(svc) is True
        assert svc.get_last_pipeline_result()["status"] == "no_new"
    finally:
        good.stop()
        flaky.stop()


@pytest.mark.parametrize("merge_mode", ["daily_digest", "per_site"])
def test_preview_identity_build_only_and_selected_translation(tmp_path, merge_mode):
    from websync.pipeline.preview import preview_articles
    from websync.pipeline.epub_only import build_selected_epubs
    from websync.pipeline.selected_sync import sync_selected_articles
    from websync.pipeline.sources import source_id
    srv = FakeCrosspointServer().start()
    try:
        sites = _same_name_sites()
        svc, db, cm = _make_service(str(tmp_path), srv.host,
            merge_mode=merge_mode, sites=sites)
        with patch.object(ScraperFactory, "get_scraper", return_value=_source_scraper()):
            selected = preview_articles(svc, log_callback=lambda _m: None)
        assert {a["source_id"] for a in selected} == {source_id(site) for site in sites}
        assert [a["include_images"] for a in selected] == [False, True]
        # Reorder and rename after preview: current settings still resolve by URL identity.
        sites.reverse()
        sites[0]["name"] = "renamed"
        cm.patch_fields(sites=sites)
        paths = build_selected_epubs(svc, selected)
        from pathlib import Path
        blobs = [Path(path).read_bytes() for path in paths]
        assert _epub_contains(blobs, "BODY-a") and _epub_contains(blobs, "BODY-b")
        assert _epub_contains(blobs, "renamed")
        assert _db_rows(db) == [] and len(srv.state.uploads) == 0
        with patch("websync.pipeline.selected_sync.Translator") as trans:
            trans.return_value.is_available_for_site.return_value = True
            trans.return_value.translate_html.side_effect = lambda content, target_lang: content + f"<p>LANG-{target_lang}</p>"
            assert sync_selected_articles(svc, selected, log_callback=lambda _m: None) is True
        assert [(call.args[0], call.kwargs["target_lang"])
                for call in trans.return_value.translate_html.call_args_list] == [
                    ("<p>BODY-a</p>", "ko"), ("<p>BODY-b</p>", "en")]
        assert all("LANG-" not in art["content"] for art in selected)
        assert _epub_contains(_uploaded_epub_texts(srv), "LANG-ko")
        assert _epub_contains(_uploaded_epub_texts(srv), "LANG-en")
        assert len(_db_rows(db)) == 2
        # Per-source build-only mode keeps two files even with the original same label.
        cm.patch_fields(sites=_same_name_sites(), epub_merge_mode="per_site")
        paths = build_selected_epubs(svc, selected)
        assert len(paths) == 2 and len(set(paths)) == 2
    finally:
        srv.stop()
