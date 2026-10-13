"""Backup export must merge the config committed while push was reading shared data."""
from __future__ import annotations

import json
import logging
import threading

import pytest

from websync.backup.format import (
    HISTORY_FILENAME, SITES_FILENAME, build_history_payload, build_sites_payload,
)
from websync.backup.portable_cfg import apply_portable_cfg, get_portable_cfg
from websync.backup.service import BackupSyncService
from websync.config.manager import ConfigManager
from websync.db.history import SyncHistoryDb


def _site(name, year):
    return {
        "name": name, "url": f"https://{name.lower()}.example/feed", "type": "rss",
        "_sync_updated_at": f"{year}-01-01T00:00:00Z",
    }


def _make_service(tmp_path, include_history):
    shared = tmp_path / "shared"
    shared.mkdir()
    config_path = tmp_path / "config.json"
    cm = ConfigManager(str(config_path))
    config = cm.load_config()
    config["sites"] = [_site("A", 2020), _site("RemovedRemote", 2020)]
    config["output_dir"] = str(tmp_path / "output")
    apply_portable_cfg(config, {
        "enabled": True, "folder": str(shared), "include_history": include_history,
        "auto_export": True,
    })
    cm.save_config(config)
    remote_sites = [_site("A", 2025), _site("Remote", 2025)]
    remote_deleted = [{"url": _site("RemovedRemote", 2020)["url"],
                       "deleted_at": "2025-01-01T00:00:00Z"}]
    (shared / SITES_FILENAME).write_text(
        json.dumps(build_sites_payload(remote_sites, deleted_sites=remote_deleted)),
        encoding="utf-8",
    )
    history_payload = build_history_payload([
        {"url": "https://remote.example/article", "site_name": "Remote",
         "title": "Article", "device_ip": "dev_remote",
         "synced_at": "2025-01-01T00:00:00Z"},
    ])
    (shared / HISTORY_FILENAME).write_text(json.dumps(history_payload), encoding="utf-8")
    db = SyncHistoryDb(str(tmp_path / "history.db"))
    logger = logging.Logger("backup-concurrency-test")
    logger.addHandler(logging.NullHandler())
    return BackupSyncService(cm, db, logger=logger), ConfigManager(str(config_path)), shared


def _push_with_interleaved_writer(service, writer, mutate, monkeypatch):
    shared_read = threading.Event()
    writer_committed = threading.Event()
    read = service._read_shared_json

    def read_then_pause(path, **kwargs):
        payload = read(path, **kwargs)
        if kwargs["list_key"] == "sites":
            shared_read.set()
            assert writer_committed.wait(timeout=10), "writer did not commit"
        return payload

    monkeypatch.setattr(service, "_read_shared_json", read_then_pause)
    results = []
    worker = threading.Thread(target=lambda: results.append(service.push(force=True)))
    worker.start()
    try:
        assert shared_read.wait(timeout=10), "push did not reach shared read"
        committed = writer.update_config(mutate)
    finally:
        writer_committed.set()
        worker.join(timeout=10)
    assert not worker.is_alive()
    assert len(results) == 1 and results[0]["ok"], results
    return results[0], committed


