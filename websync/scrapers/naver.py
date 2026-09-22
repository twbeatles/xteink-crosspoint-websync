"""NaverBlogScraper"""
from concurrent.futures import ThreadPoolExecutor
from websync.scrapers.base import BaseScraper, HEADERS, maybe_strip_images, extract_rss_link, ensure_article_url, fetch_url, normalize_limit
import re
from bs4 import BeautifulSoup
from websync.core.logger import get_logger
from websync.scrapers.naver_common import clean_naver_content
from websync.i18n import t

# 상세 페이지 병렬 수집 워커 수 (N2)
_DETAIL_MAX_WORKERS = 3

class NaverBlogScraper(BaseScraper):
    """네이버 블로그를 iframe 우회 및 RSS 피드를 활용해 깔끔하게 크롤링하는 클래스"""
    def __init__(self):
        self.logger = get_logger()
        self.last_fetch_stats: dict = {}

    def fetch_articles(self, site_config: dict) -> list:
        self.last_fetch_stats = {"skipped": 0, "reasons": []}
        url = site_config.get("url")
        limit = normalize_limit(site_config.get("limit", 5))

        # 블로그 ID 추출 (다양한 네이버 주소 유형 지원: m.blog.naver.com, blog.naver.com, ID.blog.me)
        blog_id = None

        # 1. 일반 및 모바일 도메인 매칭 (blog.naver.com/ID 또는 m.blog.naver.com/ID)
        naver_match = re.search(r"blog\.naver\.com/([a-zA-Z0-9_\-]+)", url)
        if naver_match:
            blog_id = naver_match.group(1)
        else:
            # 2. 구형/개인 도메인 매칭 (ID.blog.me)
            me_match = re.search(r"([a-zA-Z0-9_\-]+)\.blog\.me", url)
            if me_match:
                blog_id = me_match.group(1)

        if not blog_id:
            raise Exception(t("naver.invalid_url"))

        # 네이버 블로그 RSS 피드 URL 구성
        rss_url = f"https://rss.blog.naver.com/{blog_id}.xml"

        try:
            # RSS 조회하여 최신 글 고유 링크 획득
            response = fetch_url(rss_url, timeout=15)
            response.raise_for_status()
        except Exception as e:
            raise Exception(t("naver.rss_failed", error=e)) from e

        soup = BeautifulSoup(response.text, "xml")
        items = soup.find_all("item")[:limit]

        if not items:
            raise Exception(t("naver.list_failed"))

        # 메타 추출 (순서 보존)
        post_meta = []
        for item in items:
            title_elem = item.find("title")
            link_elem = item.find("link")
            if not title_elem or not link_elem:
                self._record_skip(t("naver.skip_meta"))
                continue
            title = title_elem.text.strip()
            post_link = link_elem.text.strip()

            # 포스트 고유 번호(logNo) 추출 (쿼리 스트링 제거 후 파싱)
            clean_link = post_link.split("?")[0]
            log_no_match = re.search(r"/(\d+)$", clean_link)
            if not log_no_match:
                log_no_match = re.search(r"logNo=(\d+)", post_link)

            if not log_no_match:
                self.logger.warning(t("naver.logno_warn", url=post_link))
                self._record_skip(t("naver.skip_logno", title=title))
                continue

            log_no = log_no_match.group(1)
            post_meta.append({"title": title, "post_link": post_link, "log_no": log_no})

        # 상세 페이지 병렬 수집 (N2) — 순서 유지
        articles: list[dict | None] = [None] * len(post_meta)
        if post_meta:
            workers = min(_DETAIL_MAX_WORKERS, len(post_meta))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                results = list(
                    executor.map(
                        lambda m: self._fetch_post_detail(
                            blog_id, m["log_no"], m["title"], m["post_link"], site_config
                        ),
                        post_meta,
                    )
                )
            for idx, (meta, art) in enumerate(zip(post_meta, results)):
                if art is not None:
                    articles[idx] = art
                else:
                    self._record_skip(t("naver.skip_body", title=meta["title"]))

        # None(실패) 제거
        articles = [a for a in articles if a is not None]

        if not articles:
            raise Exception(t("naver.zero_body", n=len(items)))

        skipped = self.last_fetch_stats.get("skipped", 0)
        if skipped:
            self.logger.info(t("naver.skipped_info", n=skipped))
        return articles

    def _record_skip(self, reason: str) -> None:
        stats = self.last_fetch_stats
        stats["skipped"] = int(stats.get("skipped", 0)) + 1
        reasons = stats.setdefault("reasons", [])
        if reason:
            reasons.append(reason)

    def _fetch_post_detail(self, blog_id: str, log_no: str, title: str, post_link: str, site_config: dict):
        """단일 포스트 상세 본문 수집. 실패 시 None 반환 (스킵)."""
        try:
            # iframe 우회용 실제 본문 주소 호출
            post_view_url = f"https://blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}"
            post_response = fetch_url(post_view_url, timeout=15)
            if post_response.status_code != 200:
                self.logger.error(t("naver.http_failed", status=post_response.status_code, title=title))
                return None

            # 인코딩 처리
            post_response.encoding = post_response.apparent_encoding
            post_soup = BeautifulSoup(post_response.text, "html.parser")

            # SmartEditor One 본문 또는 구버전 포스팅 본문 컨테이너 식별
            content_elem = post_soup.select_one("div.se-main-container") or post_soup.select_one("#postViewArea")

            if not content_elem:
                self.logger.warning(t("naver.no_container", title=title))
                return None

            maybe_strip_images(content_elem, site_config)
            clean_naver_content(content_elem)

            content_html = str(content_elem)
            return {
                "title": title,
                "content": content_html,
                "url": post_link,
            }
        except Exception as e:
            self.logger.warning(t("naver.parse_error", error=e))
            return None
