"""한국 기술 블로그 픽스처 기반 선택자 추천 회귀 테스트 (네트워크 없음)."""
from pathlib import Path

import pytest

from websync.scrapers.css import CssSelectorScraper
from websync.scrapers.selector_assistant import (
    analyze_html,
    build_recommended_site_config,
    evaluate_selector,
    parse_html,
    suggest_selectors,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "scrapers" / "css"


def _load(name: str) -> str:
    path = FIXTURE_DIR / name
    if not path.exists():
        pytest.skip(f"fixture missing: {name}")
    return path.read_text(encoding="utf-8", errors="replace")


def test_woowahan_prefers_post_item():
    html = _load("woowahan_list.html")
    soup = parse_html(html)
    sug = suggest_selectors(soup)
    items = sug.get("item") or []
    assert items, "우아한형제들 목록 아이템 추천이 비어 있음"
    top = items[0]["selector"]
    # .post-item 이 상위에 와야 함 (광범위 li / [class*='item'] 보다)
    assert "post-item" in top or top in ("li.post-item", ".post-item")
    assert items[0]["count"] >= 5
    # 샘플 제목이 메뉴 단어가 아니어야 함
    sample = (items[0].get("sample") or "").lower()
    assert "구독" not in sample
    assert len(sample) >= 8


def test_woowahan_analyze_recommends_rss():
    html = _load("woowahan_list.html")
    analysis = analyze_html(html, "https://techblog.woowahan.com/")
    assert analysis.feeds, "feed link 가 픽스처에 있어야 함"
    rec = build_recommended_site_config(analysis)
    assert rec["type"] == "rss"
    assert "feed" in rec["url"].lower() or "rss" in rec["url"].lower()
    assert analysis.recommend_mode == "rss"


def test_line_blog_item_quality():
    html = _load("line_list.html")
    soup = parse_html(html)
    sug = suggest_selectors(soup)
    items = sug.get("item") or []
    assert items
    # post 관련 또는 h2 a / 링크 패턴
    top = items[0]["selector"]
    joined = " ".join(i["selector"] for i in items[:3])
    assert (
        "post" in joined
        or "blog" in joined
        or "h2" in top
        or "href" in joined
    )
    r = evaluate_selector(soup, items[0]["selector"])
    assert r.count >= 3


def test_banksalad_has_article_titles():
    html = _load("banksalad_list.html")
    soup = parse_html(html)
    sug = suggest_selectors(soup)
    items = sug.get("item") or []
    assert items
    # 상위 추천 샘플에 한글 제목 성격
    samples = " ".join((i.get("sample") or "") for i in items[:3])
    assert any("\uac00" <= ch <= "\ud7a3" for ch in samples)  # hangul


def test_toss_article_path_or_rss():
    html = _load("toss_list.html")
    analysis = analyze_html(html, "https://toss.tech/")
    # RSS link 가 있으면 rss 모드
    if analysis.feeds:
        rec = analysis.recommended_site
        assert rec.get("type") == "rss"
    else:
        sug = analysis.suggestions or {}
        items = sug.get("item") or []
        assert items
        # /article/ 패턴 또는 의미 있는 아이템
        top_sels = [i["selector"] for i in items[:4]]
        assert any("article" in s or "href" in s or "post" in s for s in top_sels)


def test_css_scraper_title_fallback_on_anchor_item(monkeypatch):
    """아이템이 a 태그일 때 제목·링크 폴백."""
    import websync.scrapers.css as css_mod

    html = """
    <html><body>
      <a class="card" href="/posts/1">긴 제목의 첫 번째 글입니다</a>
      <a class="card" href="/posts/2">긴 제목의 두 번째 글입니다</a>
      <a class="card" href="/posts/3">긴 제목의 세 번째 글입니다</a>
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
            "title_selector": ".missing",
            "link_selector": "a[href]",
            "content_selector": ".missing",
            "limit": 3,
            "fetch_detail_page": False,
        }
    )
    assert len(arts) == 3
    assert "첫 번째" in arts[0]["title"]
    assert "/posts/1" in arts[0]["url"]


def test_simple_list_fixture_still_works():
    html = (FIXTURE_DIR / "list_page.html").read_text(encoding="utf-8")
    analysis = analyze_html(html, "https://blog.example.com/")
    assert analysis.feeds
    sug = analysis.suggestions
    assert sug["item"]
    # RSS 우선 추천
    rec = analysis.recommended_site
    assert rec["type"] == "rss"
