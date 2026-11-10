"""Audit regressions: synthetic files/OS results only, never user schedules."""
import os
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from websync.upload.device_client import X3DeviceClient, DeviceClientError
from websync.upload.local_path import plan_local_downloads, publish_local_download
from websync.scheduler.manager import SchedulerManager
from websync.gui.sync_tab.schedule import SyncScheduleMixin


@pytest.mark.parametrize("timing", ["before_request", "during_stream", "before_publish"])
def test_download_race_preserves_competing_file(tmp_path, monkeypatch, timing):
    target = Path(plan_local_downloads(str(tmp_path), ["book.epub"], overwrite=False)[0]["path"])
    if timing == "before_request":
        target.write_bytes(b"USER")

    def chunks(chunk_size):
        if timing == "during_stream":
            target.write_bytes(b"USER")
        yield b"DEVICE"

    response = SimpleNamespace(status_code=200, iter_content=chunks, close=Mock())
    monkeypatch.setattr("websync.upload.device_client.requests.get", lambda *a, **k: response)
    if timing == "before_publish":
        def publish(temp, local, **kwargs):
            target.write_bytes(b"USER")
            return publish_local_download(temp, local, **kwargs)
        monkeypatch.setattr("websync.upload.local_path.publish_local_download", publish)
    with pytest.raises(DeviceClientError):
        X3DeviceClient("192.0.2.1").download("/book.epub", str(target))
    assert target.read_bytes() == b"USER"
    assert not list(tmp_path.glob("*.part"))
    response.close.assert_called_once()


def test_download_explicit_overwrite(tmp_path, monkeypatch):
    target = tmp_path / "book.epub"
    target.write_bytes(b"USER")
    response = SimpleNamespace(status_code=200, iter_content=lambda **kw: [b"DEVICE"], close=Mock())
    monkeypatch.setattr("websync.upload.device_client.requests.get", lambda *a, **k: response)
    assert X3DeviceClient("192.0.2.1").download("/book.epub", str(target), overwrite=True)
    assert target.read_bytes() == b"DEVICE"


def test_download_directory_failure_is_reported_and_response_closed(tmp_path, monkeypatch):
    parent = tmp_path / "file-not-directory"
    parent.write_bytes(b"USER")
    response = SimpleNamespace(status_code=200, close=Mock())
    monkeypatch.setattr("websync.upload.device_client.requests.get", lambda *a, **k: response)
    with pytest.raises(DeviceClientError):
        X3DeviceClient("192.0.2.1").download("/book.epub", str(parent / "book.epub"))
    assert parent.read_bytes() == b"USER"
    response.close.assert_called_once()


def test_publish_after_competing_process(tmp_path):
    temp = tmp_path / "temp.part"
    temp.write_bytes(b"DEVICE")
    target = tmp_path / "book.epub"
    subprocess.run([sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'USER')", str(target)], check=True)
    with pytest.raises(FileExistsError):
        publish_local_download(str(temp), str(target))
    assert target.read_bytes() == b"USER"


def _result(code, error=""):
    return SimpleNamespace(returncode=code, stdout="", stderr=error)


@pytest.mark.parametrize("loaded", [True, None])
def test_macos_unload_failure_preserves_plist(tmp_path, monkeypatch, loaded):
    mgr = SchedulerManager(str(tmp_path / "app.py"))
    plist = tmp_path / "task.plist"
    plist.write_text("ORIGINAL", encoding="utf-8")
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("os.path.expanduser", lambda p: str(plist))
    monkeypatch.setattr(mgr, "_macos_job_loaded", lambda: loaded)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _result(5, "Unload failed: I/O error"))
    assert mgr.unregister_task() is False
    assert "I/O error" in mgr.last_error
    assert plist.read_text(encoding="utf-8") == "ORIGINAL"


@pytest.mark.parametrize("code, loaded", [(0, True), (5, False)])
def test_macos_unload_success_or_known_absence(tmp_path, monkeypatch, code, loaded):
    mgr = SchedulerManager(str(tmp_path / "app.py"))
    plist = tmp_path / "task.plist"
    plist.write_text("ORIGINAL", encoding="utf-8")
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("os.path.expanduser", lambda p: str(plist))
    monkeypatch.setattr(mgr, "_macos_job_loaded", lambda: loaded)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _result(code))
    assert mgr.unregister_task() is True
    assert not plist.exists()


