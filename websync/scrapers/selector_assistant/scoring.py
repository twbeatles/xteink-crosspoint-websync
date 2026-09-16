"""아이템·제목·링크·본문 후보 점수."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from websync.i18n import t
from websync.scrapers.selector_assistant.constants import (
    _ARTICLE_PATH_HINTS,
    _NAV_WORDS,
    _NOISE_ANCESTORS,
)
from websync.scrapers.selector_assistant.html_dom import (
    _stable_classes,
    _text_preview,
)

def _in_noise_section(tag: Tag) -> bool:
    for p in tag.parents:
        if isinstance(p, Tag) and p.name in _NOISE_ANCESTORS:
            return True
        if isinstance(p, Tag):
            cls = " ".join(_stable_classes(p)).lower()
            pid = (p.get("id") or "").lower()
            for bad in ("nav", "menu", "sidebar", "footer", "header", "gnb", "lnb", "breadcrumb"):
                if bad in cls or bad in pid:
                    return True
    return False


def _is_nav_label(text: str) -> bool:
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not t:
        return True
    if t in _NAV_WORDS:
        return True
    # 너무 짧은 메뉴성
    if len(t) <= 4 and not re.search(r"[가-힣]{2,}", t):
        return True
    return False


def _title_quality(text: str) -> float:
    """기사 제목 가능성 점수 0~1."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t or "{{" in t or "}}" in t:
        return 0.0
    if _is_nav_label(t):
        return 0.05
    score = 0.0
    n = len(t)
    if n >= 18:
        score += 0.45
    elif n >= 10:
        score += 0.25
    elif n >= 6:
        score += 0.1
    else:
        return 0.05
    hangul = len(re.findall(r"[가-힣]", t))
    if hangul >= 4:
        score += 0.25
    if re.search(r"[.!?…:：\-–—]|feat\.|feat ", t, re.I):
        score += 0.1
    # 날짜만 있는 텍스트 감점
    if re.fullmatch(r"[\d.\-/\s]+", t):
        score *= 0.1
    return min(score, 1.0)


def _href_article_score(href: str) -> float:
    if not href or href.startswith("#") or href.startswith("javascript:"):
        return 0.0
    low = href.lower()
    if any(x in low for x in ("/tag", "/category", "/author", "/page/", "notice", "login", "signup")):
        return 0.1
    score = 0.2
    for hint in _ARTICLE_PATH_HINTS:
        if hint in low:
            score += 0.5
            break
    # 숫자 id 글 (워드프레스 등 /26507/)
    if re.search(r"/\d{3,}/?$", low.split("?")[0]):
        score += 0.35
    # slug 깊이
    path = urlparse(href if "://" in href else "http://x" + href).path
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        score += 0.15
    return min(score, 1.0)


def _best_link_in(tag: Tag) -> Optional[Tag]:
    best: Optional[Tag] = None
    best_s = -1.0
    candidates = []
    if tag.name == "a" and tag.get("href"):
        candidates.append(tag)
    candidates.extend(tag.select("a[href]")[:12])
    for a in candidates:
        if not isinstance(a, Tag):
            continue
        href = a.get("href") or ""
        text = a.get_text(" ", strip=True)
        s = _href_article_score(href) * 0.6 + _title_quality(text) * 0.4
        if s > best_s:
            best_s = s
            best = a
    return best


