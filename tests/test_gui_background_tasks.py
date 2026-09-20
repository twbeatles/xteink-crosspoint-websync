import threading

from websync.gui.app_core.sync_control import AppSyncControlMixin


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
