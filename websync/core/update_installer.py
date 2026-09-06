"""Xteink X3 WebSync 업데이트 파일 다운로드, 교체, 검증, 롤백 및 헬퍼 프로세스 런처."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from uuid import uuid4

from websync.backup.atomic_io import write_json_atomic
from websync.core.update_constants import (
    UPDATE_ARTIFACT_MAX_BYTES,
    UPDATE_BACKUP_KEEP_COUNT,
    UPDATE_REQUEST_TIMEOUT_SECONDS,
)
from websync.core.update_manifest import ReleaseManifest


class UpdateApplyError(RuntimeError):
    """업데이트 적용 또는 롤백 실패 시 발생하는 예외."""


class UpdateCancelledError(Exception):
    """사용자 또는 시스템에 의해 업데이트 다운로드가 취소됨."""


def update_result_path(staging_root: str | Path) -> Path:
    """최종 업데이트 결과 기록 파일 경로를 반환합니다."""
    return (Path(staging_root).resolve() / "last-update-result.json").resolve()


def write_update_result(path: str | Path, payload: dict[str, object]) -> None:
    """업데이트 상태 결과를 원자적으로 기록합니다."""
    data = dict(payload)
    data["status"] = str(data.get("status", "failed") or "failed")
    write_json_atomic(str(Path(path).resolve()), data)


def consume_update_result(path: str | Path) -> dict[str, object] | None:
    """업데이트 결과 파일을 읽고 즉시 삭제하여 한 번만 소비하도록 합니다."""
    result_path = Path(path).resolve()
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        try:
            result_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    if not isinstance(data, dict) or str(data.get("status", "")) not in {
        "applied",
        "rolled_back",
        "failed",
    }:
        try:
            result_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    try:
        result_path.unlink(missing_ok=True)
    except OSError:
        pass
    return data


def resolve_update_staging_root(
    *,
    storage_root: str | Path,
) -> Path:
    """임시 업데이트 파일 저장 폴더를 반환합니다."""
    return (Path(storage_root) / ".updates").resolve()


def prepare_staged_update(
    manifest: ReleaseManifest,
    *,
    chunks: Iterable[bytes],
    staging_root: str | Path,
    approve: Callable[[ReleaseManifest, Path], bool] | None = None,
    cancel_event: Any = None,
) -> Path | None:
    """
    다운로드 청크를 스트리밍하면서 실시간으로 파일 크기와 SHA256 해시를 검증합니다.
    취소(cancel_event) 또는 검증 실패 시 임시 파일을 즉시 삭제합니다.
    """
    root = Path(staging_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    staged = root / f"update-{manifest.version}-{uuid4().hex}.exe"
    digest = hashlib.sha256()
    total = 0
    try:
        with open(staged, "xb") as handle:
            for chunk in chunks:
                if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                    raise UpdateCancelledError("업데이트 다운로드가 취소되었습니다.")
                if not isinstance(chunk, bytes):
                    raise TypeError("Update chunk must be bytes")
                total += len(chunk)
                if total > manifest.artifact_size or total > int(
                    UPDATE_ARTIFACT_MAX_BYTES
                ):
                    raise ValueError("Update artifact size mismatch")
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
            raise UpdateCancelledError("업데이트 다운로드가 취소되었습니다.")
        if total != manifest.artifact_size:
            raise ValueError("Update artifact size mismatch")
        if digest.hexdigest().lower() != manifest.artifact_sha256.lower():
            raise ValueError("Update artifact hash mismatch")
        if approve is not None and not approve(manifest, staged):
            staged.unlink(missing_ok=True)
            return None
        return staged
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def stream_update_artifact(
    manifest: ReleaseManifest,
    cancel_event: Any = None,
) -> Iterable[bytes]:
    """HTTPS를 통해 원격 바이너리를 청크 단위로 스트리밍합니다."""
    from urllib.parse import urlsplit
    from urllib.request import Request, urlopen

    request = Request(
        manifest.artifact_url,
        headers={"User-Agent": "XteinkX3WebSync-Updater"},
    )
    with urlopen(
        request,
        timeout=float(UPDATE_REQUEST_TIMEOUT_SECONDS),
    ) as response:
        final_url = urlsplit(response.geturl())
        if final_url.scheme.lower() != "https" or not final_url.hostname:
            raise ValueError("Update artifact redirect must remain HTTPS")
        while True:
            if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                raise UpdateCancelledError("업데이트 다운로드가 취소되었습니다.")
            chunk = response.read(1024 * 1024)
            if not chunk:
                return
            yield chunk


def _validate_apply_paths(target: Path, staged: Path, backup: Path) -> None:
    paths = [target.resolve(), staged.resolve(), backup.resolve()]
    if len(set(paths)) != 3:
        raise ValueError("Update target, staged, and backup paths must be distinct")
    if target.suffix.lower() != ".exe" or staged.suffix.lower() != ".exe":
        raise ValueError("Update target and staged artifact must be .exe files")
    if backup.parent != target.parent:
        raise ValueError("Update backup must stay in the target install directory")
    if not target.is_file() or not staged.is_file():
        raise FileNotFoundError("Update target or staged artifact is missing")
    if backup.exists():
        raise FileExistsError(f"Update backup already exists: {backup}")
    backup.parent.mkdir(parents=True, exist_ok=True)


def cleanup_update_backups(target: str | Path, *, keep_count: int | None = None) -> None:
    """오래된 이전 버전 백업 파일(.bak)을 정리합니다."""
    target_path = Path(target).resolve()
    keep = max(0, int(UPDATE_BACKUP_KEEP_COUNT if keep_count is None else keep_count))
    candidates: list[tuple[float, Path]] = []
    for backup in target_path.parent.glob(f"{target_path.name}.v*.bak"):
        try:
            candidates.append((backup.stat().st_mtime, backup))
        except OSError:
            continue
    backups = [item for _mtime, item in sorted(candidates, reverse=True)]
    for backup in backups[keep:]:
        try:
            backup.unlink()
        except OSError:
            continue


def apply_staged_update(
    *,
    target: str | Path,
    staged: str | Path,
    backup: str | Path,
    expected_sha256: str | None = None,
    expected_size: int | None = None,
    smoke_runner: Callable[[Path], bool] | None = None,
) -> None:
    """
    스테이징된 새 실행 파일로 타겟 실행 파일을 교체합니다.
    - 이전 버전을 backup 경로로 복사
    - os.replace로 원자적 교체
    - 교체된 실행 파일에 대해 --smoke 검증 실행
    - 검증 실패 시 백업으로 즉시 자동 롤백
    """
    target_path = Path(target).resolve()
    staged_path = Path(staged).resolve()
    backup_path = Path(backup).resolve()
    _validate_apply_paths(target_path, staged_path, backup_path)

    if expected_size is not None and staged_path.stat().st_size != int(expected_size):
        raise ValueError("Update artifact size mismatch before replacement")
    if expected_sha256 is not None:
        digest = hashlib.sha256()
        with open(staged_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest().lower() != str(expected_sha256).strip().lower():
            raise ValueError("Update artifact hash mismatch before replacement")

    shutil.copy2(target_path, backup_path)
    try:
        os.replace(staged_path, target_path)
        if smoke_runner is None:
            completed = subprocess.run(
                [str(target_path), "--smoke"],
                timeout=60,
                check=False,
                capture_output=True,
            )
            smoke_ok = completed.returncode == 0
        else:
            smoke_ok = bool(smoke_runner(target_path))
        if not smoke_ok:
            raise RuntimeError("updated executable smoke check failed")
        try:
            cleanup_update_backups(target_path)
        except Exception:
            pass
    except Exception as exc:
        try:
            if backup_path.is_file():
                os.replace(backup_path, target_path)
        except Exception as rollback_exc:
            raise UpdateApplyError(
                f"Update failed and rollback also failed: {rollback_exc}"
            ) from exc
        raise UpdateApplyError("Update failed and was rolled back") from exc


def launch_update_helper(
    *,
    target: str | Path,
    staged: str | Path,
    backup: str | Path,
    parent_pid: int,
    expected_sha256: str,
    expected_size: int,
    result_file: str | Path,
) -> subprocess.Popen[bytes]:
    """
    Windows에서 실행 중인 프로세스의 잠금을 피하기 위해 임시 헬퍼 프로세스를 기동합니다.
    """
    staged_path = Path(staged).resolve()
    helper_path = staged_path.parent / f"update-helper-{uuid4().hex}.exe"
    shutil.copy2(Path(sys.executable).resolve(), helper_path)
    return subprocess.Popen(
        [
            str(helper_path),
            "--apply-update",
            "--update-target",
            str(Path(target).resolve()),
            "--update-staged",
            str(staged_path),
            "--update-backup",
            str(Path(backup).resolve()),
            "--update-parent-pid",
            str(int(parent_pid)),
            "--update-expected-sha256",
            str(expected_sha256),
            "--update-expected-size",
            str(int(expected_size)),
            "--update-result-file",
            str(Path(result_file).resolve()),
        ],
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
