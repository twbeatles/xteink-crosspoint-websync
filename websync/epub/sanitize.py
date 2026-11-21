"""EPUB 본문 HTML 정제."""

from __future__ import annotations

from bs4 import BeautifulSoup, Comment

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
    # HTML 주석(네이버 스마트에디터의 <!-- SE-TEXT --> 등)은 책에
    # 불필요할 뿐 아니라, ebooklib 0.21의 nav 생성(_get_nav → get_pages)이
    # 주석 노드의 .get()에 터져 nav.xhtml 없는 '잘못된 책'을 만든다.
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    # soup.body/str(soup) 통째로 반환된 입력(API 스크래퍼 등)은 <html>/<body>
    # 래퍼를 포함한다. 빌더가 챕터 <body> 안에 삽입하므로 중첩 방지용으로
    # 래퍼는 풀고 내용만 남긴다 (자식은 아래 속성 정제를 그대로 받는다).
    for tag in soup.find_all(["html", "body"]):
        tag.unwrap()
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
