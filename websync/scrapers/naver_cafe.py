"""네이버 카페 전용 스크래퍼

공개 카페의 최신글을 수집합니다.
URL 형식: https://cafe.naver.com/{cafe_id}

목록: cafe-web ArticleListV2.json (clubid 필요)
본문: cafe-articleapi v2.1 contentHtml
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from websync.core.logger import get_logger
from websync.scrapers.base import BaseScraper, fetch_url, normalize_limit, maybe_strip_images
from websync.scrapers.naver_common import clean_naver_content
from websync.i18n import t


class NaverCafeScraper(BaseScraper):
    """네이버 카페 공개 게시판 스크래퍼"""

    _LIST_API = (
        "https://apis.naver.com/cafe-web/cafe2/ArticleListV2.json"
        "?search.clubid={club_id}&search.page=1&search.perPage={limit}"
    )
    _ARTICLE_API = (
        "https://apis.naver.com/cafe-web/cafe-articleapi/v2.1"
        "/cafes/{club_id}/articles/{article_id}"
    )

    def __init__(self):
        self.logger = get_logger()
        self.last_fetch_stats: dict = {}

    def fetch_articles(self, site_config: dict) -> list:
        url = (site_config.get("url") or "").strip()
        limit = normalize_limit(site_config.get("limit", 5))
        self.last_fetch_stats = {"skipped": 0}

        match = re.search(r"cafe\.naver\.com/([^/?#]+)", url)
        if not match:
            self.logger.error(t("naver_cafe.no_cafe_id", url=url))
            return []
        cafe_id = match.group(1)
        # 숫자 경로(게시글) 제외
        if cafe_id.isdigit():
            self.logger.error(t("naver_cafe.need_home", url=url))
            return []

        articles: list[dict] = []
        try:
            club_id = self._resolve_club_id(cafe_id, url)
            if not club_id:
                self.logger.error(t("naver_cafe.no_clubid", cafe_id=cafe_id))
                return []

            # 이미지 전용 글 등을 건너뛸 수 있어 목록은 limit 배수로 요청
            fetch_n = max(limit * 3, limit + 5)
            article_list = self._fetch_article_list(club_id, cafe_id, fetch_n)
            for item in article_list:
                if len(articles) >= limit:
                    break
                article_id = item.get("articleId")
                if article_id is None:
                    continue
                title = (item.get("subject") or t("naver_cafe.untitled")).strip()
                article_url = f"https://cafe.naver.com/{cafe_id}/{article_id}"
                content = self._fetch_article_content(
                    club_id, cafe_id, article_id, site_config, title=title
                )
                if content:
                    articles.append({"title": title, "content": content, "url": article_url})
                else:
                    self.last_fetch_stats["skipped"] = self.last_fetch_stats.get("skipped", 0) + 1

        except Exception as e:
            self.logger.error(t("naver_cafe.list_failed", error=e))

        return articles

    def _resolve_club_id(self, cafe_id: str, page_url: str) -> str | None:
        """슬러그 cafe_id → 숫자 clubid."""
        if cafe_id.isdigit():
            return cafe_id

        candidates = [
            f"https://cafe.naver.com/{cafe_id}",
            page_url if page_url else "",
        ]
        patterns = [
            r"g_sClubId\s*=\s*['\"]?(\d+)",
            r"clubid[=:](\d+)",
            r'"cafeId"\s*:\s*(\d+)',
            r"cafeId=(\d+)",
            r"/cafes/(\d+)",
        ]
        for u in candidates:
            if not u:
                continue
            try:
                resp = fetch_url(u, timeout=15)
                resp.raise_for_status()
                text = resp.text
            except Exception as e:
                self.logger.warning(t("naver_cafe.home_failed", url=u, error=e))
                continue
            for pat in patterns:
                m = re.search(pat, text, re.I)
                if m:
                    return m.group(1)
        return None

    def _fetch_article_list(self, club_id: str, cafe_id: str, limit: int) -> list[dict]:
        api = self._LIST_API.format(club_id=club_id, limit=max(limit, 1))
        resp = fetch_url(
            api,
            headers={"Referer": f"https://cafe.naver.com/{cafe_id}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        result = (data.get("message") or {}).get("result") or {}
        return list(result.get("articleList") or [])

    def _fetch_article_content(
        self,
        club_id: str,
        cafe_id: str,
        article_id,
        site_config: dict,
        title: str = "",
    ) -> str | None:
        """개별 카페 게시글 본문 수집 (API 우선, HTML 폴백)."""
        # 1) 공식 article API
        try:
            api = self._ARTICLE_API.format(club_id=club_id, article_id=article_id)
            resp = fetch_url(
                api,
                headers={"Referer": f"https://m.cafe.naver.com/{cafe_id}"},
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
            article = (payload.get("result") or {}).get("article") or {}
            html = article.get("contentHtml") or ""
            if html:
                soup = BeautifulSoup(html, "lxml")
                container = soup.body or soup
                maybe_strip_images(container, site_config)
                clean_naver_content(container)
                text = container.get_text(" ", strip=True)
                # 이미지 제거 후 본문이 거의 없으면 스킵 (e-ink에 쓸 텍스트 없음)
                if len(text) < 15:
                    self.logger.warning(t("naver_cafe.too_short", article_id=article_id))
                    return None
                # 제목을 앞에 두면 짧은 글도 가독성 향상
                if title and title not in text[: len(title) + 5]:
                    return f"<h1>{title}</h1>{container}"
                return str(container)
        except Exception as e:
            self.logger.warning(t("naver_cafe.api_failed", article_id=article_id, error=e))

        # 2) 모바일 HTML 폴백
        try:
            content_url = (
                f"https://m.cafe.naver.com/ca-fe/web/cafes/{club_id}/articles/{article_id}"
            )
            resp = fetch_url(content_url, timeout=15)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or resp.encoding
            soup = BeautifulSoup(resp.text, "html.parser")

            container = (
                soup.select_one("div.se-main-container")
                or soup.select_one("div.article_viewer")
                or soup.select_one("div#postContent")
                or soup.select_one("div.ContentRenderer")
                or soup.select_one("article")
            )
            if not container:
                self.logger.warning(t("naver_cafe.no_container", article_id=article_id))
                return None

            maybe_strip_images(container, site_config)
            clean_naver_content(container)
            return str(container)

        except Exception as e:
            self.logger.warning(t("naver_cafe.body_failed", article_id=article_id, error=e))
            return None
