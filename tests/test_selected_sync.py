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


def test_selected_sync_stops_when_shared_history_pull_fails():
    svc = _make_svc()
    selected = [
        {"site_name": "A", "title": "t", "url": "https://ex.com/1", "content": "<p>x</p>"},
    ]
    with patch.object(svc, "maybe_backup_pull", return_value={"ok": False, "message": "cloud unavailable"}), \
         patch.object(svc.uploader, "upload_to_targets") as upload:
        assert sync_selected_articles(svc, selected) is False
    upload.assert_not_called()
    assert svc.get_last_pipeline_result()["status"] == "backup_pull_failed"


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
    selected = [
        {"site_name": "A", "title": "t", "url": "https://ex.com/1", "content": "<p>x</p>"},
    ]
    with patch.object(svc, "_reload_config"), \
         patch.object(svc, "maybe_backup_pull", side_effect=lambda **kw: (svc.request_cancel() or {"skipped": True})), \
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


def test_selected_sync_cancel_after_first_device_batch_skips_remaining_batch():
    svc = _make_svc(devices=[{"name": "B", "ip": "10.0.0.2"}])
    selected = [
        {"site_name": "A", "title": "one", "url": "https://ex.com/1", "content": "<p>one</p>"},
    ]

    def first_upload(_path, *, only_ips):
        svc.request_cancel()
        return {only_ips[0]: True}

    with patch.object(svc, "_reload_config"), \
         patch.object(svc, "maybe_backup_pull", return_value={"skipped": True}), \
         patch.object(svc, "maybe_backup_push", return_value={"skipped": True}), \
         patch("websync.upload.device_ids.group_articles_by_pending_targets", return_value=[
             (["127.0.0.1"], selected), (["10.0.0.2"], selected),
         ]), \
         patch.object(svc.epub_builder, "build", return_value="/tmp/test.epub"), \
         patch.object(svc.uploader, "upload_to_targets", side_effect=first_upload) as upload, \
         patch("websync.pipeline.selected_sync.Summarizer") as summarizer, \
         patch("websync.pipeline.selected_sync.Translator") as translator:
        summarizer.return_value.is_available.return_value = False
        translator.return_value.is_available_for_site.return_value = False
        assert sync_selected_articles(svc, selected) is False

    assert svc.get_last_pipeline_result()["status"] == "cancelled"
    assert upload.call_count == 1



def test_selected_legacy_source_name_uses_only_unambiguous_translation():
    import pytest
    from websync.pipeline.sources import selected_source_groups
    arts = [{"site_name": "same", "url": "https://article.example/a", "content": "original"}]
    first = {"name": "same", "url": "https://feed.example/a", "translate_to": "ko"}
    groups, options = selected_source_groups(arts, [first], "other")
    assert list(options.values()) == [first]
    assert next(iter(groups.values()))[0]["source_url"] == first["url"]
    assert "source_url" not in arts[0]
    second = {"name": "same", "url": "https://feed.example/b", "translate_to": "en"}
    with pytest.raises(ValueError):
        selected_source_groups(arts, [first, second], "other")


def test_ambiguous_legacy_selection_fails_before_build_or_upload():
    import pytest
    svc = _make_svc()
    svc.config["sites"] = [
        {"name": "same", "url": "https://feed.example/a", "translate_to": "ko"},
        {"name": "same", "url": "https://feed.example/b", "translate_to": "en"},
    ]
    with patch.object(svc, "_reload_config"), \
         patch.object(svc, "maybe_backup_pull", return_value={"skipped": True}), \
         patch.object(svc.epub_builder, "build") as build, \
         patch.object(svc.uploader, "upload_to_targets") as upload:
        with pytest.raises(ValueError):
            sync_selected_articles(svc, [{"site_name": "same", "url": "https://article.example/a", "content": "x"}])
    build.assert_not_called()
    upload.assert_not_called()
    assert not svc._pipeline_lock.locked()


def test_source_identity_preserves_url_path_case_and_survives_rename():
    from websync.pipeline.sources import source_id, selected_source_groups
    site = {"name": "original", "url": "https://feed.example/News", "translate_to": "ko"}
    identity = source_id(site)
    assert identity != source_id({**site, "url": "https://feed.example/news"})
    renamed = {**site, "name": "renamed"}
    assert identity == source_id(renamed)
    # URL-only preview metadata from older callers also resolves the current source.
    groups, options = selected_source_groups([
        {"site_name": "old label", "source_url": site["url"], "content": "x"}
    ], [renamed], "other")
    assert options[identity] == renamed
    assert groups[identity][0]["_source_name"] == "renamed"


