"""NaverBlogScraper 단위 테스트 (N2 — 병렬 수집 + skipped stats).

외부 네트워크 호출 없이 _fetch_post_detail 과 fetch_articles 의
메타 추출·병렬 수집·skipped 통계 기록을 검증한다.
"""

from unittest.mock import MagicMock, patch

import pytest

from websync.scrapers.naver import NaverBlogScraper


def _fake_response(text: str, status: int = 200):
    resp = MagicMock()
    resp.text = text
    resp.status_code = status
    resp.apparent_encoding = "utf-8"
    resp.encoding = "utf-8"
    return resp


RSS_TWO_ITEMS = """<?xml version="1.0" encoding="UTF-8"?>
<rss><channel>
  <item>
    <title>첫 글</title>
    <link>https://blog.naver.com/abc/1001</link>
  </item>
  <item>
    <title>둘째 글</title>
    <link>https://blog.naver.com/abc/1002</link>
  </item>
</channel></rss>"""


SMART_EDITOR_BODY = (
    "<html><body><div class='se-main-container'><p>본문 내용 1</p></div></body></html>"
)
POSTVIEW_BODY = (
    "<html><body><div id='postViewArea'><p>구버전 본문</p></div></body></html>"
)


def test_extract_blog_id_from_standard_url():
    scraper = NaverBlogScraper()
    # URL 파싱은 fetch_articles 내부에서 수행 — RSS 응답으로 간접 검증
    with patch("websync.scrapers.naver.fetch_url") as mock_fetch:
        mock_fetch.return_value = _fake_response(RSS_TWO_ITEMS)
        with patch.object(
            scraper, "_fetch_post_detail", return_value=None
        ) as mock_detail:
            with pytest.raises(Exception, match="본문 수집 성공 0건"):
                scraper.fetch_articles(
                    {"url": "https://blog.naver.com/abc", "limit": 2}
                )
    # 두 포스트의 상세 수집이 병렬로 시도되었는지
    assert mock_detail.call_count == 2


def test_parallel_detail_collection_preserves_order():
    """병렬 수집 후에도 RSS 순서가 유지되는지."""
    scraper = NaverBlogScraper()
    rss = RSS_TWO_ITEMS

    def fake_detail(blog_id, log_no, title, post_link, site_config):
        # log_no 로 구분되는 더미 본문 반환
        return {
            "title": title,
            "content": f"<p>본문 {log_no}</p>",
            "url": post_link,
        }

    with patch("websync.scrapers.naver.fetch_url", return_value=_fake_response(rss)):
        with patch.object(scraper, "_fetch_post_detail", side_effect=fake_detail):
            articles = scraper.fetch_articles(
                {"url": "https://blog.naver.com/abc", "limit": 2}
            )

    assert len(articles) == 2
    assert articles[0]["title"] == "첫 글"
    assert articles[1]["title"] == "둘째 글"
    assert "1001" in articles[0]["content"]
    assert "1002" in articles[1]["content"]


def test_fetch_post_detail_smart_editor_one():
    scraper = NaverBlogScraper()
    with patch(
        "websync.scrapers.naver.fetch_url",
        return_value=_fake_response(SMART_EDITOR_BODY),
    ):
        art = scraper._fetch_post_detail(
            "abc", "1001", "제목", "https://blog.naver.com/abc/1001", {}
        )
    assert art is not None
    assert "본문 내용 1" in art["content"]
    assert art["url"] == "https://blog.naver.com/abc/1001"


def test_fetch_post_detail_legacy_postviewarea():
    scraper = NaverBlogScraper()
    with patch(
        "websync.scrapers.naver.fetch_url", return_value=_fake_response(POSTVIEW_BODY)
    ):
        art = scraper._fetch_post_detail(
            "abc", "1002", "제목", "https://blog.naver.com/abc/1002", {}
        )
    assert art is not None
    assert "구버전 본문" in art["content"]


def test_fetch_post_detail_returns_none_on_missing_container():
    scraper = NaverBlogScraper()
    empty_body = "<html><body><p>본문 컨테이너 없음</p></body></html>"
    with patch(
        "websync.scrapers.naver.fetch_url", return_value=_fake_response(empty_body)
    ):
        art = scraper._fetch_post_detail(
            "abc", "1003", "제목", "https://blog.naver.com/abc/1003", {}
        )
    assert art is None


def test_fetch_post_detail_returns_none_on_non_200():
    scraper = NaverBlogScraper()
    with patch(
        "websync.scrapers.naver.fetch_url", return_value=_fake_response("", status=500)
    ):
        art = scraper._fetch_post_detail(
            "abc", "1004", "제목", "https://blog.naver.com/abc/1004", {}
        )
    assert art is None


def test_skipped_stats_recorded_when_detail_fails():
    """상세 수집 실패 시 last_fetch_stats['skipped'] 증가."""
    scraper = NaverBlogScraper()
    rss = RSS_TWO_ITEMS

    # 첫 글은 성공, 둘째 글은 None(실패)
    results = {
        "1001": {
            "title": "첫 글",
            "content": "<p>x</p>",
            "url": "https://blog.naver.com/abc/1001",
        },
        "1002": None,
    }

    def fake_detail(blog_id, log_no, title, post_link, site_config):
        return results.get(log_no)

    with patch("websync.scrapers.naver.fetch_url", return_value=_fake_response(rss)):
        with patch.object(scraper, "_fetch_post_detail", side_effect=fake_detail):
            articles = scraper.fetch_articles(
                {"url": "https://blog.naver.com/abc", "limit": 2}
            )

    # 실패 1건은 스킵되어 1건만 반환
    assert len(articles) == 1
    assert articles[0]["title"] == "첫 글"
    assert scraper.last_fetch_stats.get("skipped") == 1


def test_invalid_url_raises_exception():
    scraper = NaverBlogScraper()
    with pytest.raises(Exception, match="올바른 네이버 블로그 URL"):
        scraper.fetch_articles({"url": "https://example.com/notnaver", "limit": 5})


def test_empty_rss_raises_exception():
    scraper = NaverBlogScraper()
    empty_rss = "<?xml version='1.0'?><rss><channel></channel></rss>"
    with patch(
        "websync.scrapers.naver.fetch_url", return_value=_fake_response(empty_rss)
    ):
        with pytest.raises(Exception, match="포스트 목록을 읽어오지 못"):
            scraper.fetch_articles({"url": "https://blog.naver.com/abc", "limit": 5})
