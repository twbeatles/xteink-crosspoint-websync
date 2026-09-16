"""핵심 모듈 import 스모크 체크 (--smoke)."""
from __future__ import annotations

from websync import __version__

# --smoke 가 실제로 로드해야 하는 핵심 모듈 (GUI 제외 — 헤드리스 헬퍼 안전)
SMOKE_MODULES: tuple[str, ...] = (
    "websync.config.manager",
    "websync.pipeline.service",
    "websync.scrapers.factory",
    "websync.epub.builder",
    "websync.db.history",
    "websync.upload.uploader",
    "websync.i18n",
)


def run_smoke_check() -> int:
    """핵심 모듈 import 무결성. 성공 0, 실패 1."""
    import importlib

    failed: list[str] = []
    for name in SMOKE_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:
            failed.append(f"{name}: {exc}")
    try:
        from websync.i18n import init_i18n, t

        init_i18n("ko")
        sample = t("gui.tabs.sync")
        if not sample or sample == "gui.tabs.sync":
            failed.append("websync.i18n: catalog missing gui.tabs.sync")
    except Exception as exc:
        failed.append(f"websync.i18n catalog: {exc}")

    if failed:
        print("Xteink X3 WebSync smoke check FAILED")
        for item in failed:
            print(f"  - {item}")
        return 1
    print(f"Xteink X3 WebSync v{__version__} smoke check OK")
    return 0
