"""기기 안정 ID — 이력 키용 (IP 변경 시에도 동일 기기로 인식)."""
from __future__ import annotations

import secrets
from typing import Any, Callable

from websync.upload.host import normalize_device_host
from websync.i18n import t


def new_device_id() -> str:
    return "dev_" + secrets.token_hex(8)


def history_key_for_device(device: dict | None, *, fallback_ip: str = "") -> str:
    """이력 DB 키: 안정 id 우선, 없으면 IP/호스트."""
    if isinstance(device, dict):
        did = (device.get("id") or "").strip()
        if did:
            return did
        ip = normalize_device_host(device.get("ip") or "")
        if ip:
            return ip
    return normalize_device_host(fallback_ip)


def ensure_device_ids_in_config(config: dict) -> bool:
    """기본 기기·추가 기기에 id 가 없으면 부여. 변경 시 True."""
    if not isinstance(config, dict):
        return False
    updated = False
    primary_id = (config.get("x3_primary_device_id") or "").strip()
    if not primary_id:
        config["x3_primary_device_id"] = new_device_id()
        updated = True

    devices = config.get("x3_devices")
    if not isinstance(devices, list):
        return updated
    for dev in devices:
        if not isinstance(dev, dict):
            continue
        if not (dev.get("id") or "").strip():
            dev["id"] = new_device_id()
            updated = True
    return updated


def build_targets_with_keys(
    x3_ip: str,
    devices: list | None = None,
    *,
    primary_id: str = "",
    primary_name: str | None = None,
) -> list[dict[str, Any]]:
    """업로드 대상 목록: name, ip, id, history_key, alias_keys (중복 IP 제거)."""
    if not primary_name:
        primary_name = t("device.default_name")
    targets: list[dict[str, Any]] = []
    seen_ips: set[str] = set()

    ip = normalize_device_host(x3_ip)
    if ip:
        pid = (primary_id or "").strip()
        aliases = _unique_keys([pid, ip, "crosspoint.local"])
        targets.append(
            {
                "name": primary_name,
                "ip": ip,
                "id": pid,
                "history_key": pid or ip,
                "alias_keys": aliases,
            }
        )
        seen_ips.add(ip)

    for dev in devices or []:
        if not isinstance(dev, dict):
            continue
        dip = normalize_device_host(dev.get("ip") or "")
        if not dip or dip in seen_ips:
            continue
        did = (dev.get("id") or "").strip()
        aliases = _unique_keys([did, dip])
        targets.append(
            {
                "name": dev.get("name") or dip,
                "ip": dip,
                "id": did,
                "history_key": did or dip,
                "alias_keys": aliases,
            }
        )
        seen_ips.add(dip)

    return targets


def _unique_keys(keys: list[str]) -> list[str]:
    out: list[str] = []
    for k in keys:
        text = (k or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def ip_to_history_key_map(targets: list[dict]) -> dict[str, str]:
    """upload 결과 IP → 이력 키 매핑."""
    out: dict[str, str] = {}
    for t in targets:
        if not isinstance(t, dict):
            continue
        ip = normalize_device_host(t.get("ip") or "")
        if not ip:
            continue
        out[ip] = (t.get("history_key") or ip).strip() or ip
    return out


def history_keys_from_targets(targets: list[dict]) -> list[str]:
    keys: list[str] = []
    for t in targets:
        if not isinstance(t, dict):
            continue
        ip = normalize_device_host(t.get("ip") or "")
        key = (t.get("history_key") or ip).strip()
        if key:
            keys.append(key)
    return keys


def alias_key_groups(targets: list[dict]) -> list[list[str]]:
    """기기별 이력 조회 후보 키 그룹 (id / IP / 레거시 host)."""
    groups: list[list[str]] = []
    for t in targets:
        if not isinstance(t, dict):
            continue
        aliases = t.get("alias_keys")
        if isinstance(aliases, list) and aliases:
            groups.append([str(a).strip() for a in aliases if str(a).strip()])
            continue
        ip = normalize_device_host(t.get("ip") or "")
        key = (t.get("history_key") or ip).strip()
        groups.append(_unique_keys([key, ip]))
    return groups


def resolve_pending_upload_ips(
    is_synced_for_device: Callable[[str, str], bool],
    is_synced_url: Callable[[str], bool],
    urls: list[str],
    upload_targets: list[dict],
    *,
    history_mode: str = "per_device",
) -> list[str]:
    """아직 업로드가 필요한 기기 IP 목록.

    - per_device: alias_keys(id·IP·레거시 host) 기준
    - global_url: URL 전역 이력이 없으면 전 대상 IP, 있으면 빈 목록
    """
    from websync.backup.portable_cfg import HISTORY_MODE_GLOBAL_URL, normalize_history_mode

    mode = normalize_history_mode(history_mode)
    pending: list[str] = []
    seen: set[str] = set()
    clean_urls = [u for u in urls if u]

    if not clean_urls or not upload_targets:
        return []

    if mode == HISTORY_MODE_GLOBAL_URL:
        if all(is_synced_url(u) for u in clean_urls):
            return []
        for t in upload_targets:
            if not isinstance(t, dict):
                continue
            ip = normalize_device_host(t.get("ip") or "")
            if ip and ip not in seen:
                seen.add(ip)
                pending.append(ip)
        return pending

    for t in upload_targets:
        if not isinstance(t, dict):
            continue
        ip = normalize_device_host(t.get("ip") or "")
        if not ip or ip in seen:
            continue
        aliases = t.get("alias_keys")
        if isinstance(aliases, list) and aliases:
            keys = [str(a).strip() for a in aliases if str(a).strip()]
        else:
            keys = _unique_keys([(t.get("history_key") or ip).strip(), ip])

        def _url_synced(u: str) -> bool:
            return any(is_synced_for_device(u, k) for k in keys if k)

        if any(not _url_synced(u) for u in clean_urls):
            seen.add(ip)
            pending.append(ip)
    return pending


def group_articles_by_pending_targets(
    is_synced_for_device: Callable[[str, str], bool],
    is_synced_url: Callable[[str], bool],
    articles: list[dict],
    upload_targets: list[dict],
    *,
    history_mode: str = "per_device",
) -> list[tuple[list[str], list[dict]]]:
    """Group targets that need exactly the same subset of articles."""
    from websync.backup.portable_cfg import HISTORY_MODE_GLOBAL_URL, normalize_history_mode

    mode = normalize_history_mode(history_mode)
    grouped: dict[tuple[str, ...], dict] = {}
    for target in upload_targets:
        if not isinstance(target, dict):
            continue
        ip = normalize_device_host(target.get("ip") or "")
        if not ip:
            continue
        aliases = target.get("alias_keys")
        keys = (
            [str(a).strip() for a in aliases if str(a).strip()]
            if isinstance(aliases, list) and aliases
            else _unique_keys([(target.get("history_key") or ip).strip(), ip])
        )
        missing = []
        for article in articles:
            url = (article.get("url") or "").strip()
            if not url:
                continue
            synced = (
                is_synced_url(url)
                if mode == HISTORY_MODE_GLOBAL_URL
                else any(is_synced_for_device(url, key) for key in keys if key)
            )
            if not synced:
                missing.append(article)
        if not missing:
            continue
        fingerprint = tuple((article.get("url") or "").strip() for article in missing)
        bucket = grouped.setdefault(fingerprint, {"ips": [], "articles": missing})
        bucket["ips"].append(ip)
    return [(bucket["ips"], bucket["articles"]) for bucket in grouped.values()]
