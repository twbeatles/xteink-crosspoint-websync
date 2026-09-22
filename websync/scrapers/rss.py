"""RssScraper — RSS/Atom 피드 수집."""
from __future__ import annotations

import html as html_lib
import re

from bs4 import BeautifulSoup

from websync.scrapers.base import (
    BaseScraper,
    ensure_article_url,
    extract_rss_link,
    fetch_url,
    normalize_limit,
    maybe_strip_images,
)
from websync.i18n import t


def _decode_feed_xml(response) -> str:
    """charset 미지정 시 ISO-8859-1로 잘못 디코딩되는 문제를 보정."""
    # XML 선언 encoding 우선
    head = response.content[:200].decode("ascii", errors="ignore")
    enc = None
    if "encoding=" in head.lower():
        m = re.search(r"encoding\s*=\s*['\"]?\s*([a-zA-Z0-9_\-]+)", head, re.I)
        if m:
            enc = m.group(1).strip()

    if not enc:
        # requests 가 ISO-8859-1 로 추론한 경우 apparent 또는 utf-8
        declared = (response.encoding or "").lower()
        if declared in ("iso-8859-1", "latin-1", "ascii", ""):
            enc = response.apparent_encoding or "utf-8"
        else:
            enc = response.encoding or "utf-8"

    try:
        return response.content.decode(enc, errors="replace")
    except LookupError:
        return response.content.decode("utf-8", errors="replace")


class RssScraper(BaseScraper):
    """RSS 피드 XML을 파싱하여 글 목록을 수집하는 클래스"""

    def fetch_articles(self, site_config: dict) -> list:
        url = site_config.get("url")
        limit = normalize_limit(site_config.get("limit", 5))

        try:
            response = fetch_url(url, timeout=15)
            response.raise_for_status()
        except Exception as e:
            raise Exception(t("rss.download_failed", error=e)) from e

        xml_text = _decode_feed_xml(response)
        # lxml-xml 이 있으면 사용, 없으면 xml
        try:
            soup = BeautifulSoup(xml_text, "lxml-xml")
        except Exception:
            soup = BeautifulSoup(xml_text, "xml")

        items = soup.find_all("item")[:limit]
        if not items:
            items = soup.find_all("entry")[:limit]

        if not items:
            raise Exception(t("rss.no_items"))

        articles = []
        for item in items:
            try:
                title_elem = item.find("title")
                # content:encoded (미디어 확장) 우선
                content_elem = (
                    item.find("content:encoded")
                    or item.find("encoded")
                    or item.find("content")
                    or item.find("description")
                    or item.find("summary")
                )

                if not title_elem:
                    continue

                title = (title_elem.get_text() or "").strip()
                raw_content = ""
                if content_elem is not None:
                    # CDATA HTML 은 string/get_text 가 원문에 가깝고,
                    # decode_contents 는 엔티티 이스케이프될 수 있음
                    raw_content = (content_elem.string or content_elem.get_text() or "").strip()
                    if not raw_content and hasattr(content_elem, "decode_contents"):
                        raw_content = (content_elem.decode_contents() or "").strip()
                    if raw_content.startswith("&lt;") or raw_content.startswith("&amp;lt;"):
                        raw_content = html_lib.unescape(raw_content)

                art_url = extract_rss_link(item, url)
                content_soup = BeautifulSoup(raw_content or "", "html.parser")
                maybe_strip_images(content_soup, site_config)

                text = content_soup.get_text(" ", strip=True)
                # 이미지·표만 있는 요약 피드는 제목+링크 안내 문단 보강
                if len(text) < 80:
                    parts = [f"<p>{html_lib.escape(title)}</p>"]
                    if text:
                        parts.append(f"<p>{html_lib.escape(text)}</p>")
                    if art_url:
                        safe = html_lib.escape(art_url, quote=True)
                        parts.append(
                            f'<p><a href="{safe}">{t("rss.original_link")}</a></p>'
                        )
                        parts.append(f"<p>{html_lib.escape(art_url)}</p>")
                    parts.append(f"<p>{t('rss.summary_only')}</p>")
                    content_html = "".join(parts)
                else:
                    content_html = str(content_soup)

                art_url = ensure_article_url(art_url, url, title)
                articles.append({"title": title, "content": content_html, "url": art_url})
            except Exception as e:
                print(t("rss.item_error", error=e))
                continue

        return articles
