"""일회성 마이그레이션: 루트 모듈 → websync/ 패키지 구조"""

import os
import re
import shutil
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "websync")

IMPORT_MAP = [
    (r"\bfrom paths import\b", "from websync.core.paths import"),
    (r"\bfrom article_utils import\b", "from websync.core.article import"),
    (r"\bfrom logger import\b", "from websync.core.logger import"),
    (r"\bfrom config_manager import\b", "from websync.config.manager import"),
    (r"\bfrom db_manager import\b", "from websync.db.history import"),
    (r"\bfrom scrapers import\b", "from websync.scrapers import"),
    (r"\bfrom builder import\b", "from websync.epub.builder import"),
    (r"\bfrom uploader import\b", "from websync.upload.uploader import"),
    (r"\bfrom service import\b", "from websync.pipeline.service import"),
    (r"\bfrom summarizer import\b", "from websync.pipeline.summarizer import"),
    (r"\bfrom translator import\b", "from websync.pipeline.translator import"),
    (r"\bfrom notifier import\b", "from websync.integrations.notifier import"),
    (r"\bfrom calibre import\b", "from websync.integrations.calibre import"),
    (r"\bfrom scheduler import\b", "from websync.scheduler.manager import"),
    (r"\bfrom opds_server import\b", "from websync.servers.opds import"),
    (r"\bfrom web_api import\b", "from websync.servers.web_dashboard import"),
    (r"\bfrom watcher import\b", "from websync.watch.calibre import"),
    (r"\bfrom gui import\b", "from websync.gui.app import"),
    (r"\bimport paths\b", "import websync.core.paths as paths"),
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
}

OLD_MODULES = [
    "article_utils.py",
    "paths.py",
    "logger.py",
    "config_manager.py",
    "db_manager.py",
    "scrapers.py",
    "builder.py",
    "uploader.py",
    "service.py",
    "summarizer.py",
    "translator.py",
    "notifier.py",
    "calibre.py",
    "scheduler.py",
    "opds_server.py",
    "web_api.py",
    "watcher.py",
    "gui.py",
]


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def rewrite_imports(content: str) -> str:
    for pattern, repl in IMPORT_MAP:
        content = re.sub(pattern, repl, content)
    return content


def write_file(rel_path: str, content: str):
    full = os.path.join(PKG, rel_path)
    ensure_dir(os.path.dirname(full))
    with open(full, "w", encoding="utf-8", newline="\n") as f:
        f.write(content.rstrip() + "\n")


def read_root(name: str) -> str:
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def migrate_core():
    paths_src = read_root("paths.py")
    paths_src = paths_src.replace(
        "PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))",
        textwrap.dedent("""
        _PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        PROJECT_ROOT = os.path.dirname(_PKG_DIR)
        """).strip(),
    )
    write_file("core/paths.py", paths_src)

    article_src = read_root("article_utils.py")
    article_src = article_src.replace(
        '"""기사 URL·동기화 키 유틸리티"""',
        '"""기사 URL·동기화 키 유틸리티"""\n',
    )
    write_file("core/article.py", article_src)

    logger_src = read_root("logger.py")
    logger_src = logger_src.replace(
        'log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")',
        'from websync.core.paths import PROJECT_ROOT\n\n    log_dir = os.path.join(PROJECT_ROOT, "logs")',
    )
    logger_src = logger_src.replace(
        'return os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")',
        'from websync.core.paths import PROJECT_ROOT\n    return os.path.join(PROJECT_ROOT, "logs")',
    )
    # fix double import in get_log_dir - do it cleanly
    logger_src = read_root("logger.py")
    logger_src = """import os
import logging
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime

from websync.core.paths import PROJECT_ROOT

_logger_initialized = False
_app_logger = None


def get_logger() -> logging.Logger:
    global _logger_initialized, _app_logger
    if _logger_initialized:
        return _app_logger

    log_dir = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"sync_{datetime.now().strftime('%Y-%m-%d')}.log")

    logger = logging.getLogger("x3_websync")
    logger.setLevel(logging.DEBUG)

    fh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))

    if sys.stdout and hasattr(sys.stdout, "write"):
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(ch)

    logger.addHandler(fh)
    _app_logger = logger
    _logger_initialized = True
    return logger


def get_log_dir() -> str:
    return os.path.join(PROJECT_ROOT, "logs")
"""
    write_file("core/logger.py", logger_src)

    write_file(
        "core/__init__.py",
        """from websync.core.paths import PROJECT_ROOT, resolve_path
from websync.core.article import ensure_article_url
from websync.core.logger import get_logger, get_log_dir

__all__ = ["PROJECT_ROOT", "resolve_path", "ensure_article_url", "get_logger", "get_log_dir"]
""",
    )


