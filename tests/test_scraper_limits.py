"""ISSUE-005: limit clamp 회귀 테스트."""
from unittest.mock import MagicMock, patch

from websync.scrapers.base import LIMIT_MAX, LIMIT_MIN, normalize_limit
from websync.scrapers.css import CssSelectorScraper
from websync.scrapers.rss import RssScraper


def test_normalize_limit_clamps_and_defaults():
    assert normalize_limit(-1) == LIMIT_MIN
    assert normalize_limit(0) == LIMIT_MIN
    assert normalize_limit(101) == LIMIT_MAX
    assert normalize_limit(1000) == LIMIT_MAX
    assert normalize_limit("abc") == 5
    assert normalize_limit(None) == 5
    assert normalize_limit("7") == 7
    assert normalize_limit(7) == 7
    assert normalize_limit(3, default=3) == 3
    assert normalize_limit("xx", default=3) == 3


def _css_resp(items=3):
    html = "<html><body>" + "".join(
        '<div class="post-item">'
        f'<h2 class="post-title">제목{i}</h2>'
        f'<a href="https://ex.com/{i}">link</a>'
        f'<div class="post-content"><p>본문{i}</p></div>'
        "</div>"
        for i in range(items)
    ) + "</body></html>"
    resp = MagicMock()
    resp.text = html
    resp.encoding = "utf-8"
    resp.raise_for_status = MagicMock()
    return resp


def _css_config(limit):
    return {
        "url": "https://ex.com/blog",
        "item_selector": ".post-item",
        "title_selector": ".post-title",
        "content_selector": ".post-content",
        "link_selector": "a[href]",
        "remove_selectors": "",
        "limit": limit,
        "fetch_detail_page": False,
        "include_images": False,
    }


def test_css_clamps_negative_limit_to_minimum():
    with patch(
        "websync.scrapers.css.fetch_url", return_value=_css_resp()
    ):
        arts = CssSelectorScraper().fetch_articles(_css_config(-1))
    assert len(arts) == LIMIT_MIN


def test_css_falls_back_to_default_on_garbage_limit():
    with patch(
        "websync.scrapers.css.fetch_url", return_value=_css_resp()
    ):
        arts = CssSelectorScraper().fetch_articles(_css_config("abc"))
    assert len(arts) == 3


def _rss_resp(items=3):
    xml = '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
    for i in range(items):
        xml += (
            "<item>"
            f"<title>뉴스 제목 {i}</title>"
            f"<link>https://ex.com/rss/{i}</link>"
            f"<description>요약 {i} 본문 내용입니다</description>"
            "</item>"
        )
    xml += "</channel></rss>"
    resp = MagicMock()
    resp.content = xml.encode("utf-8")
    resp.encoding = "utf-8"
    resp.apparent_encoding = "utf-8"
    resp.raise_for_status = MagicMock()
    return resp


def test_rss_clamps_zero_limit_to_minimum():
    with patch("websync.scrapers.rss.fetch_url", return_value=_rss_resp()):
        arts = RssScraper().fetch_articles(
            {"url": "https://ex.com/rss", "limit": 0, "include_images": False}
        )
    assert len(arts) == LIMIT_MIN


def test_rss_falls_back_to_default_on_garbage_limit():
    with patch("websync.scrapers.rss.fetch_url", return_value=_rss_resp()):
        arts = RssScraper().fetch_articles(
            {"url": "https://ex.com/rss", "limit": "bad", "include_images": False}
        )
    assert len(arts) == 3
