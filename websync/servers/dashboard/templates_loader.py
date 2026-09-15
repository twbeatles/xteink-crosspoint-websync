"""HTML 템플릿 로더 (개발 / PyInstaller frozen)."""
from __future__ import annotations

import os
import re
import sys

from websync.core.logger import get_logger
from websync.i18n import get_language, t

logger = get_logger()

_I18N_RE = re.compile(r"\{\{i18n\.([a-zA-Z0-9_.]+)\}\}")


def load_template(name: str) -> str:
    """HTML 템플릿 파일을 읽어옵니다. sys.frozen 및 PyInstaller 대응."""
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            base_dir = os.path.join(sys._MEIPASS, "websync", "servers", "templates")
        else:
            base_dir = os.path.join(os.path.dirname(sys.executable), "servers", "templates")
    else:
        base_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates"
        )

    path = os.path.join(base_dir, name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(t("dashboard.template_failed", name=name, error=e))
        return f"Template {name} not found."


def _apply_i18n(html: str) -> str:
    html = html.replace("{{lang}}", get_language())
    return _I18N_RE.sub(lambda m: t(m.group(1)), html)


def login_html() -> str:
    return _apply_i18n(load_template("login.html"))


def dashboard_html() -> str:
    return _apply_i18n(load_template("dashboard.html"))
