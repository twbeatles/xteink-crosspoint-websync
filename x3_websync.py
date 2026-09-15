import sys
import os
import argparse
import tempfile
from datetime import datetime

# 윈도우 pythonw.exe 구동 시 sys.stdout / sys.stderr 가 None 이 되는 현상 대처
class NullWriter:
    def write(self, s):
        pass
    def flush(self):
        pass

if sys.stdout is None:
    sys.stdout = NullWriter()
if sys.stderr is None:
    sys.stderr = NullWriter()

# 윈도우 콘솔 UnicodeEncodeError 방지를 위한 UTF-8 설정
if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from websync.config.manager import ConfigManager
from websync.pipeline.service import SyncService
from websync.gui.app import SyncAppGui
from websync.core.logger import get_logger


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


from websync import __version__

# --smoke 가 실제로 로드해야 하는 핵심 모듈 (GUI 제외 — 헤드리스 헬퍼 안전)
SMOKE_MODULES: tuple[str, ...] = (
    "websync.config.manager",
    "websync.pipeline.service",
    "websync.scrapers.factory",
    "websync.epub.builder",
    "websync.db.history",
    "websync.upload.uploader",
    "websync.i18n",
)


def run_smoke_check() -> int:
    """핵심 모듈 import 무결성. 성공 0, 실패 1."""
    import importlib

    failed: list[str] = []
    for name in SMOKE_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:
            failed.append(f"{name}: {exc}")
    try:
        from websync.i18n import init_i18n, t

        init_i18n("ko")
        sample = t("gui.tabs.sync")
        if not sample or sample == "gui.tabs.sync":
            failed.append("websync.i18n: catalog missing gui.tabs.sync")
    except Exception as exc:
        failed.append(f"websync.i18n catalog: {exc}")

    if failed:
        print("Xteink X3 WebSync smoke check FAILED")
        for item in failed:
            print(f"  - {item}")
        return 1
    print(f"Xteink X3 WebSync v{__version__} smoke check OK")
    return 0


def _handle_apply_update(args) -> int:
    import time
    import subprocess
    from websync.core.update_installer import apply_staged_update, write_update_result

    target = args.update_target
    staged = args.update_staged
    backup = args.update_backup
    parent_pid = args.update_parent_pid
    expected_sha256 = args.update_expected_sha256
    expected_size = args.update_expected_size
    result_file = args.update_result_file

    # 부모 프로세스 종료 대기 (최대 15초)
    if parent_pid and parent_pid > 0:
        for _ in range(150):
            if not _is_process_running(parent_pid):
                break
            time.sleep(0.1)
        if _is_process_running(parent_pid):
            err_msg = f"부모 프로세스(PID: {parent_pid}) 종료 대기 시간(15초) 초과"
            if result_file:
                write_update_result(result_file, {"status": "failed", "error": err_msg})
            return 1

    try:
        apply_staged_update(
            target=target,
            staged=staged,
            backup=backup,
            expected_sha256=expected_sha256,
            expected_size=expected_size,
        )
        if result_file:
            write_update_result(result_file, {"status": "applied", "target": target})
        # 타겟 프로세스 재기동
        if os.path.exists(target):
            subprocess.Popen([target], close_fds=True)
        return 0
    except Exception as exc:
        if result_file:
            write_update_result(result_file, {"status": "failed", "error": str(exc)})
        return 1


def main():
    from websync.i18n import detect_system_language, init_from_config, init_i18n, t

    init_i18n(detect_system_language())
    parser = argparse.ArgumentParser(description=t("cli.description"))
    parser.add_argument(
        "--sync",
        action="store_true",
        help=t("cli.help.sync"),
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help=t("cli.help.smoke"),
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"Xteink X3 WebSync v{__version__}",
    )
    parser.add_argument(
        "--check-update",
        action="store_true",
        help=t("cli.help.check_update"),
    )
    # 업데이터 헬퍼 전용 인자
    parser.add_argument("--apply-update", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--update-target", help=argparse.SUPPRESS)
    parser.add_argument("--update-staged", help=argparse.SUPPRESS)
    parser.add_argument("--update-backup", help=argparse.SUPPRESS)
    parser.add_argument("--update-parent-pid", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--update-expected-sha256", help=argparse.SUPPRESS)
    parser.add_argument("--update-expected-size", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--update-result-file", help=argparse.SUPPRESS)

    args = parser.parse_args()

    # 1. 스모크 체크
    if args.smoke:
        sys.exit(run_smoke_check())

    # 2. 업데이터 헬퍼 실행
    if args.apply_update:
        sys.exit(_handle_apply_update(args))

    # 3. 업데이트 확인 CLI
    if args.check_update:
        from websync.core.update_service import UpdateService
        service = UpdateService()
        try:
            manifest = service.check_for_update()
            if manifest:
                print(t("cli.update_available", version=manifest.version, current=__version__))
                print(t("cli.update_url", url=manifest.artifact_url))
                sys.exit(0)
            else:
                print(t("cli.up_to_date", version=__version__))
                sys.exit(0)
        except Exception as exc:
            print(t("cli.update_check_failed", error=exc))
            sys.exit(1)

    # GUI만 단일 인스턴스 락 — --sync는 프로세스 파일 락(SyncService)으로 직렬화
    gui_lock_acquired = False
    if not args.sync:
        if not acquire_instance_lock():
            print(t("cli.gui_already_running", now=datetime.now()))
            sys.exit(1)
        gui_lock_acquired = True

    try:
        logger = get_logger()
        logger.info("=" * 60)
        logger.info(f"X3 WebSync 시작 (PID: {os.getpid()}, mode={'sync' if args.sync else 'gui'})")

        try:
            config_manager = ConfigManager()
            init_from_config(config_manager.load_config())
            service = SyncService(config_manager)
        except Exception as e:
            print(t("cli.config_load_failed", now=datetime.now(), error=e))
            sys.exit(1)

        if args.sync:
            print(t("cli.sync_start", now=datetime.now()))
            success = service.run_sync_pipeline()
            print(t("cli.sync_end", now=datetime.now(), result=success))
            sys.exit(0 if success else 1)
        else:
            app = SyncAppGui(service)
            app.run()
    finally:
        if gui_lock_acquired:
            release_instance_lock()


if __name__ == "__main__":
    main()
