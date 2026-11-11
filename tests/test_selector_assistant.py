"""selector_assistant 단위 테스트 (네트워크 없음)."""
from pathlib import Path

import pytest

from websync.scrapers.css import CssSelectorScraper
from websync.scrapers.selector_assistant import (
    analyze_html,
    css_path,
    discover_feeds,
    evaluate_selector,
    fingerprint_platform,
    parse_html,
    suggest_selectors,
)

FIXTURE = Path(__file__).parent / "fixtures" / "scrapers" / "css" / "list_page.html"


@pytest.fixture
def list_html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def list_soup(list_html):
    return parse_html(list_html)


def test_discover_feeds(list_soup):
    feeds = discover_feeds(list_soup, "https://blog.example.com/")
    assert feeds
    assert any("feed.xml" in f.url for f in feeds)
    assert feeds[0].url.startswith("https://")


def test_evaluate_selector_counts(list_soup):
    r = evaluate_selector(list_soup, ".post-item")
    assert r.error == ""
    assert r.count == 3
    assert len(r.samples) == 3
    assert "첫 번째" in r.samples[0].text


def test_evaluate_selector_invalid():
    soup = parse_html("<html><body><p>x</p></body></html>")
    r = evaluate_selector(soup, "[[[")
    assert r.count == 0
    assert r.error


def test_suggest_selectors_finds_items(list_soup):
    sug = suggest_selectors(list_soup)
    assert sug["item"]
    top = sug["item"][0]["selector"]
    # post-item 또는 li 계열
    assert "post" in top or top in ("li", "article", "ul li") or "item" in top


def test_analyze_html_offline(list_html):
    analysis = analyze_html(list_html, "https://blog.example.com/blog")
    assert not analysis.error
    assert analysis.title == "예제 블로그"
    assert analysis.feeds
    assert analysis.outline
    assert analysis.suggestions.get("item")


def test_fingerprint_platform():
    assert fingerprint_platform("https://blog.naver.com/someone") == "naver"
    assert fingerprint_platform("https://foo.tistory.com/") == "tistory"
    assert fingerprint_platform("https://velog.io/@user") == "velog"
    assert fingerprint_platform("https://random.example.com/blog") is None


def test_css_path_with_id():
    soup = parse_html('<div id="main"><p class="x">hi</p></div>')
    p = soup.select_one("p")
    path = css_path(p)
    assert "p" in path
    main = soup.select_one("#main")
    assert css_path(main) == "#main" or css_path(main).endswith("#main")


def test_css_scraper_link_selector(list_html, monkeypatch):
    """link_selector 로 상세 URL 추출."""
    import websync.scrapers.css as css_mod

    class FakeResp:
        status_code = 200
        encoding = "utf-8"
        text = list_html
        url = "https://blog.example.com/"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(css_mod, "fetch_url", lambda *a, **k: FakeResp())

    scraper = CssSelectorScraper()
    arts = scraper.fetch_articles(
        {
            "url": "https://blog.example.com/",
            "item_selector": ".post-item",
            "title_selector": ".post-title",
            "link_selector": "h2 a",
            "content_selector": ".post-content",
            "limit": 3,
            "fetch_detail_page": False,
        }
    )
    assert len(arts) == 3
    assert arts[0]["title"] == "첫 번째 글"
    assert arts[0]["url"].endswith("/posts/1") or "/posts/1" in arts[0]["url"]


def test_css_scraper_default_link_selector_compat(list_html, monkeypatch):
    """link_selector 미지정 시 기존 a[href] 동작."""
    import websync.scrapers.css as css_mod

    class FakeResp:
        status_code = 200
        encoding = "utf-8"
        text = list_html
        url = "https://blog.example.com/"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(css_mod, "fetch_url", lambda *a, **k: FakeResp())
    arts = CssSelectorScraper().fetch_articles(
        {
            "url": "https://blog.example.com/",
            "item_selector": "li.post-item",
            "title_selector": "h2",
            "content_selector": ".post-content",
            "limit": 2,
        }
    )
    assert len(arts) == 2
    assert "posts/" in arts[0]["url"]
