"""선택자 추천 및 sites[] 설정 생성."""
from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup, Tag

from websync.i18n import t
from websync.scrapers.selector_assistant.constants import (
    _DETAIL_CONTENT_CANDIDATES,
    _SKIP_TAGS,
)
from websync.scrapers.selector_assistant.html_dom import (
    _stable_classes,
    _tag_simple_selector,
    _text_preview,
)
from websync.scrapers.selector_assistant.scoring import (
    _discover_link_path_selectors,
    _score_content_candidate,
    _score_item_candidate,
    _suggest_relative_title_link,
    _best_link_in,
    _title_quality,
)
from websync.scrapers.selector_assistant.types import PageAnalysis

def suggest_selectors(soup: BeautifulSoup, max_per_role: int = 5) -> dict[str, Any]:
    """목록/제목/링크/본문 후보 선택자 제안.

    반환 키: item/title/link/content (list[dict]), meta (dict).
    """
    body = soup.body or soup
    item_candidates: dict[str, list[Tag]] = {}

    # 1) 한국·워드프레스·기술 블로그 시드 (구체적 패턴 우선)
    seed_selectors = [
        ".post-item",
        "li.post-item",
        "article.post",
        "article",
        ".post-card",
        ".blog-post",
        "li.post",
        "div.post",
        ".entry",
        "div.entry",
        ".list-item",
        ".post",
        "[class*='post-item']",
        "[class*='post-card']",
        "li[class*='post']",
        "div[class*='Post']",  # Gatsby/React 대문자 (뱅크샐러드 등)
        "[class*='post']",
        "[class*='entry']",
        "h2 a",
        "h3 a",
        # 광범위 후보는 점수에서 감점
        "li",
        "ul li",
        "[class*='item']",
    ]
    for sel in seed_selectors:
        try:
            ms = [m for m in body.select(sel) if isinstance(m, Tag)]
        except Exception:
            continue
        if len(ms) >= 2:
            item_candidates[sel] = ms

    # 2) 동일 tag+class 반복 패턴
    pattern_counts: dict[str, list[Tag]] = {}
    for tag in body.find_all(True):
        if not isinstance(tag, Tag) or tag.name in _SKIP_TAGS:
            continue
        if tag.name in ("html", "body", "head"):
            continue
        classes = _stable_classes(tag)
        if not classes:
            continue
        key = tag.name + "".join(f".{c}" for c in classes[:2])
        pattern_counts.setdefault(key, []).append(tag)
    for key, ms in pattern_counts.items():
        if 3 <= len(ms) <= 60 and key not in item_candidates:
            item_candidates[key] = ms

    # 3) 기사 URL 경로 기반 a[href*="..."]
    for sel, ms in _discover_link_path_selectors(soup):
        item_candidates[sel] = ms

    scored_items: list[tuple[float, str, list[Tag]]] = []
    for sel, ms in item_candidates.items():
        sc = _score_item_candidate(sel, ms)
        if sc > 8:
            scored_items.append((sc, sel, ms))
    scored_items.sort(key=lambda x: -x[0])

    items_out: list[dict[str, Any]] = []
    for sc, sel, ms in scored_items[:max_per_role]:
        # 샘플은 가장 제목 품질 좋은 것
        best_sample = ""
        best_q = -1.0
        for m in ms[:8]:
            link = _best_link_in(m)
            text = link.get_text(" ", strip=True) if link else _text_preview(m)
            q = _title_quality(text)
            if q > best_q:
                best_q = q
                best_sample = text[:80]
        items_out.append(
            {
                "selector": sel,
                "score": round(sc, 1),
                "count": len(ms),
                "sample": best_sample,
            }
        )

    titles_out: list[dict[str, Any]] = []
    links_out: list[dict[str, Any]] = []
    if scored_items:
        best_sel, best_ms = scored_items[0][1], scored_items[0][2]
        titles_out, links_out = _suggest_relative_title_link(best_ms, best_sel, max_per_role)

    # 본문 후보
    content_out: list[dict[str, Any]] = []
    content_seeds = list(_DETAIL_CONTENT_CANDIDATES) + [
        ".content",
        "div.post",
        "main",
    ]
    scored_c: list[tuple[float, str, Tag]] = []
    for sel in content_seeds:
        try:
            el = body.select_one(sel)
        except Exception:
            el = None
        if el and isinstance(el, Tag):
            sc = _score_content_candidate(el)
            if sc > 5:
                scored_c.append((sc, sel, el))
    for tag in body.find_all(["article", "main", "div"], limit=80):
        if not isinstance(tag, Tag):
            continue
        sc = _score_content_candidate(tag)
        if sc > 25:
            sel = _tag_simple_selector(tag)
            scored_c.append((sc, sel, tag))
    scored_c.sort(key=lambda x: -x[0])
    seen_sel: set[str] = set()
    for sc, sel, el in scored_c:
        if sel in seen_sel:
            continue
        seen_sel.add(sel)
        content_out.append(
            {
                "selector": sel,
                "score": round(sc, 1),
                "count": 1,
                "sample": _text_preview(el, 100),
            }
        )
        if len(content_out) >= max_per_role:
            break

    # 목록 페이지면 본문이 약함 → 상세 후보를 기본값으로 명시
    fetch_detail = False
    if scored_items:
        # 아이템 내부 content 길이 평균
        lens = []
        for m in scored_items[0][2][:8]:
            lens.append(len(m.get_text(" ", strip=True)))
        avg_len = sum(lens) / max(len(lens), 1)
        if avg_len < 400:
            fetch_detail = True
            if not content_out:
                for sel in _DETAIL_CONTENT_CANDIDATES[:4]:
                    content_out.append(
                        {
                            "selector": sel,
                            "score": 5.0,
                            "count": 0,
                            "sample": t("selector.for_detail"),
                            "for_detail": True,
                        }
                    )

    return {
        "item": items_out,
        "title": titles_out,
        "link": links_out,
        "content": content_out,
        "meta": {
            "fetch_detail_recommended": fetch_detail,
        },
    }


