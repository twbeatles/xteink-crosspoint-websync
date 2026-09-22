"""선택 동기화 파이프라인 테스트 — N3(백업 pull 추가), N7(락 헬퍼 통일).

sync_selected_articles 가 시작 시 maybe_backup_pull 을 호출하는지,
성공 IP만 mark 하는지 검증한다.
"""
from unittest.mock import MagicMock, patch

from websync.config.manager import ConfigManager
from websync.pipeline.service import SyncService
from websync.pipeline.selected_sync import sync_selected_articles


def _make_svc(devices=None):
    cm = MagicMock(spec=ConfigManager)
    cfg = {
        "x3_ip": "127.0.0.1",
        "x3_devices": devices or [],
        "output_dir": "./output",
        "font_family": "serif",
        "font_size": 16,
        "line_height": 1.7,
        "epub_cover": False,
        "epub_merge_mode": "per_site",
        "sites": [],
        "ai_summary": {"enabled": False},
        "translation": {"enabled": False},
    }
    cm.load_config.return_value = cfg
    cm.get_resolved_output_dir.return_value = "./output"
    svc = SyncService(cm)
    svc.db.is_synced_for_device = MagicMock(return_value=False)
    svc.db.is_synced = MagicMock(return_value=False)
    svc.db.mark_synced_many = MagicMock(return_value=1)
    return svc


def test_selected_sync_calls_backup_pull_before_processing():
    """N3: 선택 동기화 시작 시 maybe_backup_pull 이 호출되는지."""
    svc = _make_svc()
    selected = [
        {"site_name": "A", "title": "t", "url": "https://ex.com/1", "content": "<p>x</p>"},
    ]
    with patch.object(svc, "_reload_config"), \
         patch.object(svc, "maybe_backup_pull", return_value={"skipped": True}) as mock_pull, \
         patch.object(svc, "maybe_backup_push", return_value={"skipped": True}), \
         patch.object(svc.epub_builder, "build", return_value="/tmp/test.epub"), \
         patch.object(svc.uploader, "upload_to_targets", return_value={"127.0.0.1": True}), \
         patch("websync.pipeline.selected_sync.Summarizer") as mock_sum, \
         patch("websync.pipeline.selected_sync.Translator") as mock_trans:
        mock_sum.return_value.is_available.return_value = False
        mock_trans.return_value.is_available_for_site.return_value = False
        result = sync_selected_articles(svc, selected)

    assert result is True
    mock_pull.assert_called_once()


def test_selected_sync_returns_false_when_no_articles():
    svc = _make_svc()
    result = sync_selected_articles(svc, [])
    assert result is False


def test_selected_sync_marks_only_successful_ips():
    """일부 기기 실패 시 성공 IP만 mark_synced_many 에 들어가는지."""
    svc = _make_svc(devices=[{"name": "추가", "ip": "10.0.0.2"}])
    selected = [
        {"site_name": "A", "title": "t", "url": "https://ex.com/1", "content": "<p>x</p>"},
    ]
    with patch.object(svc, "_reload_config"), \
         patch.object(svc, "maybe_backup_pull", return_value={"skipped": True}), \
         patch.object(svc, "maybe_backup_push", return_value={"skipped": True}), \
         patch.object(svc.epub_builder, "build", return_value="/tmp/test.epub"), \
         patch.object(svc.uploader, "upload_to_targets", return_value={"127.0.0.1": True, "10.0.0.2": False}), \
         patch("websync.pipeline.selected_sync.Summarizer") as mock_sum, \
         patch("websync.pipeline.selected_sync.Translator") as mock_trans:
        mock_sum.return_value.is_available.return_value = False
        mock_trans.return_value.is_available_for_site.return_value = False
        result = sync_selected_articles(svc, selected)

    assert result is False  # 부분 성공
    svc.db.mark_synced_many.assert_called_once()
    entries = svc.db.mark_synced_many.call_args.args[0]
    device_ips = {e["device_ip"] for e in entries}
    assert "127.0.0.1" in device_ips
    assert "10.0.0.2" not in device_ips


def test_selected_sync_rejects_when_busy():
    """N7: 락 헬퍼 통일 — 파이프라인 락 점유 시 False."""
    svc = _make_svc()
    # thread lock 선점
    assert svc._pipeline_lock.acquire(blocking=False)
    try:
        selected = [
            {"site_name": "A", "title": "t", "url": "https://ex.com/1", "content": "<p>x</p>"},
        ]
        result = sync_selected_articles(svc, selected)
        assert result is False
    finally:
        svc._pipeline_lock.release()


def test_selected_sync_returns_false_when_cancelled():
    """ISSUE-003: 취소 요청 시 빌드·전송 없이 False + cancelled 결과."""
    svc = _make_svc()
    svc.request_cancel()
    selected = [
        {"site_name": "A", "title": "t", "url": "https://ex.com/1", "content": "<p>x</p>"},
    ]
    with patch.object(svc, "_reload_config"), \
         patch.object(svc, "maybe_backup_pull", return_value={"skipped": True}), \
         patch.object(svc, "maybe_backup_push", return_value={"skipped": True}), \
         patch.object(svc.epub_builder, "build", return_value="/tmp/test.epub") as mock_build, \
         patch.object(
             svc.uploader, "upload_to_targets", return_value={"127.0.0.1": True}
         ) as mock_upload, \
         patch("websync.pipeline.selected_sync.Summarizer") as mock_sum, \
         patch("websync.pipeline.selected_sync.Translator") as mock_trans:
        mock_sum.return_value.is_available.return_value = False
        mock_trans.return_value.is_available_for_site.return_value = False
        result = sync_selected_articles(svc, selected)

    assert result is False
    mock_build.assert_not_called()
    mock_upload.assert_not_called()
    svc.db.mark_synced_many.assert_not_called()
    assert svc.get_last_pipeline_result() == {"status": "cancelled", "success": False}

