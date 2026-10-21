"""GUI revision-conflict merge must not revert fields owned by background writers."""
from __future__ import annotations

import copy

from websync.backup.portable_cfg import apply_portable_cfg, get_portable_cfg
from websync.gui.app_core.helpers import AppHelpersMixin

merge = AppHelpersMixin._merge_config_on_conflict


def _base() -> dict:
    cfg = {
        "_config_revision": 3,
        "x3_ip": "192.168.0.10",
        "x3_primary_device_id": "dev_local",
        "x3_primary_device_alias_ids": [],
        "x3_devices": [{"name": "Bedroom", "ip": "192.168.0.20", "id": "dev_b_local", "alias_ids": []}],
        "calibre_watch": {"enabled": True, "watch_dir": "C:/old", "pending_files": [], "pending_jobs": {}},
        "sites": [],
    }
    apply_portable_cfg(cfg, {"enabled": True, "folder": "C:/share", "deleted_sites": []})
    return cfg


def test_watch_queue_written_by_worker_survives_stale_gui_save():
    memory = _base()
    disk = copy.deepcopy(memory)
    disk["calibre_watch"]["pending_files"] = ["C:/lib/new.epub"]
    disk["calibre_watch"]["pending_jobs"] = {"C:/lib/new.epub": {}}
    memory["calibre_watch"]["watch_dir"] = "C:/new"

    out = merge(disk, memory)

    assert out["calibre_watch"]["watch_dir"] == "C:/new"
    assert out["calibre_watch"]["pending_files"] == ["C:/lib/new.epub"]
    assert out["calibre_watch"]["pending_jobs"] == {"C:/lib/new.epub": {}}


def test_completed_watch_job_is_not_restored_by_stale_memory():
    memory = _base()
    memory["calibre_watch"]["pending_files"] = ["C:/lib/done.epub"]
    memory["calibre_watch"]["pending_jobs"] = {"C:/lib/done.epub": {}}
    disk = _base()  # worker already removed the finished job

    out = merge(disk, memory)

    assert out["calibre_watch"]["pending_files"] == []
    assert out["calibre_watch"]["pending_jobs"] == {}


def test_adopted_device_ids_from_pull_are_kept_and_old_ids_become_aliases():
    memory = _base()
    disk = copy.deepcopy(memory)
    disk["x3_primary_device_id"] = "dev_shared"
    disk["x3_primary_device_alias_ids"] = ["dev_local"]
    disk["x3_devices"][0]["id"] = "dev_b_shared"
    disk["x3_devices"][0]["alias_ids"] = ["dev_b_local"]
    memory["x3_devices"][0]["name"] = "Living room"
    memory["x3_devices"].append({"name": "New", "ip": "192.168.0.30", "id": "dev_new", "alias_ids": []})

    out = merge(disk, memory)

    assert out["x3_primary_device_id"] == "dev_shared"
    assert out["x3_primary_device_alias_ids"] == ["dev_local"]
    first, second = out["x3_devices"]
    assert (first["name"], first["id"], first["alias_ids"]) == ("Living room", "dev_b_shared", ["dev_b_local"])
    assert second["id"] == "dev_new"


def test_device_removed_in_gui_stays_removed():
    memory = _base()
    disk = copy.deepcopy(memory)
    memory["x3_devices"] = []
    assert merge(disk, memory)["x3_devices"] == []


def test_site_deleted_by_pull_is_not_resurrected_but_readded_site_survives():
    memory = _base()
    memory["sites"] = [
        {"name": "Gone", "url": "https://gone.example/feed", "type": "rss", "_sync_updated_at": "2026-10-01T00:00:00Z"},
        {"name": "Back", "url": "https://back.example/feed", "type": "rss", "_sync_updated_at": "2026-10-21T09:00:00Z"},
    ]
    disk = _base()
    apply_portable_cfg(disk, {
        "last_sites_push_at": "2026-10-21T08:00:00Z",
        "deleted_sites": [
            {"url": "https://gone.example/feed", "deleted_at": "2026-10-20T00:00:00Z"},
            {"url": "https://back.example/feed", "deleted_at": "2026-10-20T00:00:00Z"},
        ],
    })
    apply_portable_cfg(memory, {"folder": "D:/new-share"})

    out = merge(disk, memory)

    urls = [s["url"] for s in out["sites"]]
    assert urls == ["https://back.example/feed"]
    portable = get_portable_cfg(out)
    assert [d["url"] for d in portable["deleted_sites"]] == ["https://gone.example/feed"]
    assert portable["folder"] == "D:/new-share"  # user-edited key from memory
    assert portable["last_sites_push_at"] == "2026-10-21T08:00:00Z"  # background key from disk


def test_gui_edited_top_level_values_still_win():
    memory = _base()
    disk = copy.deepcopy(memory)
    disk["x3_ip"] = "192.168.0.99"
    memory["font_size"] = 20
    out = merge(disk, memory)
    assert out["x3_ip"] == "192.168.0.10"
    assert out["font_size"] == 20
