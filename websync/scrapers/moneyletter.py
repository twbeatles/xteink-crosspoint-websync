"""MoneyLetterScraper — 어피티 머니레터(uppity.co.kr) 전용 스크래퍼

BaseNewsletterScraper를 상속. 목록은 Unlimited Elements 포스트 그리드,
상세는 Elementor 싱글 포스트 본문을 사용한다.

Stibee 기반 본문은 이메일용 중첩 테이블이 깊어 e-ink/EPUB 리더에서
빈 화면처럼 보일 수 있으므로, 수집 후 선형 HTML로 재구성한다.
"""

from __future__ import annotations

import html as html_lib
import re
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from websync.scrapers.base import fetch_url, maybe_strip_images
from websync.scrapers.newsletter_base import BaseNewsletterScraper
from websync.i18n import t


class MoneyLetterScraper(BaseNewsletterScraper):
    """어피티 머니레터 전용 구현.

    - 아카이브: `/newsletter/money-letter/` (+ 페이지네이션 `/2/` 등)
    - 상세: 도메인 루트 단일 슬러그 포스트
    """

    LINK_PATTERN = re.compile(
        r"(?:https?://(?:www\.)?uppity\.co\.kr)?/[^/\s?#]+/?$",
        re.IGNORECASE,
    )

    ARCHIVE_PATTERN = re.compile(
        r"/newsletter/money-letter/?(?:\d+/?)?$",
        re.IGNORECASE,
    )

    _EXCLUDED_SLUGS = frozenset({
        "newsletter", "category", "tag", "author", "page", "product",
        "shop", "subscription", "wp-admin", "wp-login.php", "wp-content",
        "wp-json", "feed", "cart", "checkout", "my-account", "privacy-policy",
        "about", "contact", "search",
    })

    # 짧은 구독/프로모 CTA 제거 키워드
    _CTA_KEYWORDS = ("구독하기", "무료 구독", "뉴스레터 구독", "개인정보 수집", "광고성 정보")

    CONTENT_CANDIDATES = [
        ".elementor-widget-theme-post-content .elementor-widget-container",
        ".elementor-widget-theme-post-content",
        "div.elementor-location-single",
        "div.entry-content",
        "article",
        "main",
        "body",
    ]

    def _is_detail_url(self, url: str) -> bool:
        """아카이브가 아니고 단일 슬러그 포스트이면 상세로 본다."""
        path = urlparse(url).path or ""
        if self.ARCHIVE_PATTERN.search(path):
            return False
        segments = [s for s in path.split("/") if s]
        if len(segments) != 1:
            return False
        slug = unquote(segments[0]).lower()
        if slug in self._EXCLUDED_SLUGS:
            return False
        return True

    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
        """머니레터 아카이브 포스트 그리드에서 기사 링크를 추출."""
        results: list[tuple[str, str]] = []
        seen: set[str] = set()

        items = soup.select(
            ".ue-item, .uc_post_grid_style_one_item, .ue_post_grid_item"
        )
        if items:
            for item in items:
                pair = self._best_link_from_container(item, base_url)
                if not pair:
                    continue
                full, title = pair
                if full in seen:
                    continue
                seen.add(full)
                results.append((full, title))
            if results:
                return results

        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            full = urljoin(base_url, href)
            if full in seen or not self._is_detail_url(full):
                continue
            title = a.get_text(strip=True) or t("moneyletter.fallback_title")
            if len(title) < 8:
                continue
            seen.add(full)
            results.append((full, title))
        return results

    def _best_link_from_container(
        self, container, base_url: str
    ) -> tuple[str, str] | None:
        """그리드 카드 안에서 제목 텍스트가 가장 긴 상세 링크를 고른다."""
        best: tuple[str, str] | None = None
        best_len = -1
        for a in container.select("a[href]"):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            full = urljoin(base_url, href)
            if not self._is_detail_url(full):
                continue
            text = a.get_text(strip=True) or ""
            score = len(text)
            if score > best_len:
                best_len = score
                best = (full, text or t("moneyletter.fallback_title"))
        return best

    def _get_title(self, url: str) -> str | None:
        """og:title 우선, 없으면 <title>."""
        try:
            resp = fetch_url(url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            og = soup.select_one('meta[property="og:title"]')
            if og and og.get("content"):
                return og["content"].strip()
            if soup.title and soup.title.string:
                return soup.title.string.strip()
        except Exception:
            pass
        return None

    def _fetch_and_clean_detail(self, url: str, site_config: dict) -> str:
        """상세 수집 후 e-ink용 선형 HTML로 변환해 반환."""
        try:
            resp = fetch_url(url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            self._last_detail_title = self._extract_page_title(soup) or ""

            container = self._find_content_container(soup)
            if not container:
                self.logger.warning(t("newsletter.no_container", url=url))
                return ""

            self._clean_content(container, site_config)
            maybe_strip_images(container, site_config)

            html_out = self._to_eink_html(container)
            if not html_out or len(BeautifulSoup(html_out, "lxml").get_text(strip=True)) < 50:
                self.logger.warning(t("moneyletter.too_short", url=url))
                return ""
            return html_out
        except Exception as e:
            self.logger.warning(t("newsletter.detail_failed", url=url, error=e))
            return ""

    def _clean_content(self, container: BeautifulSoup, site_config: dict) -> None:
        """머니레터 특화 정제 (클래스 선택자는 속성 제거 전에 수행)."""
        # 공통 태그 제거 (nav/script 등) — 속성 strip 전에 클래스 기반 제거
        for tag_name in ("nav", "header", "footer", "aside", "script", "style", "form", "noscript"):
            for t in container.find_all(tag_name):
                t.decompose()

        for sel in (
            ".elementor-widget-form",
            ".elementor-location-header",
            ".elementor-location-footer",
            ".sharedaddy",
            ".jp-relatedposts",
            ".elementor-widget-share-buttons",
            "[class*='subscribe']",
            "[class*='newsletter-signup']",
            "[class*='related']",
        ):
            for el in container.select(sel):
                el.decompose()

        for el in list(container.find_all(["div", "section", "p", "a"])):
            txt = el.get_text(strip=True)
            if not txt:
                continue
            if len(txt) < 40 and any(kw in txt for kw in self._CTA_KEYWORDS):
                el.decompose()

        # 속성 최소화 (EPUB 안전)
        for tag in container.find_all(True):
            kept = {k: v for k, v in tag.attrs.items() if k in ("href", "src", "alt", "title")}
            tag.attrs = kept

    def _to_eink_html(self, container: Tag) -> str:
        """이메일용 중첩 테이블 HTML → e-ink 친화 선형 HTML."""
        self._unwrap_layout_tables(container)
        self._unwrap_inline_wrappers(container)
        self._remove_empty_nodes(container)

        parts: list[str] = []
        seen: set[str] = set()

        for el in container.find_all(["h1", "h2", "h3", "h4", "p", "li", "div"]):
            if not isinstance(el, Tag):
                continue
            # 자식에 블록이 있으면 컨테이너로만 보고 건너뜀 (리프 텍스트만)
            if el.name == "div" and el.find(["h1", "h2", "h3", "h4", "p", "li", "div", "ul", "ol"]):
                continue
            if el.name != "div" and el.find(["h1", "h2", "h3", "h4", "p", "li"]):
                continue

            text = " ".join(el.get_text(" ", strip=True).split())
            if len(text) < 2:
                continue
            if text in seen:
                continue
            # 이미 수집한 긴 블록의 완전 부분 문자열은 스킵 (중복 방지)
            if any(text != s and text in s for s in seen if len(s) > len(text) + 10):
                continue
            seen.add(text)

            if el.name in ("h1", "h2", "h3", "h4") or self._looks_like_heading(text):
                parts.append(f"<h2>{html_lib.escape(text)}</h2>")
            elif el.name == "li":
                parts.append(f"<p>• {html_lib.escape(text)}</p>")
            else:
                parts.append(f"<p>{html_lib.escape(text)}</p>")

        if not parts:
            for line in container.get_text("\n", strip=True).splitlines():
                line = " ".join(line.split())
                if len(line) < 2 or line in seen:
                    continue
                seen.add(line)
                parts.append(f"<p>{html_lib.escape(line)}</p>")

        if not parts:
            return ""
        return "<div>\n" + "\n".join(parts) + "\n</div>"

    @staticmethod
    def _unwrap_layout_tables(container: Tag) -> None:
        """table/tr/td 레이아웃 껍질을 제거해 본문 흐름만 남긴다."""
        for _ in range(40):
            tags = container.find_all(
                ["table", "tbody", "thead", "tfoot", "tr", "td", "th", "colgroup", "col"]
            )
            if not tags:
                break
            for t in tags:
                t.unwrap()

    @staticmethod
    def _unwrap_inline_wrappers(container: Tag) -> None:
        for tag_name in ("span", "font", "center", "b", "i", "u", "strong", "em"):
            for el in list(container.find_all(tag_name)):
                # 의미 있는 링크 안의 강조는 unwrap만
                el.unwrap()

    @staticmethod
    def _remove_empty_nodes(container: Tag) -> None:
        for el in list(container.find_all(["a", "div", "p", "li"])):
            if el.get_text(strip=True):
                continue
            if el.find("img"):
                continue
            el.decompose()

    @staticmethod
    def _looks_like_heading(text: str) -> bool:
        """짧은 이모지 섹션 제목 등."""
        if len(text) > 48:
            return False
        # 보충 평면 이모지·심볼 범위 (대략)
        emoji_like = sum(
            1
            for ch in text
            if ord(ch) >= 0x2190  # arrows etc.
            and (
                0x2190 <= ord(ch) <= 0x21FF
                or 0x2600 <= ord(ch) <= 0x27BF
                or 0x1F300 <= ord(ch) <= 0x1FAFF
            )
        )
        if emoji_like and len(text) <= 40:
            return True
        return False
