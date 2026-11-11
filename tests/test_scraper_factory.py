import pytest

from websync.scrapers.factory import ScraperFactory
from websync.scrapers.types import SCRAPER_TYPES


def test_get_scraper_known_types():
    for t in SCRAPER_TYPES:
        scraper = ScraperFactory.get_scraper(t)
        assert scraper is not None


def test_get_scraper_unknown_raises():
    with pytest.raises(ValueError, match="지원하지 않는"):
        ScraperFactory.get_scraper("unknown_type")


def test_list_types_matches_supported():
    assert ScraperFactory.list_types() == list(SCRAPER_TYPES)
