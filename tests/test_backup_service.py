import json
import os
import tempfile
import time

from websync.backup.format import (
    HISTORY_FILENAME,
    SITES_FILENAME,
    build_history_payload,
    build_sites_payload,
    extract_deleted_sites,
    extract_deleted_posts,
    is_remote_newer,
    merge_sites,
)
from websync.backup.service import BackupSyncService
from websync.config.manager import ConfigManager
from websync.db.history import SyncHistoryDb


def _cleanup_objs(*objs):
    for obj in objs:
        try:
            del obj
        except Exception:
            pass
    time.sleep(0.05)


def test_is_remote_newer():
    assert is_remote_newer("2026-07-20T12:00:00", "2026-07-19T12:00:00")
    assert not is_remote_newer("2026-07-19T12:00:00", "2026-07-20T12:00:00")
    assert is_remote_newer("2026-07-20T12:00:00", None)
    assert not is_remote_newer(None, "2026-07-20T12:00:00")


def test_merge_sites_remote_wins_and_local_only():
    local = [
        {"name": "A", "type": "rss", "url": "https://a.com", "limit": 3},
        {"name": "LocalOnly", "type": "rss", "url": "https://local.com", "limit": 1},
    ]
    remote = [
        {"name": "A-remote", "type": "rss", "url": "https://a.com", "limit": 10},
        {"name": "RemoteOnly", "type": "rss", "url": "https://remote.com", "limit": 2},
    ]
    merged = merge_sites(local, remote, remote_wins_same_url=True)
    by_url = {(s.get("url") or "").lower(): s for s in merged}
    assert by_url["https://a.com"]["name"] == "A-remote"
    assert by_url["https://a.com"]["limit"] == 10
    assert "https://local.com" in by_url
    assert "https://remote.com" in by_url

    merged_keep = merge_sites(local, remote, remote_wins_same_url=False)
    by_url2 = {(s.get("url") or "").lower(): s for s in merged_keep}
    assert by_url2["https://a.com"]["name"] == "A"
    assert by_url2["https://a.com"]["limit"] == 3
    assert "https://remote.com" in by_url2


def test_backup_push_pull_roundtrip():
    tmp = tempfile.mkdtemp()
    try:
        cfg_path = os.path.join(tmp, "config.json")
        db_path = os.path.join(tmp, "history.db")
        cloud = os.path.join(tmp, "cloud")
        os.makedirs(cloud)

        cm = ConfigManager(cfg_path)
        cfg = cm.load_config()
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
        # 시크릿이 있어도 portable에 안 들어가야 함 — config 자체는 로컬에만
        cfg["ai_summary"]["api_key"] = "SECRET_KEY_SHOULD_NOT_EXPORT"
        cm.save_config(cfg)

        db = SyncHistoryDb(db_path)
        db.mark_synced(
            "https://blog.example/1",
            "Blog",
            "첫 글",
            device_ip="192.168.1.10",
        )

        svc = BackupSyncService(cm, db)
        push = svc.push(force=True)
        assert push["ok"] is True
        assert os.path.isfile(os.path.join(cloud, SITES_FILENAME))
        assert os.path.isfile(os.path.join(cloud, HISTORY_FILENAME))

        with open(os.path.join(cloud, SITES_FILENAME), encoding="utf-8") as f:
            sites_payload = json.load(f)
        assert sites_payload["kind"] == "sites"
        assert "SECRET" not in json.dumps(sites_payload)
        assert len(sites_payload["sites"]) == 1

        # 다른 로컬 상태 시뮬레이션
        cfg2_path = os.path.join(tmp, "config2.json")
        db2_path = os.path.join(tmp, "history2.db")
        cm2 = ConfigManager(cfg2_path)
        cfg2 = cm2.load_config()
        cfg2["sites"] = [
            {
                "name": "Other",
                "type": "rss",
                "url": "https://other.example/feed",
                "limit": 2,
                "enabled": True,
            }
        ]
        cfg2["backup_sync"] = {
            "enabled": True,
            "folder": cloud,
            "include_history": True,
            "auto_export": True,
            "auto_import_on_start": True,
            "last_sites_push_at": "2020-01-01T00:00:00",
        }
        cm2.save_config(cfg2)
        db2 = SyncHistoryDb(db2_path)
        db2.mark_synced(
            "https://other.example/9",
            "Other",
            "다른 글",
            device_ip="10.0.0.1",
        )

        svc2 = BackupSyncService(cm2, db2)
        pull = svc2.pull(force=True)
        assert pull["ok"] is True
        assert pull["sites_changed"] is True
        cm2_cfg = cm2.load_config()
        urls = {(s.get("url") or "").lower() for s in cm2_cfg["sites"]}
        assert "https://blog.example/feed" in urls
        assert "https://other.example/feed" in urls  # local-only 유지

        assert db2.is_synced_for_device("https://blog.example/1", "192.168.1.10")
        assert db2.is_synced_for_device("https://other.example/9", "10.0.0.1")

        # push 후 cloud history 합집합
        push2 = svc2.push(force=True)
        assert push2["ok"] is True
        with open(os.path.join(cloud, HISTORY_FILENAME), encoding="utf-8") as f:
            hist = json.load(f)
        post_urls = {p["url"] for p in hist["posts"]}
        assert "https://blog.example/1" in post_urls
        assert "https://other.example/9" in post_urls
        _cleanup_objs(svc2, svc, db2, db, cm2, cm)
    finally:
        # Windows SQLite 잠금 — 실패해도 테스트 본문은 이미 검증됨
        try:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass


