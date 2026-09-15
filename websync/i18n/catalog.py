"""JSON 카탈로그 로드 및 flatten."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def flatten(obj: Any, prefix: str = "") -> dict[str, str]:
    """중첩 dict를 dotted key 맵으로 펼칩니다."""
    out: dict[str, str] = {}
    if not isinstance(obj, dict):
        if prefix:
            out[prefix] = "" if obj is None else str(obj)
        return out
    for key, value in obj.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(flatten(value, dotted))
        else:
            out[dotted] = "" if value is None else str(value)
    return out


def _locale_dirs() -> list[Path]:
    """locales 디렉터리 후보 (중복 제거)."""
    dirs: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        try:
            key = str(path.resolve())
        except Exception:
            key = str(path)
        if key in seen:
            return
        seen.add(key)
        dirs.append(path)

    try:
        from importlib.resources import files

        _add(Path(str(files("websync.i18n") / "locales")))
    except Exception:
        pass
    _add(Path(__file__).resolve().parent / "locales")
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            _add(Path(meipass) / "websync" / "i18n" / "locales")
        _add(Path(sys.executable).resolve().parent / "websync" / "i18n" / "locales")
    return dirs


def _candidate_paths(lang: str) -> list[Path]:
    name = f"{lang}.json"
    return [d / name for d in _locale_dirs()]


def load_catalog(lang: str) -> dict[str, str]:
    """패키지 리소스에서 locale JSON을 읽어 flatten 합니다. 실패 시 빈 dict."""
    last_error: Exception | None = None
    for path in _candidate_paths(lang):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            last_error = exc
            continue
        try:
            data = json.loads(text)
        except Exception as exc:
            last_error = exc
            continue
        return flatten(data)
    if last_error:
        try:
            from websync.core.logger import get_logger

            get_logger().warning("i18n catalog load failed (%s): %s", lang, last_error)
        except Exception:
            pass
    return {}