def build_recommended_site_config(
    analysis: PageAnalysis,
    *,
    name: str = "",
    limit: int = 5,
) -> dict[str, Any]:
    """분석 결과로 sites[] 에 넣을 설정 딕셔너리 생성."""
    notes = list(analysis.notes)
    if analysis.platform and analysis.platform not in ("rss",):
        return {
            "name": name or analysis.title or "site",
            "type": analysis.platform,
            "url": analysis.url,
            "limit": limit,
            "enabled": True,
            "include_images": False,
            "translate_to": "",
            "fetch_detail_page": False,
            "_recommend_note": t("selector.recommend_platform", platform=analysis.platform),
        }

    # RSS 우선
    primary_feed = None
    for f in analysis.feeds:
        u = f.url.lower()
        if "comment" in u or "oembed" in u:
            continue
        primary_feed = f
        break
    if primary_feed:
        return {
            "name": name or analysis.title or "RSS",
            "type": "rss",
            "url": primary_feed.url,
            "limit": limit,
            "enabled": True,
            "include_images": False,
            "translate_to": "",
            "fetch_detail_page": False,
            "_recommend_note": t("selector.recommend_rss"),
        }

    sug = analysis.suggestions or {}
    item = (sug.get("item") or [{}])[0]
    title = (sug.get("title") or [{}])[0]
    link = (sug.get("link") or [{}])[0]
    content = (sug.get("content") or [{}])[0]
    meta = sug.get("meta") or {}
    fetch_detail = bool(meta.get("fetch_detail_recommended") or analysis.fetch_detail_recommended)

    title_sel = title.get("selector") or "h2"
    if title_sel == ".":
        title_sel = "a"  # css 스크래퍼: 아이템이 a면 자체 폴백 사용
    link_sel = link.get("selector") or "a[href]"
    if link_sel == ".":
        link_sel = "a[href]"
    content_sel = content.get("selector") or ".entry-content"
    if content.get("count") == 0:
        content_sel = content_sel or ".entry-content"
        fetch_detail = True

    cfg = {
        "name": name or analysis.title or "CSS site",
        "type": "css",
        "url": analysis.base_url or analysis.url,
        "item_selector": item.get("selector") or "article",
        "title_selector": title_sel,
        "link_selector": link_sel,
        "content_selector": content_sel,
        "remove_selectors": ".share, .comments, .comment, .related, .ad, .sidebar",
        "limit": limit,
        "enabled": True,
        "include_images": False,
        "translate_to": "",
        "fetch_detail_page": fetch_detail,
        "_recommend_note": (
            t("selector.recommend_detail") if fetch_detail else t("selector.recommend_css")
        ),
    }
    if notes:
        cfg["_notes"] = notes
    return cfg
