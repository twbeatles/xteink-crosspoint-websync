"""페이지 분석 진입점."""
from __future__ import annotations

from typing import Optional

from websync.i18n import t
from websync.scrapers.selector_assistant.feeds import (
    _is_unstable_css_site,
    discover_feeds,
    fingerprint_platform,
)
from websync.scrapers.selector_assistant.html_dom import (
    build_dom_outline,
    fetch_html,
    parse_html,
)
from websync.scrapers.selector_assistant.suggest import (
    build_recommended_site_config,
    suggest_selectors,
)
from websync.scrapers.selector_assistant.types import PageAnalysis
from websync.scrapers.selector_assistant.url_safety import is_private_or_local_url

def _finalize_analysis(analysis: PageAnalysis) -> PageAnalysis:
    notes: list[str] = list(analysis.notes or [])
    platform = analysis.platform
    feeds = analysis.feeds
    sug = analysis.suggestions or {}

    if _is_unstable_css_site(analysis.base_url or analysis.url):
        notes.append(t("selector.note_medium"))

    if platform:
        notes.append(t("selector.note_platform", platform=platform))
        mode = "platform"
    elif feeds:
        notes.append(t("selector.note_rss"))
        mode = "rss"
    else:
        mode = "css"

    meta = sug.get("meta") or {}
    fetch_detail = bool(meta.get("fetch_detail_recommended"))
    if mode == "css" and fetch_detail:
        notes.append(t("selector.note_short_body"))

    if mode == "css" and not (sug.get("item")):
        notes.append(t("selector.note_no_items"))

    analysis.recommend_mode = mode
    analysis.fetch_detail_recommended = fetch_detail
    analysis.notes = notes
    analysis.recommended_site = build_recommended_site_config(analysis)
    return analysis


def analyze_page(
    url: str,
    timeout: int = 15,
    max_outline: int = 400,
    *,
    probe_feeds: bool = True,
) -> PageAnalysis:
    """URL을 불러와 피드·플랫폼·추천 선택자·DOM 아웃라인을 한 번에 반환."""
    try:
        html, final_url, soup = fetch_html(url, timeout=timeout)
    except Exception as e:
        return PageAnalysis(url=url, base_url=url, error=t("selector.load_failed", error=e))

    page_title = ""
    if soup.title and soup.title.string:
        page_title = soup.title.string.strip()

    # 짧은 SPA 셸 감지
    notes_pre: list[str] = []
    if len(html) < 8000 and not soup.select("article, .post, .post-item, h2 a"):
        notes_pre.append(t("selector.note_spa"))

    feeds = discover_feeds(
        soup,
        final_url,
        probe_paths=probe_feeds,
        timeout=min(4, timeout),
        probe_budget_sec=8.0,
        max_probes=5,
    )
    if is_private_or_local_url(final_url):
        notes_pre.append(t("selector.note_private"))
    analysis = PageAnalysis(
        url=url,
        base_url=final_url,
        title=page_title,
        feeds=feeds,
        platform=fingerprint_platform(final_url, soup),
        suggestions=suggest_selectors(soup),
        outline=build_dom_outline(soup, max_nodes=max_outline),
        html=html,
        notes=notes_pre,
    )
    return _finalize_analysis(analysis)


def analyze_html(html: str, base_url: str = "https://example.com/") -> PageAnalysis:
    """이미 가진 HTML 문자열 분석 (단위 테스트·오프라인용)."""
    soup = parse_html(html, base_url)
    page_title = ""
    if soup.title and soup.title.string:
        page_title = soup.title.string.strip()
    analysis = PageAnalysis(
        url=base_url,
        base_url=base_url,
        title=page_title,
        feeds=discover_feeds(soup, base_url, probe_paths=False),
        platform=fingerprint_platform(base_url, soup),
        suggestions=suggest_selectors(soup),
        outline=build_dom_outline(soup),
        html=html,
    )
    return _finalize_analysis(analysis)


def preview_css_scrape(site_config: dict, html: Optional[str] = None) -> list[dict]:
    """폼 스냅샷으로 CssSelectorScraper 미리보기."""
    from websync.scrapers.css import CssSelectorScraper

    scraper = CssSelectorScraper()
    cfg = dict(site_config)
    try:
        lim = int(cfg.get("limit", 3))
    except (TypeError, ValueError):
        lim = 3
    cfg["limit"] = max(1, min(lim, 5))
    return scraper.fetch_articles(cfg)
