"""EPUB 본문 정제 — script 외 iframe/이벤트/javascript: 제거."""

from websync.epub.sanitize import sanitize_body_html


def test_sanitize_strips_iframe_and_events():
    html = (
        '<p onclick="alert(1)">본문</p>'
        '<iframe src="https://evil.example"></iframe>'
        '<a href="javascript:alert(2)">링크</a>'
        "<script>evil()</script>"
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
        "<p>본문 <o:p>워드 조각</o:p></p>"
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
    ET.fromstring(
        f'<div xmlns:xml="http://www.w3.org/XML/1998/namespace">{clean}</div>'.replace(
            ' xmlns:xml="http://www.w3.org/XML/1998/namespace"', ""
        )
    )
    assert not re.search(r"<[a-z]+:[a-z]+", clean)


def test_sanitize_removes_html_comments():
    """네이버 스마트에디터의 <!-- SE-TEXT --> 주석은 책에 불필요하고,
    ebooklib 0.21의 nav 생성(_get_nav → get_pages)을 TypeError로 깨뜨려
    nav.xhtml 없는 '잘못된 책'을 만든다."""
    dirty = "<p>본문</p><!-- SE-TEXT { --><p>더보기</p><!-- } SE-TEXT -->"
    clean = sanitize_body_html(dirty)
    assert "SE-TEXT" not in clean
    assert "<!--" not in clean
    assert "본문" in clean
    assert "더보기" in clean


def test_body_and_html_wrappers_unwrapped_for_chapter_embedding():
    """NaverCafe API 경로가 str(soup.body)를 반환하면 <body> 래퍼가 그대로 오는데,
    빌더가 챕터 <body> 안에 삽입하므로 중첩 <body>의 잘못된 XHTML이 된다."""
    import xml.etree.ElementTree as ET

    dirty = "<html><body><p>카페 본문</p></body></html>"
    clean = sanitize_body_html(dirty)
    assert "<body" not in clean.lower()
    assert "<html" not in clean.lower()
    assert "카페 본문" in clean
    # 챕터에 삽입해도 <body>는 정확히 1개여야 한다
    chapter = f"<body><h1>T</h1>{clean}</body>"
    root = ET.fromstring(f"<div>{chapter}</div>")
    assert sum(1 for el in root.iter() if el.tag == "body") == 1
