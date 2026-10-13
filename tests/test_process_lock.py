import os
import tempfile
import threading
import time

from websync.core import paths
from websync.core.process_lock import DEFAULT_PIPELINE_LOCK_NAME, ProcessFileLock


def test_process_lock_exclusive():
    fd, path = tempfile.mkstemp(suffix=".lock")
    os.close(fd)
    try:
        os.remove(path)
    except OSError:
        pass

    a = ProcessFileLock(path)
    b = ProcessFileLock(path)
    assert a.acquire(blocking=False) is True
    assert b.acquire(blocking=False) is False
    a.release()
    assert b.acquire(blocking=False) is True
    b.release()
    try:
        os.remove(path)
    except OSError:
        pass


def test_process_lock_held_flag():
    fd, path = tempfile.mkstemp(suffix=".lock")
    os.close(fd)
    try:
        os.remove(path)
    except OSError:
        pass
    lock = ProcessFileLock(path)
    assert lock.held is False
    assert lock.acquire(blocking=False)
    assert lock.held is True
    lock.release()
    assert lock.held is False
    try:
        os.remove(path)
    except OSError:
        pass


def test_is_held_by_other_while_locked():
    fd, path = tempfile.mkstemp(suffix=".lock")
    os.close(fd)
    try:
        os.remove(path)
    except OSError:
        pass
    holder = ProcessFileLock(path)
    probe = ProcessFileLock(path)
    assert holder.acquire(blocking=False)
    assert probe.is_held_by_other() is True
    holder.release()
    assert probe.is_held_by_other() is False
    try:
        os.remove(path)
    except OSError:
        pass


def test_default_pipeline_lock_lives_under_project_root():
    lock = ProcessFileLock()
    expected = os.path.normpath(os.path.join(paths.PROJECT_ROOT, DEFAULT_PIPELINE_LOCK_NAME))
    assert os.path.normpath(lock.lock_path) == expected
