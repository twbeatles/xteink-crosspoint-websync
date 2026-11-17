"""PROJECT_AUDIT 개선 항목 회귀 테스트."""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from websync.scrapers.css import CssSelectorScraper, _reparse_fragment
from websync.scrapers.selector_assistant import (
    analyze_html,
    is_private_or_local_url,
)


def test_is_private_or_local_url():
    assert is_private_or_local_url("http://localhost/blog") is True
    assert is_private_or_local_url("http://127.0.0.1/") is True
    assert is_private_or_local_url("http://192.168.1.10/x") is True
    assert is_private_or_local_url("http://10.0.0.5/") is True
    assert is_private_or_local_url("https://example.com/blog") is False


def test_reparse_fragment_isolates_decompose():
    soup = BeautifulSoup(
        "<div class='item'><p class='keep'>본문</p><span class='ad'>광고</span></div>",
        "html.parser",
    )
    item = soup.select_one(".item")
    frag = _reparse_fragment(item)
    assert frag is not None
    for ad in frag.select(".ad"):
        ad.decompose()
    # 원본은 유지
    assert soup.select_one(".ad") is not None
    assert frag.select_one(".ad") is None
    assert "본문" in frag.get_text()


def test_list_content_fallback_flag(monkeypatch):
    import websync.scrapers.css as css_mod

    html = """
    <html><body>
      <div class="post-item"><h2 class="t"><a href="/1">제목 하나 충분히 길게</a></h2><div class="x">요약</div></div>
      <div class="post-item"><h2 class="t"><a href="/2">제목 둘 충분히 길게</a></h2><div class="x">요약2</div></div>
    </body></html>
    """

    class FakeResp:
        status_code = 200
        encoding = "utf-8"
        text = html
        url = "https://example.com/"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(css_mod, "fetch_url", lambda *a, **k: FakeResp())
    scraper = CssSelectorScraper()
    arts = scraper.fetch_articles(
        {
            "url": "https://example.com/",
            "item_selector": ".post-item",
            "title_selector": "h2",
            "link_selector": "a",
            "content_selector": ".missing-body",
            "limit": 2,
            "fetch_detail_page": False,
        }
    )
    assert len(arts) == 2
    assert scraper.last_fetch_stats.get("content_fallback_count") == 2
    assert arts[0].get("_content_fallback") is True


def test_empty_item_selector_raises(monkeypatch):
    import websync.scrapers.css as css_mod

    class FakeResp:
        status_code = 200
        encoding = "utf-8"
        text = "<html></html>"
        url = "https://example.com/"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(css_mod, "fetch_url", lambda *a, **k: FakeResp())
    with pytest.raises(Exception, match="item_selector"):
        CssSelectorScraper().fetch_articles(
            {
                "url": "https://example.com/",
                "item_selector": "  ",
                "title_selector": "h2",
                "content_selector": "p",
                "limit": 1,
            }
        )


def test_anchor_item_contract(monkeypatch):
    """아이템이 a 태그일 때 제목/링크 폴백으로 수집."""
    import websync.scrapers.css as css_mod

    html = """
    <html><body>
      <a class="card" href="/posts/1">긴 제목의 첫 번째 글입니다 하나</a>
      <a class="card" href="/posts/2">긴 제목의 두 번째 글입니다 둘</a>
    </body></html>
    """

    class FakeResp:
        status_code = 200
        encoding = "utf-8"
        text = html
        url = "https://example.com/"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(css_mod, "fetch_url", lambda *a, **k: FakeResp())
    arts = CssSelectorScraper().fetch_articles(
        {
            "url": "https://example.com/",
            "item_selector": "a.card",
            "title_selector": ".nope",
            "link_selector": "a[href]",
            "content_selector": ".nope",
            "limit": 2,
        }
    )
    assert len(arts) == 2
    assert "첫 번째" in arts[0]["title"]
    assert "/posts/1" in arts[0]["url"]


def test_spec_hiddenimports_selector_modules():
    spec = Path(__file__).resolve().parents[1] / "x3_websync.spec"
    text = spec.read_text(encoding="utf-8")
    assert "websync.scrapers.selector_assistant" in text
    assert "websync.gui.sync_tab.selector_wizard" in text
    assert "websync.gui.settings_tab.updater" in text


def test_analyze_html_notes_private_not_forced():
    """오프라인 analyze_html 은 probe 없이 동작."""
    html = """
    <html><head><title>t</title>
    <link rel="alternate" type="application/rss+xml" href="/feed.xml"/>
    </head><body>
    <article class="post-item"><h2 class="post-title"><a href="/1">긴 제목 테스트 하나</a></h2>
    <div class="post-content"><p>본문</p></div></article>
    <article class="post-item"><h2 class="post-title"><a href="/2">긴 제목 테스트 둘</a></h2>
    <div class="post-content"><p>본문2</p></div></article>
    </body></html>
    """
    a = analyze_html(html, "https://example.com/")
    assert not a.error
    assert a.feeds
