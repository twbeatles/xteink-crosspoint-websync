from unittest.mock import patch

import pytest

from websync.scrapers.brunch import BrunchScraper
from websync.scrapers.substack import SubstackScraper
from websync.scrapers.tistory import TistoryScraper
from websync.scrapers.youtube import YoutubeScraper


@pytest.mark.parametrize(
    "scraper_cls,site_config,module_path",
    [
        (YoutubeScraper, {"url": "https://youtube.com/feeds/videos.xml?channel_id=x", "limit": 1}, "websync.scrapers.youtube"),
        (TistoryScraper, {"url": "https://example.tistory.com", "limit": 1}, "websync.scrapers.tistory"),
        (BrunchScraper, {"url": "https://brunch.co.kr/@author", "limit": 1}, "websync.scrapers.brunch"),
        (SubstackScraper, {"url": "https://example.substack.com", "limit": 1}, "websync.scrapers.substack"),
    ],
)
def test_scraper_raises_on_network_failure(scraper_cls, site_config, module_path):
    scraper = scraper_cls()
    # 각 스크래퍼 모듈이 import한 fetch_url을 직접 패치
    with patch(f"{module_path}.fetch_url", side_effect=ConnectionError("offline")):
        with pytest.raises(Exception):  # noqa: B017 -- intentional common denominator: brunch wraps network errors into generic Exception (brunch.py:100), others propagate; no single narrower type covers all 4 parametrized scrapers
            scraper.fetch_articles(site_config)