"""BrunchScraper — 카카오 브런치 전용 스크래퍼.

작가 프로필 페이지는 SPA로 글 목록이 비어 있을 수 있어
공식 JSON API(api.brunch.co.kr)로 목록을 가져온 뒤
상세 HTML에서 본문을 추출합니다.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from websync.core.logger import get_logger
from websync.scrapers.base import BaseScraper, ensure_article_url, fetch_url, maybe_strip_images
from websync.i18n import t


class BrunchScraper(BaseScraper):
    """카카오 브런치 전용 스크래퍼"""

    _API_LIST = "https://api.brunch.co.kr/v1/article/@{profile_id}"
    _PROFILE_RE = re.compile(r"brunch\.co\.kr/@([\w.-]+)", re.I)
    _ARTICLE_NO_RE = re.compile(r"brunch\.co\.kr/@([\w.-]+)/(\d+)", re.I)

    def __init__(self):
        self.logger = get_logger()
        self.last_fetch_stats: dict = {}

    def fetch_articles(self, site_config: dict) -> list:
        self.last_fetch_stats = {"skipped": 0}
        url = (site_config.get("url") or "").strip()
        limit = int(site_config.get("limit", 5) or 5)
        articles: list[dict] = []
        skipped = 0

        try:
            # 단일 글 URL (.../@id/123) 이면 본문만 수집
            single = self._ARTICLE_NO_RE.search(url)
            if single:
                profile_id, no = single.group(1), single.group(2)
                post_url = f"https://brunch.co.kr/@{profile_id}/{no}"
                content = self._fetch_brunch_content(post_url, site_config)
                if content:
                    title = self._fetch_title(post_url) or t(
                        "brunch.fallback_title", id=profile_id, no=no
                    )
                    articles.append({
                        "title": title,
                        "content": content,
                        "url": ensure_article_url(post_url, url, title),
                    })
                else:
                    skipped += 1
                self.last_fetch_stats = {"skipped": skipped}
                if not articles:
                    raise Exception(t("brunch.single_failed"))
                return articles

            profile_id = self._extract_profile_id(url)
            if not profile_id:
                raise Exception(t("brunch.bad_url"))

            entries = self._fetch_list_via_api(profile_id, limit)
            if not entries:
                # HTML 폴백 (구형 마크업 / 매거진 페이지 등)
                entries = self._fetch_list_via_html(url, limit)

            if not entries:
                raise Exception(t("brunch.no_list"))

            for title, post_url in entries[:limit]:
                content = self._fetch_brunch_content(post_url, site_config)
                if content:
                    post_url = ensure_article_url(post_url, url, title)
                    articles.append({"title": title, "content": content, "url": post_url})
                else:
                    skipped += 1

            self.last_fetch_stats = {"skipped": skipped}
            if entries and not articles:
                raise Exception(t("brunch.zero_body", n=len(entries)))
        except Exception as e:
            msg = str(e)
            own = (
                t("scraper.zero_body"),
                t("brunch.failed", error=""),
                t("brunch.no_list"),
                t("brunch.bad_url"),
                t("brunch.single_failed"),
            )
            if any(s and s in msg for s in own):
                raise
            raise Exception(t("brunch.failed", error=e)) from e
        return articles

    def _extract_profile_id(self, url: str) -> str | None:
        m = self._PROFILE_RE.search(url or "")
        if m:
            return m.group(1)
        # path 만 있는 경우 /@id
        path = urlparse(url).path if url else ""
        m2 = re.search(r"/@([\w.-]+)", path)
        return m2.group(1) if m2 else None

    def _fetch_list_via_api(self, profile_id: str, limit: int) -> list[tuple[str, str]]:
        """api.brunch.co.kr 글 목록. 반환: [(title, url), ...]"""
        api_url = self._API_LIST.format(profile_id=profile_id)
        try:
            resp = fetch_url(api_url, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            self.logger.warning(t("brunch.api_list_failed", id=profile_id, error=e))
            return []

        if payload.get("code") not in (200, "200", None):
            # code 200 = OK
            if payload.get("desc") != "OK":
                self.logger.warning(t("brunch.api_bad", desc=payload.get("desc")))
                return []

        data = payload.get("data") or {}
        items = data.get("list") or []
        results: list[tuple[str, str]] = []
        for item in items:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue
            if item.get("status") and item.get("status") != "publish":
                continue
            no = item.get("no")
            if no is None:
                continue
            title = (item.get("title") or item.get("contentSummary") or "").strip() or t(
                "brunch.fallback_item", no=no
            )
            post_url = f"https://brunch.co.kr/@{profile_id}/{no}"
            results.append((title, post_url))
        return results

    def _fetch_list_via_html(self, url: str, limit: int) -> list[tuple[str, str]]:
        """레거시 HTML 선택자 / 매거진 페이지 폴백."""
        try:
            resp = fetch_url(url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception as e:
            self.logger.warning(t("brunch.html_list_failed", error=e))
            return []

        links = soup.select("a.link_post")
        if not links:
            links = soup.select("ul.list_article_m li a")
        if not links:
            # 매거진 등: /@id/숫자 링크
            links = [
                a for a in soup.find_all("a", href=True)
                if re.search(r"/@[\w.-]+/\d+", a.get("href", ""))
            ]

        results: list[tuple[str, str]] = []
        seen: set[str] = set()
        for a_tag in links:
            if len(results) >= limit:
                break
            href = (a_tag.get("href") or "").strip()
            if not href:
                continue
            if not href.startswith("http"):
                href = "https://brunch.co.kr" + href
            if href in seen:
                continue
            if not re.search(r"/@[\w.-]+/\d+", href):
                continue
            seen.add(href)
            title_tag = a_tag.find("strong") or a_tag.find("h3") or a_tag.find("h4")
            title = title_tag.get_text(strip=True) if title_tag else a_tag.get_text(strip=True)
            title = (title or "").strip() or href
            results.append((title, href))
        return results

    def _fetch_title(self, url: str) -> str:
        try:
            resp = fetch_url(url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            for sel in (".cover_title", "h1.tit_subject", "h1", "title"):
                el = soup.select_one(sel)
                if el and el.get_text(strip=True):
                    text = el.get_text(strip=True)
                    if sel == "title" and "브런치" in text:
                        # "제목 | 브런치" 형태
                        return text.split("|")[0].strip() or text
                    return text
        except Exception:
            pass
        return ""

    def _fetch_brunch_content(self, url: str, site_config: dict) -> str:
        try:
            resp = fetch_url(url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            content_tag = (
                soup.select_one("div.wrap_body")
                or soup.select_one("div.wrap_article_body")
                or soup.select_one("div.article_body")
                or soup.select_one("div.wrap_article")
                or soup.find("article")
            )
            if not content_tag:
                return ""
            # 공유/댓글 영역 제거
            for sel in (".wrap_btn_share", ".wrap_donation", ".wrap_author_desc", "script", "style"):
                for el in content_tag.select(sel):
                    el.decompose()
            for tag in content_tag.find_all(True):
                tag.attrs = {k: v for k, v in tag.attrs.items() if k in ("href", "src", "alt")}
            maybe_strip_images(content_tag, site_config)
            text_len = len(content_tag.get_text(strip=True))
            if text_len < 20:
                return ""
            return str(content_tag)
        except Exception as e:
            self.logger.warning(t("brunch.post_failed", url=url, error=e))
            return ""
