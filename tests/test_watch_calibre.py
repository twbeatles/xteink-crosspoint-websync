"""Calibre Watch — on_moved 지원 및 콜백 계약."""
import time
from types import SimpleNamespace
from unittest.mock import patch

from websync.watch.calibre import CalibreWatcher, _is_watch_book_file
from websync.config.manager import ConfigManager
from websync.gui.settings_tab.watch import SettingsWatchMixin


def test_is_watch_book_file_extensions():
    assert _is_watch_book_file("/lib/new.epub") is True
    assert _is_watch_book_file("/lib/new.PDF") is True
    assert _is_watch_book_file("/lib/new.txt") is True
    assert _is_watch_book_file("/lib/new.tmp") is False
    assert _is_watch_book_file("/lib/folder") is False


def test_calibre_watch_handles_moved_epub():
    seen: list[str] = []
    watcher = CalibreWatcher("/tmp/calibre", seen.append, debounce_sec=0.01)

    class _Handler:
        pass

    # start() 없이 핸들러 로직만 재현
    handler_ns = {}

    def on_moved(event):
        if event.is_directory:
            return
        dest = getattr(event, "dest_path", "") or ""
        if _is_watch_book_file(dest):
            watcher._schedule_debounced(dest)

    handler_ns["on_moved"] = on_moved
    event = SimpleNamespace(is_directory=False, src_path="/tmp/calibre/tmp.part", dest_path="/tmp/calibre/book.epub")
    handler_ns["on_moved"](event)
    assert "/tmp/calibre/book.epub" in watcher._pending


def test_unstable_file_is_retried_until_stable(tmp_path):
    path = tmp_path / "growing.epub"
    path.write_bytes(b"partial")
    seen: list[str] = []
    watcher = CalibreWatcher(str(tmp_path), seen.append, debounce_sec=1)
    watcher._pending[str(path)] = 0
    watcher._stability_retries[str(path)] = 0

    timer = SimpleNamespace(daemon=False, start=lambda: None, cancel=lambda: None)
    with patch.object(watcher, "_is_file_stable", side_effect=[False, True]), patch(
        "websync.watch.calibre.threading.Timer", return_value=timer
    ):
        watcher._flush_pending()
        assert str(path) in watcher._pending
        watcher._pending[str(path)] = time.time() - 2
        watcher._flush_pending()

    assert seen == [str(path)]
    assert str(path) not in watcher._pending


def test_watch_pending_file_survives_config_reload(tmp_path):
    manager = ConfigManager(str(tmp_path / "config.json"))
    owner = SettingsWatchMixin()
    owner.service = SimpleNamespace(config_manager=manager, config=manager.load_config())
    book = tmp_path / "book.epub"
    book.write_bytes(b"epub")

    owner._remember_watch_file(str(book))
    reloaded = manager.load_config()
    assert reloaded["calibre_watch"]["pending_files"] == [str(book.resolve())]

    owner._forget_watch_file(str(book))
    assert manager.load_config()["calibre_watch"]["pending_files"] == []
