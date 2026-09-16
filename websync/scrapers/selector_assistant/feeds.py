"""RSS/Atom 피드 발견 및 플랫폼 핑거프린트."""
from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from websync.scrapers.base import fetch_url
from websync.scrapers.selector_assistant.constants import (
    _COMMON_FEED_PATHS,
    _FEED_TYPES,
    _PLATFORM_HOSTS,
)
from websync.scrapers.selector_assistant.html_dom import _text_preview
from websync.scrapers.selector_assistant.types import FeedInfo

def _looks_like_feed_body(text: str, content_type: str = "") -> bool:
    ct = (content_type or "").lower()
    if "rss" in ct or "atom" in ct or "xml" in ct:
        head = (text or "")[:500].lower()
        return "<rss" in head or "<feed" in head or "<rdf" in head
    head = (text or "")[:800].lower()
    return "<rss" in head or "<feed" in head or "xmlns:atom" in head



def discover_feeds(
    soup: BeautifulSoup,
    base_url: str,
    *,
    probe_paths: bool = False,
    timeout: int = 4,
    probe_budget_sec: float = 8.0,
    max_probes: int = 5,
) -> list[FeedInfo]:
    """link rel=alternate 피드 및 흔한 feed 경로 힌트.

    probe_paths=True 이면 /rss.xml, /feed 등 공통 경로를 GET 한다.
    총 probe_budget_sec / max_probes 로 지연을 제한한다.
    """
    found: list[FeedInfo] = []
    seen: set[str] = set()

    def add(href: str, title: str = "", feed_type: str = "rss", source: str = "link") -> None:
        if not href:
            return
        full = urljoin(base_url, href.strip())
        if full in seen:
            return
        seen.add(full)
        found.append(FeedInfo(url=full, title=title or "", feed_type=feed_type, source=source))

    for link in soup.find_all("link"):
        if not isinstance(link, Tag):
            continue
        rel = link.get("rel")
        if isinstance(rel, list):
            rel_s = " ".join(rel).lower()
        else:
            rel_s = (rel or "").lower()
        typ = (link.get("type") or "").lower()
        href = link.get("href") or ""
        if "alternate" in rel_s and (
            any(t in typ for t in ("rss", "atom", "xml")) or typ in _FEED_TYPES
        ):
            if "oembed" in typ or "oembed" in href.lower():
                continue
            ft = "atom" if "atom" in typ else "rss"
            add(href, title=(link.get("title") or ""), feed_type=ft, source="link")
        elif typ in _FEED_TYPES and "oembed" not in typ and "rsd" not in typ:
            add(href, title=(link.get("title") or ""), source="link")

    for a in soup.find_all("a", href=True):
        if not isinstance(a, Tag):
            continue
        href = a.get("href") or ""
        low = href.lower()
        if any(k in low for k in ("/feed", "rss", "atom.xml", "feed.xml", "feeds/posts")):
            if "comment" in low:
                continue
            add(href, title=_text_preview(a, 40) or "feed", source="link")

    # link 태그로 본문 피드를 이미 찾으면 path probe 생략 (지연·부하 감소)
    has_primary = any(
        f.source == "link" and "comment" not in f.url.lower() and "oembed" not in f.url.lower()
        for f in found
    )

    if probe_paths and not has_primary:
        parsed = urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        t0 = time.monotonic()
        probes = 0
        for path in _COMMON_FEED_PATHS:
            if probes >= max_probes:
                break
            if time.monotonic() - t0 >= probe_budget_sec:
                break
            full = origin + path
            if full in seen:
                continue
            probes += 1
            try:
                # 남은 예산에 맞춰 타임아웃 축소
                remain = max(1.0, probe_budget_sec - (time.monotonic() - t0))
                resp = fetch_url(full, timeout=min(timeout, remain))
                if resp.status_code != 200:
                    continue
                ct = resp.headers.get("Content-Type", "")
                body = resp.text or ""
                # 본문 일부만 검사 (대용량 방지)
                if _looks_like_feed_body(body[:4000], ct):
                    add(full, title=path, feed_type="rss", source="path_probe")
                    break  # 하나 찾으면 충분
            except Exception:
                continue

    def feed_rank(f: FeedInfo) -> tuple:
        u = f.url.lower()
        bad = ("comment" in u, "oembed" in u, f.source == "guess")
        good = (f.source == "link", f.source == "path_probe", "rss" in u or "feed" in u)
        return (bad, [-1 if g else 0 for g in good])

    found.sort(key=feed_rank)
    return found


def fingerprint_platform(url: str, soup: Optional[BeautifulSoup] = None) -> Optional[str]:
    """알려진 플랫폼이면 전용 scraper type 문자열 반환."""
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path or ""
    full = f"{host}{path}"
    for pat, ptype in _PLATFORM_HOSTS:
        if pat.search(host) or pat.search(full):
            return ptype
    if soup is not None:
        gen = soup.find("meta", attrs={"name": re.compile(r"generator", re.I)})
        if gen and isinstance(gen, Tag):
            content = (gen.get("content") or "").lower()
            if "tistory" in content:
                return "tistory"
        if soup.select_one("#postListBody, .se-main-container"):
            if "naver" in host:
                return "naver"
    return None


def _is_unstable_css_site(url: str) -> bool:
    """해시 CSS class 를 쓰는 사이트 (Medium 등) — RSS 강력 권장."""
    host = urlparse(url).netloc.lower()
    return "medium.com" in host
