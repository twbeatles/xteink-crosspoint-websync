"""네이버 포스트(post.naver.com) 전용 스크래퍼

⚠️ 네이버 포스트 서비스는 2025-04-30에 종료되었습니다.
   신규 수집은 불가하며, 호출 시 명확한 예외를 발생시킵니다.
   타입은 하위 호환(설정 파일)을 위해 유지합니다.

과거 URL 형식: https://post.naver.com/my.naver?memberNo={id}
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from websync.core.logger import get_logger
from websync.scrapers.base import BaseScraper, fetch_url, normalize_limit, maybe_strip_images
from websync.scrapers.naver_common import clean_naver_content
from websync.i18n import t


class NaverPostScraper(BaseScraper):
    """네이버 포스트 스크래퍼 (서비스 종료)."""

    @staticmethod
    def _ended_msg() -> str:
        return t("naver_post.ended")

    def __init__(self):
        self.logger = get_logger()
        self.last_fetch_stats: dict = {}

    def fetch_articles(self, site_config: dict) -> list:
        url = (site_config.get("url") or "").strip()
        self.last_fetch_stats = {"skipped": 0}

        # 종료 안내 페이지 여부 확인 (오프라인/아카이브 대비 레거시 파싱 시도는 하지 않음)
        try:
            if url:
                resp = fetch_url(url, timeout=10)
                text = (resp.text or "")[:4000]
                if "종료" in text or "end_post" in text or "2025년 4월 30일" in text:
                    self.logger.error(self._ended_msg())
                    raise Exception(self._ended_msg())
        except Exception as e:
            if str(e) == self._ended_msg():
                raise
            # 네트워크 오류여도 서비스 종료가 확정된 상태이므로 동일 메시지
            self.logger.error(self._ended_msg())
            raise Exception(self._ended_msg()) from e

        # 종료 문구가 없는 예외적 응답 — 레거시 파싱 최후 시도
        articles = self._legacy_fetch(site_config)
        if not articles:
            raise Exception(self._ended_msg())
        return articles

    def _legacy_fetch(self, site_config: dict) -> list:
        """서비스 종료 전 마크업용 폴백 (정상 동작 기대 안 함)."""
        url = (site_config.get("url") or "").strip()
        limit = normalize_limit(site_config.get("limit", 5))
        articles: list[dict] = []
        try:
            resp = fetch_url(url, timeout=15)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or resp.encoding
            soup = BeautifulSoup(resp.text, "html.parser")

            post_links = soup.select("a.spot_post_area, a.link_end, ul.lst_feed li a")
            if not post_links:
                post_links = soup.select("a[href*='viewer/postView']")

            seen_urls: set[str] = set()
            for link in post_links:
                if len(articles) >= limit:
                    break
                href = link.get("href", "")
                if "viewer/postView" not in href and "nhn" not in href:
                    continue
                if not href.startswith("http"):
                    href = "https://post.naver.com" + href
                if href in seen_urls:
                    continue
                seen_urls.add(href)

                title_el = link.select_one(".tit_feed, .ell, .tit")
                title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)[:60]
                if not title:
                    continue

                content = self._fetch_post_content(href, site_config)
                if content:
                    articles.append({"title": title, "content": content, "url": href})
                else:
                    self.last_fetch_stats["skipped"] = self.last_fetch_stats.get("skipped", 0) + 1
        except Exception as e:
            self.logger.warning(t("naver_post.legacy_failed", error=e))
        return articles

    def _fetch_post_content(self, post_url: str, site_config: dict) -> str | None:
        try:
            resp = fetch_url(post_url, timeout=15)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or resp.encoding
            soup = BeautifulSoup(resp.text, "html.parser")

            container = (
                soup.select_one("div.__viewer_container")
                or soup.select_one("div.se_component_wrap")
                or soup.select_one("div.post_ct")
                or soup.select_one("div#cont")
                or soup.select_one("article")
            )
            if not container:
                return None

            maybe_strip_images(container, site_config)
            clean_naver_content(container)
            return str(container)
        except Exception as e:
            self.logger.warning(t("naver_post.body_failed", url=post_url, error=e))
            return None
