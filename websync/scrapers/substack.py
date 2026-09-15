"""SubstackScraper"""
from websync.scrapers.base import BaseScraper, HEADERS, maybe_strip_images, extract_rss_link, ensure_article_url, fetch_url
from bs4 import BeautifulSoup
from websync.i18n import t

class SubstackScraper(BaseScraper):
    """Substack 뉴스레터 전용 스크래퍼 - RSS 전문을 수신 후 Substack 고유 요소 클렌징"""
    def fetch_articles(self, site_config: dict) -> list:
        url = site_config.get("url", "")  # 예: https://example.substack.com/feed
        limit = site_config.get("limit", 5)
        articles = []
        try:
            rss_url = url if "/feed" in url else url.rstrip("/") + "/feed"
            resp = fetch_url(rss_url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml-xml")
            items = soup.find_all("item")[:limit]
            for item in items:
                title_tag = item.find("title")
                link_tag = item.find("link")
                desc_tag = item.find("content:encoded") or item.find("description")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                link = link_tag.get_text(strip=True) if link_tag else ""
                content_html = desc_tag.get_text() if desc_tag else ""
                # Substack 특유의 paywall/버튼 클렌징
                content_soup = BeautifulSoup(content_html, "lxml")
                for sel in ["div.subscribe-widget", "div.paywall", "div.button-wrapper", ".post-footer"]:
                    for el in content_soup.select(sel):
                        el.decompose()
                for tag in content_soup.find_all(True):
                    tag.attrs = {k: v for k, v in tag.attrs.items() if k in ("href",)}
                maybe_strip_images(content_soup, site_config)
                clean_content = str(content_soup)
                link = ensure_article_url(link, url, title)
                articles.append({"title": title, "content": clean_content, "url": link})
        except Exception as e:
            raise Exception(t("substack.failed", error=e)) from e
        return articles
