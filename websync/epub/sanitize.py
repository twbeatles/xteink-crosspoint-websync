"""EPUB 본문 HTML 정제."""

from __future__ import annotations

from bs4 import BeautifulSoup

# 위험하거나, e-ink 책에서 쓸모없고, XHTML 로 직렬화하면 접두사 오류를 내는 태그.
# (svg <use xlink:href>, 갤러리 <button> 등 — 남기면 챕터가 XML 파싱 실패한다)
_DROP_TAGS = [
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "form",
    "svg",
    "canvas",
    "video",
    "audio",
    "button",
    "noscript",
    "input",
    "select",
    "textarea",
    "template",
]


def sanitize_body_html(content: str) -> str:
    """본문 HTML에서 위험 태그·이벤트·javascript: URL을 제거합니다."""
    if not content:
        return ""
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup.find_all(_DROP_TAGS):
        if not getattr(tag, "decomposed", False):
            tag.decompose()
    for tag in soup.find_all(True):
        # <o:p> 같은 네임스페이스 태그는 접두사가 선언되지 않아 XHTML 이 깨진다 — 내용만 남긴다
        if ":" in (tag.name or ""):
            tag.unwrap()
            continue
        # 이벤트 핸들러 속성 제거
        for attr in list(tag.attrs):
            name = str(attr).lower()
            if name.startswith("on"):
                del tag.attrs[attr]
                continue
            # xlink:/og:/data 접두사 속성은 미선언 접두사 오류를 낸다 (xml:lang 만 허용)
            if ":" in name and not name.startswith("xml:"):
                del tag.attrs[attr]
                continue
            if name in ("href", "src", "xlink:href"):
                val = tag.attrs.get(attr)
                if isinstance(val, list):
                    val = " ".join(str(v) for v in val)
                if str(val or "").strip().lower().startswith("javascript:"):
                    del tag.attrs[attr]
    return str(soup)
