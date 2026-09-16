"""선택자 도우미 상수 (정규식·경로·감점 사전)."""
from __future__ import annotations

import re

# 해시·프레임워크 임시 class 는 선택자 생성에서 제외
_UNSTABLE_CLASS = re.compile(
    r"^(css|scss|jsx|emotion|ember|svelte|ng|v|_|js|is|has)[-_]"
    r"|[-_][a-f0-9]{5,}$"
    r"|^[a-z]{1,2}\d{3,}$"
    r"|^(firstpaint|lazyload|lazy|active|selected|open|closed|hide|hidden|show|visible|invisible|on|off)$",
    re.I,
)
_SKIP_TAGS = frozenset(
    {"script", "style", "noscript", "svg", "path", "meta", "link", "br", "hr", "img", "input", "button"}
)
_NOISE_ANCESTORS = frozenset({"nav", "footer", "aside", "header"})
_FEED_TYPES = (
    "application/rss+xml",
    "application/atom+xml",
    "application/rdf+xml",
    "text/xml",
    "application/xml",
)

# 흔한 피드 경로 (link 태그 없을 때 프로브)
_COMMON_FEED_PATHS = (
    "/rss.xml",
    "/feed",
    "/feed/",
    "/feed.xml",
    "/atom.xml",
    "/index.xml",
    "/rss",
    "/rss/",
)

# 목록 페이지에서 본문이 거의 없을 때 상세 수집 권장
_DETAIL_CONTENT_CANDIDATES = [
    "article .entry-content",
    "article .post-content",
    ".entry-content",
    ".post-content",
    ".article-body",
    ".markdown-body",
    "article",
    "main article",
    "main .content",
    "#content",
    ".tt_article_useless_p_margin",  # 티스토리(전용 타입 권장)
    "div.se-main-container",  # 네이버(전용 타입 권장)
]

# 네비·UI 문구 (아이템 후보 감점)
_NAV_WORDS = frozenset(
    {
        "홈", "home", "menu", "메뉴", "서비스", "공지", "공지사항", "로그인", "로그아웃",
        "sign up", "sign in", "signup", "signin", "채용", "구독", "구독하기", "blog",
        "tags", "tag", "category", "카테고리", "검색", "search", "about", "소개",
        "contact", "문의", "more", "더보기", "prev", "next", "이전", "다음",
        "engineering", "design", "product", "culture", "tech", "개발자 채용",
        "open in app", "sitemap",
    }
)

# 기사 URL 경로 힌트 (한국 기술 블로그 실측)
_ARTICLE_PATH_HINTS = (
    "/article/",
    "/articles/",
    "/blog/",
    "/posts/",
    "/post/",
    "/helloworld",
    "/tech/",
    "/pnc/",
    "/entry/",
    "/archives/",
    "/ko/blog/",
)

# 플랫폼 핑거프린트 (URL 호스트 우선)
_PLATFORM_HOSTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"blog\.naver\.com|m\.blog\.naver\.com|\.blog\.me$", re.I), "naver"),
    (re.compile(r"cafe\.naver\.com", re.I), "naver_cafe"),
    (re.compile(r"\.tistory\.com$", re.I), "tistory"),
    (re.compile(r"brunch\.co\.kr", re.I), "brunch"),
    (re.compile(r"velog\.io", re.I), "velog"),
    (re.compile(r"substack\.com", re.I), "substack"),
    (re.compile(r"youtube\.com|youtu\.be", re.I), "youtube"),
    (re.compile(r"newneek\.co", re.I), "newneek"),
    (re.compile(r"soonsal\.com", re.I), "soonsal"),
    (re.compile(r"uppity\.co\.kr", re.I), "moneyletter"),
]
