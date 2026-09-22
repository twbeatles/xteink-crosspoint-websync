"""여러 PC가 같은 리더기를 쓸 때 이미 보낸 글이 다시 전송되지 않아야 합니다."""
import json
import os
import tempfile

from websync.backup.device_registry import reconcile_config_devices
from websync.backup.service import BackupSyncService
from websync.config.manager import ConfigManager
from websync.db.history import SyncHistoryDb
from websync.upload.device_ids import (
    alias_key_groups,
    build_targets_with_keys,
    history_keys_from_targets,
)


def _service(root: str, name: str, ip: str, device_id: str, cloud: str):
    cm = ConfigManager(os.path.join(root, f"{name}.json"))
    cfg = cm.load_config()
    cfg["x3_ip"] = ip
    cfg["x3_primary_device_id"] = device_id
    cfg["sites"] = [
        {
            "name": "Blog",
            "type": "rss",
            "url": "https://blog.example/feed",
            "limit": 5,
            "enabled": True,
        }
    ]
    cfg["backup_sync"] = {
        "enabled": True,
        "folder": cloud,
        "include_history": True,
        "auto_export": True,
        "auto_import_on_start": True,
    }
    cm.save_config(cfg)
    db = SyncHistoryDb(os.path.join(root, f"{name}.db"))
    return cm, db, BackupSyncService(cm, db)


def _needs_sync(cm: ConfigManager, db: SyncHistoryDb, url: str) -> bool:
    cfg = cm.load_config()
    targets = build_targets_with_keys(
        cfg.get("x3_ip", ""),
        cfg.get("x3_devices") or [],
        primary_id=cfg.get("x3_primary_device_id") or "",
        primary_alias_ids=cfg.get("x3_primary_device_alias_ids") or [],
    )
    return db.needs_sync(
        url,
        history_keys_from_targets(targets),
        history_mode="per_device",
        key_aliases=alias_key_groups(targets),
    )


def test_same_reader_on_another_pc_skips_posts_already_sent():
    url = "https://blog.example/already-sent"
    tmp = tempfile.mkdtemp()
    cloud = os.path.join(tmp, "cloud")
    os.makedirs(cloud)
    try:
        cm1, db1, svc1 = _service(tmp, "pc1", "192.168.1.20", "dev_bbbb", cloud)
        db1.mark_synced(url, "Blog", "이미 보낸 글", device_ip="dev_bbbb")
        pushed = svc1.push(force=True)
        assert pushed["ok"] is True

        cm2, db2, svc2 = _service(tmp, "pc2", "192.168.1.20", "dev_aaaa", cloud)
        pulled = svc2.pull(force=True)
        assert pulled["ok"] is True

        assert _needs_sync(cm2, db2, url) is False
        adopted = cm2.load_config()
        assert adopted["x3_primary_device_id"] == "dev_aaaa"
        assert "dev_bbbb" in (adopted.get("x3_primary_device_alias_ids") or [])
    finally:
        try:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except OSError:
            pass


def test_owner_pull_publishes_device_for_legacy_history_file():
    """devices 가 없는 기존 이력도, 그 기기 ID를 가진 PC가 열리면 다른 PC는 건너뜁니다."""
    url = "https://blog.example/legacy"
    tmp = tempfile.mkdtemp()
    cloud = os.path.join(tmp, "cloud")
    os.makedirs(cloud)
    history_path = os.path.join(cloud, "synced_posts.json")
    try:
        with open(history_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "export_version": 2,
                    "kind": "synced_posts",
                    "exported_at": "2026-01-01T00:00:00Z",
                    "posts": [
                        {
                            "url": url,
                            "device_ip": "dev_bbbb",
                            "site_name": "Blog",
                            "title": "예전 글",
                            "synced_at": "2026-01-01T00:00:00Z",
                        }
                    ],
                    "deleted_posts": [],
                },
                handle,
            )
        cm1, _db1, svc1 = _service(tmp, "pc1", "192.168.1.20", "dev_bbbb", cloud)
        assert svc1.pull(force=True)["ok"] is True
        with open(history_path, encoding="utf-8") as handle:
            published = json.load(handle)
        assert published["devices"][0]["id"] == "dev_bbbb"
        assert "192.168.1.20" in published["devices"][0]["hosts"]

        cm2, db2, svc2 = _service(tmp, "pc2", "192.168.1.20", "dev_aaaa", cloud)
        assert svc2.pull(force=True)["ok"] is True
        assert _needs_sync(cm2, db2, url) is False
    finally:
        try:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except OSError:
            pass


def test_different_reader_address_stays_pending():
    url = "https://blog.example/for-other-device"
    tmp = tempfile.mkdtemp()
    cloud = os.path.join(tmp, "cloud")
    os.makedirs(cloud)
    try:
        cm1, db1, svc1 = _service(tmp, "pc1", "192.168.1.20", "dev_bbbb", cloud)
        db1.mark_synced(url, "Blog", "다른 기기 글", device_ip="dev_bbbb")
        assert svc1.push(force=True)["ok"] is True

        cm2, db2, svc2 = _service(tmp, "pc2", "10.0.0.9", "dev_aaaa", cloud)
        assert svc2.pull(force=True)["ok"] is True

        assert _needs_sync(cm2, db2, url) is True
        adopted = cm2.load_config()
        assert adopted["x3_primary_device_id"] == "dev_aaaa"
        assert "dev_bbbb" not in (adopted.get("x3_primary_device_alias_ids") or [])
    finally:
        try:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except OSError:
            pass


def test_reconcile_keeps_current_host_and_other_devices():
    config = {
        "x3_ip": "192.168.1.30",
        "x3_primary_device_id": "dev_aaaa",
        "x3_devices": [{"name": "서재", "ip": "10.0.0.5", "id": "dev_local_other"}],
    }
    remote = [
        {
            "id": "dev_aaaa",
            "hosts": ["192.168.1.20"],
            "alias_ids": ["dev_bbbb"],
            "name": "",
        },
        {"id": "dev_bedroom", "hosts": ["10.1.1.1"], "alias_ids": [], "name": "침실"},
    ]
    export, changed = reconcile_config_devices(config, remote)
    assert changed is True
    assert config["x3_primary_device_alias_ids"] == ["dev_bbbb"]
    assert config["x3_devices"][0]["id"] == "dev_local_other"
    assert "alias_ids" not in config["x3_devices"][0]
    by_id = {item["id"]: item for item in export}
    assert by_id["dev_aaaa"]["hosts"] == ["192.168.1.30"]
    assert by_id["dev_local_other"]["hosts"] == ["10.0.0.5"]
    assert by_id["dev_bedroom"]["hosts"] == ["10.1.1.1"]
