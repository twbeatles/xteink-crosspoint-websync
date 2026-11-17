"""네이버 스크래퍼 공통 유틸리티"""

from websync.core.logger import get_logger

logger = get_logger()


def clean_naver_content(container) -> None:
    """
    네이버 콘텐츠에서 불필요 요소를 제거하고 인라인 스타일/클래스를 삭제합니다.
    NaverBlogScraper, NaverCafeScraper, NaverPostScraper에서 공통으로 사용.
    """
    # 네이버 고유 불필요 요소 제거
    remove_selectors = [
        "div.se-module-oglink",
        "div.se-sticker",
        "div.se-module-map",
        "div.se-module-schedule",
        "div.se-module-material",
        "script",
        "style",
        "iframe",
    ]
    for sel in remove_selectors:
        for el in container.select(sel):
            el.decompose()

    # 모든 style, class 속성 강제 삭제 (배경색/글자색 초기화)
    for tag in container.find_all(True):
        if tag.attrs:
            tag.attrs = {
                k: v for k, v in tag.attrs.items() if k not in ("style", "class")
            }