def _cancel_after_first_batch(push_result):
    svc = _make_svc(devices=[{"name": "B", "ip": "10.0.0.2"}])
    selected = [
        {"site_name": "A", "title": "one", "url": "https://ex.com/1", "content": "<p>one</p>"},
    ]

    def first_upload(_path, *, only_ips):
        svc.request_cancel()
        return {only_ips[0]: True}

    with patch.object(svc, "_reload_config"), \
         patch.object(svc, "maybe_backup_pull", return_value={"skipped": True}), \
         patch.object(svc, "maybe_backup_push", return_value=push_result) as push, \
         patch("websync.upload.device_ids.group_articles_by_pending_targets", return_value=[
             (["127.0.0.1"], selected), (["10.0.0.2"], selected),
         ]), \
         patch.object(svc.epub_builder, "build", return_value="/tmp/test.epub"), \
         patch.object(svc.uploader, "upload_to_targets", side_effect=first_upload), \
         patch("websync.pipeline.selected_sync.Summarizer") as summarizer, \
         patch("websync.pipeline.selected_sync.Translator") as translator:
        summarizer.return_value.is_available.return_value = False
        translator.return_value.is_available_for_site.return_value = False
        result = sync_selected_articles(svc, selected)
    return svc, result, push


def test_selected_sync_cancel_pushes_history_already_recorded():
    svc, result, push = _cancel_after_first_batch({"ok": True})
    assert result is False
    assert svc.db.mark_synced_many.call_count == 1
    push.assert_called_once()
    assert svc.get_last_pipeline_result()["status"] == "cancelled"


def test_selected_sync_cancel_push_failure_keeps_cancelled_status():
    svc, result, push = _cancel_after_first_batch({"ok": False, "message": "locked"})
    assert result is False
    push.assert_called_once()
    last = svc.get_last_pipeline_result()
    assert last["status"] == "cancelled" and last["success"] is False


def test_selected_sync_cancel_without_records_skips_push():
    svc = _make_svc()
    selected = [{"site_name": "A", "title": "t", "url": "https://ex.com/1", "content": "<p>x</p>"}]
    with patch.object(svc, "_reload_config"), \
         patch.object(svc, "maybe_backup_pull", side_effect=lambda **kw: (svc.request_cancel() or {"skipped": True})), \
         patch.object(svc, "maybe_backup_push", return_value={"ok": True}) as push, \
         patch("websync.pipeline.selected_sync.Summarizer") as summarizer, \
         patch("websync.pipeline.selected_sync.Translator") as translator:
        summarizer.return_value.is_available.return_value = False
        translator.return_value.is_available_for_site.return_value = False
        assert sync_selected_articles(svc, selected) is False
    push.assert_not_called()


def test_selected_sync_exception_after_record_pushes_then_raises():
    svc = _make_svc()
    selected = [
        {"site_name": "A", "title": "one", "url": "https://ex.com/1", "content": "<p>one</p>"},
        {"site_name": "B", "title": "two", "url": "https://ex.com/2", "content": "<p>two</p>"},
    ]
    builds = []

    def build(name, _articles, generate_cover=False):
        builds.append(name)
        if len(builds) == 2:
            raise OSError("disk full")
        return "/tmp/a.epub"

    with patch.object(svc, "_reload_config"), \
         patch.object(svc, "maybe_backup_pull", return_value={"skipped": True}), \
         patch.object(svc, "maybe_backup_push", return_value={"ok": True}) as push, \
         patch.object(svc.epub_builder, "build", side_effect=build), \
         patch.object(svc.uploader, "upload_to_targets", side_effect=lambda _p, *, only_ips: {ip: True for ip in only_ips}), \
         patch("websync.pipeline.selected_sync.Summarizer") as summarizer, \
         patch("websync.pipeline.selected_sync.Translator") as translator:
        summarizer.return_value.is_available.return_value = False
        translator.return_value.is_available_for_site.return_value = False
        try:
            sync_selected_articles(svc, selected)
            raised = False
        except OSError:
            raised = True
    assert raised
    assert svc.db.mark_synced_many.call_count == 1
    push.assert_called_once()
    assert svc.get_last_pipeline_result()["status"] == "failed"
    assert not svc.is_pipeline_running()
