"""기기 → PC 다운로드: 같은 이름의 로컬 파일 보호와 안전한 파일명 (2026-11-02 감사 ISSUE-001)."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from websync.gui.device_files import actions
from websync.upload.local_path import (
    find_local_conflicts,
    plan_local_downloads,
    safe_local_filename,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("book.epub", "book.epub"),
        ("한글 책.epub", "한글 책.epub"),
        ("C:evil.epub", "C_evil.epub"),       # 드라이브 상대 경로 차단
        ("a.epub:stream", "a.epub_stream"),   # NTFS ADS 차단
        ("..\\..\\x.epub", "x.epub"),
        ("../x.epub", "x.epub"),
        ("CON.epub", "_CON.epub"),
        ("trailing. ", "trailing"),
        ("", "download"),
        ("..", "download"),
    ],
)
def test_safe_local_filename(raw, expected):
    assert safe_local_filename(raw) == expected


def test_plan_renames_existing_and_batch_duplicates(tmp_path):
    (tmp_path / "book.epub").write_bytes(b"A")
    (tmp_path / "book (1).epub").write_bytes(b"A1")
    plan = plan_local_downloads(str(tmp_path), ["book.epub", "new.epub", "new.epub"], overwrite=False)
    assert [os.path.basename(p["path"]) for p in plan] == ["book (2).epub", "new.epub", "new (1).epub"]
    assert [p["conflict"] for p in plan] == [True, False, False]


def test_plan_overwrite_keeps_name_but_still_separates_batch(tmp_path):
    (tmp_path / "book.epub").write_bytes(b"A")
    plan = plan_local_downloads(str(tmp_path), ["book.epub", "book.epub"], overwrite=True)
    assert [os.path.basename(p["path"]) for p in plan] == ["book.epub", "book (1).epub"]


def test_find_local_conflicts_uses_sanitized_names(tmp_path):
    (tmp_path / "C_evil.epub").write_bytes(b"x")
    assert find_local_conflicts(str(tmp_path), ["C:evil.epub", "other.epub"]) == ["C_evil.epub"]


def _panel(tmp_path, client, *, start=None):
    items = [{"name": "book.epub", "path": "/book.epub", "isDirectory": False}]
    return SimpleNamespace(
        _busy=False,
        _selected_items=lambda: items,
        _selected_ip=lambda: "192.0.2.1",
        _make_client=lambda: client,
        _set_busy=Mock(),
        _download_finished=Mock(),
        app=SimpleNamespace(
            _log_message=Mock(),
            _start_background_task=start or (lambda fn, **kwargs: fn()),
            root=SimpleNamespace(after=lambda delay, callback: callback()),
        ),
    )


def _fake_client():
    client = Mock()

    def download(remote, local, ip=None, *, overwrite=False):
        with open(local, "wb" if overwrite else "xb") as handle:
            handle.write(b"DEVICE")
        return True

    client.download.side_effect = download
    return client


def _run(monkeypatch, tmp_path, answer):
    monkeypatch.setattr(actions.filedialog, "askdirectory", lambda **kwargs: str(tmp_path))
    ask = Mock(return_value=answer)
    monkeypatch.setattr(actions.messagebox, "askyesnocancel", ask)
    client = _fake_client()
    start = Mock(side_effect=lambda fn, **kwargs: fn())
    panel = _panel(tmp_path, client, start=start)
    actions.DeviceFilesActionsMixin._download_selected(panel)
    return ask, client, start


def test_default_answer_keeps_existing_local_file(monkeypatch, tmp_path):
    (tmp_path / "book.epub").write_bytes(b"USER")
    ask, client, _start = _run(monkeypatch, tmp_path, False)
    ask.assert_called_once()
    assert ask.call_args.kwargs.get("default") == actions.messagebox.NO
    assert (tmp_path / "book.epub").read_bytes() == b"USER"
    assert (tmp_path / "book (1).epub").read_bytes() == b"DEVICE"


def test_explicit_overwrite_replaces_local_file(monkeypatch, tmp_path):
    (tmp_path / "book.epub").write_bytes(b"USER")
    _ask, _client, _start = _run(monkeypatch, tmp_path, True)
    assert (tmp_path / "book.epub").read_bytes() == b"DEVICE"
    assert not (tmp_path / "book (1).epub").exists()


def test_cancel_downloads_nothing(monkeypatch, tmp_path):
    (tmp_path / "book.epub").write_bytes(b"USER")
    _ask, client, start = _run(monkeypatch, tmp_path, None)
    start.assert_not_called()
    client.download.assert_not_called()
    assert (tmp_path / "book.epub").read_bytes() == b"USER"


def test_no_conflict_does_not_ask(monkeypatch, tmp_path):
    ask, client, _start = _run(monkeypatch, tmp_path, None)
    ask.assert_not_called()
    assert (tmp_path / "book.epub").read_bytes() == b"DEVICE"
