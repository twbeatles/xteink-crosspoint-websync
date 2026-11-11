"""SoonsalScraper — 아카이브 스토리 앵커(#story-N) 중복 수집 방지."""
from bs4 import BeautifulSoup

from websync.scrapers.soonsal import SoonsalScraper


def _archive_html() -> str:
    """실제 순살 아카이브와 같은 구조: 일자 본문 1개 + #story-N 목차 + 크립토 별호."""
    return """
    <html><body>
      <h2>2026.08.18</h2>
      <a href="/newsletters/2026/0818.html">브리핑순살브리핑 · 편의점 주가가 폭등한 이유</a>
      <ul>
        <li><a href="/newsletters/2026/0818.html#story-1">미국 정부, 이젠 AI 회사와 돈 뺏기 경쟁</a></li>
        <li><a href="/newsletters/2026/0818.html#story-2">10년 무패 트레이더</a></li>
        <li><a href="/newsletters/2026/0818.html#story-3">코딩 배우라던 조언</a></li>
        <li><a href="/newsletters/2026/0818.html#story-4">AI 피해 도망친 돈</a></li>
        <li><a href="/newsletters/2026/0818.html#story-5">현금 없는 창업자</a></li>
      </ul>
      <h2>2026.07.16</h2>
      <a href="/newsletters/2026/0716.html">브리핑순살브리핑 · 롤러코스피</a>
      <a href="/newsletters/2026/0716-crypto.html">Crypto순살크립토 · 정부가 $288M 팔 건가</a>
      <ul>
        <li><a href="/newsletters/2026/0716.html#story-1">레버리지가 만든 롤러코스피</a></li>
      </ul>
    </body></html>
    """


def _links():
    sc = SoonsalScraper()
    soup = BeautifulSoup(_archive_html(), "lxml")
    return sc._extract_links(soup, "https://soonsal.com/newsletters/")


def test_extract_links_dedups_story_fragments():
    """본문 URL과 #story-1..5 앵커는 같은 호로 취급해 1건만 남긴다."""
    urls = [u for u, _ in _links()]

    assert urls.count("https://soonsal.com/newsletters/2026/0818.html") == 1
    assert not any("#story-" in u for u in urls)
    assert len([u for u in urls if "/0818.html" in u]) == 1


def test_extract_links_keeps_crypto_edition_distinct():
    """같은 날짜의 -crypto 별호는 다른 뉴스레터로 유지한다."""
    urls = {u for u, _ in _links()}

    assert "https://soonsal.com/newsletters/2026/0716.html" in urls
    assert "https://soonsal.com/newsletters/2026/0716-crypto.html" in urls


def test_extract_links_uses_main_title_not_story():
    """제목은 목차 스토리가 아니라 호 본문 링크 텍스트를 쓴다."""
    by_url = dict(_links())
    title = by_url["https://soonsal.com/newsletters/2026/0818.html"]
    assert "편의점" in title
    assert "미국 정부" not in title


def test_newsletter_extracts_title_from_same_detail_fetch():
    """상세 페이지를 제목용으로 다시 GET하지 않는다."""
    import re
    from unittest.mock import MagicMock, patch

    from websync.scrapers.newsletter_base import BaseNewsletterScraper

    class _Dummy(BaseNewsletterScraper):
        LINK_PATTERN = re.compile(r"/n/\d+")
        CONTENT_CANDIDATES = ["article"]

    html = """<html><head><title>상세 제목</title></head>
    <body><article>본문 텍스트가 충분히 길어야 컨테이너로 인정됩니다. """ + ("가" * 80) + """</article></body></html>"""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = html
    sc = _Dummy()
    with patch("websync.scrapers.newsletter_base.fetch_url", return_value=resp) as mocked:
        content, title = sc._fetch_detail_page("https://ex.com/n/1", {})
    assert mocked.call_count == 1
    assert "본문 텍스트" in content
    assert title == "상세 제목"
