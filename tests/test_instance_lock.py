import os
import sys
import tempfile
from unittest.mock import patch

import x3_websync
from websync.core import instance_lock


def test_acquire_and_release_lock():
    with tempfile.TemporaryDirectory() as tmp:
        lock_path = os.path.join(tmp, "test.lock")

        with patch.object(instance_lock, "_lock_path", return_value=lock_path):
            assert x3_websync.acquire_instance_lock() is True
            assert os.path.exists(lock_path)
            x3_websync.release_instance_lock()
            assert not os.path.exists(lock_path)


def test_duplicate_lock_denied():
    with tempfile.TemporaryDirectory() as tmp:
        lock_path = os.path.join(tmp, "test.lock")

        with patch.object(instance_lock, "_lock_path", return_value=lock_path):
            assert x3_websync.acquire_instance_lock() is True
            assert x3_websync.acquire_instance_lock() is False
            x3_websync.release_instance_lock()


def test_stale_lock_removed_when_pid_dead():
    with tempfile.TemporaryDirectory() as tmp:
        lock_path = os.path.join(tmp, "test.lock")
        with open(lock_path, "w", encoding="utf-8") as f:
            f.write("999999999,2020-01-01T00:00:00")

        with patch.object(instance_lock, "_lock_path", return_value=lock_path):
            with patch.object(instance_lock, "_is_process_running", return_value=False):
                assert x3_websync.acquire_instance_lock() is True
                x3_websync.release_instance_lock()


def test_sync_mode_skips_gui_lock_in_main():
    """--sync 플래그 시 GUI 락을 건너뛰는지 argparse 분기 검증"""
    with patch.object(sys, "argv", ["x3_websync.py", "--sync"]):
        with patch.object(x3_websync, "acquire_instance_lock") as mock_lock:
            with patch.object(x3_websync, "ConfigManager"):
                with patch.object(x3_websync, "SyncService") as mock_svc:
                    with patch.object(x3_websync, "get_logger"):
                        with patch.object(x3_websync, "release_instance_lock"):
                            with patch.object(x3_websync.sys, "exit"):
                                mock_svc.return_value.run_sync_pipeline.return_value = True
                                x3_websync.main()
                                mock_lock.assert_not_called()