"""RssScraper 인코딩 및 빈 description 보정 테스트."""

from unittest.mock import MagicMock, patch

from websync.scrapers.rss import RssScraper, _decode_feed_xml


def test_decode_feed_xml_uses_xml_declaration():
    raw = '<?xml version="1.0" encoding="UTF-8"?><rss><channel><title>한글</title></channel></rss>'.encode(
        "utf-8"
    )
    resp = MagicMock()
    resp.content = raw
    resp.encoding = "ISO-8859-1"
    resp.apparent_encoding = "utf-8"
    text = _decode_feed_xml(resp)
    assert "한글" in text


def test_rss_mojibake_fixed_and_short_desc_gets_fallback():
    # UTF-8 피드를 ISO-8859-1 로 잘못 잡힌 것처럼 content 만 올바르게 제공
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
      <item>
        <title>한겨레 테스트 제목입니다 충분히 김</title>
        <link>https://www.hani.co.kr/arti/1.html</link>
        <description><![CDATA[<table><tr><td><img src="x.jpg"/></td></tr></table>]]></description>
      </item>
    </channel></rss>
    """
    resp = MagicMock()
    resp.content = xml.encode("utf-8")
    resp.encoding = "ISO-8859-1"
    resp.apparent_encoding = "utf-8"
    resp.raise_for_status = MagicMock()

    with patch("websync.scrapers.rss.fetch_url", return_value=resp):
        arts = RssScraper().fetch_articles(
            {"url": "https://example.com/rss", "limit": 1, "include_images": False}
        )

    assert len(arts) == 1
    assert "한겨레" in arts[0]["title"]
    assert "한겨레" in arts[0]["title"]
    assert "원문 링크" in arts[0]["content"] or "RSS 피드" in arts[0]["content"]
