"""웹 대시보드 세션·토큰 인증 유틸."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

SESSION_COOKIE_NAME = "x3sync_session"
SESSION_MAX_AGE_SEC = 7 * 24 * 3600  # 7일


def session_value(api_token: str, issued_at: int | None = None) -> str:
    """만료 가능한 세션 쿠키 값: {unix_ts}.{hmac}"""
    ts = int(issued_at if issued_at is not None else time.time())
    msg = f"x3websync-session-v2|{ts}".encode("utf-8")
    sig = hmac.new(api_token.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"{ts}.{sig}"


def session_valid(api_token: str, cookie_val: str | None) -> bool:
    if not api_token or not cookie_val or "." not in cookie_val:
        return False
    try:
        ts_s, sig = cookie_val.split(".", 1)
        ts = int(ts_s)
        if time.time() - ts > SESSION_MAX_AGE_SEC or ts > time.time() + 300:
            return False
        expected = session_value(api_token, issued_at=ts)
        return secrets.compare_digest(cookie_val, expected)
    except (ValueError, TypeError):
        return False


def token_matches(provided: str | None, expected: str) -> bool:
    if not provided or not expected:
        return False
    return secrets.compare_digest(provided, expected)
