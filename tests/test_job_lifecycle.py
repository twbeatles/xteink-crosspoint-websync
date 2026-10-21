"""Cancellation belongs to accepted jobs; close must drain persisted work."""
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

from websync.config.manager import ConfigManager
from websync.pipeline.service import SyncService
from websync.gui.app_core.sync_control import AppSyncControlMixin


def make_service(tmp_path):
    cm = ConfigManager(str(tmp_path / "config.json"))
    cm.patch_fields(sites=[{"name": "A", "type": "rss", "url": "https://example.com/feed"}],
                    output_dir=str(tmp_path / "output"), epub_cover=False)
    return SyncService(cm)


def test_cancel_then_preview_selected_and_build_restart(tmp_path, monkeypatch):
    svc = make_service(tmp_path)
    article = {"title": "Example", "content": "<p>Article</p>", "url": "https://example.com/one"}
    scraper = SimpleNamespace(fetch_articles=lambda _: [dict(article)], last_fetch_stats={})
    monkeypatch.setattr("websync.scrapers.factory.ScraperFactory.get_scraper", lambda _: scraper)
    assert len(svc.preview_articles()) == 1
    svc.request_cancel()
    chosen = svc.preview_articles()
    assert len(chosen) == 1
    svc.request_cancel()
    assert svc.build_selected_epubs(chosen)
    assert not svc.is_cancel_requested()
    monkeypatch.setattr("websync.upload.uploader.X3Uploader.upload_to_targets",
                        lambda self, path, only_ips=None: {ip: True for ip in only_ips})
    svc.request_cancel()
    assert svc.sync_selected_articles(chosen)
    assert svc.db.get_count() == 1


def test_busy_job_does_not_clear_current_cancel(tmp_path):
    svc = make_service(tmp_path)
    assert svc._try_acquire_pipeline_locks()
    try:
        svc.request_cancel()
        assert not svc._try_acquire_pipeline_locks()
        assert svc.is_cancel_requested()
    finally:
        svc._release_pipeline_locks()


def test_shutdown_does_not_wait_unrelated_cli_lock(tmp_path, monkeypatch):
    svc = make_service(tmp_path)
    monkeypatch.setattr(svc._process_lock, "is_held_by_other", lambda: True)
    assert svc.is_pipeline_running()
    assert svc.shutdown_pipeline(timeout=0)


def test_gui_close_keeps_root_alive_until_commit(tmp_path):
    svc = make_service(tmp_path)
    accepted = threading.Event()
    release = threading.Event()

    def work():
        assert svc._try_acquire_pipeline_locks()
        try:
            accepted.set()
            assert release.wait(5)
            svc.db.mark_synced("https://example.com/committed", "A", "Done", "dev_test")
        finally:
            svc._release_pipeline_locks()

    worker = threading.Thread(target=work)
    svc.attach_pipeline_thread(worker)
    worker.start()
    assert accepted.wait(2)
    callbacks = []
    app = AppSyncControlMixin()
    app.service = svc
    app._background_threads_lock = threading.Lock()
    app._background_threads = {worker}
    app.root = SimpleNamespace(after=lambda delay, fn: callbacks.append(fn), destroy=MagicMock())
    app.tab_settings = SimpleNamespace(_stop_watch_worker=lambda **kw: None)
    app._on_close()
    callbacks.pop(0)()
    app.root.destroy.assert_not_called()
    assert not svc._try_acquire_pipeline_locks()
    release.set()
    worker.join(3)
    app._close_thread.join(3)
    assert not app._close_thread.is_alive()
    callbacks.pop(0)()
    app.root.destroy.assert_called_once()
    assert svc.db.get_count() == 1


def test_async_exception_updates_status_and_unlocks(tmp_path, monkeypatch):
    svc = make_service(tmp_path)
    monkeypatch.setattr(svc, "_run_pipeline_body", MagicMock(side_effect=ValueError("failure")))
    assert svc.begin_sync_pipeline_async()
    svc._pipeline_thread.join(3)
    assert svc.get_last_pipeline_result()["status"] == "failed"
    assert not svc.is_pipeline_running()


def test_gui_close_runs_after_drain_before_destroy(tmp_path):
    svc = make_service(tmp_path)
    order = []
    callbacks = []
    app = AppSyncControlMixin()
    app.service = svc
    app._background_threads_lock = threading.Lock()
    app._background_threads = set()
    app.root = SimpleNamespace(
        after=lambda delay, fn: callbacks.append(fn),
        destroy=lambda: order.append("destroy"),
    )
    app.tab_settings = SimpleNamespace(_stop_watch_worker=lambda **kw: None)
    flushed = MagicMock(side_effect=lambda: order.append("flush"))
    svc.flush_backup_push = flushed
    app._on_close(after_drain=lambda: order.append("after_drain"))
    app._close_thread.join(3)
    callbacks.pop(0)()
    assert order == ["flush", "after_drain", "destroy"]


def test_gui_close_destroys_even_if_after_drain_fails(tmp_path, monkeypatch):
    svc = make_service(tmp_path)
    callbacks = []
    app = AppSyncControlMixin()
    app.service = svc
    app._background_threads_lock = threading.Lock()
    app._background_threads = set()
    app.root = SimpleNamespace(after=lambda delay, fn: callbacks.append(fn), destroy=MagicMock())
    app.tab_settings = SimpleNamespace(_stop_watch_worker=lambda **kw: None)
    monkeypatch.setattr("websync.gui.app_core.sync_control.messagebox.showerror", MagicMock())

    def boom():
        raise RuntimeError("helper failed")

    app._on_close(after_drain=boom)
    app._close_thread.join(3)
    callbacks.pop(0)()
    app.root.destroy.assert_called_once()
