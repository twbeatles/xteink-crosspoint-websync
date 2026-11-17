"""기기 통신 관련 예외."""

from __future__ import annotations


class DeviceClientError(Exception):
    """기기 API 호출 실패 (연결·HTTP·파싱 등)."""

    def __init__(self, message: str, *, host: str = "", status_code: int | None = None):
        super().__init__(message)
        self.host = host
        self.status_code = status_code
