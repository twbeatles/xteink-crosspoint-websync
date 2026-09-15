"""CSS 선택자 도우미 — 페이지 분석·테스트·추천 (GUI 비의존 순수 로직).

의존성: requests(via fetch_url), beautifulsoup4, lxml 선택.
브라우저 자동화 없음. 정적 HTML만 대상으로 한다.

한국 기술 블로그·워드프레스·Gatsby 등 목록 페이지를 실측 튜닝:
- 메뉴 li / 해시 class / 템플릿 노이즈 감점
- .post-item, 글 링크 경로 패턴 가점
- RSS 경로 프로브 및 fetch_detail_page 권장
"""
from __future__ import annotations

import ipaddress
import re
import socket
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from websync.scrapers.base import fetch_url
from websync.i18n import t

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


@dataclass
class SelectorSample:
    text: str
    html_preview: str = ""


@dataclass
class SelectorTestResult:
    count: int
    samples: list[SelectorSample] = field(default_factory=list)
    error: str = ""


@dataclass
class DomNode:
    """DOM 아웃라인용 플랫/트리 노드 (부모 index로 연결)."""
    index: int
    parent_index: int  # -1 = root
    tag: str
    label: str
    css_path: str
    text_preview: str
    depth: int


@dataclass
class FeedInfo:
    url: str
    title: str = ""
    feed_type: str = "rss"
    source: str = "link"  # link | path_probe | guess


@dataclass
class PageAnalysis:
    url: str
    base_url: str
    title: str = ""
    feeds: list[FeedInfo] = field(default_factory=list)
    platform: Optional[str] = None
    suggestions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    outline: list[DomNode] = field(default_factory=list)
    error: str = ""
    html: str = ""
    # 튜닝 결과 메타
    recommend_mode: str = "css"  # rss | platform | css
    fetch_detail_recommended: bool = False
    recommended_site: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def parse_html(html: str, base_url: str = "") -> BeautifulSoup:
    """HTML 문자열을 BeautifulSoup으로 파싱 (lxml 우선, 폴백 html.parser)."""
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def fetch_html(url: str, timeout: int = 15) -> tuple[str, str, BeautifulSoup]:
    """URL에서 HTML을 가져와 (html, final_url, soup) 반환."""
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError(t("selector.url_scheme"))
    resp = fetch_url(url, timeout=timeout)
    resp.raise_for_status()
    if resp.encoding == "ISO-8859-1":
        resp.encoding = resp.apparent_encoding
    html = resp.text or ""
    final = str(resp.url) if getattr(resp, "url", None) else url
    return html, final, parse_html(html, final)


def _stable_classes(tag: Tag) -> list[str]:
    classes = tag.get("class") or []
    if isinstance(classes, str):
        classes = classes.split()
    out: list[str] = []
    for c in classes:
        c = (c or "").strip()
        if not c or len(c) < 3 or len(c) > 40:
            continue
        if _UNSTABLE_CLASS.search(c):
            continue
        # 숫자/해시성 제외
        if re.fullmatch(r"[a-f0-9]{6,}", c, re.I):
            continue
        # 1~2글자 또는 CSS module 짧은 토큰 제외 (medium 등)
        if len(c) <= 2:
            continue
        # 모음 없는 초단 class (z b c 조합) 제외
        if len(c) <= 4 and not re.search(r"[aeiou가-힣_\-]", c, re.I):
            continue
        # styled-components 스타일 랜덤 토큰 (iQzKaI) — 의미 단어·구분자 없으면 제외
        if (
            re.fullmatch(r"[A-Za-z]+", c)
            and not re.search(r"(post|entry|article|content|title|card|list|item|blog)", c, re.I)
            and ("_" not in c and "-" not in c)
            and re.search(r"[A-Z]", c)
            and re.search(r"[a-z]", c)
            and len(c) <= 12
        ):
            continue
        out.append(c)
    # 의미 있는 class 우선 (post_, entry_ 등)
    out.sort(
        key=lambda x: (
            0
            if re.search(r"(post|entry|article|content|title|card|list|item|blog)", x, re.I)
            else 1,
            len(x),
        )
    )
    return out[:3]


def _tag_simple_selector(tag: Tag) -> str:
    tid = (tag.get("id") or "").strip()
    if tid and re.match(r"^[A-Za-z][\w\-:.]*$", tid) and not re.search(r"\d{5,}", tid):
        return f"#{tid}"
    name = tag.name or "div"
    classes = _stable_classes(tag)
    if classes:
        return name + "".join(f".{c}" for c in classes)
    return name