@pytest.mark.parametrize("include_history", [False, True])
@pytest.mark.parametrize("change", ["add", "edit", "delete", "readd"])
def test_push_preserves_concurrent_sites_and_tombstones(tmp_path, monkeypatch, include_history, change):
    service, writer, shared = _make_service(tmp_path, include_history)
    if change == "readd":
        writer.update_config(lambda cfg: apply_portable_cfg(cfg, {
            "deleted_sites": [{"url": _site("A", 2020)["url"],
                               "deleted_at": "2026-01-01T00:00:00Z"}],
        }))
    before_history = (shared / HISTORY_FILENAME).read_bytes()

    def mutate(cfg):
        cfg["font_size"] = 23
        if change == "add":
            cfg["sites"].append(_site("B", 2030))
        elif change in ("edit", "readd"):
            cfg["sites"][0].update(name="Changed", limit=17,
                                    _sync_updated_at="2030-01-01T00:00:00Z")
        else:
            cfg["sites"] = cfg["sites"][1:]
            apply_portable_cfg(cfg, {"deleted_sites": [{
                "url": _site("A", 2020)["url"], "deleted_at": "2030-01-01T00:00:00Z",
            }]})

    result, committed = _push_with_interleaved_writer(service, writer, mutate, monkeypatch)
    local = writer.load_config()
    exported = json.loads((shared / SITES_FILENAME).read_text(encoding="utf-8"))
    assert local["sites"] == exported["sites"]
    assert get_portable_cfg(local)["deleted_sites"] == exported["deleted_sites"]
    assert local["font_size"] == 23
    assert local["_config_revision"] > committed["_config_revision"]
    by_url = {site["url"]: site for site in exported["sites"]}
    assert _site("Remote", 2025)["url"] in by_url
    assert _site("RemovedRemote", 2020)["url"] not in by_url
    if change == "add":
        assert _site("B", 2030)["url"] in by_url
        assert by_url[_site("A", 2020)["url"]]["_sync_updated_at"].startswith("2025")
    elif change in ("edit", "readd"):
        assert by_url[_site("A", 2020)["url"]]["name"] == "Changed"
        assert by_url[_site("A", 2020)["url"]]["limit"] == 17
        assert all(item["url"] != _site("A", 2020)["url"] for item in exported["deleted_sites"])
    else:
        assert _site("A", 2020)["url"] not in by_url
        assert {item["url"] for item in exported["deleted_sites"]} == {
            _site("A", 2020)["url"], _site("RemovedRemote", 2020)["url"],
        }
    assert result["history_written"] is include_history
    if include_history:
        history = json.loads((shared / HISTORY_FILENAME).read_text(encoding="utf-8"))
        assert {post["url"] for post in history["posts"]} == {"https://remote.example/article"}
    else:
        assert (shared / HISTORY_FILENAME).read_bytes() == before_history


@pytest.mark.parametrize("include_history", [False, True])
def test_push_history_option_change_does_not_publish_unread_history(tmp_path, monkeypatch, include_history):
    service, writer, shared = _make_service(tmp_path, include_history)
    before_history = (shared / HISTORY_FILENAME).read_bytes()
    result, _ = _push_with_interleaved_writer(
        service, writer,
        lambda cfg: apply_portable_cfg(cfg, {"include_history": not include_history}),
        monkeypatch,
    )
    assert get_portable_cfg(writer.load_config())["include_history"] is not include_history
    # An in-flight export retains its validated component set. Next push uses the new option.
    assert result["history_written"] is include_history
    if not include_history:
        assert (shared / HISTORY_FILENAME).read_bytes() == before_history
    else:
        payload = json.loads((shared / HISTORY_FILENAME).read_text(encoding="utf-8"))
        assert len(payload["posts"]) == 1


@pytest.mark.parametrize("include_history", [False, True])
def test_pull_option_change_never_publishes_unread_history(tmp_path, monkeypatch, include_history):
    service, writer, shared = _make_service(tmp_path, include_history)
    before = (shared / HISTORY_FILENAME).read_bytes()
    original = service._read_shared_json
    changed = False

    def read_then_change(path, **kwargs):
        nonlocal changed
        payload = original(path, **kwargs)
        if not changed:
            changed = True
            writer.update_config(lambda cfg: apply_portable_cfg(cfg, {
                "include_history": not include_history,
            }))
        return payload

    monkeypatch.setattr(service, "_read_shared_json", read_then_change)
    result = service.pull(force=True)
    assert result["ok"]
    assert get_portable_cfg(writer.load_config())["include_history"] is not include_history
    if include_history:
        assert service.db.get_count() == 1
        assert len(json.loads((shared / HISTORY_FILENAME).read_text())["posts"]) == 1
    else:
        assert service.db.get_count() == 0
        assert (shared / HISTORY_FILENAME).read_bytes() == before
