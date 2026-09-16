"""사설·로컬 URL 판별."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

def is_private_or_local_url(url: str) -> bool:
    """로컬호스트·사설 IP·링크 로컬 등 내부망으로 보이면 True.

    DNS 해석 실패 시 hostname 휴리스틱만 사용 (차단하지 않음).
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    if host in ("localhost", "localhost.localdomain") or host.endswith(".local"):
        return True
    # 리터럴 IP
    try:
        ip = ipaddress.ip_address(host)
        return bool(
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        )
    except ValueError:
        pass
    # 선택적 DNS (짧게) — 실패하면 외부로 간주
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        for info in infos:
            addr = info[4][0]
            try:
                ip = ipaddress.ip_address(addr)
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_reserved
                ):
                    return True
            except ValueError:
                continue
    except Exception:
        pass
    return False
