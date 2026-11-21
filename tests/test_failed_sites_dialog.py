"""실패 안내 대화상자 문구 (Tk 없이 테스트)."""

from websync.gui.app_core.sync_control import AppSyncControlMixin


def _mixin():
    return AppSyncControlMixin.__new__(AppSyncControlMixin)


def test_failed_dialog_lists_failed_sites():
    m = _mixin()
    text = m._failed_sync_dialog_text(
        {"status": "completed", "success": False, "site_errors": 1,
         "failed_sites": ["메르의 블로그", "Bad"]}
    )
    assert text is not None
    assert "메르의 블로그" in text
    assert "Bad" in text
    # 안내: 자동 재시도 + 이력 삭제 후 재전송
    assert "다음 동기화" in text
    assert "동기화 이력" in text
    assert "다시 시도" in text


def test_failed_dialog_none_when_clean():
    m = _mixin()
    assert m._failed_sync_dialog_text(
        {"status": "completed", "success": True, "site_errors": 0,
         "failed_sites": []}
    ) is None
    assert m._failed_sync_dialog_text({"status": "no_new", "success": True}) is None
    assert m._failed_sync_dialog_text({"status": "cancelled", "success": False}) is None
    assert m._failed_sync_dialog_text({}) is None
    assert m._failed_sync_dialog_text(None) is None


def test_failed_dialog_without_names_still_guides():
    m = _mixin()
    text = m._failed_sync_dialog_text({"status": "errors", "success": False,
                                       "site_errors": 2})
    assert text is not None
    assert "동기화 이력" in text
