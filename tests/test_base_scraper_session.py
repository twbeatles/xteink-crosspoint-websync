import pytest
from unittest.mock import MagicMock, patch

from websync.scrapers.base import FETCH_MAX_BYTES, _session, fetch_url, is_allowed_fetch_url


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
