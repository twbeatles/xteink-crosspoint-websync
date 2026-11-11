"""Velog / Newneek 단위 테스트."""

from websync.scrapers.factory import ScraperFactory
from websync.scrapers.newneek import NewneekScraper
from websync.scrapers.types import SCRAPER_TYPES
from websync.scrapers.velog import VelogScraper


def test_factory_has_velog_and_newneek():
    assert "velog" in SCRAPER_TYPES
    assert "newneek" in SCRAPER_TYPES
    assert isinstance(ScraperFactory.get_scraper("velog"), VelogScraper)
    assert isinstance(ScraperFactory.get_scraper("newneek"), NewneekScraper)


def test_velog_resolve_variants():
    assert VelogScraper.resolve_rss_url("https://velog.io/@foo-bar") == (
        "https://v2.velog.io/rss/@foo-bar"
    )
    assert VelogScraper.resolve_rss_url(
        "https://v2.velog.io/rss/@foo"
    ) == "https://v2.velog.io/rss/@foo"
    assert VelogScraper.resolve_rss_url("https://example.com") is None


def test_newneek_extract_handle():
    sc = NewneekScraper()
    assert sc._extract_handle("https://newneek.co/@newneek") == "newneek"
    assert sc._extract_handle("https://newneek.co/@newneek/article/1") == "newneek"
