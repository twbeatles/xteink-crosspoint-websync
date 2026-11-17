"""민감 설정 필드 처리 유틸 (마스킹·로그 안전 출력)."""

from __future__ import annotations

from typing import Any

# config.json 내 시크릿으로 취급할 키 경로 (dot 표기)
SECRET_FIELD_PATHS = (
    "ai_summary.api_key",
    "web_dashboard.api_token",
    "opds_server.api_key",
    "translation.libretranslate_api_key",
)


def mask_secret(value: str | None, *, visible_tail: int = 4) -> str:
    """표시용 마스킹. 빈 값은 그대로, 짧으면 전부 *."""
    if not value:
        return ""
    text = str(value)
    if len(text) <= visible_tail:
        return "*" * len(text)
    return "*" * (len(text) - visible_tail) + text[-visible_tail:]


def redact_config_for_log(config: dict[str, Any]) -> dict[str, Any]:
    """로그·디버그용 복사본 — 시크릿 필드를 마스킹한다."""
    import copy

    out = copy.deepcopy(config)
    for path in SECRET_FIELD_PATHS:
        parts = path.split(".")
        cur: Any = out
        for p in parts[:-1]:
            if not isinstance(cur, dict) or p not in cur:
                cur = None
                break
            cur = cur[p]
        if isinstance(cur, dict) and parts[-1] in cur and cur[parts[-1]]:
            cur[parts[-1]] = mask_secret(str(cur[parts[-1]]))
    return out
