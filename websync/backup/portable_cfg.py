"""공유 데이터 폴더(portable_data) 설정 읽기/쓰기 — backup_sync 하위 호환."""
from __future__ import annotations

import copy
from typing import Any

PORTABLE_KEY = "portable_data"
LEGACY_KEY = "backup_sync"

HISTORY_MODE_PER_DEVICE = "per_device"
HISTORY_MODE_GLOBAL_URL = "global_url"
HISTORY_MODES = (HISTORY_MODE_PER_DEVICE, HISTORY_MODE_GLOBAL_URL)

# 공유 폴더 동기화에 쓰는 공통 필드 (양쪽 키에 미러)
_MIRROR_KEYS = (
    "enabled",
    "folder",
    "include_history",
    "auto_export",
    "auto_import_on_start",
    "last_sites_push_at",
    "last_history_push_at",
    "last_sync_at",
    "last_sync_message",
)

DEFAULT_PORTABLE: dict[str, Any] = {
    "enabled": False,
    "folder": "",
    "include_history": True,
    "auto_export": True,
    "auto_import_on_start": True,
    "history_mode": HISTORY_MODE_PER_DEVICE,
    "wizard_completed": False,
    "last_sites_push_at": "",
    "last_history_push_at": "",
    "last_sync_at": "",
    "last_sync_message": "",
    "deleted_sites": [],
}


def normalize_history_mode(value: Any) -> str:
    text = (str(value) if value is not None else "").strip().lower()
    if text in HISTORY_MODES:
        return text
    return HISTORY_MODE_PER_DEVICE


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def get_portable_cfg(config: dict | None) -> dict[str, Any]:
    """portable_data + backup_sync 를 병합한 유효 설정 복사본.

    병합 규칙:
    1. 기본값
    2. backup_sync (레거시)
    3. portable_data (신규) — 빈 folder 는 레거시 folder 를 지우지 않음
    4. enabled: 어느 쪽이든 True 이고 folder 가 있으면 True 로 보정 가능
       (레거시만 켠 사용자 보호: portable 기본 False 가 레거시를 덮지 않도록
        portable 이 folder/enabled/wizard 로 '의도적으로' 쓰인 경우만 enabled 덮어씀)
    """
    cfg = config if isinstance(config, dict) else {}
    pd = _as_dict(cfg.get(PORTABLE_KEY))
    bs = _as_dict(cfg.get(LEGACY_KEY))

    out = copy.deepcopy(DEFAULT_PORTABLE)

    for k in list(out.keys()):
        if k in bs:
            out[k] = copy.deepcopy(bs[k])

    pd_folder = (pd.get("folder") or "").strip() if isinstance(pd.get("folder"), str) else ""
    bs_folder = (out.get("folder") or "").strip() if isinstance(out.get("folder"), str) else ""
    # deep_merge 로 채워진 기본 portable_data 는 '미사용'으로 보고 레거시만 신뢰
    portable_touched = bool(pd.get("wizard_completed")) or bool(pd_folder) or (
        "history_mode" in pd and normalize_history_mode(pd.get("history_mode")) != HISTORY_MODE_PER_DEVICE
    ) or bool(pd.get("last_sync_at")) or bool(pd.get("last_sites_push_at")) or bool(pd.get("enabled"))

    if portable_touched:
        for k, v in pd.items():
            if k == "folder":
                if pd_folder:
                    out["folder"] = pd_folder
                continue
            if k in out or k in DEFAULT_PORTABLE:
                out[k] = copy.deepcopy(v)
            else:
                out[k] = copy.deepcopy(v)

    # 레거시만 설정: backup enabled+folder 유지
    if not portable_touched and bs_folder and bool(bs.get("enabled")):
        out["enabled"] = True
        out["folder"] = bs_folder

    out["history_mode"] = normalize_history_mode(out.get("history_mode"))
    out["enabled"] = bool(out.get("enabled"))
    out["include_history"] = bool(out.get("include_history", True))
    out["auto_export"] = bool(out.get("auto_export", True))
    out["auto_import_on_start"] = bool(out.get("auto_import_on_start", True))
    out["wizard_completed"] = bool(out.get("wizard_completed"))
    out["folder"] = (out.get("folder") or "").strip() if isinstance(out.get("folder"), str) else ""
    return out


def apply_portable_cfg(config: dict, updates: dict[str, Any] | None = None, **kwargs: Any) -> dict:
    """config 에 portable_data 를 갱신하고 backup_sync 에 공통 필드를 미러합니다.

    Returns:
        갱신된 portable_data dict (config 내부 참조)
    """
    if not isinstance(config, dict):
        raise TypeError("config must be a dict")
    merged = get_portable_cfg(config)
    if updates:
        merged.update(updates)
    if kwargs:
        merged.update(kwargs)
    merged["history_mode"] = normalize_history_mode(merged.get("history_mode"))
    merged["folder"] = (merged.get("folder") or "").strip() if isinstance(merged.get("folder"), str) else ""
    for flag in ("enabled", "include_history", "auto_export", "auto_import_on_start", "wizard_completed"):
        merged[flag] = bool(merged.get(flag))

    config[PORTABLE_KEY] = merged

    legacy = config.get(LEGACY_KEY)
    if not isinstance(legacy, dict):
        legacy = {}
        config[LEGACY_KEY] = legacy
    for k in _MIRROR_KEYS:
        if k in merged:
            legacy[k] = merged[k]
    return merged


def migrate_portable_into_config(config: dict) -> bool:
    """로드 시 portable_data / backup_sync 를 정규화·이관. 변경 시 True."""
    if not isinstance(config, dict):
        return False
    before_pd = copy.deepcopy(_as_dict(config.get(PORTABLE_KEY)))
    before_bs = copy.deepcopy(_as_dict(config.get(LEGACY_KEY)))
    # get + apply 로 양쪽 동기화
    apply_portable_cfg(config)
    after_pd = _as_dict(config.get(PORTABLE_KEY))
    after_bs = _as_dict(config.get(LEGACY_KEY))
    return before_pd != after_pd or before_bs != after_bs
