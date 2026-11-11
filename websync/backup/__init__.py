from websync.backup.service import BackupSyncError, BackupSyncService

# 공식 명칭 alias (공유 데이터 폴더 = 사이트·이력 정본)
PortableDataService = BackupSyncService
PortableDataError = BackupSyncError

__all__ = [
    "BackupSyncService",
    "BackupSyncError",
    "PortableDataService",
    "PortableDataError",
]
