"""픽스처 기반 스크래퍼 회귀 테스트 (네트워크 불필요)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from websync.scrapers.brunch import BrunchScraper
from websync.scrapers.newneek import NewneekScraper
from websync.scrapers.rss import RssScraper
from websync.scrapers.velog import VelogScraper

FIXTURES = Path(__file__).parent / "fixtures" / "scrapers"


def _resp(text: str = "", content: bytes | None = None, json_data=None):
    m = MagicMock()
    m.raise_for_status = MagicMock()
    m.text = text
    m.content = content if content is not None else text.encode("utf-8")
    m.encoding = "utf-8"
    m.apparent_encoding = "utf-8"
    if json_data is not None:
        m.json.return_value = json_data
    return m


def test_brunch_fixture_api_and_html():
    import json

    api = json.loads(
        (FIXTURES / "brunch" / "list_api.json").read_text(encoding="utf-8")
    )
    html = (FIXTURES / "brunch" / "article_101.html").read_text(encoding="utf-8")

    def fake_fetch(url, **kwargs):
        if "api.brunch.co.kr" in url:
            return _resp(json_data=api)
        return _resp(text=html)

    with patch("websync.scrapers.brunch.fetch_url", side_effect=fake_fetch):
        arts = BrunchScraper().fetch_articles(
            {"url": "https://brunch.co.kr/@brunch", "limit": 1}
        )
    assert len(arts) == 1
    assert "픽스처 브런치" in arts[0]["title"]
    assert "e-ink" in arts[0]["content"] or "본문" in arts[0]["content"]


def test_newneek_fixture_sitemap_and_article():
    sm = (FIXTURES / "newneek" / "news_sitemap.xml").read_text(encoding="utf-8")
    page = (FIXTURES / "newneek" / "article_page.html").read_text(encoding="utf-8")

    def fake_fetch(url, **kwargs):
        if "sitemap" in url:
            return _resp(text=sm, content=sm.encode("utf-8"))
        return _resp(text=page)

    with patch("websync.scrapers.newneek.fetch_url", side_effect=fake_fetch):
        arts = NewneekScraper().fetch_articles(
            {"url": "https://newneek.co/@newneek", "limit": 1}
        )
    assert len(arts) == 1
    assert "픽스처 뉴닉" in arts[0]["title"]
    assert "시사 뉴스" in arts[0]["content"]


def test_velog_resolves_username_and_reads_rss():
    feed = (FIXTURES / "velog" / "feed.xml").read_bytes()
    assert VelogScraper.resolve_rss_url("https://velog.io/@velopert") == (
        "https://v2.velog.io/rss/@velopert"
    )

    def fake_fetch(url, **kwargs):
        return _resp(content=feed, text=feed.decode("utf-8"))

    with patch("websync.scrapers.rss.fetch_url", side_effect=fake_fetch):
        arts = VelogScraper().fetch_articles(
            {"url": "https://velog.io/@velopert", "limit": 1}
        )
    assert len(arts) == 1
    assert "Velog 픽스처" in arts[0]["title"]
    assert "본문" in arts[0]["content"]


def test_rss_hani_fixture_encoding_and_image_only_fallback():
    raw = (FIXTURES / "rss" / "hani_sample.xml").read_bytes()

    def fake_fetch(url, **kwargs):
        m = _resp(content=raw)
        m.encoding = "ISO-8859-1"
        return m

    with patch("websync.scrapers.rss.fetch_url", side_effect=fake_fetch):
        arts = RssScraper().fetch_articles(
            {"url": "https://www.hani.co.kr/rss/", "limit": 1, "include_images": False}
        )
    assert len(arts) == 1
    assert "한겨레" in arts[0]["title"]
    body = arts[0]["content"]
    assert "원문 링크" in body or "RSS 피드" in body
    from bs4 import BeautifulSoup as BS

    assert len(BS(body, "lxml").get_text(" ", strip=True)) >= 80


def test_presets_include_korean_sources():
    from websync.scrapers.presets import KOREAN_SITE_PRESETS, get_preset_by_label

    labels = [p.get("label") or "" for p in KOREAN_SITE_PRESETS]
    assert any("Velog" in x for x in labels)
    assert any("뉴닉" in x for x in labels)
    p = get_preset_by_label("뉴닉 (공식)")
    assert p is not None
    assert p.get("type") == "newneek"
