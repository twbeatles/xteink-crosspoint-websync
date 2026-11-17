"""Opt-in real launchd contract; unique temporary label, plist and synthetic job."""

import os
import subprocess
import sys
import time
import uuid

import pytest

from websync.scheduler.manager import SchedulerManager


@pytest.mark.skipif(
    sys.platform != "darwin" or os.environ.get("WEBSYNC_NATIVE_SCHEDULER") != "1",
    reason="Opt-in macOS launchd test",
)
def test_native_macos_register_change_and_remove(tmp_path, monkeypatch):
    # Only this test's random label is ever loaded or unloaded. No reader/config.
    manager = SchedulerManager(str(tmp_path / "scheduled.py"))
    manager.TASK_NAME = "WebSyncTest_" + uuid.uuid4().hex
    (tmp_path / "logs").mkdir()
    marker = tmp_path / "ran"
    (tmp_path / "scheduled.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ok')\n",
        encoding="utf-8",
    )
    real_expand = os.path.expanduser
    monkeypatch.setattr(
        os.path,
        "expanduser",
        lambda path: (
            str(tmp_path)
            if path == "~/Library/LaunchAgents"
            else (
                str(tmp_path / path.rsplit("/", 1)[-1])
                if path.startswith("~/Library/LaunchAgents/")
                else real_expand(path)
            )
        ),
    )
    plist = tmp_path / f"com.x3websync.{manager.TASK_NAME}.plist"
    try:
        assert manager.register_daily_task("07", "00"), manager.last_error
        assert manager._macos_job_loaded() is True
        # Start this synthetic job without waiting for the calendar interval.
        subprocess.run(
            ["launchctl", "start", f"com.x3websync.{manager.TASK_NAME}"],
            check=True,
            timeout=10,
        )
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.read_text() == "ok"
        assert manager.register_daily_task("08", "30"), manager.last_error
        assert "<integer>8</integer>" in plist.read_text(encoding="utf-8")
        assert manager.unregister_task(), manager.last_error
        assert not plist.exists()
        assert manager._macos_job_loaded() is False
        assert manager.unregister_task(), manager.last_error
    finally:
        # Best effort cleanup strictly targets the random test job.
        if plist.exists():
            subprocess.run(
                ["launchctl", "unload", str(plist)], capture_output=True, timeout=15
            )
