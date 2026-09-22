"""CssSelectorScraper"""
from websync.scrapers.base import BaseScraper, HEADERS, maybe_strip_images, ensure_article_url, fetch_url, normalize_limit
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from websync.i18n import t


def _reparse_fragment(elem):
    """원본 DOM을 훼손하지 않도록 조각 HTML을 새 문서로 재파싱."""
    if elem is None:
        return None
    try:
        html = str(elem)
    except Exception:
        return None
    if not html.strip():
        return None
    try:
        frag = BeautifulSoup(html, "html.parser")
    except Exception:
        return None
    # 단일 루트 선호
    if frag.body:
        children = [c for c in frag.body.children if getattr(c, "name", None)]
        if len(children) == 1:
            return children[0]
    root = frag.find(True)
    return root if root is not None else frag


class CssSelectorScraper(BaseScraper):
    """일반적인 HTML 구조에서 CSS 선택자(CSS Selector)를 이용해 스크래핑하는 클래스"""

    def __init__(self):
        self.last_fetch_stats: dict = {}

    def fetch_articles(self, site_config: dict) -> list:
        self.last_fetch_stats = {
            "skipped": 0,
            "reasons": [],
            "content_fallback_count": 0,
            "detail_fallback_count": 0,
        }
        url = site_config.get("url")
        item_selector = (site_config.get("item_selector") or "").strip()
        if not item_selector:
            raise Exception(t("css.empty_item_selector"))
        title_selector = site_config.get("title_selector", ".post-title")
        content_selector = site_config.get("content_selector", ".post-content")
        # 미지정 시 기존 동작 유지 (첫 a[href])
        link_selector = (site_config.get("link_selector") or "a[href]").strip() or "a[href]"
        remove_selectors = site_config.get("remove_selectors", "")
        limit = normalize_limit(site_config.get("limit", 5))
        fetch_detail = bool(site_config.get("fetch_detail_page", False))

        headers = dict(HEADERS)

        try:
            response = fetch_url(url, headers=headers, timeout=15)
            response.raise_for_status()
        except Exception as e:
            raise Exception(t("css.http_failed", error=e)) from e

        if response.encoding == "ISO-8859-1":
            response.encoding = response.apparent_encoding

        soup = BeautifulSoup(response.text, "html.parser")
        try:
            posts = soup.select(item_selector)[:limit]
        except Exception as e:
            raise Exception(t("css.item_selector_syntax", error=e)) from e

        if not posts:
            raise Exception(t("css.no_items"))

        articles = []
        skipped = 0
        content_fallback = 0
        detail_fallback = 0
        for idx, post in enumerate(posts):
            try:
                title = self._extract_title(post, title_selector)
                if not title:
                    skipped += 1
                    print(t("css.title_missing", n=idx + 1))
                    continue

                art_url = self._extract_link(post, link_selector, url)

                content_elem = None
                used_list_fallback = False
                used_detail_fallback = False
                if fetch_detail and art_url and art_url != url:
                    content_elem, used_detail_fallback = self._fetch_detail_content(
                        art_url, content_selector, remove_selectors, site_config, headers
                    )
                    if content_elem is None:
                        skipped += 1
                        print(t("css.detail_skip", title=title))
                        continue
                    if used_detail_fallback:
                        detail_fallback += 1
                else:
                    content_elem, used_list_fallback = self._extract_list_content(
                        post, content_selector, remove_selectors, site_config
                    )
                    if content_elem is None:
                        skipped += 1
                        print(t("css.content_missing", n=idx + 1))
                        continue
                    if used_list_fallback:
                        content_fallback += 1
                        print(t("css.list_fallback", n=idx + 1))

                content_html = str(content_elem)
                art_url = ensure_article_url(art_url, url, title)
                art = {"title": title, "content": content_html, "url": art_url}
                if used_list_fallback:
                    art["_content_fallback"] = True
                if used_detail_fallback:
                    art["_detail_fallback"] = True
                articles.append(art)
            except Exception as e:
                skipped += 1
                print(t("css.item_error", error=e))
                continue

        self.last_fetch_stats = {
            "skipped": skipped,
            "reasons": [],
            "content_fallback_count": content_fallback,
            "detail_fallback_count": detail_fallback,
        }
        if posts and not articles:
            raise Exception(t("css.zero_body", n=len(posts)))
        return articles

    @staticmethod
    def _extract_title(post, title_selector: str) -> str:
        """아이템 내 제목. 선택자 실패 시 아이템 자체/첫 링크 텍스트 폴백."""
        sel = (title_selector or "").strip()
        title_elem = None
        if sel and sel not in (".", ":scope"):
            try:
                title_elem = post.select_one(sel)
            except Exception:
                title_elem = None
        if title_elem is not None:
            text = title_elem.get_text(" ", strip=True)
            if text:
                return text
        # 아이템이 링크이거나 텍스트가 있으면 사용
        if getattr(post, "name", None) == "a":
            text = post.get_text(" ", strip=True)
            if text:
                return text
        link = post.select_one("a[href]") if hasattr(post, "select_one") else None
        if link is not None:
            text = link.get_text(" ", strip=True)
            if text:
                return text
        text = post.get_text(" ", strip=True) if hasattr(post, "get_text") else ""
        return (text or "").strip()

    @staticmethod
    def _extract_link(post, link_selector: str, page_url: str) -> str:
        sel = (link_selector or "a[href]").strip() or "a[href]"
        link_elem = None
        if sel in (".", ":scope") and getattr(post, "name", None) == "a":
            link_elem = post
        else:
            try:
                link_elem = post.select_one(sel)
            except Exception:
                link_elem = None
        if link_elem is None and getattr(post, "name", None) == "a":
            link_elem = post
        if link_elem is None:
            link_elem = post.select_one("a[href]") if hasattr(post, "select_one") else None
        if not link_elem:
            return page_url
        href = link_elem.get("href", "") if hasattr(link_elem, "get") else ""
        if not href:
            return page_url
        return href if href.startswith("http") else urljoin(page_url, href)

    def _extract_list_content(self, post, content_selector, remove_selectors, site_config):
        """목록 아이템에서 본문 추출.

        Returns:
            (element_or_none, used_fallback: bool)
        """
        content_elem = None
        used_fallback = False
        sel = (content_selector or "").strip()
        if sel:
            try:
                content_elem = post.select_one(sel)
            except Exception:
                content_elem = None
        if content_elem is None:
            content_elem = post
            used_fallback = True
        content_elem = _reparse_fragment(content_elem)
        if content_elem is None:
            return None, used_fallback
        if remove_selectors:
            selectors = [s.strip() for s in remove_selectors.split(",") if s.strip()]
            for s in selectors:
                try:
                    for match in content_elem.select(s):
                        match.decompose()
                except Exception:
                    continue
        maybe_strip_images(content_elem, site_config)
        text = content_elem.get_text(" ", strip=True) if content_elem else ""
        if not text:
            return None, used_fallback
        return content_elem, used_fallback

    # 상세 페이지 본문 폴백 후보 (한국 블로그·워드프레스)
    _DETAIL_FALLBACKS = (
        ".entry-content",
        ".post-content",
        ".article-body",
        ".markdown-body",
        "article .content",
        "article",
        "main article",
        "main",
        "#content",
        ".tt_article_useless_p_margin",
        "div.se-main-container",
    )

    def _fetch_detail_content(
        self,
        art_url: str,
        content_selector: str,
        remove_selectors: str,
        site_config: dict,
        headers: dict,
    ):
        """Returns (element_or_none, used_fallback_selector: bool)."""
        try:
            resp = fetch_url(art_url, headers=headers, timeout=15)
            resp.raise_for_status()
            if resp.encoding == "ISO-8859-1":
                resp.encoding = resp.apparent_encoding
            detail = BeautifulSoup(resp.text, "html.parser")
            candidates = []
            if content_selector:
                candidates.append(content_selector)
            candidates.extend(self._DETAIL_FALLBACKS)
            content_elem = None
            used_fallback = False
            for i, sel in enumerate(candidates):
                try:
                    content_elem = detail.select_one(sel)
                except Exception:
                    content_elem = None
                if content_elem is not None:
                    text = content_elem.get_text(" ", strip=True)
                    if len(text) >= 40:
                        used_fallback = i > 0 and bool(content_selector)
                        break
                    content_elem = None
            if content_elem is None:
                return None, False
            content_elem = _reparse_fragment(content_elem)
            if content_elem is None:
                return None, False
            if remove_selectors:
                selectors = [s.strip() for s in remove_selectors.split(",") if s.strip()]
                for sel in selectors:
                    try:
                        for match in content_elem.select(sel):
                            match.decompose()
                    except Exception:
                        continue
            maybe_strip_images(content_elem, site_config)
            return content_elem, used_fallback
        except Exception as e:
            print(t("css.detail_failed", url=art_url, error=e))
            return None, False
