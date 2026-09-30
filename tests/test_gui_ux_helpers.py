"""GUI 리팩토링에서 분리한 순수 헬퍼 (tk 창 없이 검증)."""
from __future__ import annotations

from websync.gui.sync_tab.epub_options import parse_font_size, parse_line_height
from websync.gui.sync_tab.preview import html_excerpt
from websync.gui.sync_tab.site_dialog import normalize_site_url, suggest_site_name
from websync.gui.sync_tab.sites import site_type_label
from websync.scrapers.types import SCRAPER_TYPES
from websync.i18n import t


def test_font_size_is_clamped_and_falls_back():
    assert parse_font_size("18") == 18
    assert parse_font_size("17.6") == 17
    assert parse_font_size("4") == 8
    assert parse_font_size("99") == 48
    assert parse_font_size("abc", default=16) == 16
    assert parse_font_size("", default=14) == 14


def test_line_height_is_clamped_and_falls_back():
    assert parse_line_height("1.8") == 1.8
    assert parse_line_height("0.5") == 1.0
    assert parse_line_height("5") == 3.0
    assert parse_line_height("x", default=1.7) == 1.7


def test_normalize_site_url_adds_scheme_and_trims():
    assert normalize_site_url("  news.hada.io/rss ") == "https://news.hada.io/rss"
    assert normalize_site_url("http://a.com") == "http://a.com"
    assert normalize_site_url("") == ""


def test_suggest_site_name_from_url():
    assert suggest_site_name("https://www.example.com/") == "example.com"
    assert suggest_site_name("https://velog.io/@velopert") == "velog.io/@velopert"
    assert suggest_site_name("https://blog.example.com/rss") == "blog.example.com"
    assert suggest_site_name("example.org/feed.xml") == "example.org"
    assert suggest_site_name("") == ""


def test_every_scraper_type_has_label_and_description():
    for site_type in SCRAPER_TYPES:
        assert site_type_label(site_type) != f"gui.site_types.{site_type}"
        desc_key = f"gui.site_types_desc.{site_type}"
        assert t(desc_key) != desc_key


def test_html_excerpt_strips_tags_and_truncates():
    assert html_excerpt("<p>Hello&nbsp;<b>world</b></p>") == "Hello world"
    long = "<p>" + ("a" * 50) + "</p>"
    out = html_excerpt(long, limit=10)
    assert out.startswith("a" * 10) and out.endswith("…")
