"""VelogScraper — 한국 개발자 블로그 플랫폼 Velog.

작가 프로필 URL 또는 RSS URL을 받아 내부적으로 RssScraper를 사용합니다.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

from websync.core.logger import get_logger
from websync.scrapers.base import BaseScraper
from websync.scrapers.rss import RssScraper
from websync.i18n import t


class VelogScraper(BaseScraper):
    """Velog 작가 글 수집 (RSS 래퍼).

    URL 예:
      - https://velog.io/@velopert
      - https://velog.io/@velopert/series/...
      - https://v2.velog.io/rss/@velopert
    """

    _USERNAME_RE = re.compile(r"(?:velog\.io|v2\.velog\.io)/@([^/?#\s]+)", re.I)
    _RSS_TMPL = "https://v2.velog.io/rss/@{username}"

    def __init__(self):
        self.logger = get_logger()
        self.last_fetch_stats: dict = {}
        self._rss = RssScraper()

    def fetch_articles(self, site_config: dict) -> list:
        self.last_fetch_stats = {"skipped": 0}
        url = (site_config.get("url") or "").strip()
        rss_url = self.resolve_rss_url(url)
        if not rss_url:
            raise Exception(t("velog.no_username"))
        cfg = dict(site_config)
        cfg["url"] = rss_url
        cfg["type"] = "rss"
        articles = self._rss.fetch_articles(cfg)
        self.last_fetch_stats = getattr(self._rss, "last_fetch_stats", {}) or {"skipped": 0}
        return articles

    @classmethod
    def resolve_rss_url(cls, url: str) -> str | None:
        if not url:
            return None
        # 이미 RSS 피드
        if "v2.velog.io/rss/" in url or url.rstrip("/").endswith(".xml"):
            return url
        m = cls._USERNAME_RE.search(url)
        if m:
            username = unquote(m.group(1)).strip()
            if username:
                return cls._RSS_TMPL.format(username=username)
        # path only /@user
        path = urlparse(url).path or ""
        m2 = re.search(r"/@([^/?#]+)", path)
        if m2:
            return cls._RSS_TMPL.format(username=unquote(m2.group(1)))
        return None
