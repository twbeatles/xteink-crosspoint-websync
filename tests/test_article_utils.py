from websync.core.article import ensure_article_url


def test_ensure_article_url_keeps_existing():
    assert (
        ensure_article_url("https://example.com/a", "https://ex.com", "t")
        == "https://example.com/a"
    )


def test_ensure_article_url_synthetic_from_title():
    url = ensure_article_url("", "https://feed.example.com", "Hello World")
    assert url.startswith("synckey://")
    assert ensure_article_url("", "https://feed.example.com", "Hello World") == url


def test_ensure_article_url_empty_when_no_data():
    assert ensure_article_url("", "https://ex.com", "") == ""
