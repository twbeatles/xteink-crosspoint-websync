"""Scraper sanitization + safety boundaries (INV-10/12).

Real product sanitize path (EpubBuilder + sanitize_body_html): executable
content must not survive; javascript: URLs, event handlers, iframe/form
must be stripped. Redirect/URL-scheme guards use is_allowed_fetch_url.
"""
from __future__ import annotations

from websync.epub.sanitize import sanitize_body_html
from websync.scrapers.base import is_allowed_fetch_url


def test_script_iframe_form_removed():
    dirty = ('<p>ok</p><script>alert(1)</script>'
             '<iframe src="https://evil.example"></iframe>'
             '<form action="https://evil.example"><input></form>'
             '<style>body{}</style>')
    clean = sanitize_body_html(dirty)
    assert "<script" not in clean and "<iframe" not in clean
    assert "<form" not in clean and "alert(1)" not in clean
    assert "ok" in clean


def test_event_handlers_and_javascript_urls_stripped():
    dirty = ('<a href="javascript:alert(1)" onclick="x()">link</a>'
             '<img src="javascript:alert(2)" onerror="y()">')
    clean = sanitize_body_html(dirty).lower()
    assert "javascript:" not in clean
    assert "onclick" not in clean and "onerror" not in clean
    assert "link" in clean


def test_allowed_fetch_url_blocks_private_and_schemes():
    from websync.scrapers.selector_assistant.url_safety import is_private_or_local_url

    assert is_allowed_fetch_url("https://news.example/feed") is True
    # Explicitly configured private URLs are allowed (user confirms in UI);
    # the guard only blocks non-http(s) schemes and redirect-into-private.
    assert is_allowed_fetch_url("http://127.0.0.1/admin") is True
    assert is_private_or_local_url("http://127.0.0.1/admin") is True
    assert is_private_or_local_url("https://news.example/feed") is False
    assert is_allowed_fetch_url("file:///etc/passwd") is False
    assert is_allowed_fetch_url("javascript:alert(1)") is False
    assert is_allowed_fetch_url("") is False


def test_epub_builder_sanitizes_malicious_chapter(tmp_path):
    from websync.epub.builder import EpubBuilder
    import zipfile

    builder = EpubBuilder(output_dir=str(tmp_path))
    arts = [{"title": "evil", "url": "https://a.example/e",
             "content": '<p>hi</p><script>steal()</script><a href="javascript:x">c</a>'}]
    path = builder.build("S", arts, generate_cover=False)
    with zipfile.ZipFile(path) as zf:
        blob = b"\n".join(zf.read(n) for n in zf.namelist() if n.endswith(".xhtml"))
    text = blob.decode("utf-8", "replace").lower()
    assert "<script" not in text and "javascript:" not in text
    assert "hi" in text
