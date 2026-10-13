import sys
import os
import shutil
import tempfile
import threading
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Protect user state even during collection, before any test imports services.
from storage_sandbox import install_storage_guard

# Avoid bytecode writes to installed Python/library folders as well as source.
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
STORAGE_GUARD = install_storage_guard(ROOT)
_SESSION_SANDBOX = tempfile.TemporaryDirectory(prefix="websync-pytest-")
_SANDBOX_ROOT = Path(_SESSION_SANDBOX.name)
# Child Python processes import a copy, whose default storage root is temporary.
shutil.copytree(Path(ROOT) / "websync", _SANDBOX_ROOT / "websync",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
shutil.copy2(Path(__file__).with_name("storage_sandbox.py"), _SANDBOX_ROOT)
(_SANDBOX_ROOT / "sitecustomize.py").write_text(
    "from storage_sandbox import install_storage_guard\n"
    f"install_storage_guard({ROOT!r})\n", encoding="utf-8")
_COLLECTION_STORAGE = _SANDBOX_ROOT / "collection-storage"
_COLLECTION_STORAGE.mkdir()
os.environ["X3_WEBSYNC_STORAGE_ROOT"] = str(_COLLECTION_STORAGE)

from websync.i18n import init_i18n

init_i18n("ko")


def _set_storage_roots(root: Path, patch=None):
    """Update imported aliases too; changing paths.PROJECT_ROOT alone is unsafe."""
    for name, module in list(sys.modules.items()):
        if name == "websync" or name.startswith("websync."):
            if hasattr(module, "PROJECT_ROOT"):
                if patch is None:
                    module.PROJECT_ROOT = str(root)
                else:
                    patch.setattr(module, "PROJECT_ROOT", str(root))


_set_storage_roots(_COLLECTION_STORAGE)
from websync.pipeline.service import SyncService
from websync.core.process_lock import ProcessFileLock

SyncService._process_lock = ProcessFileLock()
from websync.core import logger as _collection_logger

for _handler in list(_collection_logger._app_logger.handlers):
    _collection_logger._app_logger.removeHandler(_handler)
    _handler.close()
_collection_logger._logger_initialized = False
_collection_logger._app_logger = None
_collection_logger._log_handler = None


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Every constructor, relative output and child process gets temporary storage."""
    from websync.core import logger as logger_module
    from websync.core.update.service import UpdateService

    _set_storage_roots(tmp_path, monkeypatch)
    monkeypatch.setattr(SyncService, "_process_lock", ProcessFileLock())
    monkeypatch.setattr(SyncService, "_pipeline_lock", threading.Lock())
    # The updater captures its root in a function default at import time.
    defaults = UpdateService.__init__.__defaults__
    monkeypatch.setattr(UpdateService.__init__, "__defaults__", (*defaults[:-1], str(tmp_path)))
    logger = logger_module._app_logger
    if logger is not None:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
    monkeypatch.setattr(logger_module, "_logger_initialized", False)
    monkeypatch.setattr(logger_module, "_app_logger", None)
    monkeypatch.setattr(logger_module, "_log_handler", None)
    # Keep CLI/spec relative-path contracts, without using the checkout as cwd.
    for filename in ("x3_websync.py", "x3_websync.spec"):
        shutil.copy2(Path(ROOT) / filename, tmp_path / filename)
    monkeypatch.chdir(tmp_path)
    python_path = os.pathsep.join((str(_SANDBOX_ROOT), ROOT, os.environ.get("PYTHONPATH", "")))
    monkeypatch.setenv("PYTHONPATH", python_path)
    monkeypatch.setenv("X3_WEBSYNC_STORAGE_ROOT", str(tmp_path))
    before = len(STORAGE_GUARD.violations)
    yield tmp_path
    SyncService._process_lock.release()
    logger = logger_module._app_logger
    if logger is not None:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
    assert STORAGE_GUARD.violations[before:] == [], "\n".join(STORAGE_GUARD.violations[before:])


def pytest_sessionfinish(session, exitstatus):
    _SESSION_SANDBOX.cleanup()


@pytest.fixture(autouse=True)
def _pin_ui_language_ko():
    """테스트가 언어를 바꿔도 다음 테스트는 한국어 카탈로그를 본다."""
    init_i18n("ko")
    yield
    init_i18n("ko")
