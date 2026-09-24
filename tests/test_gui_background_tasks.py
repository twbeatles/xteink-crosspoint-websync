import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from websync.gui.app_core.config_sync import AppConfigSyncMixin
from websync.gui.app_core.sync_control import AppSyncControlMixin
from websync.gui.sync_tab.connection import SyncConnectionMixin
from websync.gui.sync_tab.preview import SyncPreviewMixin


class _DummyApp(AppSyncControlMixin):
    def __init__(self):
        self._background_threads = set()
        self._background_threads_lock = threading.Lock()


def test_background_task_registry_waits_and_unregisters_workers():
    app = _DummyApp()
    started = threading.Event()
    release = threading.Event()

    def work():
        started.set()
        release.wait(timeout=2)

    worker = app._start_background_task(work, name="test-worker")
    assert started.wait(timeout=1)
    with app._background_threads_lock:
        assert worker in app._background_threads
    release.set()
    app._wait_for_background_tasks(timeout=1)
    assert not worker.is_alive()
    with app._background_threads_lock:
        assert worker not in app._background_threads


class _PipelineApp(_DummyApp):
    def __init__(self):
        super().__init__()
        self.service = MagicMock()
        self.service.is_pipeline_running.return_value = False
        self.bottom_bar = SimpleNamespace(progress_bar={})
        self.busy = False
        self.messages = []
        self.root = SimpleNamespace(
            after=lambda _delay, callback: callback(),
            winfo_exists=lambda: True,
        )
        self.save_ok = True

    def _save_ui_settings(self):
        return self.save_ok

    def _set_sync_ui_busy(self, value):
        self.busy = value

    def _log_message(self, message):
        self.messages.append(message)

    def _make_log_callback(self):
        return lambda _message: None

    def _make_progress_callback(self):
        return lambda _current, _total: None

    def _sync_finished_ui(self):
        self.busy = False


def test_immediate_sync_does_not_start_when_settings_save_fails():
    app = _PipelineApp()
    app.save_ok = False
    app._run_immediate_sync()
    app.service.run_sync_pipeline.assert_not_called()
    app.service.attach_pipeline_thread.assert_not_called()
    assert app.busy is False
    assert not app._background_threads


def test_ui_settings_save_returns_failure_to_caller():
    class ConfigApp(AppConfigSyncMixin):
        pass

    app = ConfigApp()
    app.service = SimpleNamespace(config={})
    app.tab_sync = MagicMock()
    app.tab_sync.ip_entry.get.return_value = "10.0.0.2"
    app.tab_sync.font_size_sp.get.return_value = "16"
    app.tab_sync.line_height_sp.get.return_value = "1.7"
    app.tab_calibre = MagicMock()
    app.tab_settings = MagicMock()
    app.calibre = MagicMock()
    app.calibre.calibre_path = "original"
    app.calibre.library_path = "original"
    app._safe_save_config = MagicMock(return_value=False)

    assert app._save_ui_settings() is False
    assert app.service.config == {}
    assert app.calibre.calibre_path == "original"
    assert app.calibre.library_path == "original"
    app._safe_save_config.assert_called_once()
    app._safe_save_config.return_value = True
    assert app._save_ui_settings() is True


def test_immediate_sync_error_restores_gui_and_reports_failure():
    app = _PipelineApp()
    app.service.run_sync_pipeline.side_effect = RuntimeError("config reload failed")
    with patch("websync.gui.app_core.sync_control.messagebox.showerror") as showerror:
        app._run_immediate_sync()
        app._wait_for_background_tasks(timeout=2)
    assert app.busy is False
    assert app.bottom_bar.progress_bar["value"] == 0
    assert any("config reload failed" in message for message in app.messages)
    showerror.assert_called_once()
    assert not app._background_threads


class _PreviewTab(SyncPreviewMixin):
    def __init__(self, app):
        self.app = app
        self.service = app.service
        self.master = app.root

    def _show_preview_results(self):
        self.app.busy = False


def test_preview_error_restores_gui():
    app = _PipelineApp()
    tab = _PreviewTab(app)
    app.service.preview_articles.side_effect = RuntimeError("preview failed")
    with patch("websync.gui.app_core.sync_control.messagebox.showerror") as showerror:
        tab.open_preview_window()
        app._wait_for_background_tasks(timeout=2)
    assert app.busy is False
    showerror.assert_called_once()


def test_selected_sync_error_restores_gui():
    app = _PipelineApp()
    tab = _PreviewTab(app)
    app.service.sync_selected_articles.side_effect = RuntimeError("selected sync failed")
    with patch("websync.gui.app_core.sync_control.messagebox.showerror") as showerror:
        tab._run_selected_sync_task([{"url": "https://example.com/1"}])
        app._wait_for_background_tasks(timeout=2)
    assert app.busy is False
    showerror.assert_called_once()


def test_direct_upload_does_not_start_after_settings_save_failure(tmp_path):
    book = tmp_path / "book.epub"
    book.write_bytes(b"epub")
    tab = SyncConnectionMixin()
    tab.file_entry = MagicMock()
    tab.file_entry.get.return_value = str(book)
    tab.app = MagicMock()
    tab.app._save_ui_settings.return_value = False

    tab._direct_upload()

    tab.app._start_background_task.assert_not_called()
    tab.app._make_uploader.assert_not_called()
