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
