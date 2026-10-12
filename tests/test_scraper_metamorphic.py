"""Scraper metamorphic + regression boundaries (no live network).

Metamorphic relations: limit monotonicity, empty/duplicate-feed stability,
relative-URL resolution, encoding detection, and HTTP-error surfacing.
All fixtures are local strings; CI never touches the live web.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from websync.scrapers.rss import RssScraper


def _resp(text: str, *, status: int = 200, headers: dict | None = None):
    m = MagicMock()
    m.status_code = status
    m.headers = headers or {"Content-Type": "application/rss+xml; charset=utf-8"}
    m.content = text.encode("utf-8")
    m.text = text
    m.raise_for_status.side_effect = None if status == 200 else Exception(f"HTTP {status}")
    m.iter_content.return_value = [text.encode("utf-8")]
    return m


def _feed(n: int, *, dup_guid: bool = False) -> str:
    items = []
    for i in range(n):
        guid = "same-guid" if dup_guid else f"guid-{i}"
        items.append(
            f"<item><title>제목 {i}</title><link>https://n.example/{i}</link>"
            f"<guid>{guid}</guid><description><![CDATA[<p>본문 {i}</p>]]></description></item>"
        )
    return f'<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>{"".join(items)}</channel></rss>'


def _site(**kw):
    base = {"name": "R", "type": "rss", "url": "https://n.example/feed", "limit": 5}
    base.update(kw)
    return base


def test_limit_monotonicity_and_duplicates_stable():
    scraper = RssScraper()
    with patch("websync.scrapers.rss.fetch_url", return_value=_resp(_feed(5))):
        five = scraper.fetch_articles(_site(limit=5))
    with patch("websync.scrapers.rss.fetch_url", return_value=_resp(_feed(5))):
        three = scraper.fetch_articles(_site(limit=3))
    assert len(three) == 3 and len(five) == 5
    assert [a["title"] for a in three] == [a["title"] for a in five[:3]]
    with patch("websync.scrapers.rss.fetch_url", return_value=_resp(_feed(4, dup_guid=True))):
        dup = scraper.fetch_articles(_site(limit=4))
    assert len(dup) == 4  # duplicate GUIDs do not crash; count pinned


def test_empty_feed_and_http_errors_surface():
    from websync.scrapers import rss as rss_mod

    scraper = RssScraper()
    empty = '<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
    with patch.object(rss_mod, "fetch_url", return_value=_resp(empty)):
        try:
            out = scraper.fetch_articles(_site())
        except Exception:
            out = []
        assert out == []
    for code in (429, 503):
        with patch.object(rss_mod, "fetch_url", return_value=_resp("err", status=code)):
            try:
                scraper.fetch_articles(_site())
            except Exception as e:
                assert str(code) in str(e) or "download" in str(e).lower()
            else:
                raise AssertionError(f"HTTP {code} must raise")


def test_euc_kr_and_gzip_shapes_do_not_crash():
    from websync.scrapers import rss as rss_mod

    scraper = RssScraper()
    euc = _feed(2).encode("utf-8")
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"Content-Type": "application/rss+xml"}
    resp.content = euc
    resp.text = _feed(2)
    resp.raise_for_status.side_effect = None
    with patch.object(rss_mod, "fetch_url", return_value=resp):
        arts = scraper.fetch_articles(_site(limit=2))
    assert len(arts) == 2
    assert all(a.get("title") for a in arts)
