import pytest
from unittest.mock import MagicMock, patch

from websync.scrapers.base import FETCH_MAX_BYTES, _session, fetch_url, is_allowed_fetch_url
from support.source_server import source_server


def test_is_allowed_fetch_url_http_only():
    assert is_allowed_fetch_url("https://example.com/a") is True
    assert is_allowed_fetch_url("http://example.com/a") is True
    assert is_allowed_fetch_url("file:///tmp/x") is False
    assert is_allowed_fetch_url("ftp://example.com/a") is False
    assert is_allowed_fetch_url("") is False


def test_fetch_url_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="http"):
        fetch_url("file:///tmp/secret")


def test_fetch_url_enforces_max_bytes():
    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Length": str(FETCH_MAX_BYTES + 1)}
    mock_resp.close = MagicMock()
    with patch.object(_session, "get", return_value=mock_resp):
        with pytest.raises(ValueError, match="크기"):
            fetch_url("https://example.com/huge")
    mock_resp.close.assert_called()


def test_base_scraper_session_pool_size():
    # _session의 HTTPAdapter 커넥션 풀 크기가 20 이상으로 설정되었는지 검증
    adapters = _session.adapters
    http_adapter = adapters.get("http://")
    https_adapter = adapters.get("https://")

    assert http_adapter is not None
    assert https_adapter is not None

    assert http_adapter._pool_connections >= 20
    assert http_adapter._pool_maxsize >= 20

    assert https_adapter._pool_connections >= 20
    assert https_adapter._pool_maxsize >= 20


def test_fetch_url_blocks_public_redirect_to_private_network():
    redirect = MagicMock()
    redirect.status_code = 302
    redirect.headers = {"Location": "http://127.0.0.1/admin"}
    redirect.close = MagicMock()
    with patch.object(_session, "get", return_value=redirect) as get:
        with pytest.raises(ValueError, match="private/local"):
            fetch_url("https://example.com/start")
    assert get.call_count == 1
    redirect.close.assert_called_once()


@pytest.fixture
def content_origin(monkeypatch):
    monkeypatch.setattr(_session, "trust_env", False)
    with source_server() as origin:
        yield origin


def test_real_http_retries_transient_failure_and_follows_relative_redirect(content_origin):
    origin, routes, requests = content_origin
    routes["/start"] = (302, {"Location": "/feed"}, b"")
    responses = iter([(503, {}, b"try again"),
                      (200, {"Content-Type": "text/plain; charset=utf-8"}, "정상 본문")])
    routes["/feed"] = lambda: next(responses)
    with fetch_url(origin + "/start", timeout=2) as response:
        assert response.status_code == 200
        assert response.text == "정상 본문"
        assert response.url == origin + "/feed"
    assert requests == ["/start", "/feed", "/feed"]


def test_real_http_does_not_retry_permanent_failure(content_origin):
    import requests as http

    origin, routes, requests = content_origin
    routes["/missing"] = (404, {}, b"not found")
    with fetch_url(origin + "/missing", timeout=2) as response:
        with pytest.raises(http.HTTPError) as error:
            response.raise_for_status()
        assert error.value.response.status_code == 404
    assert requests == ["/missing"]


def test_real_http_redirect_loop_is_bounded_and_session_recovers(content_origin):
    from websync.scrapers.base import FETCH_MAX_REDIRECTS

    origin, routes, requests = content_origin
    routes["/loop"] = (302, {"Location": "/loop"}, b"")
    routes["/ok"] = (200, {}, b"recovered")
    with pytest.raises(ValueError, match="Too many HTTP redirects"):
        fetch_url(origin + "/loop", timeout=2)
    assert requests == ["/loop"] * (FETCH_MAX_REDIRECTS + 1)
    with fetch_url(origin + "/ok", timeout=2) as response:
        assert response.content == b"recovered"


@pytest.mark.parametrize("declared_length", [True, False], ids=["content-length", "stream-until-close"])
def test_real_http_size_boundary_and_recovery(content_origin, monkeypatch, declared_length):
    import websync.scrapers.base as base

    origin, routes, requests = content_origin
    monkeypatch.setattr(base, "FETCH_MAX_BYTES", 1024)
    headers = {} if declared_length else {"Connection": "close"}
    routes["/exact"] = (200, headers, b"x" * 1024)
    routes["/large"] = (200, headers, b"x" * 1025)
    with fetch_url(origin + "/exact", timeout=2) as response:
        assert response.content == b"x" * 1024
    with pytest.raises(ValueError, match="크기"):
        fetch_url(origin + "/large", timeout=2)
    # A rejected stream must not poison the shared HTTP connection pool.
    with fetch_url(origin + "/exact", timeout=2) as response:
        assert response.content == b"x" * 1024
    assert requests == ["/exact", "/large", "/exact"]
