"""AI 기사 요약 모듈 (OpenAI API 또는 Ollama 로컬 LLM 지원)"""
import html
import logging
import re

from websync.i18n import t


class Summarizer:
    """기사 텍스트를 AI로 요약하는 클래스. API 키가 없으면 자동 스킵."""

    def __init__(self, config: dict, *, logger: logging.Logger | None = None):
        ai_cfg = config.get("ai_summary", {})
        self.enabled = ai_cfg.get("enabled", False)
        self.provider = ai_cfg.get("provider", "openai")
        self.api_key = ai_cfg.get("api_key", "")
        self.ollama_host = ai_cfg.get("ollama_host", "http://localhost:11434")
        self.model = ai_cfg.get("model", "gpt-4o-mini")
        self._logger = logger  # None 이면 print 폴백 (N8)

    def _warn(self, msg: str) -> None:
        if self._logger is not None:
            self._logger.warning(msg)
        else:
            print(msg)

    def is_available(self) -> bool:
        if not self.enabled:
            return False
        if self.provider == "openai" and not self.api_key:
            return False
        return True

    def _extract_text(self, html_content: str) -> str:
        text = re.sub(r"<[^>]+>", " ", html_content)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:3000]

    def _format_summary(self, summary: str) -> str:
        safe = html.escape(summary, quote=False).replace("\n", "<br/>")
        return f'<blockquote class="ai-summary"><strong>{t("pipeline.summarizer.label")}</strong><br/>{safe}</blockquote>'

    def summarize(self, title: str, html_content: str) -> str:
        if not self.is_available():
            return ""
        try:
            text = self._extract_text(html_content)
            prompt = f"다음 기사를 한국어로 3문장 이내로 핵심만 요약해줘.\n\n제목: {title}\n\n내용: {text}"

            if self.provider == "openai":
                return self._call_openai(prompt)
            elif self.provider == "ollama":
                return self._call_ollama(prompt)
        except Exception as e:
            self._warn(t("pipeline.summarizer.fail", error=e))
        return ""

    def _call_openai(self, prompt: str) -> str:
        import urllib.request
        import json
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 300
        }
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read())
        choices = result.get("choices") or []
        if not choices:
            self._warn(t("pipeline.summarizer.no_choices"))
            return ""
        message = choices[0].get("message") or {}
        summary = (message.get("content") or "").strip()
        if not summary:
            self._warn(t("pipeline.summarizer.empty"))
            return ""
        return self._format_summary(summary)

    def _call_ollama(self, prompt: str) -> str:
        import urllib.request
        import json
        host = (self.ollama_host or "").strip()
        if not (host.startswith("http://") or host.startswith("https://")):
            self._warn(t("pipeline.summarizer.bad_host", host=host[:80]))
            return ""
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        req = urllib.request.Request(
            f"{host.rstrip('/')}/api/generate",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        summary = result.get("response", "").strip()
        return self._format_summary(summary)
