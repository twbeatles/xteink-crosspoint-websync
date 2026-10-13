"""Real I/O regression for ISSUE-004; all sentinel state is synthetic."""
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
import pytest
from storage_sandbox import StorageGuard, canonical_path

from websync.config.manager import ConfigManager
from websync.core import paths
from websync.core.process_lock import ProcessFileLock
from websync.db.history import SyncHistoryDb
from websync.pipeline.service import SyncService


def test_default_construction_is_isolated_before_any_service_io(isolated_storage):
    svc = SyncService(ConfigManager())
    assert Path(svc.config_manager.config_path).parent == isolated_storage
    assert Path(svc.db.db_path).parent == isolated_storage
    assert Path(svc.epub_builder.output_dir).parent == isolated_storage
    assert Path(svc._process_lock.lock_path).parent == isolated_storage
    assert paths.PROJECT_ROOT == str(isolated_storage)
    assert svc.db.get_count() == 0
    assert list((isolated_storage / "logs").glob("*.log"))


def test_storage_dependencies_survive_reload(tmp_path):
    cm = ConfigManager(str(tmp_path / "injected.json"))
    db = SyncHistoryDb(str(tmp_path / "injected.db"))
    log = logging.getLogger("isolated-injection")
    lock = ProcessFileLock(str(tmp_path / "injected.lock"))
    with patch("websync.pipeline.service.SyncHistoryDb", side_effect=AssertionError("default DB")), \
         patch("websync.pipeline.service.get_logger", side_effect=AssertionError("default logger")), \
         patch("websync.epub.builder.get_logger", side_effect=AssertionError("builder default logger")):
        svc = SyncService(cm, db=db, logger=log, process_lock=lock,
                          sidecar_root=str(tmp_path), output_dir=str(tmp_path / "ebooks"))
        svc._reload_config()
    assert svc.db is db and svc.logger is log and svc._process_lock is lock
    assert svc.epub_builder.logger is log
    assert svc.epub_builder.output_dir == str(tmp_path / "ebooks")


def test_subprocess_sentinel_is_unchanged_and_bad_default_access_is_blocked(tmp_path):
    # The child owns both "user" sentinels and separate test storage. Never use
    # actual checkout config/history even as a fixture or a comparison sample.
    script = r'''
import hashlib, json, logging, pathlib, sqlite3, sys
from storage_sandbox import install_storage_guard
from websync.config.manager import ConfigManager
from websync.db.history import SyncHistoryDb
from websync.core.process_lock import ProcessFileLock
from websync.pipeline.service import SyncService

base = pathlib.Path(sys.argv[1])
user = base / "sentinel-user"
test = base / "test-storage"
user.mkdir(); test.mkdir()
db_path = user / "sync_history.db"
with sqlite3.connect(db_path) as conn:
    conn.execute("CREATE TABLE synced_posts(url TEXT, device_ip TEXT)")
    conn.execute("INSERT INTO synced_posts VALUES ('https://sentinel.invalid', '*')")
(user / "config.json").write_bytes(b'{"sentinel":true}')
(user / "synced_posts.json").write_bytes(b'{"posts":[]}')
before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in user.iterdir()}
for name, module in list(sys.modules.items()):
    if name.startswith("websync.") and hasattr(module, "PROJECT_ROOT"):
        module.PROJECT_ROOT = str(user)
guard = install_storage_guard(user)
cm = ConfigManager(str(test / "config.json"))
db = SyncHistoryDb(str(test / "history.db"))
svc = SyncService(cm, db=db, logger=logging.getLogger("sentinel"),
                  process_lock=ProcessFileLock(str(test / "pipeline.lock")),
                  sidecar_root=str(test), output_dir=str(test / "output"))
assert db.get_count() == 0
assert guard.violations == []
try:
    SyncService(cm)
except Exception as exc:
    assert "Unsafe test storage access" in str(exc), str(exc)
else:
    raise AssertionError("bad default service was allowed")
assert any("sqlite3.connect" in x for x in guard.violations)
try:
    sqlite3.connect('file:' + db_path.as_posix() + '?mode=rw', uri=True)
except AssertionError as exc:
    assert 'Unsafe test storage access' in str(exc)
else:
    raise AssertionError('SQLite URI bypassed guard')
# Compare raw bytes only after disabling this synthetic guard's boundary.
# Audit hooks cannot be removed; moving the boundary disables this instance.
guard.repository = base / "nonexistent-boundary"
after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in user.iterdir()}
assert before == after, (before, after)
with sqlite3.connect(db_path) as conn:
    assert conn.execute("SELECT device_ip FROM synced_posts").fetchall() == [("*",)]
print(json.dumps({"sentinels_unchanged": True, "blocked": len(guard.violations)}))
'''
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                               capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["sentinels_unchanged"] and result["blocked"] >= 1


