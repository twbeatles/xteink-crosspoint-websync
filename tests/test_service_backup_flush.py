from unittest.mock import MagicMock

from websync.pipeline.service import SyncService


def test_sync_service_flush_backup_push(tmp_path):
    mock_config_manager = MagicMock()
    mock_config_manager.load_config.return_value = {
        "output_dir": str(tmp_path),
        "portable_data": {"enabled": True, "folder": str(tmp_path / "backup")},
    }
    mock_config_manager.get_resolved_output_dir.return_value = str(tmp_path)

    service = SyncService(mock_config_manager)
    service.maybe_backup_push = MagicMock()

    # schedule_backup_push 호출 (10초 디바운스 설정)
    service.schedule_backup_push(delay=10.0)

    assert service._backup_push_timer is not None

    # flush_backup_push 호출 시 타이머가 캔슬되고 maybe_backup_push가 동기 즉시 실행되어야 함
    service.flush_backup_push()

    assert service._backup_push_timer is None
    service.maybe_backup_push.assert_called_once_with(force=True)
