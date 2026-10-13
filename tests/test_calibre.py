"""Calibre CLI contracts without starting a native CLI or user library."""
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

from websync.integrations.calibre import CalibreManager


def manager(tmp_path):
    executable = tmp_path / "Calibre folder 한글" / "calibredb.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"not executed")
    return CalibreManager(str(executable), str(tmp_path / "Library & special % name"))


def test_calibre_list_uses_argv_utf8_and_library(tmp_path, monkeypatch):
    cm = manager(tmp_path)
    books = [{"id": 7, "title": "한글 도서", "authors": ["Author"]}]
    run = MagicMock(side_effect=[SimpleNamespace(returncode=0),
                                SimpleNamespace(returncode=0, stdout=json.dumps(books))])
    monkeypatch.setattr(subprocess, "run", run)
    assert cm.list_books() == books
    args, kwargs = run.call_args
    assert args[0][:3] == [cm.calibre_path, "--with-library", cm.library_path]
    assert args[0][-1] == "--to-json"
    assert kwargs["timeout"] == 15 and kwargs["encoding"] == "utf-8"
    assert not kwargs.get("shell", False)


def test_calibre_format_prefers_epub_and_preserves_drive_colon(tmp_path, monkeypatch):
    cm = manager(tmp_path)
    monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=[SimpleNamespace(returncode=0),
        SimpleNamespace(returncode=0, stdout="PDF: C:\\Library folder\\book.pdf\nEPUB: C:\\Library folder\\한글.epub")]))
    assert cm.get_book_file_path(7) == "C:\\Library folder\\한글.epub"


def test_calibre_timeout_returns_empty_library(tmp_path, monkeypatch):
    cm = manager(tmp_path)
    monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=subprocess.TimeoutExpired("calibredb", 3)))
    assert cm.list_books() == []
