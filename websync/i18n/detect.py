"""OS UI 언어 감지 (ko / en)."""
from __future__ import annotations

import locale
import os
import sys

SUPPORTED = ("ko", "en")
ENV_LANG = "X3_WEBSYNC_LANG"


def detect_system_language() -> str:
    """사용자 OS UI 언어를 ko 또는 en 으로 반환합니다.

    우선순위: X3_WEBSYNC_LANG → Windows UI language → locale/LANG → en
    """
    env = (os.environ.get(ENV_LANG) or "").strip().lower()
    if env in SUPPORTED:
        return env

    if sys.platform == "win32":
        try:
            import ctypes

            lang_id = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
            if (lang_id & 0xFF) == 0x12:  # LANG_KOREAN
                return "ko"
        except Exception:
            pass

    parts: list[str] = []
    try:
        loc = locale.getlocale()[0]
        if loc:
            parts.append(loc)
    except Exception:
        pass
    for var in ("LANG", "LC_ALL", "LC_MESSAGES"):
        val = os.environ.get(var) or ""
        if val:
            parts.append(val)

    blob = " ".join(parts).lower().replace("-", "_")
    if blob.startswith("ko") or " ko" in blob or blob.startswith("korean"):
        return "ko"
    for token in blob.replace(".", " ").replace(";", " ").split():
        if token.startswith("ko"):
            return "ko"
    return "en"
