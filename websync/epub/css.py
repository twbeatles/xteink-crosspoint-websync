"""EPUB 테마 CSS 로딩 및 기본 스타일 생성."""
from __future__ import annotations

import os
import sys
from typing import Any


def themes_dir() -> str:
    """테마 CSS 디렉터리 경로 (개발 / PyInstaller frozen)."""
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            return os.path.join(sys._MEIPASS, "websync", "epub", "themes")
        return os.path.join(os.path.dirname(sys.executable), "epub", "themes")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "themes")


def load_theme_css(
    epub_theme: str,
    epub_custom_css: str,
    font_family: str,
    font_size: int | float | str,
    line_height: float | str,
    logger: Any | None = None,
) -> str:
    """테마 설정에 따라 CSS를 로딩. 실패·default 시 빈 문자열."""
    css_text = ""

    if epub_theme == "custom" and epub_custom_css:
        try:
            with open(epub_custom_css, "r", encoding="utf-8") as f:
                css_text = f.read()
        except Exception as e:
            if logger:
                from websync.i18n import t
                logger.warning(t("epub.css_custom_failed", path=epub_custom_css, error=e))
    elif epub_theme and epub_theme != "default":
        theme_path = os.path.join(themes_dir(), f"{epub_theme}.css")
        try:
            with open(theme_path, "r", encoding="utf-8") as f:
                css_text = f.read()
        except Exception as e:
            if logger:
                from websync.i18n import t
                logger.warning(t("epub.css_theme_failed", path=theme_path, error=e))

    if css_text:
        css_text = css_text.replace("{{font_family}}", str(font_family))
        css_text = css_text.replace("{{font_size}}", str(font_size))
        css_text = css_text.replace("{{line_height}}", str(line_height))
        return css_text
    return ""


def build_default_css(
    font_family: str = "serif",
    font_size: int | float | str = 16,
    line_height: float | str = 1.7,
) -> str:
    """기본 CSS를 생성합니다 (검증된 값 사용)."""
    safe_font = "".join(
        c for c in str(font_family or "serif") if c.isalnum() or c in (" ", "-", "_", ",", "'")
    ).strip() or "serif"
    try:
        safe_size = max(8, min(48, int(font_size)))
    except (TypeError, ValueError):
        safe_size = 16
    try:
        safe_lh = max(1.0, min(3.0, float(line_height)))
    except (TypeError, ValueError):
        safe_lh = 1.7

    return f"""
        body {{
            font-family: {safe_font}, serif, sans-serif;
            padding: 5px;
            line-height: {safe_lh};
            font-size: {safe_size}px;
            color: #000000;
            background-color: #ffffff;
            text-align: justify;
        }}
        h1 {{
            font-size: 1.35em;
            font-weight: bold;
            border-bottom: 2px solid #555555;
            padding-bottom: 6px;
            margin-top: 15px;
            margin-bottom: 15px;
        }}
        p {{
            margin-top: 0;
            margin-bottom: 0.9em;
            text-indent: 0.5em;
        }}
        blockquote.ai-summary {{
            border-left: 3px solid #555555;
            margin: 10px 5px;
            padding: 8px 12px;
            background-color: #f5f5f5;
            font-style: italic;
            font-size: 0.9em;
        }}
        """


def resolve_css(
    epub_theme: str,
    epub_custom_css: str,
    font_family: str,
    font_size,
    line_height,
    logger: Any | None = None,
) -> str:
    """테마 CSS 또는 기본 CSS 중 하나를 반환."""
    custom = load_theme_css(
        epub_theme, epub_custom_css, font_family, font_size, line_height, logger
    )
    if custom:
        return custom
    return build_default_css(font_family, font_size, line_height)
