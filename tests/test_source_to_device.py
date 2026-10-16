"""Real scraper -> EPUB -> HTTP upload -> persisted SQLite user journeys.

Only desktop notifications are disabled. No scraper, builder, uploader or DB
method is replaced; the content origin and reader run on loopback sockets.
"""
import io
import logging
import sqlite3
import zipfile
from xml.etree import ElementTree as ET

import pytest

from support.fake_crosspoint_server import FakeCrosspointServer
from support.source_server import source_server
from websync.config.manager import ConfigManager
from websync.core.process_lock import ProcessFileLock
from websync.db.history import SyncHistoryDb
from websync.pipeline.service import SyncService


def make_service(root, host, sites=None, mode="per_site"):
    manager = ConfigManager(str(root / "config.json"))
    if sites is not None:
        manager.patch_fields(
            x3_ip=host, x3_primary_device_id="dev_reader", x3_devices=[],
            sites=sites, epub_cover=False, epub_merge_mode=mode,
            output_dir=str(root / "output"),
            device_files={"default_upload_path": "/Books/News"},
            portable_data={"enabled": False},
        )
    return SyncService(
        manager, db=SyncHistoryDb(str(root / "history.db")),
        process_lock=ProcessFileLock(str(root / "pipeline.lock")),
        sidecar_root=str(root), output_dir=str(root / "output"),
        logger=logging.getLogger("source-to-device"),
    )


def rows(root):
    # A separate connection proves data was committed, not just cached in service.
    with sqlite3.connect(root / "history.db") as connection:
        return set(connection.execute("SELECT url, device_ip FROM synced_posts"))


