"""HTML 파싱·CSS 경로·선택자 평가·DOM 아웃라인."""
from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from websync.i18n import t
from websync.scrapers.base import fetch_url
from websync.scrapers.selector_assistant.constants import _SKIP_TAGS, _UNSTABLE_CLASS
from websync.scrapers.selector_assistant.types import (
    DomNode,
    SelectorSample,
    SelectorTestResult,
)

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
