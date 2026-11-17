"""업로드 결과 처리 공통 헬퍼 (파이프라인 / 선택 동기화 공유)."""

from __future__ import annotations

from typing import Any, Callable, Iterable


def upload_all_ok(upload_results: dict[str, bool], pending_ips: list[str]) -> bool:
    """pending 전 기기가 결과에 포함되고 모두 성공인지."""
    if not upload_results or not pending_ips:
        return False
    return all(upload_results.values()) and set(upload_results.keys()) == set(
        pending_ips
    )


def upload_any_ok(upload_results: dict[str, bool]) -> bool:
    return bool(upload_results) and any(upload_results.values())


def collect_mark_entries(
    upload_results: dict[str, bool],
    articles: Iterable[dict[str, Any]],
    *,
    site_name: str,
    is_synced_for_device: Callable[[str, str], bool],
    skip_already_synced: bool = True,
    ip_to_history_key: dict[str, str] | None = None,
) -> list[dict]:
    """성공 IP에 대해 mark_synced_many용 엔트리 목록을 만든다.

    articles: url, title 키를 가진 dict (site_name은 인자 우선)
    ip_to_history_key: 업로드 결과 IP → 이력 DB 키 (안정 device id 등)
    """
    batch: list[dict] = []
    key_map = ip_to_history_key or {}
    for ip, ok in upload_results.items():
        if not ok:
            continue
        hist_key = key_map.get(ip, ip)
        for art in articles:
            url = (art.get("url") or "").strip()
            if not url:
                continue
            if skip_already_synced and is_synced_for_device(url, hist_key):
                continue
            batch.append(
                {
                    "url": url,
                    "site_name": art.get("site_name") or site_name,
                    "title": art.get("title") or "",
                    "device_ip": hist_key,
                }
            )
    return batch


def collect_mark_entries_from_triples(
    upload_results: dict[str, bool],
    triples: Iterable[tuple[str, str, str]],
    *,
    is_synced_for_device: Callable[[str, str], bool],
    skip_already_synced: bool = True,
    ip_to_history_key: dict[str, str] | None = None,
) -> list[dict]:
    """(url, site_name, title) 목록용 mark 엔트리 수집."""
    batch: list[dict] = []
    key_map = ip_to_history_key or {}
    for ip, ok in upload_results.items():
        if not ok:
            continue
        hist_key = key_map.get(ip, ip)
        for url, site_name, title in triples:
            url = (url or "").strip()
            if not url:
                continue
            if skip_already_synced and is_synced_for_device(url, hist_key):
                continue
            batch.append(
                {
                    "url": url,
                    "site_name": site_name or "",
                    "title": title or "",
                    "device_ip": hist_key,
                }
            )
    return batch
