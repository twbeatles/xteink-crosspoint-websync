import json
import logging
import shutil
import pytest

from websync.backup.portable_cfg import apply_portable_cfg
from websync.backup.service import BackupSyncService
from websync.config.manager import ConfigManager
from websync.db.history import SyncHistoryDb


def make_pc(root, name):
    root.mkdir()
    shared = root / "cloud"
    shared.mkdir()
    cm = ConfigManager(str(root / "config.json"))
    config = cm.load_config()
    config["sites"] = [{"name": name, "type": "rss", "url": f"https://{name}.example/feed"}]
    apply_portable_cfg(config, {"enabled": True, "folder": str(shared)})
    cm.save_config(config)
    db = SyncHistoryDb(str(root / "history.db"))
    db.mark_synced(f"https://{name}.example/post", name, "Article", "dev_same")
    return BackupSyncService(cm, db, logging.Logger(name)), shared


def test_delayed_replica_sync_recovers_overwritten_canonical(tmp_path):
    first, cloud_a = make_pc(tmp_path / "a", "a")
    second, cloud_b = make_pc(tmp_path / "b", "b")
    assert first.push()["ok"]
    assert second.push()["ok"]
    # Two separate cloud replicas each publish while unaware of the other PC.
    # Simulate canonical B winning, but distinct installation snapshots syncing.
    for name in ("sites.json", "synced_posts.json", "manifest.json"):
        shutil.copy2(cloud_b / name, cloud_a / name)
    shutil.copytree(cloud_b / ".websync-replicas", cloud_a / ".websync-replicas", dirs_exist_ok=True)
    assert first.pull()["ok"]
    assert {site["name"] for site in first.config_manager.load_config()["sites"]} == {"a", "b"}
    assert first.db.get_count() == 2
    assert first.push()["ok"]
    shutil.copytree(cloud_a, cloud_b, dirs_exist_ok=True)
    assert second.pull()["ok"]
    assert second.db.get_count() == 2
    assert {site["name"] for site in second.config_manager.load_config()["sites"]} == {"a", "b"}


def test_corrupt_snapshot_stops_before_local_changes(tmp_path):
    service, cloud = make_pc(tmp_path / "a", "a")
    assert service.push()["ok"]
    before = service.config_manager.load_config()["sites"]
    snapshot = next((cloud / ".websync-replicas").glob("*.json"))
    snapshot.write_text('{"kind":"replica","sites":[]}', encoding="utf-8")
    assert not service.pull()["ok"]
    assert service.config_manager.load_config()["sites"] == before
    assert not service.push()["ok"]


def test_copied_config_on_another_pc_gets_new_writer(monkeypatch):
    from websync.backup.replicas import ensure_replica_id
    monkeypatch.setattr("websync.backup.replicas.socket.gethostname", lambda: "PC-A")
    config = {}
    first = ensure_replica_id(config)
    assert ensure_replica_id(config) == first
    monkeypatch.setattr("websync.backup.replicas.socket.gethostname", lambda: "PC-B")
    assert ensure_replica_id(config) != first


def test_snapshot_directory_cannot_redirect_outside_shared_folder(tmp_path):
    service, cloud = make_pc(tmp_path / "a", "a")
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.json"
    sentinel.write_text("private sentinel", encoding="utf-8")
    try:
        (cloud / ".websync-replicas").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not available")
    assert not service.push()["ok"]
    assert not service.pull()["ok"]
    assert sentinel.read_text(encoding="utf-8") == "private sentinel"
