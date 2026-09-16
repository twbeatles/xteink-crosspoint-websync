"""업데이터 헬퍼 프로세스: 스테이징된 바이너리 교체."""
from __future__ import annotations

import os
import subprocess
import time

from websync.core.instance_lock import _is_process_running
from websync.core.update.installer import apply_staged_update, write_update_result
from websync.i18n import t


def handle_apply_update(args) -> int:
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
            err_msg = t("cli.parent_wait_timeout", pid=parent_pid)
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
