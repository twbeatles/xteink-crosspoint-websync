"""EPUB 본문 정제 — script 외 iframe/이벤트/javascript: 제거."""
from websync.epub.sanitize import sanitize_body_html


def test_sanitize_strips_iframe_and_events():
    html = (
        '<p onclick="alert(1)">본문</p>'
        '<iframe src="https://evil.example"></iframe>'
        '<a href="javascript:alert(2)">링크</a>'
        '<script>evil()</script>'
    )
    out = sanitize_body_html(html)
    assert "<iframe" not in out.lower()
    assert "onclick" not in out.lower()
    assert "javascript:" not in out.lower()
    assert "<script>" not in out.lower()
    assert "본문" in out
    assert "링크" in out


def test_namespaced_markup_and_inline_widgets_become_valid_xhtml():
    """실제 Dezeen 피드에서 나온 형태: 인라인 svg(xlink), 갤러리 button, Word 의 <o:p>."""
    import re
    import xml.etree.ElementTree as ET

    dirty = (
        '<p>본문 <o:p>워드 조각</o:p></p>'
        '<button class="arrow"><svg viewBox="0 0 24 24"><use xlink:href="#caret"/></svg></button>'
        '<p xlink:role="x" og:title="t" xml:lang="ko">유지</p>'
        '<video src="https://x/y.mp4"></video><noscript><img src="a.png"></noscript>'
    )
    clean = sanitize_body_html(dirty)
    assert "본문" in clean and "워드 조각" in clean and "유지" in clean
    for gone in ("<svg", "<button", "<video", "<noscript", "o:p", "xlink:", "og:"):
        assert gone not in clean
    assert 'xml:lang="ko"' in clean
    # 접두사 선언 없이 XML 로 파싱돼야 한다
    ET.fromstring(f'<div xmlns:xml="http://www.w3.org/XML/1998/namespace">{clean}</div>'.replace(' xmlns:xml="http://www.w3.org/XML/1998/namespace"', ""))
    assert not re.search(r"<[a-z]+:[a-z]+", clean)
