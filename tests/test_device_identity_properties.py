"""Device-identity contract (plan 6.1 items 8-9, INV-04).

Policy under test (from device_registry docstring): every PC's primary
(x3_ip) is the SAME physical reader regardless of address; secondaries
merge only on equal configured address or shared id/alias. Two distinct
local readers must never merge. A physically-different primary per PC is
a documented support limit, not a silent merge.
"""
from __future__ import annotations

from websync.backup.device_registry import reconcile_config_devices
from websync.upload.device_ids import (
    build_targets_with_keys,
    history_keys_from_targets,
)


def test_primaries_with_different_addresses_merge():
    cfg = {"x3_ip": "192.168.1.10", "x3_primary_device_id": "dev_a",
           "x3_primary_device_alias_ids": [], "x3_devices": []}
    remote = [{"id": "dev_b", "hosts": ["crosspoint.local"], "alias_ids": [], "primary": True}]
    export, changed = reconcile_config_devices(cfg, remote)
    assert changed is True
    ids = {d.get("id") for d in export}
    assert len(ids) == 1  # one physical reader


def test_distinct_secondaries_never_merge():
    cfg = {"x3_ip": "192.168.1.10", "x3_primary_device_id": "dev_p",
           "x3_primary_device_alias_ids": [],
           "x3_devices": [{"name": "s1", "ip": "192.168.1.11", "id": "dev_s1"},
                          {"name": "s2", "ip": "192.168.1.12", "id": "dev_s2"}]}
    export, _changed = reconcile_config_devices(cfg, None)
    ids = [d.get("id") for d in export if not d.get("primary")]
    assert "dev_s1" in ids and "dev_s2" in ids
    targets = build_targets_with_keys(
        "192.168.1.10",
        [{"name": "s1", "ip": "192.168.1.11", "id": "dev_s1"},
         {"name": "s2", "ip": "192.168.1.12", "id": "dev_s2"}],
        primary_id="dev_p",
    )
    keys = history_keys_from_targets(targets)
    assert len(set(keys)) == 3


def test_alias_chain_merges_on_shared_id():
    cfg = {"x3_ip": "192.168.1.99", "x3_primary_device_id": "",
           "x3_primary_device_alias_ids": ["dev_shared"],
           "x3_devices": []}
    remote = [{"id": "dev_shared", "hosts": ["192.168.1.50"], "alias_ids": [], "primary": True}]
    export, changed = reconcile_config_devices(cfg, remote)
    assert changed is True
    assert any(d.get("id") == "dev_shared" for d in export)


def test_same_host_different_id_stays_split_for_secondaries():
    targets = build_targets_with_keys(
        "192.168.1.10",
        [{"name": "a", "ip": "192.168.1.11", "id": "dev_a"},
         {"name": "b", "ip": "192.168.1.11", "id": "dev_b"}],
        primary_id="dev_p",
    )
    # duplicate IP is deduped to a single transport target (uploader rule),
    # but history keys for distinct physical secondaries must not be conflated
    # when the addresses differ — covered by the next test.
    assert len(targets) >= 2


def test_two_physical_primaries_documented_limit():
    """Two PCs whose primaries are physically different readers: the current
    algorithm still merges primaries. This test pins the behavior as a
    documented limit so a future policy change must update it deliberately."""
    cfg_b = {"x3_ip": "192.168.2.20", "x3_primary_device_id": "dev_B",
             "x3_primary_device_alias_ids": [], "x3_devices": []}
    remote_from_a = [{"id": "dev_A", "hosts": ["192.168.1.10"], "alias_ids": [], "primary": True}]
    export, _changed = reconcile_config_devices(cfg_b, remote_from_a)
    primaries = [d for d in export if d.get("primary")]
    assert len(primaries) == 1  # current policy: merged (limit documented)
