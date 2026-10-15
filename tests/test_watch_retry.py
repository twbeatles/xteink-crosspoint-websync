"""Watch queue contracts use temporary settings and deterministic fake uploads."""
import os
import threading
import time
from types import SimpleNamespace

import pytest

from websync.config.manager import ConfigManager
from websync.config.exceptions import ConfigSaveError
from websync.gui.settings_tab.watch import SettingsWatchMixin
from websync.watch.retry import WatchRetryQueue


def eventually(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    assert predicate()


class Harness:
    def __init__(self, tmp_path):
        self.book = tmp_path / "book.epub"
        self.book.write_bytes(b"book")
        self.manager = ConfigManager(str(tmp_path / "config.json"))
        self.owner = SettingsWatchMixin()
        self.owner.service = SimpleNamespace(config_manager=self.manager, config=self.manager.load_config())
        self.targets = [{"ip": "a.local", "history_key": "reader-a"}, {"ip": "b.local", "history_key": "reader-b"}]
        self.remote_dir = "/"
        self.calls = []
        self.threads = []
        self.queues = []

    def uploader(self):
        return SimpleNamespace(remote_dir=self.remote_dir, _build_target_list=lambda: list(self.targets))

    def start(self, attempt, *, base=0.025, cap=0.05):
        watch = self.manager.load_config()["calibre_watch"]
        def send(path, uploader, ips, stop):
            self.calls.append(list(ips))
            return attempt(ips, stop)
        queue = WatchRetryQueue(self.uploader, send, self.owner._save_watch_job,
                               pending_files=watch["pending_files"], pending_jobs=watch["pending_jobs"],
                               retry_base=base, retry_cap=cap, stability_interval=0.001)
        thread = threading.Thread(target=queue.run)
        self.queues.append(queue)
        self.threads.append(thread)
        thread.start()
        return queue

    def pending(self):
        return self.manager.load_config()["calibre_watch"]["pending_files"]

    def close(self):
        for queue in self.queues:
            queue.stop()
        for thread in self.threads:
            thread.join(3)
            assert not thread.is_alive()


@pytest.fixture
def harness(tmp_path):
    harness = Harness(tmp_path)
    try:
        yield harness
    finally:
        harness.close()


def test_connection_recovery_without_file_event(harness):
    def attempt(ips, stop):
        return {ip: len(harness.calls) > 1 for ip in ips}
    queue = harness.start(attempt)
    queue.enqueue(str(harness.book))
    eventually(lambda: len(harness.calls) == 2 and not harness.pending())
    assert harness.calls == [["a.local", "b.local"], ["a.local", "b.local"]]


def test_partial_success_retries_only_pending_device(harness):
    def attempt(ips, stop):
        return {ip: ip == "a.local" or len(harness.calls) > 1 for ip in ips}
    queue = harness.start(attempt)
    queue.enqueue(str(harness.book))
    eventually(lambda: len(harness.calls) == 2 and not harness.pending())
    assert harness.calls == [["a.local", "b.local"], ["b.local"]]


def test_duplicate_events_during_upload_and_after_acknowledgement(harness):
    entered, release = threading.Event(), threading.Event()
    def attempt(ips, stop):
        entered.set()
        assert release.wait(2)
        return dict.fromkeys(ips, True)
    queue = harness.start(attempt)
    queue.enqueue(str(harness.book))
    assert entered.wait(2)
    for _ in range(30):
        assert not queue.enqueue(str(harness.book))
    release.set()
    eventually(lambda: not harness.pending())
    queue.enqueue(str(harness.book))
    eventually(lambda: not harness.pending())
    assert len(harness.calls) == 1


def test_stop_during_backoff_and_restart_preserves_successful_device(harness):
    queue = harness.start(lambda ips, stop: {ip: ip == "a.local" for ip in ips}, base=60, cap=60)
    queue.enqueue(str(harness.book))
    eventually(lambda: any(state.get("completed") for state in harness.manager.load_config()["calibre_watch"]["pending_jobs"].values()))
    started = time.monotonic()
    queue.stop()
    harness.threads[-1].join(0.5)
    assert not harness.threads[-1].is_alive()
    assert time.monotonic() - started < 0.5
    assert harness.pending() == [str(harness.book)]
    harness.start(lambda ips, stop: dict.fromkeys(ips, True))
    eventually(lambda: not harness.pending())
    assert harness.calls == [["a.local", "b.local"], ["b.local"]]


def test_stop_active_upload_keeps_durable_pending(harness):
    entered, release = threading.Event(), threading.Event()
    def attempt(ips, stop):
        entered.set()
        assert release.wait(2)
        return dict.fromkeys(ips, False)
    queue = harness.start(attempt)
    queue.enqueue(str(harness.book))
    assert entered.wait(2)
    queue.stop()
    assert queue.stop_event.is_set()
    assert harness.pending()
    release.set()
    harness.threads[-1].join(1)
    assert not harness.threads[-1].is_alive()
    assert harness.pending()
    harness.start(lambda ips, stop: dict.fromkeys(ips, True))
    eventually(lambda: not harness.pending())


def test_changed_content_even_same_size_mtime_invalidates_success(harness):
    queue = harness.start(lambda ips, stop: {ip: ip == "a.local" for ip in ips}, base=60, cap=60)
    queue.enqueue(str(harness.book))
    eventually(lambda: any(state.get("completed") for state in harness.manager.load_config()["calibre_watch"]["pending_jobs"].values()))
    queue.stop()
    harness.threads[-1].join(1)
    original = harness.book.stat()
    harness.book.write_bytes(b"edit")
    os.utime(harness.book, ns=(original.st_atime_ns, original.st_mtime_ns))
    harness.start(lambda ips, stop: dict.fromkeys(ips, True))
    eventually(lambda: not harness.pending())
    assert harness.calls[-1] == ["a.local", "b.local"]


def test_target_address_change_preserves_identity_but_new_target_is_sent(harness):
    queue = harness.start(lambda ips, stop: {ip: ip == "a.local" for ip in ips}, base=60, cap=60)
    queue.enqueue(str(harness.book))
    eventually(lambda: any(state.get("completed") for state in harness.manager.load_config()["calibre_watch"]["pending_jobs"].values()))
    queue.stop()
    harness.threads[-1].join(1)
    harness.targets = [{"ip": "a-new.local", "history_key": "reader-a"},
                       {"ip": "b.local", "history_key": "reader-b"},
                       {"ip": "c.local", "history_key": "reader-c"}]
    harness.start(lambda ips, stop: dict.fromkeys(ips, True))
    eventually(lambda: not harness.pending())
    assert harness.calls[-1] == ["b.local", "c.local"]


def test_legacy_pending_files_recovered_and_folder_change_invalidates_completion(harness):
    harness.owner._remember_watch_file(str(harness.book))
    harness.manager.update_config(lambda cfg: cfg["calibre_watch"].pop("pending_jobs", None))
    queue = harness.start(lambda ips, stop: {ip: ip == "a.local" for ip in ips}, base=60, cap=60)
    eventually(lambda: any(state.get("completed") for state in harness.manager.load_config()["calibre_watch"]["pending_jobs"].values()))
    queue.stop()
    harness.threads[-1].join(1)
    harness.remote_dir = "/Books"
    harness.start(lambda ips, stop: dict.fromkeys(ips, True))
    eventually(lambda: not harness.pending())
    assert harness.calls[-1] == ["a.local", "b.local"]


def test_changed_during_inflight_upload_retries_new_bytes(harness):
    def attempt(ips, stop):
        if len(harness.calls) == 1:
            harness.book.write_bytes(b"updated book")
        return dict.fromkeys(ips, True)
    queue = harness.start(attempt)
    queue.enqueue(str(harness.book))
    eventually(lambda: len(harness.calls) == 2 and not harness.pending())
    assert harness.calls[-1] == ["a.local", "b.local"]


def test_missing_pending_file_is_retained_until_library_returns(harness):
    harness.owner._remember_watch_file(str(harness.book))
    harness.book.unlink()
    harness.start(lambda ips, stop: dict.fromkeys(ips, True))
    assert harness.pending()
    harness.book.write_bytes(b"book")
    eventually(lambda: bool(harness.calls) and not harness.pending())


@pytest.mark.parametrize("state", [None, [], {"fingerprint": [1, "x", 2]},
                                    {"targets": [42]}, {"completed": "a"}])
def test_persisted_job_shape_validation(harness, state):
    with pytest.raises(ConfigSaveError):
        harness.manager.update_config(lambda cfg: cfg["calibre_watch"].update(pending_jobs={str(harness.book): state}))


def test_watch_worker_uses_saved_settings_without_tk(harness):
    owner = harness.owner
    owner.service._pipeline_lock = threading.Lock()
    owner.service._process_lock = threading.Lock()
    owner.service._shutting_down = False
    owner.service.logger = SimpleNamespace(info=lambda *args: None)
    # No app, Tk root or entries exist on this object.
    uploader = owner._make_watch_uploader()
    calls = []
    uploader.upload_to_targets = lambda path, **kwargs: calls.append(kwargs) or {"a.local": True}
    assert owner._attempt_watch_upload(str(harness.book), uploader, ["a.local"], threading.Event()) == {"a.local": True}
    assert calls == [{"only_ips": ["a.local"]}]


def test_stop_interrupts_pipeline_lock_wait(harness):
    owner = harness.owner
    owner.service._pipeline_lock = threading.Lock()
    owner.service._process_lock = threading.Lock()
    owner.service._shutting_down = False
    owner.service._pipeline_lock.acquire()
    stop = threading.Event()
    result = []
    worker = threading.Thread(target=lambda: result.append(owner._attempt_watch_upload(str(harness.book), object(), [], stop)))
    worker.start()
    stop.set()
    worker.join(0.5)
    owner.service._pipeline_lock.release()
    assert not worker.is_alive()
    assert result == [{}]


def test_target_changed_during_upload_is_not_forgotten(harness):
    def attempt(ips, stop):
        if len(harness.calls) == 1:
            harness.targets.append({"ip": "new.local", "history_key": "new-reader"})
        return dict.fromkeys(ips, True)
    queue = harness.start(attempt)
    queue.enqueue(str(harness.book))
    eventually(lambda: len(harness.calls) == 2 and not harness.pending())
    assert harness.calls[-1] == ["new.local"]


def test_retries_are_capped_and_stop_does_not_start_later_attempts(harness, monkeypatch):
    attempts = []
    def attempt(ips, stop):
        attempts.append(time.monotonic())
        return dict.fromkeys(ips, False)
    queue = harness.start(attempt, base=0.01, cap=0.02)
    requested_delays = []
    original_wait = queue._condition.wait
    def wait(timeout=None):
        if timeout is not None:
            requested_delays.append(timeout)
        return original_wait(timeout)
    monkeypatch.setattr(queue._condition, "wait", wait)
    queue.enqueue(str(harness.book))
    eventually(lambda: len(attempts) >= 7)
    queue.stop()
    harness.threads[-1].join(1)
    assert not harness.threads[-1].is_alive()
    # Inspect actual requested scheduler delays, excluding filesystem fsync and
    # other suite load. Uncapped backoff would request 0.04s on failure three.
    assert len(requested_delays) >= 4
    assert requested_delays[0] <= 0.01
    assert all(0 < delay <= 0.02 for delay in requested_delays)
    assert harness.pending()


def test_transient_initial_save_failure_keeps_event_and_retries_without_new_event(harness):
    errors = []
    def upload(ips, stop):
        assert harness.pending() == [str(harness.book)]
        return dict.fromkeys(ips, True)
    queue = harness.start(upload)
    original = queue.save
    writes = []
    def save(path, state):
        writes.append(state)
        if len(writes) == 1:
            raise ConfigSaveError("temporary configuration write failure")
        return original(path, state)
    queue.save = save
    queue.on_error = lambda path, error: errors.append(error)
    assert queue.enqueue(str(harness.book))
    eventually(lambda: bool(harness.calls) and not harness.pending())
    assert len(errors) == 1
    assert len(harness.calls) == 1


def test_watch_rechecks_file_stability_after_waiting_for_shared_locks(harness):
    owner = harness.owner
    pipeline = threading.Lock()
    process = threading.Lock()
    owner.service._pipeline_lock = pipeline
    owner.service._process_lock = process
    owner.service._shutting_down = False
    waits = []

    def wait(interval):
        assert pipeline.locked() and process.locked()
        waits.append(interval)
        # The file copy resumes while the job is blocked behind another sync.
        harness.book.write_bytes(b"copy still growing after lock wait")
        return False

    stop = SimpleNamespace(is_set=lambda: False, wait=wait)
    uploader = SimpleNamespace(upload_to_targets=lambda *args, **kwargs: pytest.fail(
        "unstable source reached the device after acquiring shared locks"))
    assert owner._attempt_watch_upload(str(harness.book), uploader, ["a.local"], stop) == {}
    assert waits
    assert not pipeline.locked() and not process.locked()


def test_retained_shutdown_event_cannot_upload_until_restart(harness):
    queue = harness.start(lambda ips, stop: dict.fromkeys(ips, True))
    queue.retain(str(harness.book))
    assert harness.pending() == [str(harness.book)]
    # A normal event for another book proves the worker is running and has
    # skipped the retained-only job, rather than merely not being scheduled yet.
    second = harness.book.with_name("second.epub")
    second.write_bytes(b"second")
    queue.enqueue(str(second))
    eventually(lambda: len(harness.calls) == 1 and str(second) not in harness.pending())
    assert harness.pending() == [str(harness.book)]
    queue.stop()
    harness.threads[-1].join(1)
    harness.start(lambda ips, stop: dict.fromkeys(ips, True))
    eventually(lambda: len(harness.calls) == 2 and not harness.pending())


def test_actual_observer_event_immediate_shutdown_restart_checks_source_stability(harness, monkeypatch):
    import sys
    from types import ModuleType
    from websync.watch.calibre import CalibreWatcher
    import websync.watch.retry as retry_module

    registered = []
    observer = SimpleNamespace(
        schedule=lambda handler, *args, **kwargs: registered.append(handler),
        start=lambda: None, stop=lambda: None, join=lambda **kwargs: None,
    )
    observers = ModuleType("watchdog.observers")
    observers.Observer = lambda: observer
    events = ModuleType("watchdog.events")
    events.FileSystemEventHandler = type("FileSystemEventHandler", (), {})
    monkeypatch.setitem(sys.modules, "watchdog", ModuleType("watchdog"))
    monkeypatch.setitem(sys.modules, "watchdog.observers", observers)
    monkeypatch.setitem(sys.modules, "watchdog.events", events)

    queue = harness.start(lambda ips, stop: pytest.fail("shutdown handoff uploaded an unstabilized file"))
    watcher = CalibreWatcher(str(harness.book.parent), queue.enqueue, debounce_sec=60,
                             on_pending_file=queue.retain)
    assert watcher.start()
    registered[0].on_created(SimpleNamespace(is_directory=False, src_path=str(harness.book)))
    watcher.stop()
    queue.stop()
    harness.threads[-1].join(1)
    assert harness.pending() == [str(harness.book)]
    assert watcher._debounce_timer is None
    assert not harness.calls

    original = retry_module.file_fingerprint
    reads = []
    def changed_during_stability_check(path):
        signature = original(path)
        reads.append(signature)
        if len(reads) == 1:
            # The library copy resumes after app startup: its first sample must
            # not reach the network before the changed file has stabilized.
            harness.book.write_bytes(b"finished copy")
        return signature
    monkeypatch.setattr(retry_module, "file_fingerprint", changed_during_stability_check)
    def upload(ips, stop):
        assert len(reads) >= 2
        assert harness.book.read_bytes() == b"finished copy"
        return dict.fromkeys(ips, True)
    harness.start(upload)
    eventually(lambda: len(harness.calls) == 1 and not harness.pending())
