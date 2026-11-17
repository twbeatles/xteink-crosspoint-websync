"""daily_digest 합본 모드 파이프라인 회귀 테스트 (N1).

기존 test_service.py::test_daily_digest_already_synced_is_success 는
"이미 전부 전송됨" 얼리 리턴만 검증. 본 파일은 실제 build_digest + upload 경로와
합본 전용 카운팅(digest_success / digest_partial)을 검증한다.
"""

from unittest.mock import MagicMock, patch

from websync.config.manager import ConfigManager
from websync.pipeline.service import SyncService
from websync.scrapers.factory import ScraperFactory


def _digest_config(sites=None, devices=None):
    cfg = {
        "x3_ip": "127.0.0.1",
        "x3_devices": devices or [],
        "output_dir": "./output",
        "font_family": "serif",
        "font_size": 16,
        "line_height": 1.7,
        "epub_cover": False,
        "epub_merge_mode": "daily_digest",
        "sites": sites or [],
        "ai_summary": {"enabled": False},
        "translation": {"enabled": False},
    }
    return cfg


def _make_svc(cfg):
    cm = MagicMock(spec=ConfigManager)
    cm.load_config.return_value = cfg
    cm.get_resolved_output_dir.return_value = "./output"
    svc = SyncService(cm)
    svc.db.needs_sync = MagicMock(return_value=True)
    svc.db.is_synced_for_device = MagicMock(return_value=False)
    svc.db.mark_synced_many = MagicMock(return_value=1)
    return svc


def test_daily_digest_happy_path_marks_all_and_success():
    """합본 업로드 전 기기 성공 → digest_success=True, overall_ok=True."""
    cfg = _digest_config(
        sites=[
            {
                "name": "A",
                "type": "rss",
                "url": "https://ex.com/feed",
                "enabled": True,
                "limit": 1,
            }
        ],
        devices=[{"name": "추가", "ip": "10.0.0.2"}],
    )
    svc = _make_svc(cfg)
    with (
        patch.object(svc, "_reload_config"),
        patch.object(svc, "maybe_backup_pull", return_value={"skipped": True}),
        patch.object(svc, "maybe_backup_push", return_value={"skipped": True}),
        patch.object(ScraperFactory, "get_scraper") as mock_get,
        patch.object(
            svc.epub_builder, "build_digest", return_value="/tmp/digest.epub"
        ) as mock_digest,
        patch.object(
            svc.uploader,
            "upload_to_targets",
            return_value={"127.0.0.1": True, "10.0.0.2": True},
        ),
        patch("websync.pipeline.sync_pipeline.ToastNotifier.show_toast"),
    ):
        mock_get.return_value.fetch_articles.return_value = [
            {"title": "t", "content": "<p>x</p>", "url": "https://ex.com/1"},
        ]
        result = svc.run_sync_pipeline()

    assert result is True
    mock_digest.assert_called_once()
    res = svc.get_last_pipeline_result()
    assert res["merge_mode"] == "daily_digest"
    assert res["digest_success"] is True
    assert res["digest_partial"] is False
    assert res["success"] is True


def test_daily_digest_all_upload_fail_not_success():
    """합본 업로드 전 기기 실패 → digest_success=False, overall_ok=False (N1 핵심)."""
    cfg = _digest_config(
        sites=[
            {
                "name": "A",
                "type": "rss",
                "url": "https://ex.com/feed",
                "enabled": True,
                "limit": 1,
            }
        ],
        devices=[{"name": "추가", "ip": "10.0.0.2"}],
    )
    svc = _make_svc(cfg)
    with (
        patch.object(svc, "_reload_config"),
        patch.object(svc, "maybe_backup_pull", return_value={"skipped": True}),
        patch.object(svc, "maybe_backup_push", return_value={"skipped": True}),
        patch.object(ScraperFactory, "get_scraper") as mock_get,
        patch.object(svc.epub_builder, "build_digest", return_value="/tmp/digest.epub"),
        patch.object(
            svc.uploader,
            "upload_to_targets",
            return_value={"127.0.0.1": False, "10.0.0.2": False},
        ),
        patch("websync.pipeline.sync_pipeline.ToastNotifier.show_toast"),
    ):
        mock_get.return_value.fetch_articles.return_value = [
            {"title": "t", "content": "<p>x</p>", "url": "https://ex.com/1"},
        ]
        result = svc.run_sync_pipeline()

    assert result is False
    res = svc.get_last_pipeline_result()
    assert res["digest_success"] is False
    assert res["digest_partial"] is False
    assert res["success"] is False
    # 전 실패 시 mark_synced_many 호출 없음
    svc.db.mark_synced_many.assert_not_called()


