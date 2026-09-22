"""TistoryScraper"""
from websync.scrapers.base import BaseScraper, HEADERS, maybe_strip_images, extract_rss_link, ensure_article_url, fetch_url, normalize_limit
from bs4 import BeautifulSoup
from websync.core.logger import get_logger
from websync.i18n import t

class TistoryScraper(BaseScraper):
    """티스토리 블로그 전용 스크래퍼 - RSS에서 URL 추출 후 본문 직접 수집"""

    def __init__(self):
        self.logger = get_logger()
        self.last_fetch_stats: dict = {}


    def fetch_articles(self, site_config: dict) -> list:
        self.last_fetch_stats = {"skipped": 0}
        url = site_config.get("url", "")
        limit = normalize_limit(site_config.get("limit", 5))
        articles = []
        skipped = 0
        try:
            # RSS 피드에서 글 목록 수집
            rss_url = url if url.endswith("/rss") else url.rstrip("/") + "/rss"
            resp = fetch_url(rss_url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml-xml")
            items = soup.find_all("item")[:limit]
            for item in items:
                title_tag = item.find("title")
                link_tag = item.find("link")
                if not title_tag or not link_tag:
                    skipped += 1
                    continue
                title = title_tag.get_text(strip=True)
                post_url = link_tag.get_text(strip=True) if link_tag else ""
                if not post_url:
                    link_tag2 = item.find("link")
                    post_url = str(link_tag2) if link_tag2 else ""
                content = self._fetch_post_content(post_url, site_config)
                if content:
                    post_url = ensure_article_url(post_url, url, title)
                    articles.append({"title": title, "content": content, "url": post_url})
                else:
                    skipped += 1
            self.last_fetch_stats = {"skipped": skipped}
            if items and not articles:
                raise Exception(t("tistory.zero_body", n=len(items)))
        except Exception as e:
            msg = str(e)
            if (
                t("scraper.zero_body") in msg
                or t("tistory.failed", error="") in msg
            ):
                raise
            raise Exception(t("tistory.failed", error=e)) from e
        return articles

    def _fetch_post_content(self, url: str, site_config: dict) -> str:
        if not url:
            return ""
        try:
            resp = fetch_url(url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            content_tag = (
                soup.find("div", class_="tt_article_useless_p_margin") or
                soup.find("div", class_="article-view") or
                soup.find("div", id="content") or
                soup.find("article")
            )
            if not content_tag:
                return ""
            for tag in content_tag.find_all(True):
                tag.attrs = {k: v for k, v in tag.attrs.items() if k in ("href", "src")}
            maybe_strip_images(content_tag, site_config)
            return str(content_tag)
        except Exception as e:
            self.logger.warning(t("tistory.post_failed", url=url, error=e))
            return ""

