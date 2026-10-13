"""Translator 단위 테스트 — N8(logger 주입) 중심.

외부 번역 API 호출은 mock 하고, logger 주입 동작만 검증한다.
"""
from io import BytesIO
import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from websync.pipeline.translator import Translator


def _config(provider="libretranslate", enabled=True):
    return {
        "translation": {
            "enabled": enabled,
            "provider": provider,
            "libretranslate_host": "http://localhost:5000",
            "libretranslate_api_key": "",
        }
    }


def test_translator_uses_logger_on_failure():
    """logger 주입 시 번역 실패를 logger.warning 으로 출력."""
    logger = MagicMock()
    t = Translator(_config(), logger=logger)

    with patch("urllib.request.urlopen", side_effect=RuntimeError("libre 죽음")):
        result = t.translate_html("<p>hello world this is long enough</p>", target_lang="ko")

    # 실패 시 원문 반환
    assert "hello world" in result
    logger.warning.assert_called()
    warned = " ".join(str(c) for c in logger.warning.call_args_list)
    assert "번역 실패" in warned


def test_translator_print_fallback_when_no_logger():
    """logger=None 일 때 print 폴백."""
    t = Translator(_config(), logger=None)
    with patch("urllib.request.urlopen", side_effect=RuntimeError("boom")):
        with patch("builtins.print") as mock_print:
            t.translate_html("<p>hello world this is long enough</p>", target_lang="ko")
    mock_print.assert_called()


def test_translator_is_available_for_site_requires_translate_to():
    t = Translator(_config())
    assert t.is_available_for_site("") is False
    assert t.is_available_for_site("  ") is False


def test_translator_googletrans_respects_enabled_false():
    """전역 번역이 꺼져 있으면 googletrans가 있어도 사이트를 번역하지 않는다."""
    t = Translator(_config(provider="googletrans", enabled=False))
    with patch.object(t, "_get_gtrans") as mock_gt:
        mock_gt.return_value = MagicMock()
        assert t.is_available_for_site("ko") is False
        mock_gt.assert_not_called()


def test_translator_libretranslate_rejects_non_http_host():
    cfg = _config(provider="libretranslate", enabled=True)
    cfg["translation"]["libretranslate_host"] = "file:///tmp/evil"
    t = Translator(cfg)
    result = t._do_translate("hello world", "ko", "en")
    assert result == "hello world"


def test_translator_logger_warns_on_googletrans_load_failure():
    """googletrans provider 에서 로드 실패 시 logger.warning."""
    logger = MagicMock()
    t = Translator(_config(provider="googletrans", enabled=True), logger=logger)

    # googletrans import 자체가 실패하는 환경을 흉내
    builtins_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == "googletrans":
            raise ImportError("no googletrans")
        return builtins_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        gt = t._get_gtrans()

    assert gt is None
    logger.warning.assert_called()
    warned = " ".join(str(c) for c in logger.warning.call_args_list)
    assert "googletrans 로드 실패" in warned


def test_translator_libretranslate_success():
    """libretranslate 정상 응답 시 번역문 반환."""
    t = Translator(_config())
    fake_resp = BytesIO(json.dumps({"translatedText": "안녕하세요"}).encode())
    with patch("urllib.request.urlopen", return_value=fake_resp):
        result = t._do_translate("hello", "ko", "en")
    assert result == "안녕하세요"


class _AsyncGoogleClient:
    def __init__(self, *, timeout, raise_exception):
        assert timeout == 10.0
        assert raise_exception is True
        self.loop = asyncio.get_running_loop()
        self.thread = threading.get_ident()
        self.calls = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        assert asyncio.get_running_loop() is self.loop
        self.closed = True

    async def translate(self, text, *, dest, src):
        assert asyncio.get_running_loop() is self.loop
        self.calls.append((text, dest, src))
        return SimpleNamespace(text="번역된 문장")


def _google_factory(translator):
    clients = []

    def factory(**kwargs):
        client = _AsyncGoogleClient(**kwargs)
        clients.append(client)
        return client

    translator._gtrans = factory
    return clients


def test_googletrans_awaits_nodes_preserves_tags_and_closes_client():
    translator = Translator(_config(provider="googletrans"))
    clients = _google_factory(translator)
    result = translator.translate_html('<p class="keep"> hello world </p><b>another sentence</b>')
    assert result == '<p class="keep"> 번역된 문장 </p><b>번역된 문장</b>'
    assert len(clients) == 1
    assert clients[0].calls == [("hello world", "ko", "auto"), ("another sentence", "ko", "auto")]
    assert clients[0].closed


def test_googletrans_creates_and_closes_client_for_each_call():
    translator = Translator(_config(provider="googletrans"))
    clients = _google_factory(translator)
    for _ in range(2):
        assert translator.translate_html("<p>hello world</p>", "ja", "en") == "<p>번역된 문장</p>"
    assert len(clients) == 2
    assert clients[0].loop is not clients[1].loop
    assert all(client.closed and client.loop.is_closed() for client in clients)
    assert all(client.calls == [("hello world", "ja", "en")] for client in clients)


def test_googletrans_sync_api_from_running_event_loop():
    translator = Translator(_config(provider="googletrans"))
    clients = _google_factory(translator)

    async def caller():
        host_loop = asyncio.get_running_loop()
        host_thread = threading.get_ident()
        assert translator.translate_html("<p>hello world</p>") == "<p>번역된 문장</p>"
        assert clients[0].loop is not host_loop
        assert clients[0].thread != host_thread
        assert asyncio.get_running_loop() is host_loop

    asyncio.run(caller())
    assert clients[0].closed


def test_googletrans_failure_closes_client_logs_and_returns_entire_original():
    logger = MagicMock()
    translator = Translator(_config(provider="googletrans"), logger=logger)
    clients = _google_factory(translator)
    original_translate = _AsyncGoogleClient.translate

    async def fail_second(self, text, **kwargs):
        if self.calls:
            raise TimeoutError("translation timeout")
        return await original_translate(self, text, **kwargs)

    html = "<p>first sentence</p><p>second sentence</p>"
    with patch.object(_AsyncGoogleClient, "translate", fail_second):
        assert translator.translate_html(html) == html
    assert clients[0].closed
    assert clients[0].loop.is_closed()
    logger.warning.assert_called_once()


def test_googletrans_availability_does_not_construct_client():
    translator = Translator(_config(provider="googletrans"))
    clients = _google_factory(translator)
    assert translator.is_available_for_site("ko")
    assert not clients
