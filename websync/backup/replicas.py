"""Per-installation snapshots retain changes across cloud-replica overwrites.

This is eventual data reconciliation, not a distributed delivery lock.
"""
from pathlib import Path
import socket
from uuid import UUID, uuid4

from websync.backup.atomic_io import read_json_checked, write_json_atomic
from websync.backup.format import (
    build_sites_payload, build_history_payload, merge_sites, merge_site_tombstones,
    apply_site_tombstones,
)
from websync.db.history import SyncHistoryDb

DIRECTORY = ".websync-replicas"


def merge_replica_inputs(folder, sites_payload, history_payload, include_history):
    root = Path(folder) / DIRECTORY
    if not root.resolve().is_relative_to(Path(folder).resolve()):
        raise ValueError("Replica directory escapes shared folder")
    if not root.exists():
        return sites_payload, history_payload
    paths = sorted(root.glob("*.json"))
    if len(paths) > 128:
        raise ValueError("Too many shared replica snapshots")
    snapshots = []
    for path in paths:
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Replica snapshot escapes shared directory")
        snapshot = read_json_checked(str(path))
        if not isinstance(snapshot, dict) or snapshot.get("kind") != "replica":
            raise ValueError("Invalid replica snapshot")
        for key in ("sites", "deleted_sites", "posts", "deleted_posts", "devices"):
            if not isinstance(snapshot.get(key), list):
                raise ValueError(f"Replica snapshot has invalid {key}")
        snapshots.append(snapshot)
    # Oldest first makes legacy timestamp-free entries deterministic; modern
    # site update timestamps and tombstones decide per-URL conflicts.
    snapshots.sort(key=lambda item: item.get("exported_at") or "")
    sites = list((sites_payload or {}).get("sites", []))
    deleted = list((sites_payload or {}).get("deleted_sites", []))
    exported_at = (sites_payload or {}).get("exported_at") or ""
    history = dict(history_payload or build_history_payload([]))
    for snapshot in snapshots:
        sites = merge_sites(sites, snapshot["sites"], remote_wins_same_url=False)
        deleted = merge_site_tombstones(deleted, snapshot["deleted_sites"])
        exported_at = max(exported_at, snapshot.get("exported_at") or "")
        if include_history:
            for key in ("posts", "deleted_posts", "devices"):
                history[key] = list(history.get(key) or []) + snapshot[key]
    sites, deleted = apply_site_tombstones(sites, deleted)
    if include_history:
        # Reconcile records before publishing the merged payload. Duplicate
        # snapshots must not resurrect an older deletion or duplicate a resend.
        posts, tombstones = {}, {}
        for key, output, timestamp in (("posts", posts, "synced_at"),
                                       ("deleted_posts", tombstones, "deleted_at")):
            for item in history.get(key) or []:
                if not isinstance(item, dict):
                    raise ValueError("Invalid replica history record")
                identity = (item.get("url"), item.get("device_ip"))
                if not all(isinstance(value, str) and value for value in identity):
                    raise ValueError("Invalid replica history identity")
                old = output.get(identity)
                if old is None or SyncHistoryDb._time_key(item.get(timestamp) or "") > SyncHistoryDb._time_key(old.get(timestamp) or ""):
                    output[identity] = item
        for identity in set(posts) & set(tombstones):
            if SyncHistoryDb._time_key(tombstones[identity].get("deleted_at") or "") >= SyncHistoryDb._time_key(posts[identity].get("synced_at") or ""):
                del posts[identity]
            else:
                del tombstones[identity]
        history["posts"] = list(posts.values())
        history["deleted_posts"] = list(tombstones.values())
    return build_sites_payload(sites, exported_at=exported_at or None,
                               deleted_sites=deleted), history if include_history else None


def publish_replica(folder, replica_id, sites_payload, history_payload):
    # Validate an ID read from local config before using it as a filename.
    replica_id = UUID(replica_id).hex
    root = Path(folder) / DIRECTORY
    if not root.resolve().is_relative_to(Path(folder).resolve()):
        raise ValueError("Replica directory escapes shared folder")
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{replica_id}.json"
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Replica snapshot escapes shared directory")
    history = history_payload or {}
    if history_payload is None and path.exists():
        # Disabling new history export does not erase already-shared history.
        history = read_json_checked(str(path)) or {}
    payload = dict(sites_payload)
    payload["kind"] = "replica"
    for key in ("posts", "deleted_posts", "devices"):
        payload[key] = list(history.get(key) or [])
    write_json_atomic(str(path), payload)


def ensure_replica_id(config):
    try:
        if config.get("backup_replica_host") != socket.gethostname():
            raise ValueError("Installation moved to another computer")
        config["backup_replica_id"] = UUID(config.get("backup_replica_id", "")).hex
    except (ValueError, TypeError, AttributeError):
        config["backup_replica_id"] = uuid4().hex
    config["backup_replica_host"] = socket.gethostname()
    return config["backup_replica_id"]
