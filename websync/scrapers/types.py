"""스크래퍼 타입 상수 — factory / validator / GUI 공유."""

# GUI 콤보박스 표시 순서
SCRAPER_TYPES: tuple[str, ...] = (
    "css",
    "rss",
    "velog",
    "naver",
    "tistory",
    "brunch",
    "newneek",
    "youtube",
    "substack",
    "naver_cafe",
    "naver_post",
    "soonsal",
    "moneyletter",
)

# CSS 선택자가 필요 없는 전용 타입 (폼 필드 비활성)
SPECIALIZED_TYPES: frozenset[str] = frozenset(t for t in SCRAPER_TYPES if t != "css")
