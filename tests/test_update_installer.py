"""업데이트 다운로드 준비, 교체, 스모크 검증, 백업 및 롤백 단위 테스트."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from websync.core.update_installer import (
    UpdateApplyError,
    apply_staged_update,
    cleanup_stale_update_artifacts,
    cleanup_update_backups,
    consume_update_result,
    find_update_target_for_staging,
    is_running_from_staging,
    is_staging_artifact_name,
    prepare_staged_update,
    write_update_result,
)
from websync.core.update_manifest import ReleaseManifest


@pytest.fixture
def dummy_manifest():
    return ReleaseManifest(
        version="1.1.0",
        artifact_url="https://example.invalid/test.exe",
        artifact_sha256="",
        artifact_size=0,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        signature="dummy",
    )


def test_prepare_staged_update_success(tmp_path):
    data = b"hello update binary content"
    digest = hashlib.sha256(data).hexdigest()
    manifest = ReleaseManifest(
        version="1.1.0",
        artifact_url="https://example.invalid/test.exe",
        artifact_sha256=digest,
        artifact_size=len(data),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        signature="dummy",
    )

    staged = prepare_staged_update(
        manifest,
        chunks=[data[:10], data[10:]],
        staging_root=tmp_path,
    )
    assert staged is not None
    assert staged.is_file()
    assert staged.read_bytes() == data


def test_prepare_staged_update_hash_mismatch(tmp_path):
    data = b"hello update binary content"
    manifest = ReleaseManifest(
        version="1.1.0",
        artifact_url="https://example.invalid/test.exe",
        artifact_sha256="0" * 64,  # 잘못된 해시
        artifact_size=len(data),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        signature="dummy",
    )

    with pytest.raises(ValueError, match="hash mismatch"):
        prepare_staged_update(
            manifest,
            chunks=[data],
            staging_root=tmp_path,
        )
    # 실패 후 임시 파일이 정리되었는지 확인
    assert len(list(tmp_path.glob("update-*.exe"))) == 0


def test_apply_staged_update_success_and_backup(tmp_path):
    target = tmp_path / "app.exe"
    target.write_bytes(b"version 1.0.0")

    staged = tmp_path / "update.exe"
    staged.write_bytes(b"version 1.1.0")

    backup = tmp_path / "app.exe.v1.0.0.bak"

    def fake_smoke(p: Path) -> bool:
        return True

    apply_staged_update(
        target=target,
        staged=staged,
        backup=backup,
        smoke_runner=fake_smoke,
    )

    assert target.read_bytes() == b"version 1.1.0"
    assert backup.read_bytes() == b"version 1.0.0"
    assert not staged.exists()


def test_apply_staged_update_smoke_fail_triggers_rollback(tmp_path):
    target = tmp_path / "app.exe"
    target.write_bytes(b"good version 1.0.0")

    staged = tmp_path / "update.exe"
    staged.write_bytes(b"corrupted version 1.1.0")

    backup = tmp_path / "app.exe.v1.0.0.bak"

    def failing_smoke(p: Path) -> bool:
        return False

    with pytest.raises(UpdateApplyError, match="rolled back"):
        apply_staged_update(
            target=target,
            staged=staged,
            backup=backup,
            smoke_runner=failing_smoke,
        )

    # 원본 파일로 자동 롤백되었는지 확인
    assert target.read_bytes() == b"good version 1.0.0"


def test_cleanup_update_backups(tmp_path):
    target = tmp_path / "app.exe"
    target.write_text("main", encoding="utf-8")

    # 백업 4개 생성
    for i in range(4):
        bk = tmp_path / f"app.exe.v1.0.{i}.bak"
        bk.write_text(f"bk{i}", encoding="utf-8")

    cleanup_update_backups(target, keep_count=2)
    remaining = list(tmp_path.glob("app.exe.v*.bak"))
    assert len(remaining) <= 2


def test_write_and_consume_update_result(tmp_path):
    res_file = tmp_path / "last-update-result.json"
    assert consume_update_result(res_file) is None

    write_update_result(res_file, {"status": "applied", "version": "1.1.0"})
    assert res_file.is_file()

    consumed = consume_update_result(res_file)
    assert consumed is not None
    assert consumed["status"] == "applied"
    assert consumed["version"] == "1.1.0"

    # 소비 후 파일 삭제 확인
    assert not res_file.exists()
    assert consume_update_result(res_file) is None


def test_prepare_staged_update_cancel_event(tmp_path):
    import threading
    from websync.core.update_installer import UpdateCancelledError

    data = b"test cancellation content"
    digest = hashlib.sha256(data).hexdigest()
    manifest = ReleaseManifest(
        version="1.1.0",
        artifact_url="https://example.invalid/test.exe",
        artifact_sha256=digest,
        artifact_size=len(data),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        signature="dummy",
    )

    cancel_event = threading.Event()
    cancel_event.set()  # 이미 취소됨

    with pytest.raises(UpdateCancelledError, match="취소"):
        prepare_staged_update(
            manifest,
            chunks=[data],
            staging_root=tmp_path,
            cancel_event=cancel_event,
        )

    # 임시 파일이 깨끗하게 정리되었는지 확인
    assert len(list(tmp_path.glob("update-*.exe"))) == 0


def test_cleanup_stale_update_artifacts(tmp_path):
    staging = tmp_path / ".updates"
    staging.mkdir()
    staged = staging / "update-1.3.6-abc123.exe"
    staged.write_bytes(b"new")
    helper = staging / "update-helper-def456.exe"
    helper.write_bytes(b"helper")
    result = staging / "last-update-result.json"
    result.write_text("{}", encoding="utf-8")
    keep = staging / "notes.txt"
    keep.write_text("keep", encoding="utf-8")

    removed = cleanup_stale_update_artifacts(staging)

    assert {p.name for p in removed} == {staged.name, helper.name}
    assert not staged.exists()
    assert not helper.exists()
    assert result.is_file()
    assert keep.is_file()


def test_cleanup_stale_update_artifacts_missing_dir(tmp_path):
    assert cleanup_stale_update_artifacts(tmp_path / "no-such-dir") == []


def test_cleanup_stale_update_artifacts_skips_current_exe(tmp_path):
    staging = tmp_path / ".updates"
    staging.mkdir()
    current = staging / "update-helper-running.exe"
    current.write_bytes(b"running")
    other = staging / "update-1.0.0-old.exe"
    other.write_bytes(b"old")

    removed = cleanup_stale_update_artifacts(staging, current_exe=current)

    assert [p.name for p in removed] == [other.name]
    assert current.is_file()
    assert not other.exists()


def test_is_staging_artifact_name():
    assert is_staging_artifact_name("update-1.3.6-abc.exe")
    assert is_staging_artifact_name("UPDATE-HELPER-ABC.EXE")
    assert not is_staging_artifact_name("x3_websync.exe")
    assert not is_staging_artifact_name("update-notes.txt")
    assert not is_staging_artifact_name("")


def test_is_running_from_staging_dev_mode():
    assert is_running_from_staging("/app/.updates/update-helper-x.exe") is False


def test_find_update_target_for_staging_prefers_primary(tmp_path):
    base = tmp_path / "app"
    staging = base / ".updates"
    staging.mkdir(parents=True)
    primary = base / "x3_websync.exe"
    primary.write_bytes(b"app")
    (base / "other-tool.exe").write_bytes(b"other")

    assert find_update_target_for_staging(staging) == primary.resolve()


def test_find_update_target_for_staging_falls_back_to_other_exe(tmp_path):
    base = tmp_path / "app"
    staging = base / ".updates"
    staging.mkdir(parents=True)
    other = base / "renamed-app.exe"
    other.write_bytes(b"app")

    assert find_update_target_for_staging(staging) == other.resolve()


def test_apply_staged_update_retries_transient_lock(tmp_path, monkeypatch):
    import os as _os

    real_replace = _os.replace
    calls = {"count": 0}

    def flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] <= 2:
            raise PermissionError(13, "access denied")
        return real_replace(src, dst)

    monkeypatch.setattr(_os, "replace", flaky_replace)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    target = tmp_path / "app.exe"
    target.write_bytes(b"old")
    staged = tmp_path / "update.exe"
    staged.write_bytes(b"new")
    backup = tmp_path / "app.exe.v1.0.0.bak"

    apply_staged_update(
        target=target,
        staged=staged,
        backup=backup,
        smoke_runner=lambda _p: True,
    )

    assert target.read_bytes() == b"new"
    assert backup.read_bytes() == b"old"
    assert calls["count"] == 3


def test_apply_rollback_retries_transient_lock(tmp_path, monkeypatch):
    import os as _os

    real_replace = _os.replace
    calls = {"count": 0}

    def flaky_replace(src, dst):
        calls["count"] += 1
        # 1st: staged -> target (ok), 2nd: rollback attempt (locked once)
        if calls["count"] == 2:
            raise PermissionError(13, "access denied")
        return real_replace(src, dst)

    monkeypatch.setattr(_os, "replace", flaky_replace)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    target = tmp_path / "app.exe"
    target.write_bytes(b"good version 1.0.0")
    staged = tmp_path / "update.exe"
    staged.write_bytes(b"corrupted version 1.1.0")
    backup = tmp_path / "app.exe.v1.0.0.bak"

    with pytest.raises(UpdateApplyError, match="rolled back"):
        apply_staged_update(
            target=target,
            staged=staged,
            backup=backup,
            smoke_runner=lambda _p: False,
        )

    assert target.read_bytes() == b"good version 1.0.0"
    assert calls["count"] == 3
