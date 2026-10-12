"""Pipeline lock contract: class-level lock serializes instances; GUI+CLI share path."""
import threading
import time

from websync.config.manager import ConfigManager
from websync.core.process_lock import ProcessFileLock
from websync.db.history import SyncHistoryDb
from websync.pipeline.service import SyncService
from unittest.mock import patch


def _svc(tmp_path, name):
    cm = ConfigManager(str(tmp_path / f"{name}.json"))
    cfg = cm.load_config()
    cfg["portable_data"] = {"enabled": False}
    cm.save_config(cfg)
    db = SyncHistoryDb(str(tmp_path / f"{name}.db"))
    with patch("websync.pipeline.service.SyncHistoryDb", return_value=db), \
         patch("websync.backup.local_import.import_local_sidecars", return_value={}):
        return SyncService(cm)


def test_class_lock_serializes_two_instances(tmp_path):
    a = _svc(tmp_path, "a")
    b = _svc(tmp_path, "b")
    assert SyncService._pipeline_lock is type(a)._pipeline_lock
    acquired = []
    release = threading.Event()

    def _hold():
        assert a._try_acquire_pipeline_locks()
        acquired.append(True)
        release.wait(timeout=5)
        a._release_pipeline_locks()

    t = threading.Thread(target=_hold)
    t.start()
    while not acquired:
        time.sleep(0.01)
    try:
        assert b._try_acquire_pipeline_locks() is False
    finally:
        release.set()
        t.join(timeout=5)
    assert b._try_acquire_pipeline_locks() is True
    b._release_pipeline_locks()


def test_second_run_while_running_returns_false(tmp_path):
    svc = _svc(tmp_path, "solo")
    assert svc._try_acquire_pipeline_locks() is True
    try:
        assert svc.run_sync_pipeline(log_callback=lambda _m: None) is False
    finally:
        svc._release_pipeline_locks()


def test_process_lock_paths_agree():
    a = ProcessFileLock()
    b = ProcessFileLock()
    assert a.lock_path == b.lock_path