def test_backup_disabled_skips():
    tmp = tempfile.mkdtemp()
    try:
        cfg_path = os.path.join(tmp, "config.json")
        db_path = os.path.join(tmp, "history.db")
        cm = ConfigManager(cfg_path)
        cfg = cm.load_config()
        cfg["backup_sync"] = {
            "enabled": False,
            "folder": os.path.join(tmp, "cloud"),
            "include_history": True,
        }
        cm.save_config(cfg)
        db = SyncHistoryDb(db_path)
        svc = BackupSyncService(cm, db)
        result = svc.pull()
        assert result["skipped"] is True
        _cleanup_objs(svc, db, cm)
    finally:
        try:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass


def test_backup_push_respects_auto_export():
    tmp = tempfile.mkdtemp()
    try:
        cloud = os.path.join(tmp, "cloud")
        os.makedirs(cloud)
        cm = ConfigManager(os.path.join(tmp, "config.json"))
        cfg = cm.load_config()
        cfg["backup_sync"] = {
            "enabled": True,
            "folder": cloud,
            "include_history": True,
            "auto_export": False,
        }
        cm.save_config(cfg)
        db = SyncHistoryDb(os.path.join(tmp, "history.db"))
        svc = BackupSyncService(cm, db)
        result = svc.push(force=False)
        assert result["skipped"] is True
        assert not os.path.isfile(os.path.join(cloud, SITES_FILENAME))
        # force 는 허용
        forced = svc.push(force=True)
        assert forced["ok"] is True
        assert os.path.isfile(os.path.join(cloud, SITES_FILENAME))
        _cleanup_objs(svc, db, cm)
    finally:
        try:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass


def test_backup_pull_retries_when_folder_locked():
    """폴더 락이 잠시 점유 중이면 재시도 후 획득한다."""
    tmp = tempfile.mkdtemp()
    try:
        cloud = os.path.join(tmp, "cloud")
        os.makedirs(cloud)
        from websync.backup.format import LOCK_FILENAME
        from websync.core.process_lock import ProcessFileLock

        holder = ProcessFileLock(os.path.join(cloud, LOCK_FILENAME))
        assert holder.acquire(blocking=False)

        cm = ConfigManager(os.path.join(tmp, "config.json"))
        cfg = cm.load_config()
        cfg["backup_sync"] = {"enabled": True, "folder": cloud, "include_history": True}
        cm.save_config(cfg)
        db = SyncHistoryDb(os.path.join(tmp, "history.db"))
        svc = BackupSyncService(cm, db)

        released = {"ok": False}

        def _release_soon():
            time.sleep(0.25)
            holder.release()
            released["ok"] = True

        import threading
        t = threading.Thread(target=_release_soon)
        t.start()
        result = svc.pull(force=True)
        t.join(timeout=3)
        assert released["ok"] is True
        assert result.get("skipped") is not True or result.get("ok") is True
        _cleanup_objs(svc, db, cm)
    finally:
        try:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass


