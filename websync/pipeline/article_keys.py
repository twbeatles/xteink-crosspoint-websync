"""기사 동기화 키(URL) 유틸."""

from __future__ import annotations

from websync.core.article import ensure_article_url


def article_sync_key(article: dict, site_name: str, base_url: str) -> str:
    """기사 dict에서 중복 판별용 URL 키를 생성."""
    _ = site_name  # 시그니처 호환(호출부 유지)
    return ensure_article_url(
        article.get("url", ""),
        base_url,
        article.get("title", ""),
    )