def migrate_simple_moves():
    for src, dst in SIMPLE_MOVES.items():
        content = rewrite_imports(read_root(src))
        if dst == "config/manager.py":
            content = content.replace(
                "from paths import PROJECT_ROOT, resolve_path",
                "from websync.core.paths import PROJECT_ROOT, resolve_path",
            )
        if dst == "db/history.py":
            content = content.replace(
                "from paths import PROJECT_ROOT, resolve_path",
                "from websync.core.paths import PROJECT_ROOT, resolve_path",
            )
        if dst == "servers/web_dashboard.py":
            content = content.replace(
                "from paths import PROJECT_ROOT",
                "from websync.core.paths import PROJECT_ROOT",
            )
        write_file(dst, content)


def split_scrapers():
    src = read_root("scrapers.py")
    base_header = '''"""스크래퍼 공통 기반 및 유틸리티"""
import re
import requests
from abc import ABC, abstractmethod
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from websync.core.article import ensure_article_url

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def maybe_strip_images(element, site_config: dict):
    if site_config.get("include_images", False):
        return
    for img in element.find_all("img"):
        img.decompose()


def extract_rss_link(item, feed_url: str) -> str:
    link_elem = item.find("link")
    if not link_elem:
        return ""
    href = link_elem.get("href")
    if href:
        return href.strip()
    return (link_elem.text or "").strip()


class BaseScraper(ABC):
    @abstractmethod
    def fetch_articles(self, site_config: dict) -> list:
        pass
'''
    write_file("scrapers/base.py", base_header)

    # Extract class blocks by regex
    classes = {
        "css.py": "CssSelectorScraper",
        "rss.py": "RssScraper",
        "naver.py": "NaverBlogScraper",
        "tistory.py": "TistoryScraper",
        "brunch.py": "BrunchScraper",
        "youtube.py": "YoutubeScraper",
        "substack.py": "SubstackScraper",
    }

    for fname, cls_name in classes.items():
        pattern = rf"(class {cls_name}\(BaseScraper\):.*?)(?=\nclass |\nclass ScraperFactory|\Z)"
        m = re.search(pattern, src, re.DOTALL)
        if not m:
            raise RuntimeError(f"Missing class {cls_name}")
        body = m.group(1)
        body = body.replace("_maybe_strip_images", "maybe_strip_images")
        body = body.replace("_extract_rss_link", "extract_rss_link")
        imports = "from websync.scrapers.base import BaseScraper, HEADERS, maybe_strip_images, extract_rss_link, ensure_article_url\n"
        if cls_name == "CssSelectorScraper":
            imports += "from urllib.parse import urljoin\nimport requests\nfrom bs4 import BeautifulSoup\n"
        elif cls_name in ("RssScraper", "NaverBlogScraper"):
            imports += "import re\nimport requests\nfrom bs4 import BeautifulSoup\n"
        elif cls_name in (
            "TistoryScraper",
            "BrunchScraper",
            "YoutubeScraper",
            "SubstackScraper",
        ):
            imports += "import requests\nfrom bs4 import BeautifulSoup\n"
        write_file(f"scrapers/{fname}", f'"""{cls_name}"""\n{imports}\n{body}')

    factory = '''"""스크래퍼 팩토리"""
from websync.scrapers.base import BaseScraper
from websync.scrapers.css import CssSelectorScraper
from websync.scrapers.rss import RssScraper
from websync.scrapers.naver import NaverBlogScraper
from websync.scrapers.tistory import TistoryScraper
from websync.scrapers.brunch import BrunchScraper
from websync.scrapers.youtube import YoutubeScraper
from websync.scrapers.substack import SubstackScraper


class ScraperFactory:
    _scrapers = {
        "css": CssSelectorScraper(),
        "rss": RssScraper(),
        "naver": NaverBlogScraper(),
        "tistory": TistoryScraper(),
        "brunch": BrunchScraper(),
        "youtube": YoutubeScraper(),
        "substack": SubstackScraper(),
    }

    @classmethod
    def get_scraper(cls, scraper_type: str) -> BaseScraper:
        scraper = cls._scrapers.get(scraper_type.lower())
        if not scraper:
            raise ValueError(f"지원하지 않는 스크래퍼 타입: {scraper_type}")
        return scraper

    @classmethod
    def register_scraper(cls, scraper_type: str, scraper: BaseScraper):
        cls._scrapers[scraper_type.lower()] = scraper
'''
    write_file("scrapers/factory.py", factory)

    write_file(
        "scrapers/__init__.py",
        """from websync.scrapers.base import BaseScraper
from websync.scrapers.factory import ScraperFactory

__all__ = ["BaseScraper", "ScraperFactory"]
""",
    )


