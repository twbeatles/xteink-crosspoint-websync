"""공유 폴더의 기기 신원.

전송 이력 키는 PC마다 config.json 에만 있는 안정 기기 ID입니다.
같은 리더기를 다른 PC에 같은 주소로 등록하면 ID가 달라 이미 보낸 글이
다시 전송됩니다. 공유 이력의 devices 목록으로 주소가 같은 기기를
하나의 ID로 맞추고, 나머지 ID는 조회 별칭으로 남깁니다.
"""
from __future__ import annotations

from typing import Any

from websync.upload.host import normalize_device_host

_MAX_HOSTS = 16


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip() if item is not None else ""
        if text and text not in out:
            out.append(text)
    return out


def _host(value: Any) -> str:
    return normalize_device_host(str(value or ""))


def _local_records(config: dict) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    host = _host(config.get("x3_ip"))
    if host:
        records.append(
            {
                "id": (config.get("x3_primary_device_id") or "").strip(),
                "hosts": [host],
                "alias_ids": _text_list(config.get("x3_primary_device_alias_ids")),
                "name": "",
                "slot": ("primary",),
            }
        )
    devices = config.get("x3_devices")
    if isinstance(devices, list):
        for index, dev in enumerate(devices):
            if not isinstance(dev, dict):
                continue
            dip = _host(dev.get("ip"))
            if not dip:
                continue
            records.append(
                {
                    "id": (dev.get("id") or "").strip(),
                    "hosts": [dip],
                    "alias_ids": _text_list(dev.get("alias_ids")),
                    "name": (dev.get("name") or "").strip(),
                    "slot": ("device", index),
                }
            )
    return records


def _remote_records(remote_devices: list | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in remote_devices or []:
        if not isinstance(item, dict):
            continue
        did = (item.get("id") or "").strip()
        hosts: list[str] = []
        for host in _text_list(item.get("hosts")):
            normalized = _host(host)
            if normalized and normalized not in hosts:
                hosts.append(normalized)
        single = _host(item.get("host"))
        if single and single not in hosts:
            hosts.append(single)
        if not did and not hosts:
            continue
        records.append(
            {
                "id": did,
                "hosts": hosts[:_MAX_HOSTS],
                "alias_ids": [a for a in _text_list(item.get("alias_ids")) if a != did],
                "name": (item.get("name") or "").strip(),
                "slot": None,
            }
        )
    return records


def reconcile_config_devices(
    config: dict, remote_devices: list | None
) -> tuple[list[dict], bool]:
    """같은 설정 주소·같은 ID를 한 기기로 묶고 config 이력 키를 맞춥니다.

    Returns:
        (공유 파일에 쓸 devices, 로컬 config 변경 여부)
    설정된 주소만 동일 기기 판정에 씁니다. 기본 기기의 조회용
    ``crosspoint.local`` 별칭은 주소로 넣지 않습니다.
    """
    if not isinstance(config, dict):
        return [], False

    nodes = _local_records(config) + _remote_records(remote_devices)
    if not nodes:
        return [], False

    parent = list(range(len(nodes)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    by_host: dict[str, list[int]] = {}
    by_id: dict[str, list[int]] = {}
    for index, node in enumerate(nodes):
        for host in node["hosts"]:
            by_host.setdefault(host, []).append(index)
        identities = [node["id"], *node["alias_ids"]] if node["id"] else list(node["alias_ids"])
        for identity in identities:
            if identity:
                by_id.setdefault(identity, []).append(index)
    for group in (*by_host.values(), *by_id.values()):
        head = group[0]
        for other in group[1:]:
            union(head, other)

    clusters: dict[int, list[int]] = {}
    for index in range(len(nodes)):
        clusters.setdefault(find(index), []).append(index)

    export: list[dict] = []
    changed = False
    for members in clusters.values():
        group = [nodes[index] for index in members]
        candidate_ids = sorted({node["id"] for node in group if node["id"]})
        if not candidate_ids:
            continue
        canonical = candidate_ids[0]
        aliases: list[str] = []
        local_hosts: list[str] = []
        remote_hosts: list[str] = []
        name = ""
        for node in group:
            if node["slot"] is not None and node["name"] and not name:
                name = node["name"]
        if not name:
            for node in group:
                if node["name"]:
                    name = node["name"]
                    break
        for node in group:
            if node["id"] and node["id"] != canonical and node["id"] not in aliases:
                aliases.append(node["id"])
            for alias in node["alias_ids"]:
                if alias and alias != canonical and alias not in aliases:
                    aliases.append(alias)
            # 이 PC에 등록된 주소만 남긴다. 예전 주소가 공유 파일에 남으면
            # 그 주소를 받은 다른 리더기까지 같은 이력으로 붙는다.
            host_out = local_hosts if node["slot"] is not None else remote_hosts
            for host in node["hosts"]:
                if host not in host_out:
                    host_out.append(host)
        aliases = sorted(a for a in aliases if a != canonical)
        hosts = (local_hosts or remote_hosts)[:_MAX_HOSTS]
        export.append(
            {
                "id": canonical,
                "hosts": hosts,
                "alias_ids": aliases,
                "name": name,
            }
        )
        for node in group:
            slot = node["slot"]
            if not slot:
                continue
            if slot[0] == "primary":
                current_id = (config.get("x3_primary_device_id") or "").strip()
                current_aliases = _text_list(config.get("x3_primary_device_alias_ids"))
                if current_id != canonical:
                    config["x3_primary_device_id"] = canonical
                    changed = True
                if current_aliases != aliases:
                    config["x3_primary_device_alias_ids"] = list(aliases)
                    changed = True
                continue
            devices = config.get("x3_devices")
            index = slot[1]
            if not isinstance(devices, list) or not (0 <= index < len(devices)):
                continue
            dev = devices[index]
            if not isinstance(dev, dict):
                continue
            current_id = (dev.get("id") or "").strip()
            current_aliases = _text_list(dev.get("alias_ids"))
            if current_id != canonical:
                dev["id"] = canonical
                changed = True
            if current_aliases != aliases:
                if aliases or "alias_ids" in dev:
                    dev["alias_ids"] = list(aliases)
                    changed = True

    export.sort(key=lambda item: (item["hosts"][0] if item["hosts"] else "", item["id"]))
    return export, changed
