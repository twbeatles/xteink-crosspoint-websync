import os
import sqlite3
import tempfile
import threading
import time

import pytest

from websync.db.history import SyncHistoryDb, SyncHistoryDbError, LEGACY_DEVICE_IP


def _make_db() -> tuple[SyncHistoryDb, str]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return SyncHistoryDb(path), path


def _cleanup_db(db: SyncHistoryDb, path: str):
    del db
    time.sleep(0.05)
    try:
        os.remove(path)
    except OSError:
        pass


def test_mark_and_is_synced():
    db, path = _make_db()
    try:
        assert not db.is_synced("https://example.com/1")
        db.mark_synced("https://example.com/1", "site", "title", device_ip="192.168.1.1")
        assert db.is_synced("https://example.com/1")
        assert db.is_synced_for_device("https://example.com/1", "192.168.1.1")
    finally:
        _cleanup_db(db, path)


def test_needs_sync_per_device():
    db, path = _make_db()
    try:
        url = "https://example.com/1"
        db.mark_synced(url, "site", "title", device_ip="10.0.0.1")
        assert db.needs_sync(url, ["10.0.0.1", "10.0.0.2"])
        assert not db.needs_sync(url, ["10.0.0.1"])
        db.mark_synced(url, "site", "title", device_ip="10.0.0.2")
        assert not db.needs_sync(url, ["10.0.0.1", "10.0.0.2"])
    finally:
        _cleanup_db(db, path)


def test_needs_sync_global_url_mode():
    db, path = _make_db()
    try:
        url = "https://example.com/global"
        db.mark_synced(url, "site", "title", device_ip="10.0.0.1")
        # 다른 기기 키가 대상이어도 URL 이력이 있으면 스킵
        assert not db.needs_sync(
            url, ["10.0.0.2", "10.0.0.3"], history_mode="global_url"
        )
        assert db.pending_device_ips(url, ["10.0.0.2"], history_mode="global_url") == []
        assert db.needs_sync(
            "https://example.com/new",
            ["10.0.0.2"],
            history_mode="global_url",
        )
        assert db.pending_device_ips(
            "https://example.com/new", ["10.0.0.2", "10.0.0.3"], history_mode="global_url"
        ) == ["10.0.0.2", "10.0.0.3"]
        # per_device + 다중 기기: 미전송 기기 존재
        assert db.needs_sync(url, ["10.0.0.2", "10.0.0.3"], history_mode="per_device")
        # per_device + 단일 기기라도 다른 기기 키의 이력을 전역 완료로 취급하지 않음
        assert db.needs_sync(url, ["10.0.0.2"], history_mode="per_device")
    finally:
        _cleanup_db(db, path)


