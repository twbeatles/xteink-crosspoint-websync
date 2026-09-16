"""하위 호환: 설치 API는 websync.core.update.installer 로 이동."""
from websync.core.update.installer import (
    UpdateApplyError,
    UpdateCancelledError,
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

__all__ = [
    "UpdateApplyError",
    "UpdateCancelledError",
    "apply_staged_update",
    "cleanup_update_backups",
    "consume_update_result",
    "launch_update_helper",
    "prepare_staged_update",
    "resolve_update_staging_root",
    "stream_update_artifact",
    "update_result_path",
    "write_update_result",
]
