"""BrunchScraper — 프로필 추출·API 목록 파싱 단위 테스트."""
from unittest.mock import MagicMock, patch

from websync.scrapers.brunch import BrunchScraper


def test_extract_profile_id():
    sc = BrunchScraper()
    assert sc._extract_profile_id("https://brunch.co.kr/@brunch") == "brunch"
    assert sc._extract_profile_id("https://brunch.co.kr/@my-author/") == "my-author"
    assert sc._extract_profile_id("https://example.com/foo") is None


def test_fetch_list_via_api_parses_items():
    sc = BrunchScraper()
    payload = {
        "desc": "OK",
        "code": 200,
        "data": {
            "list": [
                {"no": 10, "title": "첫 글", "status": "publish"},
                {"no": 9, "title": "둘째", "status": "publish"},
                {"no": 8, "title": "초안", "status": "draft"},
            ]
        },
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = payload

    with patch("websync.scrapers.brunch.fetch_url", return_value=mock_resp):
        entries = sc._fetch_list_via_api("brunch", limit=5)

    assert len(entries) == 2
    assert entries[0] == ("첫 글", "https://brunch.co.kr/@brunch/10")
    assert entries[1][0] == "둘째"


def test_fetch_articles_uses_api_then_content():
    sc = BrunchScraper()
    list_payload = {
        "desc": "OK",
        "code": 200,
        "data": {"list": [{"no": 1, "title": "테스트 글", "status": "publish"}]},
    }
    list_resp = MagicMock()
    list_resp.raise_for_status = MagicMock()
    list_resp.json.return_value = list_payload

    html = """
    <html><body>
      <div class="wrap_body"><p>본문 내용이 충분히 길게 들어갑니다. 브런치 테스트.</p></div>
    </body></html>
    """
    html_resp = MagicMock()
    html_resp.raise_for_status = MagicMock()
    html_resp.text = html

    def fake_fetch(url, **kwargs):
        if "api.brunch.co.kr" in url:
            return list_resp
        return html_resp

    with patch("websync.scrapers.brunch.fetch_url", side_effect=fake_fetch):
        arts = sc.fetch_articles({"url": "https://brunch.co.kr/@brunch", "limit": 1})

    assert len(arts) == 1
    assert arts[0]["title"] == "테스트 글"
    assert "본문 내용" in arts[0]["content"]
    assert arts[0]["url"].endswith("/@brunch/1")
