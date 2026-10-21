"""External settings are rejected before any persistent state can change."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from websync.config.manager import ConfigManager
from websync.config.exceptions import ConfigLoadError, ConfigSaveError
from websync.config.validator import validate_config, validate_config_issues, validate_site_issues


def manager(tmp_path):
    cm = ConfigManager(str(tmp_path / "config.json"))
    cm.save_config({"sites": []})
    cm.load_config()
    return cm


def snapshots(cm):
    return {suffix: Path(cm.config_path + suffix).read_bytes() for suffix in ("", ".bak")}


@pytest.mark.parametrize("bad", [None, [], 3, {"name": None, "url": "https://a", "type": "rss"},
    {"name": "bad", "url": ["https://a"], "type": "rss"},
    {"name": "bad", "url": "https://a", "type": "rss", "enabled": "false"},
    {"name": "bad", "url": "https://a", "type": "rss", "limit": 0},
    {"name": "bad", "url": "https://", "type": "rss"},
    {"name": "bad", "url": "https://a", "type": "css", "item_selector": "[[["}])
def test_import_rejection_is_all_or_nothing(tmp_path, bad):
    cm = manager(tmp_path)
    before = snapshots(cm)
    source = tmp_path / "import.json"
    source.write_text(json.dumps({"sites": [{"name": "valid", "url": "https://valid", "type": "rss"}, bad]}), encoding="utf-8")
    with pytest.raises(ConfigLoadError):
        cm.import_sites(str(source))
    assert snapshots(cm) == before
    assert cm.load_config()["sites"] == []


@pytest.mark.parametrize("patch", [{"sites": None}, {"sites": [None]}, {"sites": [{"_sync_updated_at": 42}]}, {"calibre_watch": {"pending_files": [None]}}, {"x3_devices": [{"alias_ids": [3]}]}, {"opds_server": None},
    {"font_size": {}}, {"config_version": []}, {"config_version": "3"}, {"_config_revision": "0"}, {"_config_revision": None},
    {"x3_devices": [3]}, {"portable_data": {"deleted_sites": [None]}},
    {"line_height": float("nan")}, {"web_dashboard": {"port": float("inf")}}])
def test_save_and_rmw_reject_before_mutation(tmp_path, patch):
    cm = manager(tmp_path)
    before = snapshots(cm)
    cfg = cm.load_config()
    cfg.update(patch)
    revision = cfg.get("_config_revision")
    with pytest.raises(ConfigSaveError):
        cm.save_config(cfg)
    assert cfg.get("_config_revision") == revision
    with pytest.raises(ConfigSaveError):
        cm.update_config(lambda candidate: candidate.update(patch))
    assert snapshots(cm) == before


@pytest.mark.parametrize("bad", [[], None, {"sites": [{"name": None}]}, {"opds_server": []}, {"config_version": "3"}])
def test_load_rejects_before_normalization_write(tmp_path, bad):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ConfigLoadError):
        ConfigManager(str(path)).load_config()
    assert path.read_bytes() == before
    assert not Path(str(path) + ".bak").exists()


def test_explicit_recovery_preserves_bad_original_and_good_backup(tmp_path):
    cm = manager(tmp_path)
    backup = Path(cm.config_path + ".bak")
    backup_bytes = backup.read_bytes()
    rejected = b'{"sites":[{"name":null}]}'
    Path(cm.config_path).write_bytes(rejected)
    preserved = cm.restore_config(str(backup))
    assert Path(preserved).read_bytes() == rejected
    assert backup.read_bytes() == backup_bytes
    assert cm.load_config()["sites"] == []


@pytest.mark.parametrize("bad", [{"sites": None}, {"config_version": "3"}, {"calibre_watch": {"pending_files": [None]}}, {"sites": [{"_sync_updated_at": 42}]}])
def test_invalid_recovery_does_not_change_config_or_backup(tmp_path, bad):
    cm = manager(tmp_path)
    before = snapshots(cm)
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ConfigLoadError):
        cm.restore_config(str(source))
    assert snapshots(cm) == before
    assert not list(tmp_path.glob("*.rejected.*"))


def test_structured_validation_has_stable_field_code_and_legacy_strings():
    issues = validate_config_issues({"sites": [{"name": None}]})
    assert issues[0].field == "sites[0].name"
    assert issues[0].code == "type"
    assert validate_config({"sites": [{"name": None}]}) == [i.message for i in issues]
    issues = validate_site_issues({"name": "x", "url": "https://a", "type": "rss", "limit": 0})
    assert issues[0].field == "limit" and issues[0].code == "invalid_value"


def test_legacy_semantic_warning_remains_loadable(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"sites": [], "font_size": 99}), encoding="utf-8")
    assert ConfigManager(str(path)).load_config()["font_size"] == 99


def test_gui_cancel_has_no_recovery_write(monkeypatch):
    from websync.gui import config_recovery
    root = Mock()
    monkeypatch.setattr(config_recovery.tk, "Tk", lambda: root)
    monkeypatch.setattr(config_recovery.messagebox, "askyesno", lambda *a, **k: False)
    cm = SimpleNamespace(config_path="unused.json", restore_config=Mock())
    assert not config_recovery.offer_config_recovery(cm, ConfigLoadError("bad"))
    cm.restore_config.assert_not_called()
    root.destroy.assert_called_once()


@pytest.mark.parametrize("source,restore_error,expected", [("chosen.json", None, True), ("", None, False), ("chosen.json", ConfigLoadError("bad source"), False)])
def test_gui_chosen_recovery_cleans_up_on_every_exit(monkeypatch, source, restore_error, expected):
    from websync.gui import config_recovery
    root = Mock()
    monkeypatch.setattr(config_recovery.tk, "Tk", lambda: root)
    monkeypatch.setattr(config_recovery.os.path, "isfile", lambda path: False)
    monkeypatch.setattr(config_recovery.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(config_recovery.messagebox, "showinfo", Mock())
    monkeypatch.setattr(config_recovery.messagebox, "showerror", Mock())
    monkeypatch.setattr(config_recovery.filedialog, "askopenfilename", lambda **kwargs: source)
    cm = SimpleNamespace(config_path="unused.json", restore_config=Mock(return_value="preserved.json", side_effect=restore_error))
    assert config_recovery.offer_config_recovery(cm, ConfigLoadError("bad")) is expected
    root.destroy.assert_called_once()
    if source:
        cm.restore_config.assert_called_once_with(source)
    else:
        cm.restore_config.assert_not_called()


def test_cli_explicit_recovery_and_sync_failure(monkeypatch):
    import x3_websync
    from websync.gui import config_recovery
    cm = Mock()
    cm.restore_config.return_value = "rejected.json"
    cm.load_config.side_effect = ConfigLoadError("invalid settings")
    monkeypatch.setattr(x3_websync, "ConfigManager", lambda: cm)
    monkeypatch.setattr(x3_websync, "acquire_instance_lock", lambda: True)
    monkeypatch.setattr(x3_websync, "release_instance_lock", Mock())
    monkeypatch.setattr(x3_websync, "SyncService", Mock())
    offer = Mock()
    monkeypatch.setattr(config_recovery, "offer_config_recovery", offer)
    monkeypatch.setattr("sys.argv", ["x3_websync.py", "--recover-config", "backup.json"])
    with pytest.raises(SystemExit) as outcome:
        x3_websync.main()
    assert outcome.value.code == 0
    cm.restore_config.assert_called_once_with("backup.json")
    cm.load_config.assert_not_called()
    monkeypatch.setattr("sys.argv", ["x3_websync.py", "--sync"])
    with pytest.raises(SystemExit) as outcome:
        x3_websync.main()
    assert outcome.value.code == 1
    offer.assert_not_called()
    x3_websync.SyncService.assert_not_called()


def test_recovery_accepts_config_with_only_semantic_warnings(tmp_path):
    """load_config가 경고만 남기고 읽는 설정은 복구도 허용한다 (구조 오류만 거부)."""
    cm = manager(tmp_path)
    good = cm.load_config()
    good["web_dashboard"]["port"] = 80
    good["sites"] = [{"name": "legacy", "type": "css", "url": "https://example.test/", "item_selector": ""}]
    source = tmp_path / "warned.json"
    source.write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
    assert validate_config(good)  # semantic warnings exist
    backup_before = Path(cm.config_path + ".bak").read_bytes()
    rejected = b'{"sites": "oops"}'
    Path(cm.config_path).write_bytes(rejected)
    with pytest.raises(ConfigLoadError):
        cm.load_config()

    preserved = cm.restore_config(str(source))

    assert Path(preserved).read_bytes() == rejected
    assert Path(cm.config_path + ".bak").read_bytes() == backup_before
    loaded = cm.load_config()
    assert loaded["web_dashboard"]["port"] == 80
    assert loaded["sites"][0]["name"] == "legacy"
