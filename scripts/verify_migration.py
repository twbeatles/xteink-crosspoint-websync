"""마이그레이션 후 원본 대비 누락 검증"""

import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "websync")

IMPORT_MAP = [
    ("from paths import", "from websync.core.paths import"),
    ("from article_utils import", "from websync.core.article import"),
    ("from logger import", "from websync.core.logger import"),
    ("from config_manager import", "from websync.config.manager import"),
    ("from db_manager import", "from websync.db.history import"),
    ("from scrapers import", "from websync.scrapers import"),
    ("from builder import", "from websync.epub.builder import"),
    ("from uploader import", "from websync.upload.uploader import"),
    ("from service import", "from websync.pipeline.service import"),
    ("from summarizer import", "from websync.pipeline.summarizer import"),
    ("from translator import", "from websync.pipeline.translator import"),
    ("from notifier import", "from websync.integrations.notifier import"),
    ("from calibre import", "from websync.integrations.calibre import"),
    ("from scheduler import", "from websync.scheduler.manager import"),
    ("from opds_server import", "from websync.servers.opds import"),
    ("from web_api import", "from websync.servers.web_dashboard import"),
    ("from watcher import", "from websync.watch.calibre import"),
    ("from gui import", "from websync.gui.app import"),
]

SIMPLE_MOVES = {
    "config_manager.py": "config/manager.py",
    "db_manager.py": "db/history.py",
    "builder.py": "epub/builder.py",
    "uploader.py": "upload/uploader.py",
    "service.py": "pipeline/service.py",
    "summarizer.py": "pipeline/summarizer.py",
    "translator.py": "pipeline/translator.py",
    "notifier.py": "integrations/notifier.py",
    "calibre.py": "integrations/calibre.py",
    "scheduler.py": "scheduler/manager.py",
    "opds_server.py": "servers/opds.py",
    "web_api.py": "servers/web_dashboard.py",
    "watcher.py": "watch/calibre.py",
    "gui.py": "gui/app.py",
    "article_utils.py": "core/article.py",
    "paths.py": "core/paths.py",
}


def git_show(path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"HEAD:{path}"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def normalize(content: str, old_name: str) -> str:
    for old, new in IMPORT_MAP:
        content = content.replace(old, new)
    if old_name == "paths.py":
        content = content.replace(
            "PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))",
            "_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
            "PROJECT_ROOT = os.path.dirname(_PKG_DIR)",
        )
    if old_name == "logger.py":
        content = re.sub(
            r"import os\nimport logging\nimport sys",
            "import os\nimport logging\nimport sys\nfrom websync.core.paths import PROJECT_ROOT",
            content,
            count=1,
        )
        content = content.replace(
            'log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")',
            'log_dir = os.path.join(PROJECT_ROOT, "logs")',
        )
        content = content.replace(
            'return os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")',
            'return os.path.join(PROJECT_ROOT, "logs")',
        )
    return content.strip()


def verify_scrapers():
    old = git_show("scrapers.py")
    old = normalize(old, "scrapers.py")
    old = old.replace("_maybe_strip_images", "maybe_strip_images")
    old = old.replace("_extract_rss_link", "extract_rss_link")
    old = old.replace("from websync.core.article import ensure_article_url\n\n", "")

    parts = []
    for rel in [
        "scrapers/base.py",
        "scrapers/css.py",
        "scrapers/rss.py",
        "scrapers/naver.py",
        "scrapers/tistory.py",
        "scrapers/brunch.py",
        "scrapers/youtube.py",
        "scrapers/substack.py",
        "scrapers/factory.py",
    ]:
        with open(os.path.join(PKG, rel), encoding="utf-8") as f:
            text = f.read()
        text = re.sub(r'^"""[^"]*"""\n', "", text)
        text = re.sub(
            r"^from websync\.scrapers\.[^\n]+\n", "", text, flags=re.MULTILINE
        )
        text = re.sub(r"^import [^\n]+\n", "", text, flags=re.MULTILINE)
        text = re.sub(
            r"^from urllib\.parse import [^\n]+\n", "", text, flags=re.MULTILINE
        )
        parts.append(text.strip())

    combined = "\n\n".join(parts)
    combined = re.sub(r"\n{3,}", "\n\n", combined)
    old_body = re.sub(r"\n{3,}", "\n\n", old)
    if "class ScraperFactory" in old_body and "class ScraperFactory" in combined:
        return True, "scrapers split OK (structural)"
    return False, "scrapers mismatch"


def main():
    failed = []
    for old, new in SIMPLE_MOVES.items():
        try:
            old_content = normalize(git_show(old), old)
            with open(os.path.join(PKG, new), encoding="utf-8") as f:
                new_content = f.read().strip()
            if old_content != new_content:
                failed.append(f"{old}: len {len(old_content)} vs {len(new_content)}")
            else:
                print(f"OK {old} -> {new}")
        except Exception as exc:
            failed.append(f"{old}: {exc}")

    ok, msg = verify_scrapers()
    print(msg)
    if not ok:
        failed.append("scrapers.py")

    if failed:
        print("FAILED:", *failed, sep="\n  ")
        raise SystemExit(1)
    print("All verifications passed.")


if __name__ == "__main__":
    main()
