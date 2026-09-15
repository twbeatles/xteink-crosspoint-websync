"""크로스 프로세스 파일 락 (동기화 파이프라인 직렬화용)"""
from __future__ import annotations

import os
import sys
import time
import io
from typing import Optional


from websync.i18n import t

DEFAULT_PIPELINE_LOCK_NAME = "x3_websync_pipeline.lock"


class ProcessFileLock:
    """
    프로세스 간 배타 락.
    - Unix: fcntl.flock
    - Windows: msvcrt.locking
    락을 잡은 동안 파일 핸들을 유지합니다.
    기본 경로는 설치/프로젝트 폴더(PROJECT_ROOT)라서 휴대용 다중 설치가 서로 막히지 않습니다.
    """

    def __init__(self, lock_path: str | None = None):
        if lock_path is None:
            from websync.core.paths import PROJECT_ROOT

            lock_path = os.path.join(PROJECT_ROOT, DEFAULT_PIPELINE_LOCK_NAME)
        self.lock_path = lock_path
        self._fh: Optional[object] = None
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    def acquire(self, blocking: bool = False, timeout: float = 0.0) -> bool:
        """락 획득. 성공 시 True."""
        if self._held:
            return True

        deadline = None if not blocking else (time.monotonic() + max(timeout, 0.0))
        while True:
            if self._try_acquire_once():
                return True
            if not blocking:
                return False
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def _try_acquire_once(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.lock_path) or ".", exist_ok=True)
            # a+ 로 열고 배타 바이트 락
            fh = io.open(self.lock_path, "a+", encoding="utf-8")
            try:
                if sys.platform == "win32":
                    import msvcrt

                    fh.seek(0)
                    if fh.read(1) == "":
                        fh.write("0")
                        fh.flush()
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fh.seek(0)
                fh.truncate()
                fh.write(f"{os.getpid()}\n")
                fh.flush()
            except OSError:
                fh.close()
                return False
            self._fh = fh
            self._held = True
            return True
        except OSError:
            return False

    def release(self) -> None:
        if not self._held or self._fh is None:
            self._held = False
            self._fh = None
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                try:
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None
            self._held = False

    def is_held_by_other(self) -> bool:
        """다른 프로세스가 락을 잡고 있는지 비파괴 검사 (try-lock).

        자체 락 파일 경로로 새 프로브(`ProcessFileLock`)를 만들어
        ``acquire(blocking=False)``를 시도한다.

        - 프로브 획득 성공 → 다른 보유자가 없음 → release 후 ``False`` 반환
        - 프로브 획득 실패 → 다른 프로세스가 보유 중 → ``True`` 반환

        이 프로브는 실제 락을 점유하지 않는다(성공 시 즉시 release).
        따라서 호출 자체가 기존 보유자에게 간섭하지 않으며, 매 요청마다
        파일 시스템 try-lock을 수행하는 ``is_pipeline_running`` 보조 판정으로
        안전하게 쓸 수 있다.
        """
        if self._held:
            return False
        probe = ProcessFileLock(self.lock_path)
        if probe.acquire(blocking=False):
            probe.release()
            return False
        return True

    def __enter__(self):
        if not self.acquire(blocking=True, timeout=30.0):
            raise TimeoutError(t("lock.timeout", path=self.lock_path))
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False
