"""GUI 단일 인스턴스 락 (파이프라인 ProcessFileLock 과 별개)."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime

lock_file = None
_win_mutex = None
LOCK_FILENAME = "x3_websync_instance.lock"
WIN_MUTEX_NAME = "Local\\XteinkX3WebSync_GUI_SingleInstance"


def _lock_path() -> str:
    return os.path.join(tempfile.gettempdir(), LOCK_FILENAME)


def _is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_lock_pid(lock_path: str) -> int | None:
    try:
        with open(lock_path, "r", encoding="utf-8") as f:
            line = f.read().strip()
        if not line:
            return None
        return int(line.split(",")[0])
    except (OSError, ValueError):
        return None


def _remove_stale_lock(lock_path: str) -> bool:
    """락 파일이 남았지만 프로세스가 없으면 제거합니다."""
    if not os.path.exists(lock_path):
        return False
    pid = _read_lock_pid(lock_path)
    if pid is None or not _is_process_running(pid):
        try:
            os.remove(lock_path)
            return True
        except OSError:
            pass
    return False


def _acquire_windows_mutex() -> bool:
    """Windows named mutex로 GUI 단일 인스턴스를 보장합니다."""
    global _win_mutex
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.GetLastError.restype = wintypes.DWORD

    handle = kernel32.CreateMutexW(None, False, WIN_MUTEX_NAME)
    if not handle:
        return False
    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _win_mutex = handle
    return True


def _release_windows_mutex():
    global _win_mutex
    if _win_mutex is None:
        return
    try:
        import ctypes
        ctypes.windll.kernel32.ReleaseMutex(_win_mutex)
        ctypes.windll.kernel32.CloseHandle(_win_mutex)
    except Exception:
        pass
    _win_mutex = None


def acquire_instance_lock() -> bool:
    """단일 인스턴스 기동 검사 (stale 락 파일 복구 포함, Windows는 named mutex 병행)"""
    global lock_file

    if sys.platform == "win32":
        if not _acquire_windows_mutex():
            return False

    lock_path = _lock_path()
    _remove_stale_lock(lock_path)
    payload = f"{os.getpid()},{datetime.now().isoformat()}"

    try:
        if sys.platform == "win32":
            lock_file = os.open(lock_path, os.O_CREAT | os.O_WRONLY | os.O_EXCL)
            os.write(lock_file, payload.encode("utf-8"))
        else:
            lock_file = open(lock_path, "x", encoding="utf-8")
            lock_file.write(payload)
            lock_file.flush()
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (OSError, FileExistsError):
        if _remove_stale_lock(lock_path):
            # mutex는 이미 잡힌 상태이므로 파일만 재시도
            try:
                if sys.platform == "win32":
                    lock_file = os.open(lock_path, os.O_CREAT | os.O_WRONLY | os.O_EXCL)
                    os.write(lock_file, payload.encode("utf-8"))
                else:
                    lock_file = open(lock_path, "x", encoding="utf-8")
                    lock_file.write(payload)
                    lock_file.flush()
                    import fcntl
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except (OSError, FileExistsError):
                pass
        if sys.platform == "win32":
            _release_windows_mutex()
        return False


def release_instance_lock():
    """인스턴스 락 해제"""
    global lock_file
    lock_path = _lock_path()
    if lock_file is not None:
        try:
            if sys.platform == "win32":
                os.close(lock_file)
            else:
                lock_file.close()
        except Exception:
            pass
        lock_file = None
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except Exception:
        pass
    if sys.platform == "win32":
        _release_windows_mutex()