def css_path(tag: Tag, max_depth: int = 6) -> str:
    """요소에 대한 비교적 안정적인 CSS 선택자 경로 생성."""
    if not isinstance(tag, Tag):
        return ""
    parts: list[str] = []
    current: Optional[Tag] = tag
    depth = 0
    while current is not None and isinstance(current, Tag) and current.name and depth < max_depth:
        if current.name in ("html", "[document]"):
            break
        simple = _tag_simple_selector(current)
        if simple.startswith("#"):
            parts.append(simple)
            break
        parent = current.parent if isinstance(current.parent, Tag) else None
        if parent and parent.name not in ("html", "[document]", None):
            siblings = [
                s for s in parent.find_all(current.name, recursive=False) if isinstance(s, Tag)
            ]
            if len(siblings) > 1:
                try:
                    nth = siblings.index(current) + 1
                except ValueError:
                    nth = 1
                if simple != current.name:
                    same = [s for s in siblings if _tag_simple_selector(s) == simple]
                    if len(same) > 1:
                        simple = f"{simple}:nth-of-type({nth})"
                else:
                    simple = f"{current.name}:nth-of-type({nth})"
        parts.append(simple)
        if simple.startswith("#"):
            break
        current = parent
        depth += 1
    parts.reverse()
    return " > ".join(parts) if parts else (tag.name or "")


def _text_preview(tag: Tag, max_len: int = 80) -> str:
    text = " ".join(tag.stripped_strings)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def evaluate_selector(
    soup: BeautifulSoup,
    selector: str,
    limit: int = 5,
    root: Optional[Tag] = None,
) -> SelectorTestResult:
    """CSS 선택자 매칭 개수와 샘플 텍스트 반환."""
    sel = (selector or "").strip()
    if not sel:
        return SelectorTestResult(count=0, error=t("selector.empty"))
    target = root if root is not None else soup
    try:
        matches = target.select(sel)
    except Exception as e:
        return SelectorTestResult(count=0, error=t("selector.syntax", error=e))
    samples: list[SelectorSample] = []
    for m in matches[:limit]:
        if not isinstance(m, Tag):
            continue
        html = str(m)
        if len(html) > 200:
            html = html[:199] + "…"
        samples.append(SelectorSample(text=_text_preview(m), html_preview=html))
    return SelectorTestResult(count=len(matches), samples=samples)


def _looks_like_feed_body(text: str, content_type: str = "") -> bool:
    ct = (content_type or "").lower()
    if "rss" in ct or "atom" in ct or "xml" in ct:
        head = (text or "")[:500].lower()
        return "<rss" in head or "<feed" in head or "<rdf" in head
    head = (text or "")[:800].lower()
    return "<rss" in head or "<feed" in head or "xmlns:atom" in head


def is_private_or_local_url(url: str) -> bool:
    """로컬호스트·사설 IP·링크 로컬 등 내부망으로 보이면 True.

    DNS 해석 실패 시 hostname 휴리스틱만 사용 (차단하지 않음).
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    if host in ("localhost", "localhost.localdomain") or host.endswith(".local"):
        return True
    # 리터럴 IP
    try:
        ip = ipaddress.ip_address(host)
        return bool(
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        )
    except ValueError:
        pass
    # 선택적 DNS (짧게) — 실패하면 외부로 간주
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        for info in infos:
            addr = info[4][0]
            try:
                ip = ipaddress.ip_address(addr)
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_reserved
                ):
                    return True
            except ValueError:
                continue
    except Exception:
        pass
    return False


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


def build_dom_outline(
    soup: BeautifulSoup,
    max_nodes: int = 400,
    max_depth: int = 8,
) -> list[DomNode]:
    """GUI Treeview용 DOM 아웃라인 (script/style 제외, 깊이·개수 제한)."""
    body = soup.body or soup
    nodes: list[DomNode] = []
    stack: list[tuple[Tag, int, int]] = [(body, -1, 0)]

    while stack and len(nodes) < max_nodes:
        tag, parent_idx, depth = stack.pop(0)
        if not isinstance(tag, Tag) or not tag.name:
            continue
        if tag.name in _SKIP_TAGS:
            continue
        if depth > max_depth:
            continue
        idx = len(nodes)
        label_parts = [tag.name]
        tid = (tag.get("id") or "").strip()
        if tid:
            label_parts.append(f"#{tid}")
        classes = _stable_classes(tag)
        if classes:
            label_parts.append("." + ".".join(classes[:2]))
        preview = _text_preview(tag, 50)
        label = " ".join(label_parts)
        if preview:
            label = f"{label}  — {preview}"
        nodes.append(
            DomNode(
                index=idx,
                parent_index=parent_idx,
                tag=tag.name,
                label=label[:120],
                css_path=css_path(tag),
                text_preview=preview,
                depth=depth,
            )
        )
        children = [
            c
            for c in tag.children
            if isinstance(c, Tag) and c.name and c.name not in _SKIP_TAGS
        ]
        for child in children:
            stack.append((child, idx, depth + 1))

    return nodes


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