def _score_item_candidate(selector: str, matches: list[Tag]) -> float:
    n = len(matches)
    if n < 2:
        return 0.0
    if n > 100:
        return 0.0

    sample = matches[:12]
    score = 0.0

    # 개수 대역 (글 목록 3~40 이상적)
    if 3 <= n <= 40:
        score += 20
    elif n <= 60:
        score += 10
    else:
        score += 2

    # 선택자 품질
    if selector in ("li", "ul li", "ol li", "h2", "h3", "a"):
        score -= 18  # 너무 광범위
    if selector.startswith("[class*="):
        score -= 8  # 속성 부분일치 — 노이즈 많음
    if ".post-item" in selector or selector.endswith("post-item") or "post-item" in selector:
        score += 18
    if any(k in selector for k in (".post", ".entry", "article", "post-card", "blog-post")):
        score += 10
    if "href*=" in selector or "href*=" in selector:
        score += 12

    qualities: list[float] = []
    href_scores: list[float] = []
    noise = 0
    template = 0
    for m in sample:
        text = _text_preview(m, 200)
        if "{{" in text or "}}" in text:
            template += 1
        if _in_noise_section(m):
            noise += 1
        # 아이템 안 최장 의미 텍스트 (제목 후보)
        link = _best_link_in(m)
        if link is not None:
            t = link.get_text(" ", strip=True)
            qualities.append(_title_quality(t))
            href_scores.append(_href_article_score(link.get("href") or ""))
        else:
            qualities.append(_title_quality(text) * 0.5)
            href_scores.append(0.0)

    avg_q = sum(qualities) / max(len(qualities), 1)
    avg_h = sum(href_scores) / max(len(href_scores), 1)
    score += avg_q * 45
    score += avg_h * 30
    score -= (noise / len(sample)) * 35
    score -= (template / len(sample)) * 50

    # 동일 텍스트 반복(메뉴) 감점
    texts = [re.sub(r"\s+", " ", _text_preview(m, 40)).lower() for m in sample]
    if texts and len(set(texts)) <= max(1, len(texts) // 4):
        score -= 20

    return score


def _score_content_candidate(tag: Tag) -> float:
    text = " ".join(tag.stripped_strings)
    text_len = len(text)
    if text_len < 80:
        return 0.0
    score = min(text_len / 50.0, 40.0)
    p_count = len(tag.find_all("p"))
    score += min(p_count * 3, 30)
    if tag.name in ("article", "main"):
        score += 15
    classes = " ".join(_stable_classes(tag)).lower()
    for bad in ("comment", "sidebar", "related", "share", "footer", "nav", "ad", "menu"):
        if bad in classes or bad in (tag.get("id") or "").lower():
            score -= 20
    for good in ("content", "entry", "post", "article", "markdown", "body", "tt_article"):
        if good in classes:
            score += 8
    if _in_noise_section(tag):
        score -= 30
    return score


def _discover_link_path_selectors(soup: BeautifulSoup, max_groups: int = 5) -> list[tuple[str, list[Tag]]]:
    """반복되는 기사 URL 패턴으로 a[href*='...'] 후보 생성 (토스 /article/ 등)."""
    body = soup.body or soup
    buckets: dict[str, list[Tag]] = defaultdict(list)

    for a in body.find_all("a", href=True):
        if not isinstance(a, Tag):
            continue
        href = a.get("href") or ""
        text = a.get_text(" ", strip=True)
        if _title_quality(text) < 0.25 and _href_article_score(href) < 0.4:
            continue
        if _in_noise_section(a):
            continue
        low = href.lower().split("?")[0]
        # 패턴 키: /article/, /blog/, /tech/, /digits/
        key = None
        for hint in _ARTICLE_PATH_HINTS:
            if hint in low:
                key = hint
                break
        if key is None and re.search(r"/\d{4,}/?$", low):
            # /26507/ 형태 — 부모 경로 한 단계
            key = "numeric_id"
        if key is None:
            continue
        buckets[key].append(a)

    out: list[tuple[str, list[Tag]]] = []
    for key, links in buckets.items():
        # 중복 href 제거
        seen_h: set[str] = set()
        uniq: list[Tag] = []
        for a in links:
            h = a.get("href") or ""
            if h in seen_h:
                continue
            seen_h.add(h)
            uniq.append(a)
        if len(uniq) < 3:
            continue
        if key == "numeric_id":
            # 선택자 만들기 어려움 — 부모 post-item 쪽이 나음. 스킵하거나 느슨한 패턴
            continue
        sel = f'a[href*="{key}"]'
        out.append((sel, uniq))
    out.sort(key=lambda x: -len(x[1]))
    return out[:max_groups]


def _suggest_relative_title_link(
    best_ms: list[Tag], best_sel: str, max_per_role: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    titles_out: list[dict[str, Any]] = []
    links_out: list[dict[str, Any]] = []

    # 아이템이 이미 a 인 경우
    if best_ms and best_ms[0].name == "a":
        titles_out.append(
            {
                "selector": ".",
                "score": 99.0,
                "count": len(best_ms),
                "sample": _text_preview(best_ms[0]),
                "relative_to": best_sel,
                "note": t("selector.item_is_link"),
            }
        )
        links_out.append(
            {
                "selector": ".",
                "score": 99.0,
                "count": len(best_ms),
                "sample": (best_ms[0].get("href") or "")[:80],
                "relative_to": best_sel,
            }
        )
        return titles_out[:max_per_role], links_out[:max_per_role]

    title_seeds = [
        "h2 a", "h3 a", "h2", "h3", "h1", "h4",
        ".title", ".post-title", ".entry-title",
        "a.title", ".card-title", "a[href]",
    ]
    # 시맨틱 제목 태그 가점 (날짜·작성자 뭉치 a 전체보다 h2 선호)
    _title_bonus = {
        "h2 a": 25, "h3 a": 22, "h2": 20, "h3": 18, "h1": 15,
        ".post-title": 20, ".entry-title": 20, ".title": 12,
    }
    for tsel in title_seeds:
        hits = 0
        sample = ""
        q_sum = 0.0
        for m in best_ms[:15]:
            try:
                el = m.select_one(tsel) if tsel != "." else m
            except Exception:
                el = None
            if el:
                text = el.get_text(" ", strip=True)
                q = _title_quality(text)
                if q < 0.15:
                    continue
                hits += 1
                q_sum += q
                if not sample:
                    sample = _text_preview(el)
        if hits >= max(2, len(best_ms[:15]) // 3):
            titles_out.append(
                {
                    "selector": tsel,
                    "score": round(q_sum * 10 + hits + _title_bonus.get(tsel, 0), 1),
                    "count": hits,
                    "sample": sample,
                    "relative_to": best_sel,
                }
            )
    titles_out.sort(key=lambda x: -x["score"])

    link_seeds = ["h2 a", "h3 a", "a[href]", ".title a", "a.title", "h2 a[href]", "h3 a[href]"]
    for lsel in link_seeds:
        hits = 0
        sample = ""
        h_sum = 0.0
        for m in best_ms[:15]:
            try:
                el = m.select_one(lsel)
            except Exception:
                el = None
            if el and el.get("href"):
                hs = _href_article_score(el.get("href") or "")
                if hs < 0.15 and _title_quality(el.get_text(" ", strip=True)) < 0.2:
                    continue
                hits += 1
                h_sum += hs
                if not sample:
                    sample = (el.get("href") or "")[:80]
        if hits >= max(2, len(best_ms[:15]) // 3):
            links_out.append(
                {
                    "selector": lsel,
                    "score": round(h_sum * 10 + hits, 1),
                    "count": hits,
                    "sample": sample,
                    "relative_to": best_sel,
                }
            )
    links_out.sort(key=lambda x: -x["score"])
    return titles_out[:max_per_role], links_out[:max_per_role]
