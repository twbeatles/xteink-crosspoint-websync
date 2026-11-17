"""NaverCafeScraper — clubid 해석 및 API 목록 파싱 단위 테스트."""

from unittest.mock import MagicMock, patch

from websync.scrapers.naver_cafe import NaverCafeScraper


def test_resolve_club_id_from_page():
    sc = NaverCafeScraper()
    html = '<script>var g_sClubId = "27842958";</script>'
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = html

    with patch("websync.scrapers.naver_cafe.fetch_url", return_value=resp):
        cid = sc._resolve_club_id(
            "steamindiegame", "https://cafe.naver.com/steamindiegame"
        )
    assert cid == "27842958"


def test_fetch_articles_api_path():
    sc = NaverCafeScraper()

    home_resp = MagicMock()
    home_resp.raise_for_status = MagicMock()
    home_resp.text = "g_sClubId = 12345;"

    list_resp = MagicMock()
    list_resp.raise_for_status = MagicMock()
    list_resp.json.return_value = {
        "message": {
            "result": {
                "articleList": [
                    {"articleId": 99, "subject": "카페 테스트 글 제목"},
                ]
            }
        }
    }

    article_resp = MagicMock()
    article_resp.raise_for_status = MagicMock()
    article_resp.json.return_value = {
        "result": {
            "article": {
                "contentHtml": "<div><p>본문이 충분히 긴 카페 글 내용입니다. e-ink 테스트용.</p></div>",
                "isReadable": True,
            }
        }
    }

    def fake_fetch(url, **kwargs):
        if "ArticleListV2" in url:
            return list_resp
        if "cafe-articleapi" in url:
            return article_resp
        return home_resp

    with patch("websync.scrapers.naver_cafe.fetch_url", side_effect=fake_fetch):
        arts = sc.fetch_articles({"url": "https://cafe.naver.com/mycafe", "limit": 1})

    assert len(arts) == 1
    assert arts[0]["title"] == "카페 테스트 글 제목"
    assert "본문이 충분히" in arts[0]["content"]
    assert arts[0]["url"].endswith("/mycafe/99")