def write_subpackage_inits():
    inits = {
        "config/__init__.py": "from websync.config.manager import ConfigManager\n__all__ = ['ConfigManager']\n",
        "db/__init__.py": "from websync.db.history import SyncHistoryDb\n__all__ = ['SyncHistoryDb']\n",
        "epub/__init__.py": "from websync.epub.builder import EpubBuilder\n__all__ = ['EpubBuilder']\n",
        "upload/__init__.py": "from websync.upload.uploader import X3Uploader\n__all__ = ['X3Uploader']\n",
        "pipeline/__init__.py": "from websync.pipeline.service import SyncService\n__all__ = ['SyncService']\n",
        "integrations/__init__.py": "",
        "scheduler/__init__.py": "from websync.scheduler.manager import SchedulerManager\n__all__ = ['SchedulerManager']\n",
        "servers/__init__.py": "",
        "watch/__init__.py": "from websync.watch.calibre import CalibreWatcher\n__all__ = ['CalibreWatcher']\n",
        "gui/__init__.py": "from websync.gui.app import SyncAppGui\n__all__ = ['SyncAppGui']\n",
    }
    for path, content in inits.items():
        write_file(path, content)

    write_file(
        "__init__.py",
        '''"""Xteink X3 WebSync Manager 패키지"""
__version__ = "1.0.0"

from websync.pipeline.service import SyncService
from websync.config.manager import ConfigManager
from websync.gui.app import SyncAppGui

__all__ = ["__version__", "SyncService", "ConfigManager", "SyncAppGui"]
''',
    )


def update_entrypoint():
    content = read_root("x3_websync.py")
    content = content.replace(
        "from config_manager import ConfigManager\nfrom service import SyncService\nfrom gui import SyncAppGui\nfrom logger import get_logger",
        "from websync.config.manager import ConfigManager\nfrom websync.pipeline.service import SyncService\nfrom websync.gui.app import SyncAppGui\nfrom websync.core.logger import get_logger",
    )
    with open(
        os.path.join(ROOT, "x3_websync.py"), "w", encoding="utf-8", newline="\n"
    ) as f:
        f.write(content.rstrip() + "\n")


def update_tests():
    tests_dir = os.path.join(ROOT, "tests")
    conftest = os.path.join(tests_dir, "conftest.py")
    with open(conftest, "w", encoding="utf-8", newline="\n") as f:
        f.write("""import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
""")

    for name in os.listdir(tests_dir):
        if not name.startswith("test_") or not name.endswith(".py"):
            continue
        path = os.path.join(tests_dir, name)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        content = rewrite_imports(content)
        content = content.replace(
            "from article_utils import", "from websync.core.article import"
        )
        content = content.replace(
            "from config_manager import", "from websync.config.manager import"
        )
        content = content.replace(
            "from db_manager import", "from websync.db.history import"
        )
        content = content.replace(
            "from uploader import", "from websync.upload.uploader import"
        )
        content = content.replace(
            "from service import", "from websync.pipeline.service import"
        )
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)


def remove_old_modules():
    for name in OLD_MODULES:
        path = os.path.join(ROOT, name)
        if os.path.exists(path):
            os.remove(path)


def main():
    if os.path.exists(PKG):
        shutil.rmtree(PKG)
    ensure_dir(PKG)
    migrate_core()
    migrate_simple_moves()
    split_scrapers()
    write_subpackage_inits()
    update_entrypoint()
    update_tests()
    remove_old_modules()
    print("Migration complete:", PKG)


if __name__ == "__main__":
    main()
