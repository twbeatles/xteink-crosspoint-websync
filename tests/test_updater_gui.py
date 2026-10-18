from types import SimpleNamespace
from unittest.mock import Mock, patch

from websync.gui.settings_tab.updater import SettingsUpdaterMixin


class _InlineThread:
    def __init__(self, target, **_kwargs):
        self.target = target

    def start(self):
        self.target()


def test_update_check_error_survives_deferred_ui_callback():
    queued = []
    view = SimpleNamespace(
        check_update_btn=Mock(),
        update_status_lbl=Mock(),
        _safe_ui=queued.append,
        _on_update_check_failed=Mock(),
    )
    with patch("websync.gui.settings_tab.updater.UpdateService") as service_cls, patch(
        "websync.gui.settings_tab.updater.threading.Thread", _InlineThread
    ):
        service_cls.return_value.check_for_update.side_effect = RuntimeError("offline")
        SettingsUpdaterMixin._on_check_update_clicked(view)

    queued.pop()()
    view._on_update_check_failed.assert_called_once_with("offline")


def test_update_download_error_survives_deferred_ui_callback():
    queued = []
    service = Mock()
    service.download_and_stage.side_effect = RuntimeError("download failed")
    view = SimpleNamespace(
        check_update_btn=Mock(),
        cancel_download_btn=Mock(),
        update_status_lbl=Mock(),
        _safe_ui=queued.append,
        _download_cancel_event=None,
        _on_download_cancelled=Mock(),
        _on_download_failed=Mock(),
        _on_download_complete=Mock(),
    )
    with patch("websync.gui.settings_tab.updater.threading.Thread", _InlineThread):
        SettingsUpdaterMixin._start_update_download(view, Mock(), service)

    queued.pop()()
    view._on_download_failed.assert_called_once_with("download failed")


def test_download_decline_deletes_staged_file(tmp_path):
    staged = tmp_path / "update-9.9.9-abc.exe"
    staged.write_bytes(b"fake-binary")
    manifest = SimpleNamespace(version="9.9.9")
    service = Mock()
    view = SimpleNamespace(
        check_update_btn=Mock(),
        cancel_download_btn=Mock(),
        update_status_lbl=Mock(),
    )
    with patch(
        "websync.gui.settings_tab.updater.messagebox.askyesno", return_value=False
    ), patch("sys.frozen", True, create=True):
        SettingsUpdaterMixin._on_download_complete(view, staged, manifest, service)

    assert not staged.exists()
    service.launch_update_and_exit.assert_not_called()
    view.update_status_lbl.configure.assert_called()


def test_download_apply_keeps_staged_and_launches(tmp_path):
    staged = tmp_path / "update-9.9.9-abc.exe"
    staged.write_bytes(b"fake-binary")
    manifest = SimpleNamespace(version="9.9.9")
    service = Mock()
    view = SimpleNamespace(
        check_update_btn=Mock(),
        cancel_download_btn=Mock(),
        update_status_lbl=Mock(),
    )
    with patch(
        "websync.gui.settings_tab.updater.messagebox.askyesno", return_value=True
    ), patch("sys.frozen", True, create=True):
        SettingsUpdaterMixin._on_download_complete(view, staged, manifest, service)

    assert staged.exists()
    service.launch_update_and_exit.assert_called_once_with(staged, manifest)


def test_startup_state_reports_failed_result_once():
    from websync.gui.app_core.app import SyncAppGui

    view = SimpleNamespace(_log_message=Mock())
    with patch("websync.gui.app_core.app.messagebox.showwarning") as warn:
        SyncAppGui._on_update_startup_state(
            view, [], {"status": "failed", "error": "boom"}
        )
    view._log_message.assert_called_once()
    warn.assert_called_once()


def test_startup_state_reports_applied_and_cleanup():
    from websync.gui.app_core.app import SyncAppGui

    view = SimpleNamespace(_log_message=Mock())
    cleaned = [Mock(), Mock()]
    with patch("websync.gui.app_core.app.messagebox.showwarning") as warn:
        SyncAppGui._on_update_startup_state(
            view, cleaned, {"status": "applied", "target": "C:/app/x3_websync.exe"}
        )
    assert view._log_message.call_count == 2
    warn.assert_not_called()


def test_startup_state_ignores_missing_result():
    from websync.gui.app_core.app import SyncAppGui

    view = SimpleNamespace(_log_message=Mock())
    with patch("websync.gui.app_core.app.messagebox.showwarning") as warn:
        SyncAppGui._on_update_startup_state(view, [], None)
    view._log_message.assert_not_called()
    warn.assert_not_called()
