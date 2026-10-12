"""GUI user-journey guards (headless Fake Service, no Tk mainloop).

Journey: settings-save failure -> 0 sync/schedule; worker exception ->
busy/buttons/progress recover; cancel between batches. INV-14.
"""
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from websync.gui.app_core.sync_control import AppSyncControlMixin


class _JourneyApp(AppSyncControlMixin):
    def __init__(self):
        self._background_threads = set()
        self._background_threads_lock = threading.Lock()
        self.service = MagicMock()
        self.service.is_pipeline_running.return_value = False
        self.service.config = {"sites": [{"name": "s", "url": "https://example.com", "enabled": True}]}
        self.bottom_bar = SimpleNamespace(progress_bar={})
        self.busy = False
        self.messages = []
        self.root = SimpleNamespace(after=lambda _d, cb: cb(), winfo_exists=lambda: True)
        self.save_ok = True

    def _save_ui_settings(self):
        return self.save_ok

    def _set_sync_ui_busy(self, value):
        self.busy = value

    def _log_message(self, message):
        self.messages.append(message)

    def _make_log_callback(self):
        return lambda _m: None

    def _make_progress_callback(self):
        return lambda _c, _t: None

    def _sync_finished_ui(self):
        self.busy = False


def test_save_failure_starts_zero_background_work():
    app = _JourneyApp()
    app.save_ok = False
    app._run_immediate_sync()
    app.service.run_sync_pipeline.assert_not_called()
    app.service.attach_pipeline_thread.assert_not_called()
    assert app.busy is False
    assert not app._background_threads


def test_worker_exception_recovers_busy_and_progress():
    app = _JourneyApp()
    app.service.run_sync_pipeline.side_effect = RuntimeError("worker boom")
    with patch("websync.gui.app_core.sync_control.messagebox.showerror"):
        app._run_immediate_sync()
        app._wait_for_background_tasks(timeout=3)
    assert app.busy is False
    assert app.bottom_bar.progress_bar["value"] == 0
    assert any("worker boom" in m for m in app.messages)


def test_epub_only_journey_never_touches_uploader_or_db():
    from websync.pipeline.epub_only import build_selected_epubs
    import logging

    builder = MagicMock()
    builder.build.side_effect = lambda name, arts, generate_cover=True: f"/out/{name}.epub"
    service = SimpleNamespace(
        logger=logging.getLogger("journey"),
        config={"epub_merge_mode": "per_site", "epub_cover": False},
        epub_builder=builder, uploader=MagicMock(), db=MagicMock(),
        is_cancel_requested=lambda: False,
    )
    service._reload_config = lambda: None
    arts = [
        {"site_name": "S", "title": "one", "url": "https://x.example/1", "content": "<p>1</p>"},
        {"site_name": "S", "title": "two", "url": "https://x.example/2", "content": "<p>2</p>"},
    ]
    paths = build_selected_epubs(service, arts)
    assert paths == ["/out/S.epub"]
    service.uploader.upload_to_targets.assert_not_called()
    service.db.mark_synced_many.assert_not_called()
