"""기기 호스트 주소 정규화."""

from __future__ import annotations

import re


def normalize_device_host(value: str | None) -> str:
    """기기 주소 정규화: 스킴·경로·끝 슬래시 제거.

    예: 'http://192.168.31.54/' → '192.168.31.54'
    끝 슬래시가 남으면 업로드 URL이 http://IP//upload 가 되어 CrossPoint가 404를 반환한다.
    """
    if value is None:
        return ""
    host = str(value).strip()
    if not host:
        return ""
    # http(s):// 접두 제거
    host = re.sub(r"^https?://", "", host, flags=re.IGNORECASE)
    # 경로/쿼리/프래그먼트 제거 (호스트:포트만 유지)
    host = host.split("/", 1)[0]
    host = host.split("?", 1)[0]
    host = host.split("#", 1)[0]
    return host.strip().rstrip(".")
