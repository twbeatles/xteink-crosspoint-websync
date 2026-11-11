"""기사 번역 모듈 (googletrans 또는 LibreTranslate 지원)"""
import asyncio
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

from websync.i18n import t


class Translator:
    """기사 HTML을 지정 언어로 번역하는 클래스."""

    ARTICLE_TIMEOUT = 30.0

    def __init__(self, config: dict, *, logger: logging.Logger | None = None):
        cfg = config.get("translation", {})
        self.enabled = cfg.get("enabled", False)
        self.provider = cfg.get("provider", "googletrans")
        self.libretranslate_host = cfg.get("libretranslate_host", "http://localhost:5000")
        self.libretranslate_api_key = cfg.get("libretranslate_api_key", "")
        self._gtrans = None
        self._logger = logger  # None 이면 print 폴백 (N8)
        self.cancel_requested = lambda: False
        self._deadline = None

    def _check_budget(self) -> None:
        if self.cancel_requested():
            raise RuntimeError("Translation cancelled")
        if self._deadline is not None and time.monotonic() >= self._deadline:
            raise TimeoutError("Article translation time budget exceeded")

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
                # Cache the factory, never an AsyncClient tied to another loop.
                # Availability checks must not open a network client.
                self._gtrans = GT
            except Exception as e:
                self._gtrans = None
                self._warn(t("pipeline.translator.gtrans_fail", error=e))
        return self._gtrans

    def _translate_google_parts(self, parts: list[str], target: str, source: str) -> list[str]:
        factory = self._get_gtrans()
        if factory is None:
            return parts

        async def translate_parts() -> list[str]:
            # Construction, requests and close all belong to this one loop.
            async with factory(timeout=10.0, raise_exception=True) as client:
                translated_parts = []
                for part in parts:
                    self._check_budget()
                    stripped = part.strip()
                    if not part.startswith("<") and len(stripped) > 5:
                        result = await client.translate(stripped, dest=target, src=source)
                        translated_parts.append(part.replace(stripped, result.text))
                    else:
                        translated_parts.append(part)
                return translated_parts

        async def bounded() -> list[str]:
            task = asyncio.create_task(translate_parts())
            deadline = time.monotonic() + self.ARTICLE_TIMEOUT
            try:
                while not task.done():
                    self._check_budget()
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Article translation time budget exceeded")
                    await asyncio.wait({task}, timeout=0.1)
                return await task
            finally:
                if not task.done():
                    task.cancel()
                # Await cancellation so the client closes before its loop exits.
                import contextlib
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        def run() -> list[str]:
            return asyncio.run(bounded())

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return run()
        # The public API is synchronous even when called from an async host.
        # asyncio.run cannot nest in that host's thread; own a separate loop.
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="websync-translate") as executor:
            return executor.submit(run).result()

    def translate_html(self, html_content: str, target_lang: str = "ko", source_lang: str = "auto") -> str:
        """HTML 내 텍스트 노드만 번역. 태그 구조는 보존."""
        if not target_lang:
            return html_content
        self._deadline = time.monotonic() + self.ARTICLE_TIMEOUT
        try:
            self._check_budget()
            parts = re.split(r"(<[^>]+>)", html_content)
            if self.provider == "googletrans":
                return "".join(self._translate_google_parts(parts, target_lang, source_lang))
            translated_parts = []
            for part in parts:
                self._check_budget()
                if part.startswith("<"):
                    translated_parts.append(part)
                else:
                    stripped = part.strip()
                    if len(stripped) > 5:
                        translated = self._do_translate(stripped, target_lang, source_lang)
                        self._check_budget()
                        translated_parts.append(part.replace(stripped, translated))
                    else:
                        translated_parts.append(part)
            return "".join(translated_parts)
        except Exception as e:
            self._warn(t("pipeline.translator.fail", error=e))
            return html_content
        finally:
            self._deadline = None

    def _do_translate(self, text: str, target: str, source: str) -> str:
        if self.provider == "googletrans":
            return self._translate_google_parts([text], target, source)[0]
        elif self.provider == "libretranslate":
            host = (self.libretranslate_host or "").strip()
            if not (host.startswith("http://") or host.startswith("https://")):
                self._warn(t("pipeline.translator.bad_host", host=host[:80]))
                return text
            import json
            import urllib.request
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
            self._check_budget()
            remaining = max(0.001, self._deadline - time.monotonic()) if self._deadline else 10.0
            with urllib.request.urlopen(req, timeout=min(10.0, remaining)) as resp:
                result = json.loads(resp.read())
            return result.get("translatedText", text)
        return text
