"""Xteink X3 WebSync 고수준 업데이트 서비스."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

from websync import __version__
from websync.core.logger import get_logger
from websync.core.paths import PROJECT_ROOT
from websync.core.update_constants import (
    UPDATE_MANIFEST_URL,
    UPDATE_PUBLIC_KEY_B64,
)
from websync.core.update_installer import (
    apply_staged_update,
    cleanup_update_backups,
    consume_update_result,
    launch_update_helper,
    prepare_staged_update,
    resolve_update_staging_root,
    stream_update_artifact,
    update_result_path,
    write_update_result,
)
from websync.core.update_manifest import (
    NoUpdateAvailableError,
    ReleaseManifest,
    download_release_manifest,
    verify_release_manifest,
)


class UpdateService:
    """앱 업데이트 확인, 다운로드, 검증 및 설치 조율 서비스."""

    def __init__(
        self,
        current_version: str = __version__,
        manifest_url: str = UPDATE_MANIFEST_URL,
        public_key: str = UPDATE_PUBLIC_KEY_B64,
        storage_root: str | Path = PROJECT_ROOT,
    ):
        self.current_version = current_version
        self.manifest_url = manifest_url
        self.public_key = public_key
        self.storage_root = Path(storage_root).resolve()
        self.staging_root = resolve_update_staging_root(storage_root=self.storage_root)
        self.logger = get_logger()

    def check_for_update(self) -> ReleaseManifest | None:
        """
        원격 매니페스트를 확인하고 최신 버전이 있으면 ReleaseManifest를 반환합니다.
        새 버전이 없거나 확인 중 오류 발생 시 None을 반환하거나 예외를 발생시킵니다.
        """
        try:
            self.logger.info(f"업데이트 확인 요청: {self.manifest_url}")
            manifest_bytes = download_release_manifest(self.manifest_url)
            manifest = verify_release_manifest(
                manifest_bytes,
                public_key=self.public_key,
                current_version=self.current_version,
            )
            self.logger.info(f"새 업데이트 발견: v{manifest.version}")
            return manifest
        except NoUpdateAvailableError:
            self.logger.info(f"현재 버전(v{self.current_version})이 최신 버전입니다.")
            return None
        except Exception as exc:
            self.logger.warning(f"업데이트 확인 실패: {exc}")
            raise

    def check_last_result(self) -> dict[str, object] | None:
        """이전 업데이트 작업 결과를 확인합니다."""
        result_file = update_result_path(self.staging_root)
        return consume_update_result(result_file)

    def download_and_stage(
        self,
        manifest: ReleaseManifest,
        progress_callback: Callable[[int, int], None] | None = None,
        cancel_event: Any = None,
    ) -> Path:
        """새 릴리즈 바이너리를 다운로드하여 스테이징 영역에 안전하게 저장합니다."""
        self.staging_root.mkdir(parents=True, exist_ok=True)

        def progress_chunks():
            total_downloaded = 0
            for chunk in stream_update_artifact(manifest, cancel_event=cancel_event):
                total_downloaded += len(chunk)
                if progress_callback:
                    progress_callback(total_downloaded, manifest.artifact_size)
                yield chunk

        staged_path = prepare_staged_update(
            manifest,
            chunks=progress_chunks(),
            staging_root=self.staging_root,
            cancel_event=cancel_event,
        )
        if staged_path is None or not staged_path.is_file():
            raise RuntimeError("스테이징 파일 준비 실패")

        return staged_path

    def launch_update_and_exit(
        self,
        staged_path: Path,
        manifest: ReleaseManifest,
    ) -> None:
        """헬퍼 프로세스를 구동하고 현재 프로세스를 종료하여 안전한 교체를 진행합니다."""
        target = Path(sys.executable).resolve()
        backup = target.parent / f"{target.name}.v{self.current_version}.bak"
        result_file = update_result_path(self.staging_root)

        if getattr(sys, "frozen", False):
            launch_update_helper(
                target=target,
                staged=staged_path,
                backup=backup,
                parent_pid=os.getpid(),
                expected_sha256=manifest.artifact_sha256,
                expected_size=manifest.artifact_size,
                result_file=result_file,
            )
            self.logger.info("업데이터 헬퍼 기동 완료. 본 프로세스를 종료합니다.")
            sys.exit(0)
        else:
            # 개발 환경에서는 직접 교체 대신 에러를 발생시켜 GUI/호출자가 처리하도록 함
            self.logger.info(f"개발 환경(non-frozen)에서는 바이너리 교체를 생략합니다: {staged_path}")
            raise RuntimeError(
                f"개발 모드(소스 코드 실행)에서는 바이너리 자동 교체가 지원되지 않습니다.\n"
                f"다운로드된 파일: {staged_path}"
            )
