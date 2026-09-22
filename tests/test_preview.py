"""ISSUE-003: preview 취소 계약 회귀 테스트."""
from unittest.mock import MagicMock, patch

from websync.pipeline.preview import preview_articles


def _make_preview_svc(sites, cancel_seq):
    svc = MagicMock()
    svc._try_acquire_pipeline_locks.return_value = True
    svc.maybe_backup_pull.return_value = {"skipped": True}
    svc.config_manager.load_config.return_value = {
        "x3_ip": "127.0.0.1",
        "x3_devices": [],
        "x3_primary_device_id": "",
        "device_files": {"default_upload_path": "/"},
        "portable_data": {"history_mode": "per_device"},
        "backup_sync": {},
        "sites": sites,
    }
    svc.db.needs_sync.return_value = True
    svc.is_cancel_requested.side_effect = cancel_seq
    return svc


def _sites():
    return [
        {"name": "A", "type": "css", "url": "https://a.example/feed"},
        {"name": "B", "type": "css", "url": "https://b.example/feed"},
    ]


def test_preview_returns_partial_results_when_cancelled():
    """두 번째 사이트 전에 취소되면 수집済み 결과만 반환하고 중단한다."""
    svc = _make_preview_svc(_sites(), [False, True])
    scraper_a = MagicMock()
    scraper_a.fetch_articles.return_value = [
        {"title": "A1", "url": "https://a.example/1", "content": "<p>a</p>"}
    ]
    scraper_b = MagicMock()
    with patch(
        "websync.pipeline.preview.ScraperFactory"
    ) as mock_factory:
        mock_factory.get_scraper.side_effect = [scraper_a, scraper_b]
        results = preview_articles(svc)

    assert [r["site_name"] for r in results] == ["A"]
    scraper_b.fetch_articles.assert_not_called()
    svc._release_pipeline_locks.assert_called_once()