@pytest.mark.skipif(os.name != "nt", reason="Windows extended path equivalence")
def test_guard_normalizes_extended_windows_paths(tmp_path):
    guard = StorageGuard(tmp_path / "synthetic-user")
    normal = str(tmp_path / "safe.lock")
    extended = "\\\\?\\" + normal
    assert canonical_path(extended) == canonical_path(normal)
    guard("open", (extended, "w", os.O_WRONLY | os.O_CREAT))
    protected = "\\\\?\\" + str(guard.repository / "config.json")
    with pytest.raises(AssertionError, match="Unsafe test storage access"):
        guard("open", (protected, "w", os.O_WRONLY | os.O_CREAT))
    assert canonical_path(r"\\?\UNC\server\share\folder") == canonical_path(r"\\server\share\folder")


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory descriptors")
def test_guard_resolves_directory_descriptor_mutations_in_subprocess(tmp_path):
    script = r'''
import os, pathlib, sys
from storage_sandbox import install_storage_guard
root = pathlib.Path(sys.argv[1]) / 'user'
root.mkdir()
target = root / 'config.json'
target.write_bytes(b'sentinel')
safe = root.parent / 'safe'
safe.mkdir()
(safe / 'config.json').write_bytes(b'allowed')
fd = os.open(root, os.O_RDONLY)
safe_fd = os.open(safe, os.O_RDONLY)
guard = install_storage_guard(root)
try:
    os.chdir(root)
    allowed_fd = os.open('config.json', os.O_RDONLY, dir_fd=safe_fd)
    try:
        assert os.read(allowed_fd, 7) == b'allowed'
    finally:
        os.close(allowed_fd)
    assert guard.violations == []
    for operation in (
        lambda: os.unlink('config.json', dir_fd=fd),
        lambda: os.open('config.json', os.O_WRONLY | os.O_TRUNC, dir_fd=fd),
        lambda: os.rename('config.json', 'renamed.json', src_dir_fd=fd, dst_dir_fd=fd),
    ):
        try:
            operation()
        except AssertionError:
            pass
        else:
            raise AssertionError('descriptor mutation bypassed guard')
finally:
    os.close(fd)
    os.close(safe_fd)
    os.chdir(root.parent)
assert len(guard.violations) == 3
guard.repository = root / 'disabled'
assert target.read_bytes() == b'sentinel'
print('descriptor guard OK')
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "descriptor guard OK" in result.stdout


def test_guard_allows_pytest_toolchain_metadata_but_blocks_app_state(tmp_path):
    """Regression: a clean checkout has no .pytest_cache, so pytest's own
    sessionfinish (atomic cache creation) and coverage.py data files must not
    trip the storage guard. Every CI job failed on this after collection."""
    repo = tmp_path / "repo"
    repo.mkdir()
    guard = StorageGuard(repo)
    # pytest _make_cachedir: anchor mkdir, staging dir, atomic rename.
    guard("os.mkdir", (str(repo), 0o777, None))
    guard("open", (str(repo / ".pytest_cache" / "v" / "cache" / "nodeids"),
                   "w", os.O_WRONLY | os.O_CREAT))
    guard("open", (str(repo / "pytest-cache-files-abc123" / "CACHEDIR.TAG"),
                   "w", os.O_WRONLY | os.O_CREAT))
    guard("os.rename", (str(repo / "pytest-cache-files-abc123"),
                        str(repo / ".pytest_cache"), None, None))
    # coverage.py parallel data files and XML report next to the invocation dir.
    coverage_data = repo / ".coverage.localhost.12345.abcdef"
    guard("open", (str(coverage_data), "w", os.O_WRONLY | os.O_CREAT))
    guard("os.remove", (str(coverage_data), None))
    guard("open", (str(repo / ".coverage"), "w", os.O_WRONLY | os.O_CREAT))
    guard("open", (str(repo / "coverage.xml"), "w", os.O_WRONLY | os.O_CREAT))
    assert guard.violations == []
    # Application state in the checkout is still blocked.
    with pytest.raises(AssertionError, match="Unsafe test storage access"):
        guard("open", (str(repo / "config.json"), "w", os.O_WRONLY | os.O_CREAT))
    with pytest.raises(AssertionError, match="Unsafe test storage access"):
        guard("open", (str(repo / "output" / "book.epub"),
                       "w", os.O_WRONLY | os.O_CREAT))


def test_descriptor_open_context_applies_to_one_matching_event(tmp_path, monkeypatch):
    user = tmp_path / "user"
    safe = tmp_path / "safe"
    user.mkdir()
    safe.mkdir()
    guard = StorageGuard(user)
    monkeypatch.chdir(user)
    guard._descriptor_open.context = {
        "path": "config.json", "resolved": str(safe / "config.json"), "consumed": False,
    }
    guard("open", ("config.json", None, os.O_RDONLY))
    assert guard.violations == []
    assert guard._descriptor_open.context["consumed"]
    # A subsequent raw open must use its own cwd; the context cannot grant it.
    with pytest.raises(AssertionError, match="Unsafe test storage access"):
        guard("open", ("config.json", None, os.O_RDONLY))
