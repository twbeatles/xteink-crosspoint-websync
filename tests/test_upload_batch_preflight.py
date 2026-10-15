"""Exercise the actual GUI handlers without creating a native Tk window."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from websync.gui.device_files import actions
from websync.gui.tab_calibre import CalibreTab
from websync.upload.uploader import X3Uploader


@pytest.fixture
def duplicate_paths(tmp_path):
    paths = []
    for folder in ("a", "b"):
        directory = tmp_path / folder
        directory.mkdir()
        path = directory / "book.epub"
        path.write_bytes(folder.encode())
        paths.append(str(path))
    return paths


@pytest.mark.parametrize("warn", [False, True])
def test_manual_batch_collision_refused_before_remote_check(monkeypatch, duplicate_paths, warn):
    client = Mock()
    start = Mock()
    errors = Mock()
    monkeypatch.setattr(actions.filedialog, "askopenfilenames", lambda **kwargs: duplicate_paths)
    monkeypatch.setattr(actions.messagebox, "showerror", errors)
    panel = SimpleNamespace(
        _busy=False, _selected_ip=lambda: "localhost", _current_path="/Books",
        _make_client=lambda: client, warn_overwrite_var=SimpleNamespace(get=lambda: warn),
        _set_busy=Mock(), app=SimpleNamespace(_start_background_task=start),
    )
    actions.DeviceFilesActionsMixin._upload_to_current(panel)
    errors.assert_called_once()
    client.remote_file_exists.assert_not_called()
    client.upload_to_path.assert_not_called()
    start.assert_not_called()
    panel._set_busy.assert_not_called()


def test_calibre_resolves_entire_batch_before_any_upload(monkeypatch, duplicate_paths):
    import websync.gui.tab_calibre as module

    uploader = X3Uploader("localhost")
    uploader.upload_to_targets = Mock()
    errors = Mock()
    monkeypatch.setattr(module.messagebox, "showerror", errors)
    app = SimpleNamespace(
        _save_ui_settings=lambda: True, _sync_busy=False, _log_message=Mock(),
        _make_uploader=lambda: uploader,
        _start_background_task=lambda fn, **kwargs: fn(),
    )
    panel = SimpleNamespace(
        app=app, calibre_tree=SimpleNamespace(selection=lambda: ("1", "2")),
        calibre_send_btn=Mock(),
        calibre=SimpleNamespace(get_book_file_path=lambda book_id: duplicate_paths[book_id - 1]),
        master=SimpleNamespace(after=lambda delay, callback: callback()),
    )
    panel._calibre_batch_rejected = lambda error: CalibreTab._calibre_batch_rejected(panel, error)
    CalibreTab._send_calibre_books(panel)
    uploader.upload_to_targets.assert_not_called()
    errors.assert_called_once()
    panel.calibre_send_btn.configure.assert_called_with(state="normal")


def test_manual_existing_remote_overwrite_confirmation_is_retained(monkeypatch, tmp_path):
    path = tmp_path / "book.epub"
    path.write_bytes(b"new")
    client = Mock()
    client.remote_file_exists.return_value = True
    start = Mock()
    confirm = Mock(return_value=False)
    monkeypatch.setattr(actions.filedialog, "askopenfilenames", lambda **kwargs: [str(path)])
    monkeypatch.setattr(actions.messagebox, "askyesno", confirm)
    panel = SimpleNamespace(
        _busy=False, _selected_ip=lambda: "localhost", _current_path="/Books",
        _make_client=lambda: client, warn_overwrite_var=SimpleNamespace(get=lambda: True),
        _set_busy=Mock(), app=SimpleNamespace(_start_background_task=start),
    )
    actions.DeviceFilesActionsMixin._upload_to_current(panel)
    confirm.assert_called_once()
    start.assert_not_called()
    client.remote_file_exists.assert_called_once_with(
        "/Books", X3Uploader("localhost")._sanitize_filename(str(path)), ip="localhost")
