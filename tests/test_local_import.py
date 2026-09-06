"""로컬 사이드카 JSON (synced_posts / 설정백업) 호환 테스트.

dist/ 배포 폴더는 gitignore 이므로 CI·클론 환경에 없습니다.
실제 dist 샘플과 동일한 스키마를 임시 파일로 만들어 검증합니다.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from websync.backup.format import extract_posts, extract_sites
from websync.backup.local_import import import_local_sidecars
from websync.config.manager import ConfigManager
from websync.db.history import SyncHistoryDb
from websync.upload.device_ids import build_targets_with_keys, resolve_pending_upload_ips

# dist 실물 샘플과 동일한 스키마 (kind 없는 레거시 설정 백업 포함)
SAMPLE_HISTORY = {
    "export_version": 1,
    "kind": "synced_posts",
    "exported_at": "2026-07-20T12:00:00",
    "posts": [
        {
            "url": "https://blog.naver.com/example/1",
            "device_ip": "crosspoint.local",
            "site_name": "example",
            "title": "첫 글",
            "synced_at": "2026-07-20T10:00:00",
        }
    ],
}

# 레거시: kind 없음, sites 배열만 (예: dist 의 *설정백업*.json / 블로그 설정.json)
SAMPLE_SITES_BACKUP = {
    "export_version": 1,
    "exported_at": "2026-07-14T20:50:47.348179",
    "sites": [
        {
            "name": "예시 블로그",
            "type": "rss",
            "url": "https://blog.example/feed",
            "limit": 5,
            "enabled": True,
        }
    ],
}


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_synced_posts_format():
    posts, exported_at = extract_posts(SAMPLE_HISTORY)
    assert SAMPLE_HISTORY.get("kind") == "synced_posts"
    assert len(posts) >= 1
    assert posts[0].get("url")
    assert posts[0].get("device_ip")
    assert exported_at


def test_settings_backup_format_without_kind():
    sites, exported_at = extract_sites(SAMPLE_SITES_BACKUP)
    # kind 없어도 sites 배열만 있으면 됨 (레거시 설정 백업)
    assert "kind" not in SAMPLE_SITES_BACKUP or SAMPLE_SITES_BACKUP.get("kind") in (
        None,
        "sites",
    )
    assert len(sites) >= 1
    assert sites[0].get("url")
    assert exported_at


def test_import_sidecars_into_fresh_local():
    # Windows 에서 SQLite 핸들이 잡힌 채 TemporaryDirectory 정리하면 PermissionError
    tmp = tempfile.mkdtemp()
    try:
        root = Path(tmp)
        history_name = "synced_posts.json"
        # 파일명에 '설정백업' 이 있으면 사이드카 후보로 인식
        sites_name = "260720 설정백업.json"
        _write_json(root / history_name, SAMPLE_HISTORY)
        _write_json(root / sites_name, SAMPLE_SITES_BACKUP)

        cm = ConfigManager(str(root / "config.json"))
        cfg = cm.load_config()
        cfg["sites"] = []  # 비운 뒤 사이드카로 채움
        cm.save_config(cfg)

        db = SyncHistoryDb(str(root / "history.db"))
        result = import_local_sidecars(cm, db, root=str(root))
        assert result["ok"] is True
        assert result["history_changed"] > 0
        assert result["sites_changed"] is True
        assert db.get_count() > 0

        # 전역 URL fallback은 사용하지 않고 명시된 legacy alias로만 스킵
        sample_url = db.export_all_posts()[0]["url"]
        assert db.is_synced(sample_url)
        assert db.needs_sync(sample_url, ["192.168.31.54"], history_mode="per_device")

        targets = build_targets_with_keys("192.168.31.54", primary_id="dev_testprimary")
        pending = resolve_pending_upload_ips(
            db.is_synced_for_device,
            db.is_synced,
            [sample_url],
            targets,
            history_mode="per_device",
        )
        assert pending == []

        cfg2 = cm.load_config()
        assert len(cfg2.get("sites") or []) >= 1
        del db
        del cm
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_needs_sync_single_device_legacy_host():
    """이전 주소는 명시적 alias일 때만 같은 기기로 인정합니다."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = SyncHistoryDb(path)
        url = "https://blog.naver.com/example/1"
        db.mark_synced(url, "site", "t", device_ip="crosspoint.local")
        assert db.needs_sync(url, ["192.168.31.54"])
        assert not db.needs_sync(
            url,
            ["dev_primary"],
            key_aliases=[["dev_primary", "192.168.31.54", "crosspoint.local"]],
        )
        assert db.needs_sync(url, ["192.168.31.54", "10.0.0.2"])  # 다중 기기는 엄격
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