def test_legacy_migration():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with sqlite3.connect(path) as conn:
            conn.execute("""
                CREATE TABLE synced_posts (
                    url TEXT PRIMARY KEY,
                    site_name TEXT,
                    title TEXT,
                    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute(
                "INSERT INTO synced_posts (url, site_name, title) VALUES (?, ?, ?)",
                ("https://legacy.com/1", "s", "t"),
            )
            conn.commit()
        db = SyncHistoryDb(path)
        # 레거시 * 행은 더 이상 모든 기기에 완료로 취급하지 않음
        assert not db.is_synced_for_device("https://legacy.com/1", "192.168.0.5")
        assert db.is_synced("https://legacy.com/1")
        # 이관 후 해당 기기만 완료
        n = db.remap_legacy_star_to_device("192.168.0.5")
        assert n >= 1
        assert db.is_synced_for_device("https://legacy.com/1", "192.168.0.5")
        assert not db.is_synced_for_device("https://legacy.com/1", "10.0.0.9")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def test_pending_device_ips_empty_targets():
    db, path = _make_db()
    try:
        url = "https://example.com/pending"
        assert db.pending_device_ips(url, []) == []
        db.mark_synced(url, "s", "t", device_ip="10.0.0.1")
        assert db.pending_device_ips(url, ["10.0.0.1", "10.0.0.2"]) == ["10.0.0.2"]
        assert db.pending_device_ips(url, ["10.0.0.1"]) == []
    finally:
        _cleanup_db(db, path)


def test_delete_entry_raises_on_error():
    db, path = _make_db()
    try:
        db.mark_synced("https://x.com/1", "s", "t", device_ip="1.1.1.1")
        # 잘못된 경로로 연결 유도: db_path 변경 후 delete
        db.db_path = os.path.join(tempfile.gettempdir(), "nonexistent_dir_xyz", "no.db")
        with pytest.raises(SyncHistoryDbError):
            db.delete_entry("https://x.com/1")
    finally:
        # path 원본 정리는 실패할 수 있음
        try:
            _cleanup_db(db, path)
        except Exception:
            pass


def test_concurrent_access():
    db, path = _make_db()
    try:
        def worker(i):
            url = f"https://example.com/{i}"
            db.mark_synced(url, "s", f"t{i}", device_ip=f"10.0.0.{i % 5}")
            db.is_synced(url)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert db.get_count() == 20
    finally:
        _cleanup_db(db, path)


def test_export_all_posts_and_import_union():
    db, path = _make_db()
    try:
        db.mark_synced("https://a.com/1", "s1", "t1", device_ip="10.0.0.1")
        db.mark_synced("https://a.com/1", "s1", "t1", device_ip="10.0.0.2")
        posts = db.export_all_posts()
        assert len(posts) == 2
        assert all("url" in p and "device_ip" in p for p in posts)

        db2, path2 = _make_db()
        try:
            # 한쪽만 있는 이력 + 동일 키 갱신
            db2.mark_synced("https://a.com/1", "old", "old title", device_ip="10.0.0.1")
            changed = db2.import_posts_union(
                [
                    {
                        "url": "https://a.com/1",
                        "device_ip": "10.0.0.1",
                        "site_name": "s1",
                        "title": "t1-new",
                        "synced_at": "2099-01-01 00:00:00",
                    },
                    {
                        "url": "https://a.com/1",
                        "device_ip": "10.0.0.2",
                        "site_name": "s1",
                        "title": "t1",
                        "synced_at": "2026-01-01 00:00:00",
                    },
                    {
                        "url": "https://b.com/2",
                        "device_ip": "10.0.0.1",
                        "site_name": "s2",
                        "title": "tb",
                        "synced_at": "2026-01-02 00:00:00",
                    },
                ]
            )
            assert changed >= 2
            assert db2.is_synced_for_device("https://a.com/1", "10.0.0.1")
            assert db2.is_synced_for_device("https://a.com/1", "10.0.0.2")
            assert db2.is_synced_for_device("https://b.com/2", "10.0.0.1")
            exported = db2.export_all_posts()
            row = next(
                p
                for p in exported
                if p["url"] == "https://a.com/1" and p["device_ip"] == "10.0.0.1"
            )
            assert row["title"] == "t1-new"
            assert "2099" in (row["synced_at"] or "")
        finally:
            _cleanup_db(db2, path2)
    finally:
        _cleanup_db(db, path)


def test_is_synced_raises_on_db_error():
    from unittest.mock import patch

    db, path = _make_db()
    try:
        db.mark_synced("https://example.com/x", "s", "t", device_ip="1.1.1.1")

        def bad_connect(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        with patch("websync.db.history.sqlite3.connect", side_effect=bad_connect):
            with pytest.raises(SyncHistoryDbError):
                db.is_synced("https://example.com/x")
    finally:
        _cleanup_db(db, path)


def test_mark_synced_raises_on_db_error():
    from unittest.mock import patch

    db, path = _make_db()
    try:
        def bad_connect(*args, **kwargs):
            raise sqlite3.OperationalError("disk I/O error")

        with patch("websync.db.history.sqlite3.connect", side_effect=bad_connect):
            with pytest.raises(SyncHistoryDbError):
                db.mark_synced("https://example.com/x", "s", "t", device_ip="1.1.1.1")
    finally:
        _cleanup_db(db, path)


def test_init_db_failure_raises():
    from unittest.mock import patch

    with patch("websync.db.history.sqlite3.connect", side_effect=OSError("permission denied")):
        with pytest.raises(SyncHistoryDbError, match="DB 초기화 실패"):
            SyncHistoryDb(os.path.join(tempfile.gettempdir(), "nonexistent_sub/db.db"))


def test_db_wal_mode_enabled():
    db, path = _make_db()
    try:
        with db._connect() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.lower() == "wal"
    finally:
        _cleanup_db(db, path)


def test_deleted_history_tombstone_blocks_stale_remote_and_allows_resend():
    db, path = _make_db()
    try:
        url = "https://example.com/deleted"
        device = "dev_primary"
        db.mark_synced(url, "site", "old", device_ip=device)
        old_post = db.export_all_posts()[0]

        db.delete_entry(url)
        tombstones = db.export_deleted_posts()
        assert len(tombstones) == 1
        assert not db.is_synced_for_device(url, device)

        assert db.import_posts_union([old_post]) == 0
        assert not db.is_synced_for_device(url, device)

        db.mark_synced(url, "site", "resent", device_ip=device)
        assert db.is_synced_for_device(url, device)
        assert db.export_deleted_posts() == []
    finally:
        _cleanup_db(db, path)


def test_import_newer_tombstone_removes_local_history():
    db, path = _make_db()
    try:
        url = "https://example.com/remote-delete"
        device = "dev_other"
        db.mark_synced(url, "site", "title", device_ip=device)
        changed = db.import_deleted_posts(
            [{"url": url, "device_ip": device, "deleted_at": "2099-01-01T00:00:00"}]
        )
        assert changed == 1
        assert not db.is_synced_for_device(url, device)
    finally:
        _cleanup_db(db, path)
