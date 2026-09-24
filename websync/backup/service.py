"""공유 데이터 폴더(OneDrive 등) 사이트·이력 정본 동기화 서비스.

로컬 SQLite(`sync_history.db`)와 `config.json`의 sites 는 작업 캐시이고,
공유 폴더의 sites.json / synced_posts.json 이 정본입니다.
SQLite 파일을 공유 폴더에 직접 두지 마세요.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

from websync.backup.atomic_io import JsonReadError, ensure_dir, read_json_checked, write_json_atomic
from websync.backup.format import (
    HISTORY_FILENAME,
    LOCK_FILENAME,
    MANIFEST_FILENAME,
    SITES_FILENAME,
    build_history_payload,
    build_manifest,
    build_sites_payload,
    apply_site_tombstones,
    extract_deleted_sites,
    extract_posts,
    extract_deleted_posts,
    extract_devices,
    extract_sites,
    is_remote_newer,
    merge_sites,
    merge_site_tombstones,
    now_iso,
)
from websync.backup.device_registry import reconcile_config_devices
from websync.backup.portable_cfg import apply_portable_cfg, get_portable_cfg
from websync.config.manager import ConfigManager
from websync.core.paths import resolve_path
from websync.core.process_lock import ProcessFileLock
from websync.db.history import SyncHistoryDb, SyncHistoryDbError
from websync.i18n import t


class BackupSyncError(Exception):
    """공유 데이터 폴더 동기화 실패"""


def _same_device_registry(export: list[dict], remote: list[dict]) -> bool:
    def signature(devices: list[dict]) -> tuple:
        rows = []
        for item in devices:
            if not isinstance(item, dict):
                continue
            rows.append(
                (
                    (item.get("id") or "").strip(),
                    tuple(item.get("hosts") or []),
                    tuple(item.get("alias_ids") or []),
                    (item.get("name") or ""),
                )
            )
        return tuple(sorted(rows))

    return signature(export) == signature(remote)


class BackupSyncService:
    """사이트 설정 + 전송 이력을 공유 폴더 JSON 정본으로 pull/push 합니다."""

    def __init__(
        self,
        config_manager: ConfigManager,
        db: SyncHistoryDb,
        logger: Optional[logging.Logger] = None,
    ):
        self.config_manager = config_manager
        self.db = db
        self.logger = logger or logging.getLogger("websync.backup")
        self._lock = threading.Lock()
        self.last_result: dict[str, Any] = {}

    def _load_config(self) -> dict:
        return self.config_manager.load_config()

    def _backup_cfg(self, config: dict | None = None) -> dict:
        """portable_data (+ backup_sync 하위 호환) 설정."""
        cfg = config if config is not None else self._load_config()
        return get_portable_cfg(cfg)

    def get_folder(self, config: dict | None = None) -> str:
        folder = (self._backup_cfg(config).get("folder") or "").strip()
        if not folder:
            return ""
        return resolve_path(folder)

    def is_enabled(self, config: dict | None = None) -> bool:
        return bool(self._backup_cfg(config).get("enabled"))

    def is_configured(self, config: dict | None = None) -> bool:
        cfg = config if config is not None else self._load_config()
        return self.is_enabled(cfg) and bool(self.get_folder(cfg))

    def _update_backup_meta(self, config: dict, **kwargs) -> dict:
        apply_portable_cfg(config, kwargs)
        return config

    def _adopt_shared_device_ids(
        self, config: dict, remote_devices: list
    ) -> tuple[dict, bool]:
        """같은 주소의 공유 기기 ID를 로컬 이력 키·별칭에 반영합니다."""
        import copy

        preview = copy.deepcopy(config)
        _export, changed = reconcile_config_devices(preview, remote_devices)
        if not changed:
            return config, False

        def _apply(cfg: dict) -> None:
            reconcile_config_devices(cfg, remote_devices)

        return self.config_manager.update_config(_apply), True

    def _publish_device_registry(
        self, folder: str, config: dict, remote_payload: Any
    ) -> None:
        """시작 시 pull만 해도 기기 ID↔주소를 공유 파일에 남깁니다.

        예전 synced_posts.json 에는 글의 기기 ID만 있고 주소가 없습니다.
        그 ID를 가진 PC가 한 번 열리면 다른 PC가 같은 주소를 같은 기기로 봅니다.
        """
        import copy

        remote_devices = extract_devices(remote_payload)
        export, _changed = reconcile_config_devices(copy.deepcopy(config), remote_devices)
        if not export or _same_device_registry(export, remote_devices):
            return
        posts, _exported_at = extract_posts(remote_payload)
        write_json_atomic(
            os.path.join(folder, HISTORY_FILENAME),
            build_history_payload(
                posts,
                deleted_posts=extract_deleted_posts(remote_payload),
                devices=export,
            ),
        )

    def pull(self, *, force: bool = False) -> dict[str, Any]:
        """클라우드 폴더 → 로컬 병합.

        force=True 이면 enabled 여부와 관계없이 folder만 있으면 수행 (수동 동기화용).
        """
        with self._lock:
            return self._pull_unlocked(force=force)

    def push(self, *, force: bool = False) -> dict[str, Any]:
        """로컬 → 클라우드 폴더 기록."""
        with self._lock:
            return self._push_unlocked(force=force)

    def sync_now(self) -> dict[str, Any]:
        """양방향: pull 후 push."""
        with self._lock:
            pull_result = self._pull_unlocked(force=True)
            if pull_result.get("ok"):
                push_result = self._push_unlocked(force=True)
            else:
                # pull이 실패한 상태에서는 로컬 캐시를 정본으로 게시하지 않는다.
                push_result = {
                    "ok": False,
                    "skipped": True,
                    "message": t("backup.push_skipped_after_pull_failure"),
                }
            result = {
                "ok": pull_result.get("ok", False) and push_result.get("ok", False),
                "pull": pull_result,
                "push": push_result,
            }
            self.last_result = result
            return result

    def _acquire_folder_lock(
        self,
        folder: str,
        *,
        attempts: int = 6,
        delay: float = 0.4,
    ) -> ProcessFileLock | None:
        lock = ProcessFileLock(os.path.join(folder, LOCK_FILENAME))
        tries = max(1, int(attempts))
        for i in range(tries):
            if lock.acquire(blocking=False):
                return lock
            if i < tries - 1:
                time.sleep(max(0.05, float(delay)))
        return None

    @staticmethod
    def _read_shared_json(
        path: str,
        *,
        list_key: str,
        attempts: int = 3,
        delay: float = 0.15,
    ):
        """Read a cloud-synced file, retrying brief partial-sync states."""
        last_error: JsonReadError | None = None
        for attempt in range(max(1, attempts)):
            try:
                payload = read_json_checked(path)
                if payload is not None and (
                    not isinstance(payload, dict)
                    or not isinstance(payload.get(list_key), list)
                ):
                    raise JsonReadError(
                        f"Shared JSON is missing a valid '{list_key}' list: {path}"
                    )
                return payload
            except JsonReadError as exc:
                last_error = exc
                if attempt < max(1, attempts) - 1:
                    time.sleep(delay)
        raise BackupSyncError(str(last_error)) from last_error

    def _pull_unlocked(self, *, force: bool = False) -> dict[str, Any]:
        config = self._load_config()
        bs = self._backup_cfg(config)
        folder = self.get_folder(config)
        result: dict[str, Any] = {
            "ok": False,
            "action": "pull",
            "sites_changed": False,
            "sites_added": 0,
            "history_changed": 0,
            "skipped": False,
            "message": "",
        }

        if not folder:
            result["skipped"] = True
            result["message"] = t("backup.no_folder")
            self.last_result = result
            return result
        if not force and not bs.get("enabled"):
            result["skipped"] = True
            result["message"] = t("backup.disabled")
            self.last_result = result
            return result

        file_lock = self._acquire_folder_lock(folder)
        if file_lock is None:
            result["skipped"] = True
            result["message"] = t("backup.busy")
            self.logger.warning(result["message"])
            self.last_result = result
            return result

        try:
            sites_path = os.path.join(folder, SITES_FILENAME)
            history_path = os.path.join(folder, HISTORY_FILENAME)

            # Validate every input before mutating local state.  A cloud client
            # may expose a zero-byte or partial file briefly while syncing.
            remote_sites_payload = self._read_shared_json(sites_path, list_key="sites")
            remote_hist_payload = (
                self._read_shared_json(history_path, list_key="posts")
                if bs.get("include_history", True)
                else None
            )

            # --- sites ---
            remote_sites, remote_sites_at = extract_sites(remote_sites_payload)
            remote_deleted_sites = extract_deleted_sites(remote_sites_payload)
            raw_sites = config.get("sites")
            local_sites: list[dict] = raw_sites if isinstance(raw_sites, list) else []
            last_sites_push = bs.get("last_sites_push_at")
            remote_wins = is_remote_newer(remote_sites_at, last_sites_push if isinstance(last_sites_push, str) else None)
            local_deleted_sites = bs.get("deleted_sites", [])
            combined_deleted = merge_site_tombstones(local_deleted_sites, remote_deleted_sites)

            if remote_sites or combined_deleted:
                before_urls = {
                    (s.get("url") or "").strip().lower()
                    for s in local_sites
                    if isinstance(s, dict) and s.get("url")
                }
                merged = merge_sites(
                    local_sites,
                    remote_sites,
                    remote_wins_same_url=remote_wins,
                )
                merged, combined_deleted = apply_site_tombstones(merged, combined_deleted)
                after_urls = {
                    (s.get("url") or "").strip().lower()
                    for s in merged
                    if isinstance(s, dict) and s.get("url")
                }
                added = len(after_urls - before_urls)
                # 내용 변경 감지 (길이 또는 remote wins 적용)
                if merged != local_sites or combined_deleted != local_deleted_sites:
                    expected_rev = config.get("_config_revision")
                    try:
                        expected_i = int(expected_rev) if expected_rev is not None else None
                    except (TypeError, ValueError):
                        expected_i = None

                    def _apply_sites(cfg: dict) -> None:
                        # RMW: 디스크 최신 사이트와 다시 병합
                        cur = cfg.get("sites") if isinstance(cfg.get("sites"), list) else []
                        portable = get_portable_cfg(cfg)
                        deleted = merge_site_tombstones(
                            portable.get("deleted_sites", []), remote_deleted_sites
                        )
                        merged_current = merge_sites(
                            cur, remote_sites, remote_wins_same_url=remote_wins
                        )
                        cfg["sites"], deleted = apply_site_tombstones(merged_current, deleted)
                        apply_portable_cfg(cfg, {"deleted_sites": deleted})

                    try:
                        config = self.config_manager.update_config(_apply_sites)
                    except Exception:
                        config["sites"] = merged
                        apply_portable_cfg(config, {"deleted_sites": combined_deleted})
                        self.config_manager.save_config(
                            config, expected_revision=expected_i
                        )
                        config = self._load_config()
                    result["sites_changed"] = True
                    result["sites_added"] = added
                    bs = self._backup_cfg(config)

            # --- history ---
            history_changed = 0
            if bs.get("include_history", True):
                config, devices_changed = self._adopt_shared_device_ids(
                    config, extract_devices(remote_hist_payload)
                )
                if devices_changed:
                    bs = self._backup_cfg(config)
                    result["devices_changed"] = True
                remote_posts, _ = extract_posts(remote_hist_payload)
                remote_deleted = extract_deleted_posts(remote_hist_payload)
                if remote_posts or remote_deleted:
                    try:
                        history_changed = self.db.import_deleted_posts(remote_deleted)
                        history_changed += self.db.import_posts_union(remote_posts)
                    except SyncHistoryDbError as e:
                        result["message"] = t("backup.history_import_failed", error=e)
                        self.logger.error(result["message"])
                        self.last_result = result
                        return result
            result["history_changed"] = history_changed
            if bs.get("include_history", True):
                self._publish_device_registry(folder, config, remote_hist_payload)

            result["ok"] = True
            parts = []
            if result["sites_changed"]:
                parts.append(t("backup.sites_merged", n=result["sites_added"]))
            if history_changed:
                parts.append(t("backup.history_applied", n=history_changed))
            if not parts:
                parts.append(t("backup.no_change"))
            result["message"] = t("backup.pull_done", parts=", ".join(parts))
            self.logger.info(result["message"])
            self.last_result = result
            return result
        except Exception as e:
            result["message"] = t("backup.pull_failed", error=e)
            self.logger.exception(result["message"])
            self.last_result = result
            return result
        finally:
            file_lock.release()

    def _push_unlocked(self, *, force: bool = False) -> dict[str, Any]:
        config = self._load_config()
        bs = self._backup_cfg(config)
        folder = self.get_folder(config)
        result: dict[str, Any] = {
            "ok": False,
            "action": "push",
            "sites_written": False,
            "history_written": False,
            "manifest_written": False,
            "history_count": 0,
            "skipped": False,
            "message": "",
        }

        if not folder:
            result["skipped"] = True
            result["message"] = t("backup.no_folder")
            self.last_result = result
            return result
        if not force and not bs.get("enabled"):
            result["skipped"] = True
            result["message"] = t("backup.disabled")
            self.last_result = result
            return result
        if not force and not bs.get("auto_export", True):
            result["skipped"] = True
            result["message"] = t("backup.auto_export_off")
            self.last_result = result
            return result

        file_lock = self._acquire_folder_lock(folder)
        if file_lock is None:
            result["skipped"] = True
            result["message"] = t("backup.busy")
            self.logger.warning(result["message"])
            self.last_result = result
            return result

        try:
            ensure_dir(folder)
            exported_at = now_iso()
            components: list[str] = []

            sites_path = os.path.join(folder, SITES_FILENAME)
            history_path = os.path.join(folder, HISTORY_FILENAME)
            # Read and validate all existing shared inputs before the first
            # local DB/config mutation or remote write.
            remote_sites_payload = self._read_shared_json(sites_path, list_key="sites")
            remote_history_payload = (
                self._read_shared_json(history_path, list_key="posts")
                if bs.get("include_history", True)
                else None
            )

            # 공유 파일을 변경하기 전에 로컬 이력과 원격 정본의 합집합을 확정한다.
            # DB 병합이 실패하면 기존 sites/history/manifest를 그대로 보존한다.
            include_history = bool(bs.get("include_history", True))
            posts: list[dict] = []
            deleted_posts: list[dict] = []
            if include_history:
                try:
                    posts = self.db.export_all_posts()
                    deleted_posts = self.db.export_deleted_posts()
                except SyncHistoryDbError as e:
                    result["message"] = t("backup.history_export_failed", error=e)
                    self.logger.error(result["message"])
                    self.last_result = result
                    return result

                remote_posts, _ = extract_posts(remote_history_payload)
                remote_deleted = extract_deleted_posts(remote_history_payload)
                if remote_posts or remote_deleted:
                    try:
                        self.db.import_deleted_posts(remote_deleted)
                        self.db.import_posts_union(remote_posts)
                        posts = self.db.export_all_posts()
                        deleted_posts = self.db.export_deleted_posts()
                    except SyncHistoryDbError as e:
                        result["message"] = t("backup.push_merge_failed", error=e)
                        self.logger.error(result["message"])
                        self.last_result = result
                        return result

            # sites — 원격 변경과 삭제 표식을 먼저 병합해 다른 PC 변경을 보존
            sites = config.get("sites") if isinstance(config.get("sites"), list) else []
            deleted_sites = bs.get("deleted_sites", [])
            remote_sites, _ = extract_sites(remote_sites_payload)
            remote_deleted_sites = extract_deleted_sites(remote_sites_payload)
            sites = merge_sites(sites, remote_sites, remote_wins_same_url=False)
            deleted_sites = merge_site_tombstones(deleted_sites, remote_deleted_sites)
            sites, deleted_sites = apply_site_tombstones(sites, deleted_sites)
            remote_devices = extract_devices(remote_history_payload) if include_history else []
            devices_export: list[dict] = []

            def _apply_site_merge(cfg: dict) -> None:
                nonlocal devices_export
                cfg["sites"] = sites
                apply_portable_cfg(cfg, {"deleted_sites": deleted_sites})
                if include_history:
                    devices_export, _changed = reconcile_config_devices(cfg, remote_devices)

            config = self.config_manager.update_config(_apply_site_merge)
            bs = self._backup_cfg(config)
            sites_payload = build_sites_payload(
                sites, exported_at=exported_at, deleted_sites=deleted_sites
            )
            write_json_atomic(sites_path, sites_payload)
            result["sites_written"] = True
            components.append("sites")

            # history
            if bs.get("include_history", True):
                hist_payload = build_history_payload(
                    posts,
                    exported_at=exported_at,
                    deleted_posts=deleted_posts,
                    devices=devices_export,
                )
                write_json_atomic(history_path, hist_payload)
                result["history_written"] = True
                result["history_count"] = len(posts)
                components.append("synced_posts")

            write_json_atomic(
                os.path.join(folder, MANIFEST_FILENAME),
                build_manifest(exported_at=exported_at, components=components),
            )
            result["manifest_written"] = True

            # 메타 기록 (LWW 기준) — RMW 로 다른 설정 덮어쓰기 방지
            hist_written = result["history_written"]
            prev_hist = bs.get("last_history_push_at", "")

            def _apply_meta(cfg: dict) -> None:
                self._update_backup_meta(
                    cfg,
                    last_sites_push_at=exported_at,
                    last_history_push_at=exported_at if hist_written else prev_hist,
                    last_sync_at=exported_at,
                    last_sync_message=t("backup.export_done_at", at=exported_at),
                )

            self.config_manager.update_config(_apply_meta)

            result["ok"] = True
            result["message"] = t("backup.export_done", n=len(sites)) + (
                t("backup.export_history", n=result["history_count"])
                if result["history_written"]
                else ""
            )
            self.logger.info(result["message"])
            self.last_result = result
            return result
        except Exception as e:
            written = [
                name for name, field in (
                    ("sites.json", "sites_written"),
                    ("synced_posts.json", "history_written"),
                    ("manifest.json", "manifest_written"),
                ) if result[field]
            ]
            result["message"] = (
                t("backup.export_partial_failed", files=", ".join(written), error=e)
                if written else t("backup.export_failed", error=e)
            )
            self.logger.exception(result["message"])
            self.last_result = result
            return result
        finally:
            file_lock.release()
