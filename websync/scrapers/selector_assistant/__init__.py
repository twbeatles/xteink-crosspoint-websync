"""CSS 선택자 도우미 — 페이지 분석·테스트·추천 (GUI 비의존 순수 로직).

의존성: requests(via fetch_url), beautifulsoup4, lxml 선택.
브라우저 자동화 없음. 정적 HTML만 대상으로 한다.

한국 기술 블로그·워드프레스·Gatsby 등 목록 페이지를 실측 튜닝:
- 메뉴 li / 해시 class / 템플릿 노이즈 감점
- .post-item, 글 링크 경로 패턴 가점
- RSS 경로 프로브 및 fetch_detail_page 권장
"""
from websync.scrapers.selector_assistant.analyze import (
    analyze_html,
    analyze_page,
    preview_css_scrape,
)
from websync.scrapers.selector_assistant.feeds import (
    discover_feeds,
    fingerprint_platform,
)
from websync.scrapers.selector_assistant.html_dom import (
    css_path,
    evaluate_selector,
    parse_html,
)
from websync.scrapers.selector_assistant.suggest import (
    build_recommended_site_config,
    suggest_selectors,
)
from websync.scrapers.selector_assistant.types import (
    DomNode,
    FeedInfo,
    PageAnalysis,
    SelectorSample,
    SelectorTestResult,
)
from websync.scrapers.selector_assistant.url_safety import is_private_or_local_url

__all__ = [
    "DomNode",
    "FeedInfo",
    "PageAnalysis",
    "SelectorSample",
    "SelectorTestResult",
    "analyze_html",
    "analyze_page",
    "build_recommended_site_config",
    "css_path",
    "discover_feeds",
    "evaluate_selector",
    "fingerprint_platform",
    "is_private_or_local_url",
    "parse_html",
    "preview_css_scrape",
    "suggest_selectors",
]
