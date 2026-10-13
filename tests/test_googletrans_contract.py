"""Exercise the installed optional package with a fake HTTP transport only."""
import importlib.metadata

import pytest

from websync.pipeline.translator import Translator


@pytest.mark.parametrize("failure", [None, "timeout", "status"])
def test_installed_googletrans_async_http_contract(monkeypatch, failure):
    googletrans = pytest.importorskip("googletrans")
    httpx = pytest.importorskip("httpx")
    version = importlib.metadata.version("googletrans")
    assert tuple(int(part) for part in version.split(".")[:2]) >= (4, 0)
    real_async_client = httpx.AsyncClient
    clients = []
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.params["sl"] == "auto"
        assert request.url.params["tl"] == "ko"
        if failure == "timeout":
            raise httpx.ReadTimeout("fake timeout", request=request)
        if failure == "status":
            return httpx.Response(503, request=request)
        return httpx.Response(200, json=[[["안녕하세요", "hello world", None, None]], None, "en"], request=request)

    def client_factory(**kwargs):
        kwargs["http2"] = False
        kwargs["transport"] = httpx.MockTransport(handle)
        client = real_async_client(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(googletrans.client.httpx, "AsyncClient", client_factory)
    translator = Translator({"translation": {"enabled": True, "provider": "googletrans"}})
    assert translator.is_available_for_site("ko")
    assert not clients
    html = "<p>hello world</p>"
    result = translator.translate_html(html)
    assert result == ("<p>안녕하세요</p>" if failure is None else html)
    assert len(requests) == 1
    assert len(clients) == 1
    assert clients[0].is_closed
