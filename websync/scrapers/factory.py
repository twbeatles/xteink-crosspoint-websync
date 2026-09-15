"""스크래퍼 팩토리"""
from websync.scrapers.base import BaseScraper
from websync.scrapers.css import CssSelectorScraper
from websync.scrapers.rss import RssScraper
from websync.scrapers.naver import NaverBlogScraper
from websync.scrapers.tistory import TistoryScraper
from websync.scrapers.brunch import BrunchScraper
from websync.scrapers.youtube import YoutubeScraper
from websync.scrapers.substack import SubstackScraper
from websync.scrapers.naver_cafe import NaverCafeScraper
from websync.scrapers.naver_post import NaverPostScraper
from websync.scrapers.soonsal import SoonsalScraper
from websync.scrapers.moneyletter import MoneyLetterScraper
from websync.scrapers.velog import VelogScraper
from websync.scrapers.newneek import NewneekScraper
from websync.scrapers.types import SCRAPER_TYPES
from websync.i18n import t


class ScraperFactory:
    _scrapers = {
        "css": CssSelectorScraper(),
        "rss": RssScraper(),
        "velog": VelogScraper(),
        "naver": NaverBlogScraper(),
        "tistory": TistoryScraper(),
        "brunch": BrunchScraper(),
        "newneek": NewneekScraper(),
        "youtube": YoutubeScraper(),
        "substack": SubstackScraper(),
        "naver_cafe": NaverCafeScraper(),
        "naver_post": NaverPostScraper(),
        "soonsal": SoonsalScraper(),
        "moneyletter": MoneyLetterScraper(),
    }

    SUPPORTED_TYPES = SCRAPER_TYPES

    @classmethod
    def get_scraper(cls, scraper_type: str) -> BaseScraper:
        scraper = cls._scrapers.get(scraper_type.lower())
        if not scraper:
            raise ValueError(t("factory.unsupported", type=scraper_type))
        return scraper

    @classmethod
    def register_scraper(cls, scraper_type: str, scraper: BaseScraper):
        cls._scrapers[scraper_type.lower()] = scraper

    @classmethod
    def list_types(cls) -> list[str]:
        return list(SCRAPER_TYPES)
