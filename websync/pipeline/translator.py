"""기사 번역 모듈 (googletrans 또는 LibreTranslate 지원)"""
import logging
import re

from websync.i18n import t


class Translator:
    """기사 HTML을 지정 언어로 번역하는 클래스."""

    def __init__(self, config: dict, *, logger: logging.Logger | None = None):
        cfg = config.get("translation", {})
        self.enabled = cfg.get("enabled", False)
        self.provider = cfg.get("provider", "googletrans")
        self.libretranslate_host = cfg.get("libretranslate_host", "http://localhost:5000")
        self.libretranslate_api_key = cfg.get("libretranslate_api_key", "")
        self._gtrans = None
        self._logger = logger  # None 이면 print 폴백 (N8)

    def _warn(self, msg: str) -> None:
        if self._logger is not None:
            self._logger.warning(msg)
        else:
            print(msg)

    def is_available(self) -> bool:
        return self.enabled

    def is_available_for_site(self, translate_to: str) -> bool:
        """사이트별 translate_to가 설정된 경우 번역 가능 여부를 판단합니다."""
        if not self.enabled:
            return False
        if not (translate_to or "").strip():
            return False
        if self.provider == "googletrans":
            return self._get_gtrans() is not None
        return True

    def _get_gtrans(self):
        if self._gtrans is None:
            try:
                from googletrans import Translator as GT
                self._gtrans = GT()
            except Exception as e:
                self._gtrans = None
                self._warn(t("pipeline.translator.gtrans_fail", error=e))
        return self._gtrans

    def translate_html(self, html_content: str, target_lang: str = "ko", source_lang: str = "auto") -> str:
        """HTML 내 텍스트 노드만 번역. 태그 구조는 보존."""
        if not target_lang:
            return html_content
        try:
            parts = re.split(r"(<[^>]+>)", html_content)
            translated_parts = []
            for part in parts:
                if part.startswith("<"):
                    translated_parts.append(part)
                else:
                    stripped = part.strip()
                    if len(stripped) > 5:
                        translated = self._do_translate(stripped, target_lang, source_lang)
                        translated_parts.append(part.replace(stripped, translated))
                    else:
                        translated_parts.append(part)
            return "".join(translated_parts)
        except Exception as e:
            self._warn(t("pipeline.translator.fail", error=e))
            return html_content

    def _do_translate(self, text: str, target: str, source: str) -> str:
        if self.provider == "googletrans":
            gt = self._get_gtrans()
            if gt is None:
                return text
            result = gt.translate(text, dest=target, src=source if source != "auto" else None)
            return result.text
        elif self.provider == "libretranslate":
            host = (self.libretranslate_host or "").strip()
            if not (host.startswith("http://") or host.startswith("https://")):
                self._warn(t("pipeline.translator.bad_host", host=host[:80]))
                return text
            import urllib.request
            import json
            payload = {
                "q": text,
                "source": source if source != "auto" else "en",
                "target": target,
                "api_key": self.libretranslate_api_key
            }
            req = urllib.request.Request(
                f"{host.rstrip('/')}/translate",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
            return result.get("translatedText", text)
        return text
