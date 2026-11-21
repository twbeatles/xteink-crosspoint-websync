import json
from io import BytesIO
from unittest.mock import MagicMock, patch

from websync.pipeline.summarizer import Summarizer


def _config(enabled=True):
    return {
        "ai_summary": {"enabled": enabled, "provider": "openai", "api_key": "test-key"}
    }


def test_summarizer_unavailable_when_disabled():
    s = Summarizer({"ai_summary": {"enabled": False}})
    assert s.summarize("t", "<p>x</p>") == ""


def test_summarize_cancelled_before_http_does_no_request():
    """취소가 요청된 상태에서는 HTTP 호출 없이 빈 요약을 반환한다."""
    from unittest.mock import patch as _patch

    s = Summarizer(_config())
    s.cancel_requested = lambda: True
    with _patch("urllib.request.urlopen") as mock_open:
        assert s.summarize("제목", "<p>본문</p>") == ""
    mock_open.assert_not_called()


def test_summarize_check_budget_cancel_and_deadline():
    """취소·예산 초과는 예산 검사에서 즉시 예외로 보고된다."""
    import time as _time

    import pytest as _pytest

    s = Summarizer(_config())
    s.cancel_requested = lambda: True
    with _pytest.raises(RuntimeError):
        s._check_budget()
    s.cancel_requested = lambda: False
    s._deadline = _time.monotonic() - 1.0
    with _pytest.raises(TimeoutError):
        s._check_budget()


def test_call_openai_malformed_no_choices():
    s = Summarizer(_config())
    fake_resp = BytesIO(json.dumps({"id": "x"}).encode())

    with patch("urllib.request.urlopen", return_value=fake_resp):
        assert s._call_openai("prompt") == ""


def test_call_openai_empty_content():
    s = Summarizer(_config())
    fake_resp = BytesIO(
        json.dumps({"choices": [{"message": {"content": ""}}]}).encode()
    )

    with patch("urllib.request.urlopen", return_value=fake_resp):
        assert s._call_openai("prompt") == ""


def test_call_openai_valid_response():
    s = Summarizer(_config())
    fake_resp = BytesIO(
        json.dumps({"choices": [{"message": {"content": "요약문입니다."}}]}).encode()
    )

    with patch("urllib.request.urlopen", return_value=fake_resp):
        result = s._call_openai("prompt")
        assert "요약문입니다" in result
        assert "ai-summary" in result


# --- N8: logger 주입 테스트 ---


def test_summarizer_uses_logger_when_provided():
    """logger 주입 시 API 호출 실패를 logger.warning 으로 출력."""
    logger = MagicMock()
    s = Summarizer(_config(), logger=logger)

    with patch("urllib.request.urlopen", side_effect=RuntimeError("network down")):
        result = s.summarize("제목", "<p>본문</p>")

    assert result == ""
    logger.warning.assert_called()
    warned = " ".join(str(c) for c in logger.warning.call_args_list)
    assert "AI 요약 실패" in warned


def test_summarizer_logger_falls_back_to_print_when_none():
    """logger=None 일 때 기존처럼 print 폴백 (에러 없이 동작)."""
    s = Summarizer(_config(), logger=None)
    with patch("urllib.request.urlopen", side_effect=RuntimeError("boom")):
        with patch("builtins.print") as mock_print:
            result = s.summarize("제목", "<p>본문</p>")
    assert result == ""
    mock_print.assert_called()


def test_summarizer_logger_warns_on_empty_choices():
    """빈 choices 응답도 logger.warning 으로 노출되는지."""
    logger = MagicMock()
    s = Summarizer(_config(), logger=logger)
    fake_resp = BytesIO(json.dumps({"id": "x"}).encode())

    with patch("urllib.request.urlopen", return_value=fake_resp):
        s._call_openai("prompt")

    logger.warning.assert_called()
