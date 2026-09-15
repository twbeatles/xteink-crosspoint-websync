import os
import json
import secrets
import shutil
import threading
import copy
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from websync.core.paths import PROJECT_ROOT, resolve_path
from websync.core.process_lock import ProcessFileLock
from websync.config.exceptions import ConfigLoadError, ConfigSaveError, ConfigConflictError
from websync.config.validator import log_validation_warnings, validate_config
from websync.i18n import t

class ConfigManager:


    """설정 파일(config.json)의 로드 및 저장을 전담하는 클래스"""
    _lock = threading.Lock()

    DEFAULT_SITE = {
        "name": "",
        "type": "css",
        "url": "",
        "item_selector": ".post-item",
        "title_selector": ".post-title",
        "content_selector": ".post-content",
        "link_selector": "a[href]",
        "remove_selectors": "",
        "limit": 5,
        "enabled": True,
        "include_images": False,
        "translate_to": "",
        "fetch_detail_page": False,
    }

    CONFIG_VERSION = 3

    DEFAULT_CONFIG = {
        "config_version": CONFIG_VERSION,
        "x3_ip": "crosspoint.local",
        "x3_primary_device_id": "",
        "x3_devices": [],
        "output_dir": "./output",
        "calibre_path": "C:\\Program Files\\Calibre2\\calibredb.exe",
        "calibre_library_path": "",
        "font_family": "serif",
        "font_size": 16,
        "line_height": 1.7,
        "epub_cover": True,
        "epub_merge_mode": "per_site",
        "epub_theme": "default",
        "epub_custom_css": "",
        "sites": [
            {
                "name": "예시 블로그 (일반 웹)",
                "type": "css",
                "url": "https://example.com/blog",
                "item_selector": ".post-item",
                "title_selector": ".post-title",
                "content_selector": ".post-content",
                "link_selector": "a[href]",
                "remove_selectors": ".ad-banner, .reply-box",
                "limit": 5,
                "enabled": True,
                "include_images": False,
                "translate_to": "",
            },
            {
                "name": "예시 뉴스 피드 (RSS)",
                "type": "rss",
                "url": "https://example.com/feed.xml",
                "limit": 5,
                "enabled": False,
                "include_images": False,
                "translate_to": "",
            }
        ],
        "schedule": {
            "enabled": False,
            "hour": "07",
            "minute": "00"
        },
        "ai_summary": {
            "enabled": False,
            "provider": "openai",
            "api_key": "",
            "model": "gpt-4o-mini",
            "ollama_host": "http://localhost:11434"
        },
        "translation": {
            "enabled": False,
            "provider": "googletrans",
            "libretranslate_host": "http://localhost:5000",
            "libretranslate_api_key": ""
        },
        "opds_server": {
            "enabled": False,
            "port": 8765,
            "bind_host": "127.0.0.1",
            "allow_lan": False,
            "api_key": ""
        },
        "web_dashboard": {
            "enabled": False,
            "port": 8766,
            "bind_host": "127.0.0.1",
            "allow_lan": False,
            "api_token": ""
        },
        "calibre_watch": {
            "enabled": False,
            "watch_dir": "",
            "pending_files": [],
        },
        "device_files": {
            "default_browse_path": "/",
            "default_upload_path": "/",
            "cleanup_older_days": 14,
            "warn_overwrite": True
        },
        # 공유 데이터 폴더 (OneDrive 등) — 사이트·이력 정본
        "portable_data": {
            "enabled": False,
            "folder": "",
            "include_history": True,
            "auto_export": True,
            "auto_import_on_start": True,
            "history_mode": "per_device",
            "wizard_completed": False,
            "last_sites_push_at": "",
            "last_history_push_at": "",
            "last_sync_at": "",
            "last_sync_message": "",
            "deleted_sites": [],
        },
        # 하위 호환: portable_data 와 공통 필드 미러
        "backup_sync": {
            "enabled": False,
            "folder": "",
            "include_history": True,
            "auto_export": True,
            "auto_import_on_start": True,
            "last_sites_push_at": "",
            "last_history_push_at": "",
            "last_sync_at": "",
            "last_sync_message": "",
        },
        "auto_check_update": True,
        "ui_language": "auto",
        # RMW 충돌 감지용 (파일에 저장, UI 비노출)
        "_config_revision": 0,
    }


    def __init__(self, config_path: str | None = None):
        if config_path is None:
            self.config_path = os.path.join(PROJECT_ROOT, "config.json")
        else:
            self.config_path = resolve_path(config_path)
        self._process_lock_path = f"{self.config_path}.lock"

    def _acquire_process_lock(self) -> ProcessFileLock:
        """동일 config의 프로세스 간 read-modify-write를 직렬화합니다."""
        lock = ProcessFileLock(self._process_lock_path)
        if not lock.acquire(blocking=True, timeout=30.0):
            raise TimeoutError(t("config.lock_timeout", path=self._process_lock_path))
        return lock

    @contextmanager
    def _process_guard(self, error_type):
        try:
            lock = self._acquire_process_lock()
        except TimeoutError as e:
            raise error_type(str(e)) from e
        try:
            yield
        finally:
            lock.release()

    @classmethod
    def _deep_merge(cls, default: dict, current: dict) -> tuple[dict, bool]:
        """default를 기준으로 current에 결손 키를 재귀 보강합니다."""
        updated = False
        result = copy.deepcopy(current)
        for key, default_val in default.items():
            if key not in result:
                result[key] = copy.deepcopy(default_val)
                updated = True
            elif isinstance(default_val, dict) and isinstance(result.get(key), dict):
                merged, sub_updated = cls._deep_merge(default_val, result[key])
                if sub_updated:
                    result[key] = merged
                    updated = True
        return result, updated

    @classmethod
    def _merge_sites(cls, sites: list) -> tuple[list, bool]:
        """사이트 항목별 결손 필드를 DEFAULT_SITE 기준으로 보강합니다."""
        updated = False
        merged_sites = []
        for site in sites:
            if not isinstance(site, dict):
                continue
            merged, changed = cls._deep_merge(cls.DEFAULT_SITE, site)
            merged_sites.append(merged)
            if changed:
                updated = True
        return merged_sites, updated

    def _ensure_api_token(self, config: dict) -> bool:
        """웹 대시보드 API 토큰이 없으면 자동 생성합니다."""
        web = config.get("web_dashboard")
        if not isinstance(web, dict):
            return False
        if web.get("api_token"):
            return False
        web["api_token"] = secrets.token_urlsafe(24)
        return True

    def _ensure_opds_api_key(self, config: dict) -> bool:
        """OPDS LAN 공개용 API 키가 없으면 자동 생성합니다."""
        opds = config.get("opds_server")
        if not isinstance(opds, dict):
            return False
        if opds.get("api_key"):
            return False
        opds["api_key"] = secrets.token_urlsafe(16)
        return True

    def _normalize_loaded(self, config: dict) -> tuple[dict, bool]:
        """로드된 dict에 결손 키 보강. (updated 여부 반환)"""
        config, updated = self._deep_merge(self.DEFAULT_CONFIG, config)

        if "sites" in config and isinstance(config["sites"], list):
            merged_sites, sites_updated = self._merge_sites(config["sites"])
            config["sites"] = merged_sites
            updated = updated or sites_updated

        if self._ensure_api_token(config):
            updated = True

        if self._ensure_opds_api_key(config):
            updated = True

        # portable_data ← backup_sync 이관 및 양방향 미러
        from websync.backup.portable_cfg import migrate_portable_into_config
        from websync.upload.device_ids import ensure_device_ids_in_config

        if migrate_portable_into_config(config):
            updated = True

        if ensure_device_ids_in_config(config):
            updated = True

        if config.get("config_version", 0) < self.CONFIG_VERSION:
            config["config_version"] = self.CONFIG_VERSION
            updated = True

        if "_config_revision" not in config:
            config["_config_revision"] = 0
            updated = True

        return config, updated

    def _read_raw_unlocked(self) -> dict:
        """락 보유 중 디스크에서 읽고 정규화 (자동 저장 없음)."""
        if not os.path.exists(self.config_path):
            cfg = copy.deepcopy(self.DEFAULT_CONFIG)
            self._ensure_api_token(cfg)
            self._ensure_opds_api_key(cfg)
            return cfg
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            if not isinstance(config, dict):
                raise ConfigLoadError(t("config.must_be_object"))
            config, _ = self._normalize_loaded(config)
            return config
        except json.JSONDecodeError as e:
            corrupt_path = f"{self.config_path}.corrupt"
            try:
                shutil.copy2(self.config_path, corrupt_path)
            except OSError:
                corrupt_path = None
            raise ConfigLoadError(
                t("config.parse_failed", error=e, path=corrupt_path),
                corrupt_path=corrupt_path,
            ) from e
        except ConfigLoadError:
            raise
        except OSError as e:
            raise ConfigLoadError(t("config.read_failed", error=e)) from e

    def load_config(self) -> dict:
        with self._lock, self._process_guard(ConfigLoadError):
            if not os.path.exists(self.config_path):
                cfg = copy.deepcopy(self.DEFAULT_CONFIG)
                self._ensure_api_token(cfg)
                self._save_config_unlocked(cfg, bump_revision=False)
                return cfg
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)

                config, updated = self._normalize_loaded(config)

                if updated:
                    self._save_config_unlocked(config, bump_revision=False)
                log_validation_warnings(config)
                return config

            except json.JSONDecodeError as e:
                corrupt_path = f"{self.config_path}.corrupt"
                try:
                    shutil.copy2(self.config_path, corrupt_path)
                except OSError:
                    corrupt_path = None
                raise ConfigLoadError(
                    t("config.parse_failed", error=e, path=corrupt_path),
                    corrupt_path=corrupt_path,
                ) from e
            except OSError as e:
                raise ConfigLoadError(t("config.read_failed", error=e)) from e

    def save_config(self, config_data: dict, *, expected_revision: int | None = None):
        """설정을 원자적으로 저장합니다.

        expected_revision 이 주어지면 디스크 revision 과 일치할 때만 저장합니다.
        불일치 시 ConfigConflictError (disk_config 포함).
        """
        with self._lock, self._process_guard(ConfigSaveError):
            if expected_revision is not None:
                try:
                    disk = self._read_raw_unlocked()
                except ConfigLoadError:
                    disk = copy.deepcopy(self.DEFAULT_CONFIG)
                disk_rev = int(disk.get("_config_revision") or 0)
                if disk_rev != int(expected_revision):
                    raise ConfigConflictError(
                        t("config.conflict", disk=disk_rev, expected=expected_revision),
                        disk_config=disk,
                    )
            self._save_config_unlocked(config_data, bump_revision=True)

    def update_config(self, mutator) -> dict:
        """디스크 최신본을 읽어 mutator(config) 적용 후 저장 (RMW 안전).

        mutator: Callable[[dict], None]
        Returns: 저장된 config
        """
        with self._lock, self._process_guard(ConfigSaveError):
            config = self._read_raw_unlocked()
            mutator(config)
            self._save_config_unlocked(config, bump_revision=True)
            log_validation_warnings(config)
            return config

    def patch_fields(self, **fields) -> dict:
        """디스크 최신본에 최상위 필드만 덮어씁니다 (사이트 목록 등 다른 키 보존)."""
        def mutate(cfg: dict) -> None:
            for key, value in fields.items():
                cfg[key] = value

        return self.update_config(mutate)

    def _save_config_unlocked(self, config_data: dict, *, bump_revision: bool = True):
        """락이 이미 잡힌 상태에서 호출하는 내부 저장 전용 함수 (원자적 쓰기).

        실패 시 ConfigSaveError를 발생시킵니다.
        """
        tmp_path = (
            f"{self.config_path}.{os.getpid()}.{threading.get_ident()}."
            f"{uuid.uuid4().hex}.tmp"
        )
        try:
            config_data.setdefault("config_version", self.CONFIG_VERSION)
            if bump_revision:
                try:
                    rev = int(config_data.get("_config_revision") or 0)
                except (TypeError, ValueError):
                    rev = 0
                config_data["_config_revision"] = rev + 1
            else:
                config_data.setdefault("_config_revision", 0)
            directory = os.path.dirname(self.config_path) or "."
            os.makedirs(directory, exist_ok=True)
            bak_path = f"{self.config_path}.bak"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
                f.flush()
                os.fsync(f.fileno())
            if os.path.exists(self.config_path):
                try:
                    shutil.copy2(self.config_path, bak_path)
                except OSError:
                    pass
            os.replace(tmp_path, self.config_path)
        except ConfigSaveError:
            raise
        except Exception as e:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise ConfigSaveError(t("config.save_failed", error=e)) from e

    def get_validation_errors(self, config: dict | None = None) -> list[str]:
        cfg = config if config is not None else self.load_config()
        return validate_config(cfg)

    def get_resolved_output_dir(self, config: dict | None = None) -> str:
        cfg = config or self.load_config()
        return resolve_path(cfg.get("output_dir", "./output"))

    def export_sites(self, file_path: str, site_indices: list[int] | None = None) -> None:
        """선택된 인덱스의 사이트 설정을 JSON 파일로 내보냅니다."""
        config = self.load_config()
        sites = config.get("sites", [])
        
        if site_indices is not None:
            exported_sites = [sites[i] for i in site_indices if 0 <= i < len(sites)]
        else:
            exported_sites = sites

        export_data = {
            "export_version": 1,
            "exported_at": datetime.now().isoformat() if hasattr(datetime, "now") else str(time.time()),
            "sites": exported_sites
        }
        
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            raise ConfigSaveError(t("config.export_failed", error=e)) from e

    def import_sites(self, file_path: str) -> list[dict]:
        """JSON 파일에서 사이트 설정을 읽어와 기존 설정에 중복 없이 임포트한 뒤 추가된 목록을 반환합니다.

        디스크 최신본에 대해 RMW(`update_config`)로 병합하여 동시 저장과 경합해도
        다른 필드를 덮어쓰지 않습니다.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                import_data = json.load(f)
        except Exception as e:
            raise ConfigLoadError(t("config.import_read_failed", error=e)) from e

        if not isinstance(import_data, dict) or "sites" not in import_data:
            raise ConfigLoadError(t("config.import_format"))

        imported_sites = import_data.get("sites", [])
        if not isinstance(imported_sites, list):
            raise ConfigLoadError(t("config.import_format"))

        # 임포트 후보를 미리 정규화 (mutator 밖)
        prepared: list[dict] = []
        from websync.backup.format import now_iso
        for site in imported_sites:
            if not isinstance(site, dict):
                continue
            url = site.get("url", "").strip().lower()
            if not url:
                continue
            merged_site, _ = self._deep_merge(self.DEFAULT_SITE, site)
            merged_site["_sync_updated_at"] = now_iso()
            prepared.append(merged_site)

        if not prepared:
            return []

        added_holder: list[dict] = []

        def _mutator(config: dict) -> None:
            current_sites = config.setdefault("sites", [])
            if not isinstance(current_sites, list):
                current_sites = []
                config["sites"] = current_sites
            current_urls = {
                (s.get("url") or "").strip().lower()
                for s in current_sites
                if isinstance(s, dict) and s.get("url")
            }
            for site in prepared:
                url = (site.get("url") or "").strip().lower()
                if not url or url in current_urls:
                    continue
                current_sites.append(site)
                current_urls.add(url)
                added_holder.append(site)
            if added_holder:
                from websync.backup.portable_cfg import apply_portable_cfg, get_portable_cfg
                added_urls = {
                    (site.get("url") or "").strip().lower() for site in added_holder
                }
                portable = get_portable_cfg(config)
                portable["deleted_sites"] = [
                    item for item in portable.get("deleted_sites", [])
                    if (item.get("url") or "").strip().lower() not in added_urls
                ]
                apply_portable_cfg(config, portable)

        self.update_config(_mutator)
        return added_holder