def test_macos_state_is_not_inferred_from_plist(monkeypatch, tmp_path):
    mgr = SchedulerManager(str(tmp_path / "app.py"))
    monkeypatch.setattr("sys.platform", "darwin")
    from websync.i18n import t
    for result, expected in [(_result(0), "registered_launchd"),
                             (_result(113, "Could not find service"), "not_registered"),
                             (_result(5, "Permission denied"), "status_unknown")]:
        monkeypatch.setattr("subprocess.run", lambda *a, _r=result, **k: _r)
        assert mgr.get_task_status() == t("scheduler." + expected)


def test_macos_schedule_change_keeps_old_plist_when_unload_fails(tmp_path, monkeypatch):
    mgr = SchedulerManager(str(tmp_path / "app.py"))
    plist = tmp_path / f"com.x3websync.{mgr.TASK_NAME}.plist"
    plist.write_text("ORIGINAL", encoding="utf-8")
    monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path))
    monkeypatch.setattr(mgr, "_macos_job_loaded", lambda: True)
    run = Mock(return_value=_result(5, "Unload failed"))
    monkeypatch.setattr("subprocess.run", run)
    assert mgr._register_macos(8, 30) is False
    assert plist.read_text(encoding="utf-8") == "ORIGINAL"
    assert run.call_count == 1


def _cron_command(command):
    """Cronie's pre-shell escape state machine (including backslashes)."""
    output = []
    escaped = False
    for char in command:
        if escaped:
            if char == "%":
                output.pop()
            output.append(char)
            escaped = False
        elif char == "\\":
            output.append(char)
            escaped = True
        elif char == "%":
            break
        else:
            output.append(char)
    return "".join(output)


@pytest.mark.parametrize("path", ["/tmp/100%news", "/tmp/a % b", "/tmp/a'\\%b%%", "/tmp/a\\\\%"])
def test_cron_percent_and_shell_roundtrip(path):
    quoted = SchedulerManager._cron_quote(path)
    assert shlex.split(_cron_command(quoted)) == [path]


@pytest.mark.parametrize("bad", ["\n", "\r", "\x00", "\t"])
def test_cron_control_character_rejected_before_install(tmp_path, monkeypatch, bad):
    mgr = SchedulerManager(str(tmp_path / "app.py"))
    mgr.project_dir += bad
    run = Mock()
    monkeypatch.setattr("subprocess.run", run)
    assert mgr._register_linux(7, 0) is False
    assert "control characters" in mgr.last_error
    run.assert_not_called()


@pytest.mark.skipif(os.name == "nt", reason="Requires POSIX shell")
def test_cron_generated_command_reaches_fake_sync(tmp_path, monkeypatch):
    project = tmp_path / "reader ' \\% news"
    (project / "logs").mkdir(parents=True)
    script = project / "app.py"
    script.write_text("import pathlib,sys; pathlib.Path('called').write_text('|'.join(sys.argv[1:]))", encoding="utf-8")
    mgr = SchedulerManager(str(script))
    command = mgr._build_cron_line(7, 0).split(" ", 5)[5]
    subprocess.run(["/bin/sh", "-c", _cron_command(command)], check=True)
    assert (project / "called").read_text() == "--sync"


@pytest.mark.parametrize("operation", ["register", "unregister"])
@pytest.mark.parametrize("os_ok, save_ok", [(False, True), (True, False), (True, True)])
def test_schedule_gui_distinguishes_os_and_config_results(monkeypatch, operation, os_ok, save_ok):
    from websync.gui.sync_tab import schedule
    info, warning, error = Mock(), Mock(), Mock()
    monkeypatch.setattr(schedule.messagebox, "showinfo", info)
    monkeypatch.setattr(schedule.messagebox, "showwarning", warning)
    monkeypatch.setattr(schedule.messagebox, "showerror", error)
    original = {"schedule": {"enabled": operation == "unregister"}}
    save = Mock(return_value=save_ok)
    panel = SimpleNamespace(
        service=SimpleNamespace(config=original),
        app=SimpleNamespace(_save_ui_settings=lambda: True, _safe_save_config=save),
        scheduler=SimpleNamespace(register_daily_task=lambda *a: os_ok, unregister_task=lambda: os_ok, last_error="OS ERROR"),
        hour_cb=SimpleNamespace(get=lambda: "07"), min_cb=SimpleNamespace(get=lambda: "00"),
        _refresh_schedule_status=Mock(),
    )
    getattr(SyncScheduleMixin, "_" + operation + "_schedule")(panel)
    assert info.called == (os_ok and save_ok)
    assert save.called == os_ok
    assert original["schedule"]["enabled"] == (operation == "unregister")
    panel._refresh_schedule_status.assert_called_once()
