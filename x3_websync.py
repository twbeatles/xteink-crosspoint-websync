import sys
import os
import argparse
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
from websync import __version__
from websync.core.instance_lock import (
    acquire_instance_lock,
    release_instance_lock,
    _lock_path,
    _is_process_running,
    _read_lock_pid,
    _remove_stale_lock,
    _acquire_windows_mutex,
    _release_windows_mutex,
)
from websync.core.smoke import SMOKE_MODULES, run_smoke_check
from websync.cli.update_apply import handle_apply_update as _handle_apply_update


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
