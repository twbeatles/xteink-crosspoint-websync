"""앱 UI 언어 (한국어 / English)."""
from __future__ import annotations

import threading
from typing import Any

from websync.i18n.catalog import load_catalog
from websync.i18n.detect import SUPPORTED, detect_system_language

__all__ = [
    "SUPPORTED",
    "detect_system_language",
    "get_language",
    "init_from_config",
    "init_i18n",
    "t",
]

_lock = threading.Lock()
_language = "ko"
_primary: dict[str, str] = {}
_fallback: dict[str, str] = {}
_initialized = False


class _SafeMap(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def init_i18n(lang: str | None) -> str:
    """카탈로그를 로드하고 현재 언어를 설정합니다. 반환: 실제 적용 언어."""
    global _language, _primary, _fallback, _initialized
    chosen = (lang or "").strip().lower()
    if chosen not in SUPPORTED:
        chosen = "en"
    ko = load_catalog("ko")
    if chosen == "ko":
        primary, fallback = ko, {}
    else:
        primary, fallback = load_catalog(chosen), ko
    with _lock:
        _language = chosen
        _primary = primary
        _fallback = fallback
        _initialized = True
    return chosen


def init_from_config(cfg: dict | None) -> str:
    """config.ui_language (auto|ko|en) 를 해석해 init_i18n 합니다."""
    raw = ""
    if isinstance(cfg, dict):
        raw = str(cfg.get("ui_language") or "").strip().lower()
    if raw in ("", "auto"):
        return init_i18n(detect_system_language())
    if raw in SUPPORTED:
        return init_i18n(raw)
    return init_i18n("en")


def get_language() -> str:
    _ensure_init()
    with _lock:
        return _language


def t(key: str, /, **kwargs: Any) -> str:
    """dotted key 번역. 없으면 한국어 폴백, 그것도 없으면 키 자체.

    첫 인자는 위치 전용이라 카탈로그 `{key}` 플레이스홀더와 충돌하지 않는다.
    """
    _ensure_init()
    with _lock:
        text = _primary.get(key) or _fallback.get(key) or key
    if kwargs:
        try:
            return text.format_map(_SafeMap(kwargs))
        except Exception:
            return text
    return text


def _ensure_init() -> None:
    global _initialized
    if _initialized:
        return
    with _lock:
        if _initialized:
            return
    init_i18n(detect_system_language())
