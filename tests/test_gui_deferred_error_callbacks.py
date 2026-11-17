"""Deferred `after(0, ...)` error callbacks must not rely on `except ... as e`.

Regression: both callbacks below captured the `except ... as e` variable by
reference. `after(0, ...)` runs the callback after the handler returns, at
which point CPython has deleted `e` -> NameError on the error path and the
failure is never reported. The fix binds `e` eagerly (`lambda e=e` /
`def err(e=e)`).
"""

from types import SimpleNamespace
from unittest.mock import patch

from websync.gui.app_core.app import SyncAppGui
from websync.gui.settings_tab.backup_sync import SettingsBackupSyncMixin


def _deferred_root():
    callbacks = []

    def after(_delay, callback):
        callbacks.append(callback)

    return callbacks, SimpleNamespace(after=after)


def test_backup_pull_failure_callback_runs_after_handler_exit():
    callbacks, root = _deferred_root()
    messages = []
    service = SimpleNamespace(
        config={
            "backup_sync": {
                "enabled": True,
                "auto_import_on_start": True,
                "folder": "C:\\shared",
            }
        },
    )

    def maybe_backup_pull():
        raise RuntimeError("pull-boom")

    service.maybe_backup_pull = maybe_backup_pull
    host = SimpleNamespace(
        service=service,
        root=root,
        tab_sync=SimpleNamespace(_refresh_site_tree=lambda: None),
        tab_history=SimpleNamespace(_refresh_history=lambda: None),
        tab_settings=SimpleNamespace(_refresh_backup_status_label=lambda: None),
        _start_background_task=lambda target, **kwargs: target(),
        _log_message=messages.append,
    )
    SyncAppGui._start_backup_pull_if_enabled(host)
    assert len(callbacks) == 1
    callbacks[0]()  # NameError here before the fix
    assert any("pull-boom" in str(m) for m in messages)


def test_backup_sync_error_callback_runs_after_handler_exit():
    callbacks, root = _deferred_root()
    configured = []
    service = SimpleNamespace(
        config={"backup_sync": {"folder": "C:\\shared"}},
    )

    def run_backup_sync_now(*, log_callback=None):
        raise RuntimeError("sync-boom")

    service.run_backup_sync_now = run_backup_sync_now
    service._reload_config = lambda: None
    app = SimpleNamespace(
        root=root,
        _log_message=lambda _m: None,
        _make_log_callback=lambda: lambda _m: None,
        _start_background_task=lambda target, **kwargs: target(),
        tab_sync=SimpleNamespace(_refresh_site_tree=lambda: None),
        tab_history=SimpleNamespace(_refresh_history=lambda: None),
    )
    host = SimpleNamespace(
        service=service,
        app=app,
        backup_status_label=SimpleNamespace(
            configure=lambda **kwargs: configured.append(kwargs)
        ),
        _save_backup_sync_settings=lambda: None,
        _refresh_backup_status_label=lambda: None,
    )
    with patch("websync.gui.settings_tab.backup_sync.messagebox") as box:
        SettingsBackupSyncMixin._run_backup_sync_now(host)
        assert len(callbacks) == 1
        callbacks[0]()  # NameError here before the fix
    assert any(
        "sync-boom" in str(a) for c in box.showerror.call_args_list for a in c.args
    )
    assert any("sync-boom" in str(kw.get("text", "")) for kw in configured)
