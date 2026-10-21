"""Regression guard: the updater must be able to replace an executable that is still held.

History: on Windows a running exe cannot be overwritten or deleted, only renamed. The
old copy-then-overwrite swap failed with WinError 5, its rollback failed the same
way, and the leftover backup then blocked every later attempt (FileExistsError).
These tests pin the behaviour that keeps the update path from breaking again.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from argparse import Namespace
from pathlib import Path

import pytest

from websync.core.update import installer
from websync.core.update.installer import (
    UpdateApplyError,
    apply_staged_update,
    clean_frozen_environment,
    consume_update_result,
    launch_update_helper,
)

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows locks running executables")


def _files(tmp_path, old=b"old-1.0.0", new=b"new-1.1.0"):
    target = tmp_path / "app.exe"
    staged = tmp_path / "update.exe"
    backup = tmp_path / "app.exe.v1.0.0.bak"
    target.write_bytes(old)
    staged.write_bytes(new)
    return target, staged, backup


@pytest.fixture
def held_exe(tmp_path):
    """A real running process whose image file is the update target."""
    target = tmp_path / "app.exe"
    staged = tmp_path / "update.exe"
    shutil.copy2(sys.executable, target)
    shutil.copy2(sys.executable, staged)
    with open(staged, "ab") as handle:
        handle.write(b"\0new-build-marker")
    proc = subprocess.Popen([str(target), "-c", "import time; time.sleep(60)"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.0)
        if proc.poll() is not None:
            pytest.skip("copied interpreter does not stay running in this environment")
        yield target, staged, tmp_path / "app.exe.v1.0.0.bak", proc
    finally:
        proc.kill()
        proc.wait()


@windows_only
def test_fixture_really_locks_the_target(held_exe):
    """Sanity: if this fails the tests below prove nothing."""
    target, staged, _backup, _proc = held_exe
    with pytest.raises(PermissionError):
        os.replace(staged, target)


@windows_only
def test_replaces_executable_that_is_still_running(held_exe, monkeypatch):
    target, staged, backup, proc = held_exe
    old_bytes = target.read_bytes()
    new_bytes = staged.read_bytes()
    monkeypatch.setattr("time.sleep", lambda _s: None)  # no retry delay may be needed

    apply_staged_update(target=target, staged=staged, backup=backup, smoke_runner=lambda _p: True)

    assert target.read_bytes() == new_bytes
    assert backup.read_bytes() == old_bytes
    assert not staged.exists()
    assert proc.poll() is None  # the old process keeps running from the renamed image


@windows_only
def test_rollback_works_while_old_executable_is_still_running(held_exe, monkeypatch):
    target, staged, backup, proc = held_exe
    old_bytes = target.read_bytes()
    monkeypatch.setattr("time.sleep", lambda _s: None)

    with pytest.raises(UpdateApplyError, match="rolled back"):
        apply_staged_update(target=target, staged=staged, backup=backup, smoke_runner=lambda _p: False)

    assert target.read_bytes() == old_bytes
    assert proc.poll() is None


def test_stale_backup_from_failed_attempt_does_not_block_retry(tmp_path):
    target, staged, backup = _files(tmp_path)
    backup.write_bytes(b"leftover-from-earlier-failed-attempt")

    apply_staged_update(target=target, staged=staged, backup=backup, smoke_runner=lambda _p: True)

    assert target.read_bytes() == b"new-1.1.0"
    assert backup.read_bytes() == b"old-1.0.0"


def test_failed_first_move_leaves_installation_untouched(tmp_path, monkeypatch):
    target, staged, backup = _files(tmp_path)
    real_replace = os.replace

    def locked(src, dst):
        if Path(src) == target.resolve() or Path(src) == target:
            raise PermissionError(13, "access denied")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", locked)
    monkeypatch.setattr(installer, "_REPLACE_RETRY_ATTEMPTS", 3)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    with pytest.raises(UpdateApplyError, match="not changed"):
        apply_staged_update(target=target, staged=staged, backup=backup, smoke_runner=lambda _p: True)

    assert target.read_bytes() == b"old-1.0.0"
    assert staged.read_bytes() == b"new-1.1.0"
    assert not backup.exists()  # nothing left behind to block the next attempt


def test_failed_attempt_does_not_poison_the_next_one(tmp_path, monkeypatch):
    target, staged, backup = _files(tmp_path)
    real_replace = os.replace
    state = {"locked": True}

    def maybe_locked(src, dst):
        if state["locked"] and Path(src) in (target, target.resolve()):
            raise PermissionError(13, "access denied")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", maybe_locked)
    monkeypatch.setattr(installer, "_REPLACE_RETRY_ATTEMPTS", 2)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    with pytest.raises(UpdateApplyError):
        apply_staged_update(target=target, staged=staged, backup=backup, smoke_runner=lambda _p: True)

    state["locked"] = False
    apply_staged_update(target=target, staged=staged, backup=backup, smoke_runner=lambda _p: True)
    assert target.read_bytes() == b"new-1.1.0"


def test_interrupted_swap_is_recovered_before_the_next_update(tmp_path):
    """Killed between the two moves: target missing, backup holds the only good copy."""
    target, staged, backup = _files(tmp_path)
    backup.write_bytes(b"old-1.0.0")
    target.unlink()

    apply_staged_update(target=target, staged=staged, backup=backup, smoke_runner=lambda _p: True)

    assert target.read_bytes() == b"new-1.1.0"
    assert backup.read_bytes() == b"old-1.0.0"


def test_interrupted_swap_with_failing_update_restores_the_good_copy(tmp_path):
    target, staged, backup = _files(tmp_path)
    backup.write_bytes(b"old-1.0.0")
    target.unlink()

    with pytest.raises(UpdateApplyError, match="rolled back"):
        apply_staged_update(target=target, staged=staged, backup=backup, smoke_runner=lambda _p: False)

    assert target.read_bytes() == b"old-1.0.0"


def test_consecutive_upgrades_keep_working(tmp_path):
    target = tmp_path / "app.exe"
    target.write_bytes(b"v1")
    for old, new in ((b"v1", b"v2"), (b"v2", b"v3"), (b"v3", b"v4")):
        staged = tmp_path / "update.exe"
        staged.write_bytes(new)
        backup = tmp_path / f"app.exe.v{old.decode()}.bak"
        apply_staged_update(target=target, staged=staged, backup=backup, smoke_runner=lambda _p: True)
        assert target.read_bytes() == new
        assert backup.read_bytes() == old
    # Retrying the same version name after a success overwrites its own old backup.
    staged = tmp_path / "update.exe"
    staged.write_bytes(b"v5")
    apply_staged_update(target=target, staged=staged, backup=tmp_path / "app.exe.vv3.bak",
                        smoke_runner=lambda _p: True)
    assert target.read_bytes() == b"v5"


def test_clean_frozen_environment_drops_bootloader_state(monkeypatch):
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "C:/old/app.exe")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "C:/Temp/_MEI123")
    monkeypatch.setenv("_MEIPASS2", "C:/Temp/_MEI123")
    monkeypatch.setenv("PATH_MARKER", "keep")
    env = clean_frozen_environment()
    assert not [key for key in env if key.startswith("_PYI_")]
    assert "_MEIPASS2" not in env
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert env["PATH_MARKER"] == "keep"


def test_helper_is_spawned_with_clean_environment(tmp_path, monkeypatch):
    staged = tmp_path / ".updates" / "update-9.9.9-abc.exe"
    staged.parent.mkdir()
    staged.write_bytes(b"x")
    captured = {}
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "C:/old/app.exe")
    monkeypatch.setattr(shutil, "copy2", lambda src, dst: Path(dst).write_bytes(b"helper"))
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: captured.update(cmd=cmd, **kw) or object())

    launch_update_helper(target=tmp_path / "app.exe", staged=staged, backup=tmp_path / "app.exe.bak",
                         parent_pid=123, expected_sha256="ab" * 32, expected_size=1,
                         result_file=tmp_path / "result.json")

    assert "--apply-update" in captured["cmd"]
    assert "_PYI_ARCHIVE_FILE" not in captured["env"]
    assert captured["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert Path(captured["cmd"][0]).parent == staged.parent


def _args(tmp_path, target, staged, backup, **over):
    base = dict(update_target=str(target), update_staged=str(staged), update_backup=str(backup),
                update_parent_pid=0, update_expected_sha256=None, update_expected_size=None,
                update_result_file=str(tmp_path / "result.json"))
    base.update(over)
    return Namespace(**base)


def test_helper_success_reports_applied_and_relaunches_cleanly(tmp_path, monkeypatch):
    from websync.cli import update_apply

    target, staged, backup = _files(tmp_path)
    launched = {}
    real_apply = update_apply.apply_staged_update
    monkeypatch.setattr(update_apply, "apply_staged_update",
                        lambda **kw: real_apply(**kw, smoke_runner=lambda _p: True))
    monkeypatch.setattr(update_apply.subprocess, "Popen",
                        lambda cmd, **kw: launched.update(cmd=cmd, **kw) or object())

    assert update_apply.handle_apply_update(_args(tmp_path, target, staged, backup)) == 0

    assert target.read_bytes() == b"new-1.1.0"
    assert consume_update_result(tmp_path / "result.json")["status"] == "applied"
    assert launched["cmd"] == [str(target)]
    assert launched["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_helper_failure_reports_reason_and_does_not_relaunch(tmp_path, monkeypatch):
    from websync.cli import update_apply

    target, staged, backup = _files(tmp_path)
    staged.unlink()
    launched = []
    monkeypatch.setattr(update_apply.subprocess, "Popen", lambda *a, **k: launched.append(a))

    assert update_apply.handle_apply_update(_args(tmp_path, target, staged, backup)) == 1

    result = consume_update_result(tmp_path / "result.json")
    assert result["status"] == "failed" and result["error"]
    assert target.read_bytes() == b"old-1.0.0"
    assert not launched


def test_helper_gives_up_cleanly_when_parent_never_exits(tmp_path, monkeypatch):
    from websync.cli import update_apply

    target, staged, backup = _files(tmp_path)
    monkeypatch.setattr(update_apply, "_is_process_running", lambda _pid: True)
    monkeypatch.setattr(update_apply.time, "sleep", lambda _s: None)

    assert update_apply.handle_apply_update(_args(tmp_path, target, staged, backup, update_parent_pid=4242)) == 1

    assert consume_update_result(tmp_path / "result.json")["status"] == "failed"
    assert target.read_bytes() == b"old-1.0.0" and staged.exists()
    assert not backup.exists()


def test_apply_never_overwrites_target_in_place():
    """Static contract: the swap must move the target aside, never overwrite it directly."""
    source = Path(installer.__file__).read_text(encoding="utf-8")
    body = source[source.index("def apply_staged_update("):source.index("def launch_update_helper(")]
    assert "shutil.copy2(target_path, backup_path)" not in body
    assert body.index("_replace_with_retry(target_path, backup_path)") < body.index(
        "_replace_with_retry(staged_path, target_path)")
