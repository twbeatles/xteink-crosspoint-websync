"""포터블 백업 JSON 스키마 및 병합 유틸."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

FORMAT_NAME = "xteink-websync-backup"
FORMAT_VERSION = 1
SITES_EXPORT_VERSION = 3
HISTORY_EXPORT_VERSION = 2

SITES_FILENAME = "sites.json"
HISTORY_FILENAME = "synced_posts.json"
MANIFEST_FILENAME = "manifest.json"
LOCK_FILENAME = ".backup_sync.lock"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # "2026-07-20T12:34:56" 또는 공백 구분
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace(" ", "T", 1))
        if parsed.tzinfo is None:
            # SQLite CURRENT_TIMESTAMP values use a space and are UTC.  Older
            # application-generated ISO values used T and local wall time.
            tz = timezone.utc if " " in text else datetime.now().astimezone().tzinfo
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _time_key(value: str | None) -> datetime:
    return parse_iso(value) or datetime.min.replace(tzinfo=timezone.utc)


def is_remote_newer(remote_at: str | None, local_at: str | None) -> bool:
    """remote exported_at 이 local 마지막 push 시각보다 최신이면 True.

    로컬 시각이 없으면 remote 가 있을 때 True (초기 pull).
    remote 시각이 없으면 False.
    """
    r = parse_iso(remote_at)
    if r is None:
        return False
    l = parse_iso(local_at)
    if l is None:
        return True
    return r > l


def build_sites_payload(
    sites: list[dict],
    exported_at: str | None = None,
    deleted_sites: list[dict] | None = None,
) -> dict:
    return {
        "export_version": SITES_EXPORT_VERSION,
        "kind": "sites",
        "exported_at": exported_at or now_iso(),
        "sites": copy.deepcopy(sites),
        "deleted_sites": copy.deepcopy(deleted_sites or []),
    }


def build_history_payload(
    posts: list[dict],
    exported_at: str | None = None,
    deleted_posts: list[dict] | None = None,
    devices: list[dict] | None = None,
) -> dict:
    return {
        "export_version": HISTORY_EXPORT_VERSION,
        "kind": "synced_posts",
        "exported_at": exported_at or now_iso(),
        "posts": copy.deepcopy(posts),
        "deleted_posts": copy.deepcopy(deleted_posts or []),
        "devices": copy.deepcopy(devices or []),
    }


def build_manifest(
    *,
    exported_at: str | None = None,
    components: list[str] | None = None,
) -> dict:
    return {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "exported_at": exported_at or now_iso(),
        "app": "xteink-x3-websync",
        "components": components or ["sites", "synced_posts"],
    }


def extract_sites(payload: Any) -> tuple[list[dict], str | None]:
    """sites.json 또는 레거시 export 파일에서 (sites, exported_at) 추출.

    지원 형식:
    - 표준: {export_version, kind?, exported_at, sites: [...]}
    - 레거시 설정 백업(예: ``260720 설정백업.json``): kind 없음, sites 배열만 있으면 됨
    """
    if not isinstance(payload, dict):
        return [], None
    sites = payload.get("sites")
    if not isinstance(sites, list):
        return [], None
    cleaned: list[dict] = [s for s in sites if isinstance(s, dict)]
    exported_at = payload.get("exported_at")
    if not isinstance(exported_at, str):
        exported_at = None
    return cleaned, exported_at


def extract_posts(payload: Any) -> tuple[list[dict], str | None]:
    """synced_posts.json 이력 추출.

    지원 형식:
    - 표준: {export_version, kind: synced_posts, exported_at, posts: [...]}
    - 각 post: url, device_ip, site_name, title, synced_at
    """
    if not isinstance(payload, dict):
        return [], None
    posts = payload.get("posts")
    if not isinstance(posts, list):
        return [], None
    cleaned: list[dict] = [p for p in posts if isinstance(p, dict)]
    exported_at = payload.get("exported_at")
    if not isinstance(exported_at, str):
        exported_at = None
    return cleaned, exported_at


def extract_deleted_sites(payload: Any) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("deleted_sites"), list):
        return []
    return [item for item in payload["deleted_sites"] if isinstance(item, dict)]


def merge_site_tombstones(*groups: list[dict]) -> list[dict]:
    """URL별로 가장 최신 사이트 삭제 표식만 보존합니다."""
    by_url: dict[str, dict] = {}
    for group in groups:
        for item in group if isinstance(group, list) else []:
            if not isinstance(item, dict):
                continue
            url = (item.get("url") or "").strip().lower()
            deleted_at = (item.get("deleted_at") or "").strip()
            if not url or not deleted_at:
                continue
            old = by_url.get(url)
            if old is None or _time_key(deleted_at) > _time_key(old["deleted_at"]):
                by_url[url] = {"url": url, "deleted_at": deleted_at}
    return [by_url[url] for url in sorted(by_url)]


def apply_site_tombstones(
    sites: list[dict], deleted_sites: list[dict]
) -> tuple[list[dict], list[dict]]:
    """삭제보다 새로 저장된 사이트만 살리고 소비된 표식은 제거합니다."""
    tombstones = {item["url"]: item for item in merge_site_tombstones(deleted_sites)}
    kept: list[dict] = []
    for site in sites:
        if not isinstance(site, dict):
            continue
        url = _site_url_key(site)
        tombstone = tombstones.get(url)
        if not tombstone:
            kept.append(site)
            continue
        updated_at = (site.get("_sync_updated_at") or "").strip()
        if updated_at and _time_key(updated_at) > _time_key(tombstone["deleted_at"]):
            kept.append(site)
            tombstones.pop(url, None)
    return kept, [tombstones[url] for url in sorted(tombstones)]


def extract_devices(payload: Any) -> list[dict]:
    """이력 파일의 기기 신원 목록. 없으면 빈 목록 (구버전 호환)."""
    if not isinstance(payload, dict):
        return []
    devices = payload.get("devices")
    if not isinstance(devices, list):
        return []
    return [item for item in devices if isinstance(item, dict)]


def extract_deleted_posts(payload: Any) -> list[dict]:
    """v2 이력 payload의 삭제 tombstone 목록을 추출합니다."""
    if not isinstance(payload, dict):
        return []
    deleted = payload.get("deleted_posts")
    if not isinstance(deleted, list):
        return []
    return [item for item in deleted if isinstance(item, dict)]


def _site_url_key(site: dict) -> str:
    return (site.get("url") or "").strip().lower()


def merge_sites(
    local_sites: list[dict],
    remote_sites: list[dict],
    *,
    remote_wins_same_url: bool,
    default_site: dict | None = None,
) -> list[dict]:
    """URL 기준 사이트 병합.

    - remote_wins_same_url=True: 동일 URL은 remote 필드로 덮어씀 (DEFAULT_SITE 머지)
    - False: 동일 URL은 local 유지, remote-only URL만 추가
    - 로컬에만 있는 URL은 항상 유지
    - 순서는 local 순서 우선, 그다음 remote-only 추가
    """
    from websync.config.manager import ConfigManager

    base = default_site if default_site is not None else ConfigManager.DEFAULT_SITE
    by_url: dict[str, dict] = {}
    order: list[str] = []

    def _put(site: dict, overwrite: bool) -> None:
        key = _site_url_key(site)
        if not key:
            # URL 없는 사이트: 로컬 순서 보존용 유니크 키
            key = f"__nourl__{id(site)}"
        if key in by_url and not overwrite:
            return
        merged, _ = ConfigManager._deep_merge(base, site)
        if key not in by_url:
            order.append(key)
        by_url[key] = merged

    for s in local_sites:
        if isinstance(s, dict):
            _put(s, overwrite=True)

    for s in remote_sites:
        if not isinstance(s, dict):
            continue
        key = _site_url_key(s)
        if not key:
            continue
        if key in by_url:
            current_at = by_url[key].get("_sync_updated_at") or ""
            incoming_at = s.get("_sync_updated_at") or ""
            if incoming_at and _time_key(incoming_at) > _time_key(current_at):
                _put(s, overwrite=True)
            elif not current_at and not incoming_at and remote_wins_same_url:
                _put(s, overwrite=True)
        else:
            _put(s, overwrite=True)

    return [by_url[k] for k in order if k in by_url]
