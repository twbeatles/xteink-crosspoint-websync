"""여러 PC · 같은 리더기 — 실제 동기화 파이프라인 회귀 테스트.

증상(v1.2.4 이전): PC마다 리더기 주소가 다르게 적혀(DHCP IP / crosspoint.local)
기기 ID가 합쳐지지 않아, 다른 PC가 이미 보낸 글이 새 글과 섞여 다시 전송됐다.
"""
import os
import shutil
import tempfile
from unittest.mock import patch

import pytest

from websync.config.manager import ConfigManager
from websync.db.history import SyncHistoryDb
from websync.epub.builder import EpubBuilder
from websync.pipeline.service import SyncService
from websync.scrapers.factory import ScraperFactory
from websync.upload.uploader import X3Uploader


def _article(n: int) -> dict:
    return {"title": f"글 {n}", "content": f"<p>{n}</p>", "url": f"https://blog.example/{n}"}


def _make_pc(root: str, name: str, ip: str, device_id: str, cloud: str) -> SyncService:
    cm = ConfigManager(os.path.join(root, f"{name}.json"))
    cfg = cm.load_config()
    cfg["x3_ip"] = ip
    cfg["x3_primary_device_id"] = device_id
    cfg["x3_devices"] = []
    cfg["output_dir"] = os.path.join(root, f"{name}_out")
    cfg["epub_cover"] = False
    cfg["sites"] = [
        {"name": "Blog", "type": "rss", "url": "https://blog.example/feed", "limit": 10, "enabled": True}
    ]
    cfg["portable_data"] = {
        "enabled": True,
        "folder": cloud,
        "include_history": True,
        "auto_export": True,
        "auto_import_on_start": True,
        "history_mode": "per_device",
        "wizard_completed": True,
    }
    cm.save_config(cfg)
    db = SyncHistoryDb(os.path.join(root, f"{name}.db"))
    with patch("websync.pipeline.service.SyncHistoryDb", return_value=db), \
         patch("websync.backup.local_import.import_local_sidecars", return_value={}):
        return SyncService(cm)


@pytest.fixture
def cloud_env():
    root = tempfile.mkdtemp()
    cloud = os.path.join(root, "cloud")
    os.makedirs(cloud)
    try:
        yield root, cloud
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _run(svc: SyncService, articles: list[dict]) -> list[list[str]]:
    """파이프라인을 실행하고 기기로 보낸 EPUB별 기사 URL 목록을 돌려준다."""
    built: list[list[str]] = []

    def build(_self, _name, batch, generate_cover=True):
        built.append([a["url"] for a in batch])
        return os.path.join(tempfile.gettempdir(), f"fake_{len(built)}.epub")

    def upload(_self, _path, only_ips=None, remote_dir=None):
        return {ip: True for ip in (only_ips or [])}

    with patch.object(ScraperFactory, "get_scraper") as get_scraper, \
         patch.object(EpubBuilder, "build", build), \
         patch.object(X3Uploader, "upload_to_targets", upload), \
         patch("websync.pipeline.sync_pipeline.ToastNotifier.show_toast"):
        get_scraper.return_value.fetch_articles.side_effect = lambda _site: [dict(a) for a in articles]
        get_scraper.return_value.last_fetch_stats = {}
        assert svc.run_sync_pipeline(log_callback=lambda _m: None) is True
    return built


def test_second_pc_with_different_reader_address_sends_only_new_posts(cloud_env):
    root, cloud = cloud_env
    pc1 = _make_pc(root, "pc1", "192.168.219.113", "dev_bbbb", cloud)
    pc2 = _make_pc(root, "pc2", "crosspoint.local", "dev_aaaa", cloud)

    assert _run(pc1, [_article(1), _article(2)]) == [
        ["https://blog.example/1", "https://blog.example/2"]
    ]
    # pc2 는 공유 폴더에서 pc1 이력을 받아 3번 글만 보낸다.
    assert _run(pc2, [_article(1), _article(2), _article(3)]) == [["https://blog.example/3"]]
    # pc1 도 pc2 가 보낸 3번 글을 다시 보내지 않는다.
    assert _run(pc1, [_article(1), _article(2), _article(3), _article(4)]) == [
        ["https://blog.example/4"]
    ]
    # 새 글이 없으면 아무것도 만들지 않는다.
    assert _run(pc2, [_article(3), _article(4)]) == []


def test_pcs_that_both_already_published_ids_still_converge(cloud_env):
    """두 PC가 각자 다른 ID로 이미 전송한 뒤에도 이후 전송은 증분만 한다."""
    root, cloud = cloud_env
    pc1 = _make_pc(root, "pc1", "192.168.31.54", "dev_bbbb", cloud)
    pc2 = _make_pc(root, "pc2", "192.168.219.113", "dev_aaaa", cloud)

    assert _run(pc1, [_article(1)]) == [["https://blog.example/1"]]
    assert _run(pc2, [_article(1), _article(2)]) == [["https://blog.example/2"]]
    assert _run(pc1, [_article(1), _article(2), _article(3)]) == [["https://blog.example/3"]]
    assert _run(pc2, [_article(1), _article(2), _article(3)]) == []