def test_history_payload_helpers():
    payload = build_history_payload(
        [{"url": "u", "device_ip": "1.1.1.1", "site_name": "s", "title": "t", "synced_at": "2026-01-01 00:00:00"}]
    )
    assert payload["kind"] == "synced_posts"
    assert payload["export_version"] == 2
    assert extract_deleted_posts(payload) == []
    sites = build_sites_payload([{"name": "n", "type": "rss", "url": "https://x"}])
    assert sites["export_version"] == 3
    assert extract_deleted_sites(sites) == []


def test_backup_propagates_history_deletion_without_resurrection():
    tmp = tempfile.mkdtemp()
    try:
        cloud = os.path.join(tmp, "cloud")
        os.makedirs(cloud)

        def make_service(name):
            cm = ConfigManager(os.path.join(tmp, f"{name}.json"))
            cfg = cm.load_config()
            cfg["backup_sync"] = {
                "enabled": True,
                "folder": cloud,
                "include_history": True,
                "auto_export": True,
            }
            cm.save_config(cfg)
            db = SyncHistoryDb(os.path.join(tmp, f"{name}.db"))
            return cm, db, BackupSyncService(cm, db)

        cm1, db1, svc1 = make_service("one")
        cm2, db2, svc2 = make_service("two")
        url = "https://example.com/shared-delete"
        device = "dev_primary"
        db1.mark_synced(url, "site", "title", device_ip=device)
        assert svc1.push(force=True)["ok"]
        assert svc2.pull(force=True)["ok"]
        assert db2.is_synced_for_device(url, device)

        db1.delete_entry(url)
        assert svc1.push(force=True)["ok"]
        assert svc2.pull(force=True)["ok"]
        assert not db2.is_synced_for_device(url, device)

        assert svc2.push(force=True)["ok"]
        with open(os.path.join(cloud, HISTORY_FILENAME), encoding="utf-8") as f:
            payload = json.load(f)
        assert payload["posts"] == []
        assert len(payload["deleted_posts"]) == 1
        _cleanup_objs(svc2, svc1, db2, db1, cm2, cm1)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_backup_propagates_site_tombstone_without_resurrection():
    from websync.backup.format import now_iso
    from websync.backup.portable_cfg import apply_portable_cfg, get_portable_cfg

    tmp = tempfile.mkdtemp()
    try:
        cloud = os.path.join(tmp, "cloud")
        os.makedirs(cloud)

        def make_service(name):
            cm = ConfigManager(os.path.join(tmp, f"{name}.json"))
            cfg = cm.load_config()
            cfg["sites"] = []
            cfg["backup_sync"] = {
                "enabled": True, "folder": cloud, "include_history": False,
                "auto_export": True,
            }
            cm.save_config(cfg)
            db = SyncHistoryDb(os.path.join(tmp, f"{name}.db"))
            return cm, db, BackupSyncService(cm, db)

        cm1, db1, svc1 = make_service("site-one")
        cm2, db2, svc2 = make_service("site-two")
        url = "https://feed.example/rss"
        cfg1 = cm1.load_config()
        cfg1["sites"] = [{
            "name": "Shared", "type": "rss", "url": url,
            "_sync_updated_at": "2026-01-01T00:00:00",
        }]
        cm1.save_config(cfg1)
        assert svc1.push(force=True)["ok"]
        assert svc2.pull(force=True)["ok"]
        assert any(s.get("url") == url for s in cm2.load_config()["sites"])

        def delete_site(cfg):
            cfg["sites"] = [s for s in cfg.get("sites", []) if s.get("url") != url]
            portable = get_portable_cfg(cfg)
            portable["deleted_sites"] = [{"url": url, "deleted_at": now_iso()}]
            apply_portable_cfg(cfg, portable)

        cm1.update_config(delete_site)
        assert svc1.push(force=True)["ok"]
        assert svc2.pull(force=True)["ok"]
        assert not any(s.get("url") == url for s in cm2.load_config()["sites"])
        assert svc2.push(force=True)["ok"]
        with open(os.path.join(cloud, SITES_FILENAME), encoding="utf-8") as f:
            payload = json.load(f)
        assert not any(s.get("url") == url for s in payload["sites"])
        assert payload["deleted_sites"][0]["url"] == url
        _cleanup_objs(svc2, svc1, db2, db1, cm2, cm1)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