def chapter_text(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert archive.testzip() is None
        assert archive.read("mimetype") == b"application/epub+zip"
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        opf = container.find(".//{*}rootfile").attrib["full-path"]
        package = ET.fromstring(archive.read(opf))
        manifest = {item.attrib["id"]: item.attrib["href"]
                    for item in package.find("{*}manifest")}
        base = opf.rpartition("/")[0]
        chapters = []
        for item in package.find("{*}spine"):
            path = manifest[item.attrib["idref"]]
            document = ET.fromstring(archive.read(f"{base}/{path}" if base else path))
            assert document.find("{*}body") is not None
            chapters.append(" ".join(document.itertext()))
        return " ".join(chapters)


def feed(origin, *ids):
    items = "".join(
        f"<item><title>기사 {key}</title><link>{origin}/posts/{key}</link>"
        f"<description><![CDATA[<p>RSS-BODY-{key} {'충분한 본문입니다. ' * 12}</p>]]>"
        "</description></item>" for key in ids
    )
    return 200, {"Content-Type": "application/rss+xml"}, (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0">'
        f"<channel><title>News</title>{items}</channel></rss>"
    )


@pytest.fixture
def journey(monkeypatch):
    monkeypatch.setattr("websync.integrations.notifier.ToastNotifier.show_toast", lambda *a, **k: None)
    # Ignore machine proxy settings, retaining the production adapter and retries.
    from websync.scrapers.base import _session
    monkeypatch.setattr(_session, "trust_env", False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    with source_server() as source, FakeCrosspointServer() as reader:
        yield (*source, reader)


def sites_for(origin):
    return [
        {"name": "RSS 뉴스", "type": "rss", "url": origin + "/feed", "limit": 10, "enabled": True},
        {"name": "개발 블로그", "type": "css", "url": origin + "/list", "limit": 10,
         "enabled": True, "item_selector": ".post", "title_selector": "h2",
         "link_selector": "a", "content_selector": "article", "fetch_detail_page": True,
         "remove_selectors": ".ad", "include_images": False},
    ]


def install_content(origin, routes):
    routes["/feed"] = feed(origin, "A")
    routes["/list"] = (200, {"Content-Type": "text/html; charset=utf-8"},
                       '<div class="post"><h2>개발 이야기</h2><a href="/detail">read</a></div>')
    routes["/detail"] = (200, {"Content-Type": "text/html; charset=utf-8"},
                         f'<article><p>CSS-DETAIL-BODY {"실제 상세 본문입니다. " * 12}</p>'
                         '<aside class="ad">AD-MUST-BE-REMOVED</aside>'
                         '<img src="/must-not-fetch.png"/></article>')


@pytest.mark.parametrize("mode", ["per_site", "daily_digest"])
def test_real_sources_incremental_sync_survives_service_restart(tmp_path, journey, mode):
    origin, routes, requests, reader = journey
    install_content(origin, routes)
    service = make_service(tmp_path, reader.host, sites_for(origin), mode)
    assert service.run_sync_pipeline(log_callback=lambda _: None) is True
    first_count = 2 if mode == "per_site" else 1
    assert len(reader.state.uploads) == first_count
    texts = [chapter_text(blob) for blob in reader.state.files.values()]
    assert sum("RSS-BODY-A" in text for text in texts) == 1
    assert sum("CSS-DETAIL-BODY" in text for text in texts) == 1
    assert all("AD-MUST-BE-REMOVED" not in text for text in texts)
    assert "/must-not-fetch.png" not in requests
    assert all(upload["dest"] == "/Books/News" for upload in reader.state.uploads)
    assert rows(tmp_path) == {(origin + "/posts/A", "dev_reader"), (origin + "/detail", "dev_reader")}

    # New objects read the saved config + DB, then see one new feed article.
    routes["/feed"] = feed(origin, "A", "B")
    restarted = make_service(tmp_path, reader.host)
    assert restarted.run_sync_pipeline(log_callback=lambda _: None) is True
    assert len(reader.state.uploads) == first_count + 1
    last = reader.state.uploads[-1]
    text = chapter_text(reader.state.files[last["path"]])
    assert "RSS-BODY-B" in text
    assert "RSS-BODY-A" not in text and "CSS-DETAIL-BODY" not in text
    assert rows(tmp_path) == {(origin + path, "dev_reader") for path in ("/posts/A", "/posts/B", "/detail")}
    assert restarted.run_sync_pipeline(log_callback=lambda _: None) is True
    assert restarted.get_last_pipeline_result()["status"] == "no_new"
    assert len(reader.state.uploads) == first_count + 1
    assert set(requests) == {"/feed", "/list", "/detail"}


def test_real_preview_build_only_then_selected_upload(tmp_path, journey):
    origin, routes, requests, reader = journey
    install_content(origin, routes)
    service = make_service(tmp_path, reader.host, sites_for(origin))
    preview = service.preview_articles(log_callback=lambda _: None)
    assert {article["url"] for article in preview} == {origin + "/posts/A", origin + "/detail"}
    assert rows(tmp_path) == set() and reader.state.uploads == []
    chosen = [next(article for article in preview if article["url"].endswith("/detail"))]
    paths = service.build_selected_epubs(chosen, log_callback=lambda _: None)
    assert len(paths) == 1
    with open(paths[0], "rb") as output:
        text = chapter_text(output.read())
    assert "CSS-DETAIL-BODY" in text and "RSS-BODY-A" not in text
    assert rows(tmp_path) == set() and reader.state.uploads == []
    before_requests = list(requests)
    assert service.sync_selected_articles(chosen, log_callback=lambda _: None) is True
    assert requests == before_requests  # Selection uses the captured preview body.
    assert len(reader.state.uploads) == 1
    text = chapter_text(next(iter(reader.state.files.values())))
    assert "CSS-DETAIL-BODY" in text and "RSS-BODY-A" not in text
    assert rows(tmp_path) == {(origin + "/detail", "dev_reader")}


@pytest.mark.parametrize("mode", ["per_site", "daily_digest"])
def test_real_source_error_recovers_without_resending_success(tmp_path, journey, mode):
    origin, routes, requests, reader = journey
    install_content(origin, routes)
    routes["/feed"] = (404, {}, "feed temporarily unavailable")
    service = make_service(tmp_path, reader.host, sites_for(origin), mode)
    assert service.run_sync_pipeline(log_callback=lambda _: None) is False
    assert rows(tmp_path) == {(origin + "/detail", "dev_reader")}
    assert len(reader.state.uploads) == 1
    assert "CSS-DETAIL-BODY" in chapter_text(next(iter(reader.state.files.values())))
    assert service.get_last_pipeline_result()["site_errors"] == 1
    assert not service.is_pipeline_running()
    routes["/feed"] = feed(origin, "A")
    assert service.run_sync_pipeline(log_callback=lambda _: None) is True
    assert len(reader.state.uploads) == 2
    text = chapter_text(reader.state.files[reader.state.uploads[-1]["path"]])
    assert "RSS-BODY-A" in text and "CSS-DETAIL-BODY" not in text
    assert rows(tmp_path) == {(origin + "/detail", "dev_reader"), (origin + "/posts/A", "dev_reader")}