def test_daily_digest_partial_upload_marks_only_ok():
    """합본 일부 기기 성공 → 성공 IP만 mark, digest_partial=True."""
    cfg = _digest_config(
        sites=[
            {
                "name": "A",
                "type": "rss",
                "url": "https://ex.com/feed",
                "enabled": True,
                "limit": 1,
            }
        ],
        devices=[{"name": "추가", "ip": "10.0.0.2"}],
    )
    svc = _make_svc(cfg)
    with (
        patch.object(svc, "_reload_config"),
        patch.object(svc, "maybe_backup_pull", return_value={"skipped": True}),
        patch.object(svc, "maybe_backup_push", return_value={"skipped": True}),
        patch.object(ScraperFactory, "get_scraper") as mock_get,
        patch.object(svc.epub_builder, "build_digest", return_value="/tmp/digest.epub"),
        patch.object(
            svc.uploader,
            "upload_to_targets",
            return_value={"127.0.0.1": True, "10.0.0.2": False},
        ),
        patch("websync.pipeline.sync_pipeline.ToastNotifier.show_toast"),
    ):
        mock_get.return_value.fetch_articles.return_value = [
            {"title": "t", "content": "<p>x</p>", "url": "https://ex.com/1"},
        ]
        result = svc.run_sync_pipeline()

    assert result is False  # 부분 성공은 overall 실패
    res = svc.get_last_pipeline_result()
    assert res["digest_success"] is False
    assert res["digest_partial"] is True
    # 성공 IP(127.0.0.1)만 mark 엔트리에 존재
    svc.db.mark_synced_many.assert_called_once()
    entries = svc.db.mark_synced_many.call_args.args[0]
    device_ips = {e["device_ip"] for e in entries}
    assert "127.0.0.1" in device_ips
    assert "10.0.0.2" not in device_ips


def test_daily_digest_result_includes_site_count():
    """합본 결과에 사이트 수(site_count)가 포함되는지 검증."""
    cfg = _digest_config(
        sites=[
            {
                "name": "A",
                "type": "rss",
                "url": "https://ex.com/a",
                "enabled": True,
                "limit": 1,
            },
            {
                "name": "B",
                "type": "rss",
                "url": "https://ex.com/b",
                "enabled": True,
                "limit": 1,
            },
        ],
    )
    svc = _make_svc(cfg)
    with (
        patch.object(svc, "_reload_config"),
        patch.object(svc, "maybe_backup_pull", return_value={"skipped": True}),
        patch.object(svc, "maybe_backup_push", return_value={"skipped": True}),
        patch.object(ScraperFactory, "get_scraper") as mock_get,
        patch.object(svc.epub_builder, "build_digest", return_value="/tmp/digest.epub"),
        patch.object(
            svc.uploader, "upload_to_targets", return_value={"127.0.0.1": True}
        ),
        patch("websync.pipeline.sync_pipeline.ToastNotifier.show_toast"),
    ):
        # 두 사이트 모두 같은 더미 스크래퍼 반환
        mock_get.return_value.fetch_articles.return_value = [
            {"title": "t", "content": "<p>x</p>", "url": "https://ex.com/1"},
        ]
        result = svc.run_sync_pipeline()

    assert result is True
    res = svc.get_last_pipeline_result()
    assert res["site_count"] == 2
