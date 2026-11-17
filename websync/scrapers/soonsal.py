"""SoonsalScraper — 순살브리핑(soonsal.com) 뉴스레터 전용 스크래퍼

BaseNewsletterScraper를 상속받아 구현.
이렇게 하면 동일한 '목록 → 상세' 패턴의 다른 뉴스레터 사이트도
매우 적은 코드로 추가할 수 있습니다.
"""

import re

from bs4 import BeautifulSoup

from websync.scrapers.newsletter_base import BaseNewsletterScraper


class SoonsalScraper(BaseNewsletterScraper):
    """순살브리핑(soonsal.com) 전용 구현.

    사용 예:
        {
          "name": "순살브리핑",
          "type": "soonsal",
          "url": "https://soonsal.com/newsletters/",
          "limit": 2
        }
    """

    LINK_PATTERN = re.compile(r"/newsletters/\d{4}/\d{4}(-[a-zA-Z0-9]+)?\.html")

    CONTENT_CANDIDATES = [
        "div.content",
        "div.word-section",
        "div.wrapper",
        "article",
        "main",
        "body",
    ]

    def _clean_content(self, container: BeautifulSoup, site_config: dict) -> None:
        """soonsal.com 특화 추가 정제."""
        super()._clean_content(container, site_config)

        # 홈으로 가는 링크나 하단 카피라이트 제거
        for el in container.select("a[href='/'], a[href='https://soonsal.com']"):
            txt = el.get_text(strip=True)
            if "홈" in txt or "soonsal" in txt.lower() or len(txt) < 12:
                el.decompose()

        # 기타 불필요 (구독 유도 등)
        for sel in [".subscribe", ".footer", "aside"]:
            for bad in container.select(sel):
                bad.decompose()
