"""하위 호환: 매니페스트 API는 websync.core.update.manifest 로 이동."""
from websync.core.update.manifest import (
    NoUpdateAvailableError,
    ReleaseManifest,
    canonical_manifest_payload,
    download_release_manifest,
    is_newer_version,
    verify_release_manifest,
)

__all__ = [
    "NoUpdateAvailableError",
    "ReleaseManifest",
    "canonical_manifest_payload",
    "download_release_manifest",
    "is_newer_version",
    "verify_release_manifest",
]
