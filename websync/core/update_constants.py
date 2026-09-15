"""Xteink X3 WebSync 자동 업데이트 관련 상수 정의."""
from __future__ import annotations

import os

# GitHub 원격 매니페스트 URL
UPDATE_MANIFEST_URL: str = os.environ.get(
    "X3_UPDATE_MANIFEST_URL",
    "https://raw.githubusercontent.com/twbeatles/xteink-crosspoint-websync/main/updates/latest.json",
)

# Ed25519 공개키 기본값 (Base64)
# 개인키는 절대 소스코드나 바이너리에 포함되지 않으며, GitHub Actions Secret에만 보관됩니다.
UPDATE_PUBLIC_KEY_B64_DEFAULT: str = "7SJtaXOPi+sRE6Ci7voP4/vdDbfzZXLV7mguS9GxbxU="

UPDATE_PUBLIC_KEY_B64: str = os.environ.get(
    "X3_UPDATE_PUBLIC_KEY_B64",
    UPDATE_PUBLIC_KEY_B64_DEFAULT,
)

# GitHub 릴리즈 페이지 URL
UPDATE_RELEASES_URL: str = "https://github.com/twbeatles/xteink-crosspoint-websync/releases/latest"

# 안전 제한 상수
UPDATE_MANIFEST_MAX_BYTES: int = 256 * 1024          # 256 KB
UPDATE_ARTIFACT_MAX_BYTES: int = 500 * 1024 * 1024  # 500 MB
UPDATE_REQUEST_TIMEOUT_SECONDS: float = 20.0
UPDATE_BACKUP_KEEP_COUNT: int = 2
