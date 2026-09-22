import threading
import time
from typing import Callable, Optional

from websync.epub.builder import EpubBuilder
from websync.upload.uploader import X3Uploader
from websync.config.manager import ConfigManager
from websync.db.history import SyncHistoryDb
from websync.core.logger import get_logger
from websync.core.process_lock import ProcessFileLock
from websync.backup.service import BackupSyncService
from websync.pipeline.article_keys import article_sync_key
from websync.pipeline.sync_pipeline import run_sync_pipeline_locked
from websync.pipeline.preview import preview_articles as run_preview_articles
from websync.pipeline.selected_sync import sync_selected_articles as run_sync_selected_articles
from websync.i18n import t


class SyncService:
    """전체 동기화 비즈니스 로직 조율을 전담하는 파사드 (SOLID: SRP/DIP)."""

    _pipeline_lock = threading.Lock()
    _process_lock = ProcessFileLock()

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.config = self.config_manager.load_config()
        self.db = SyncHistoryDb()
        self.logger = get_logger()
        self.backup_sync = BackupSyncService(self.config_manager, self.db, self.logger)
        self._last_pipeline_result: dict = {}
        self._cancel_event = threading.Event()
        self._backup_push_timer: threading.Timer | None = None
        self._backup_timer_lock = threading.Lock()
        self._pipeline_thread: threading.Thread | None = None
        self._apply_config_to_components()
        # dist 등과 함께 둔 synced_posts.json / *설정백업*.json 이어받기
        self._import_local_sidecars_once()

    def _import_local_sidecars_once(self) -> None:
        """실행 폴더의 레거시 JSON 이력을 로컬 DB·사이트에 합집합 반영."""
        try:
            from websync.backup.local_import import import_local_sidecars

            result = import_local_sidecars(
                self.config_manager, self.db, logger=self.logger
            )
            if result.get("history_changed") or result.get("sites_changed"):
                self._reload_config()
                for msg in result.get("messages") or []:
                    self.logger.info(f"[portable] {msg}")
        except Exception as e:
            self.logger.warning(t("pipeline.backup.sidecar_skip", error=e))

    def _apply_config_to_components(self):
        self.epub_builder = EpubBuilder(
            output_dir=self.config_manager.get_resolved_output_dir(self.config),
            font_family=self.config.get("font_family", "serif"),
            font_size=self.config.get("font_size", 16),
            line_height=self.config.get("line_height", 1.7),
            epub_theme=self.config.get("epub_theme", "default"),
            epub_custom_css=self.config.get("epub_custom_css", "")
        )
        df = self.config.get("device_files") or {}
        self.uploader = X3Uploader(
            x3_ip=self.config.get("x3_ip", "crosspoint.local"),
            devices=self.config.get("x3_devices", []),
            remote_dir=df.get("default_upload_path", "/"),
            primary_device_id=self.config.get("x3_primary_device_id", "") or "",
            primary_alias_ids=self.config.get("x3_primary_device_alias_ids") or [],
        )

    def is_pipeline_running(self) -> bool:
        if self._pipeline_lock.locked() or self._process_lock.held:
            return True
        return self._process_lock.is_held_by_other()

    def get_last_pipeline_result(self) -> dict:
        return dict(self._last_pipeline_result)

    def request_cancel(self) -> None:
        """실행 중인 파이프라인에 취소 요청 (사이트 경계에서 중단)."""
        self._cancel_event.set()

    def attach_pipeline_thread(self, thread: threading.Thread) -> None:
        """GUI 등 외부에서 기동한 파이프라인 스레드를 종료 대기에 등록합니다."""
        self._pipeline_thread = thread

    def shutdown_pipeline(self, timeout: float = 5.0) -> bool:
        """취소를 요청하고 워커·락이 풀릴 때까지 최대 timeout 초 대기합니다."""
        self.request_cancel()
        deadline = time.monotonic() + max(0.0, float(timeout))
        thread = self._pipeline_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        while self.is_pipeline_running() and time.monotonic() < deadline:
            time.sleep(0.05)
        return not self.is_pipeline_running()

    def clear_cancel(self) -> None:
        self._cancel_event.clear()

    def is_cancel_requested(self) -> bool:
        return self._cancel_event.is_set()

    def _reload_config(self):
        """최신 설정을 리로드하고 서비스 컴포넌트에 반영"""
        self.config = self.config_manager.load_config()
        self._apply_config_to_components()

    def _backup_cfg(self) -> dict:
        from websync.backup.portable_cfg import get_portable_cfg

        if not isinstance(self.config, dict):
            self._reload_config()
        return get_portable_cfg(self.config if isinstance(self.config, dict) else {})

    def maybe_backup_pull(
        self,
        *,
        force: bool = False,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> dict:
        """시작/파이프라인 전 공유 데이터 폴더 → 로컬 캐시 가져오기."""
        self._reload_config()
        bs = self._backup_cfg()
        if not force and not (bs.get("enabled") and bs.get("auto_import_on_start", True)):
            return {"ok": True, "skipped": True, "message": t("pipeline.backup.auto_import_off")}
        if not self.backup_sync.is_configured() and not force:
            return {"ok": True, "skipped": True, "message": t("pipeline.backup.folder_unset")}
        result = self.backup_sync.pull(force=force)
        self._reload_config()
        msg = result.get("message") or ""
        if msg and not result.get("skipped"):
            self.logger.info(f"[portable] pull: {msg}")
            if log_callback:
                log_callback(t("pipeline.backup.pull_log", msg=msg))
        return result

    def maybe_backup_push(
        self,
        *,
        force: bool = False,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> dict:
        """파이프라인/사이트 변경 후 로컬 → 공유 데이터 폴더 내보내기."""
        self._reload_config()
        bs = self._backup_cfg()
        if not force and not (bs.get("enabled") and bs.get("auto_export", True)):
            return {"ok": True, "skipped": True, "message": t("pipeline.backup.auto_export_off")}
        if not self.backup_sync.is_configured() and not force:
            return {"ok": True, "skipped": True, "message": t("pipeline.backup.folder_unset")}
        result = self.backup_sync.push(force=force)
        self._reload_config()
        msg = result.get("message") or ""
        if msg and not result.get("skipped"):
            self.logger.info(f"[portable] push: {msg}")
            if log_callback:
                log_callback(t("pipeline.backup.push_log", msg=msg))
        return result

    def schedule_backup_push(self, delay: float = 1.5) -> None:
        """사이트 저장 등 연속 변경 시 디바운스 후 push."""
        bs = self._backup_cfg()
        if not (bs.get("enabled") and bs.get("auto_export", True)):
            return
        if not self.backup_sync.is_configured():
            return

        def _fire():
            try:
                self.maybe_backup_push()
            except Exception as e:
                self.logger.warning(t("pipeline.backup.schedule_fail", error=e))

        with self._backup_timer_lock:
            if self._backup_push_timer is not None:
                try:
                    self._backup_push_timer.cancel()
                except Exception:
                    pass
            timer = threading.Timer(delay, _fire)
            timer.daemon = True
            self._backup_push_timer = timer
            timer.start()

    def flush_backup_push(self) -> None:
        """대기 중인 백업 push 타이머가 있다면 캔슬하고 즉시 동기 실행 (종료/클린업용)."""
        with self._backup_timer_lock:
            if self._backup_push_timer is not None:
                try:
                    self._backup_push_timer.cancel()
                except Exception:
                    pass
                self._backup_push_timer = None
                try:
                    self.maybe_backup_push(force=True)
                except Exception as e:
                    self.logger.warning(t("pipeline.backup.flush_fail", error=e))

    def run_backup_sync_now(
        self,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> dict:
        """수동 양방향 공유 데이터 동기화."""
        result = self.backup_sync.sync_now()
        self._reload_config()
        msg_parts = []
        pull = result.get("pull") or {}
        push = result.get("push") or {}
        if pull.get("message"):
            msg_parts.append(t("pipeline.backup.pull_part", msg=pull["message"]))
        if push.get("message"):
            msg_parts.append(t("pipeline.backup.push_part", msg=push["message"]))
        msg = " | ".join(msg_parts) if msg_parts else result.get("message", "")
        if msg:
            self.logger.info(f"[portable] sync_now: {msg}")
            if log_callback:
                log_callback(t("pipeline.backup.sync_log", msg=msg))
        return result

    @staticmethod
    def _article_sync_key(article: dict, site_name: str, base_url: str) -> str:
        return article_sync_key(article, site_name, base_url)

    def _try_acquire_pipeline_locks(
        self,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """파이프라인 스레드·프로세스 락을 비차단 획득. 실패 시 False."""
        if not self._pipeline_lock.acquire(blocking=False):
            msg = t("pipeline.lock.already_running")
            self.logger.warning(msg)
            if log_callback:
                log_callback(msg)
            else:
                print(msg)
            return False

        if not self._process_lock.acquire(blocking=False):
            self._pipeline_lock.release()
            msg = t("pipeline.lock.other_process")
            self.logger.warning(msg)
            if log_callback:
                log_callback(msg)
            else:
                print(msg)
            return False
        return True

    def _release_pipeline_locks(self) -> None:
        try:
            self._process_lock.release()
        finally:
            self._pipeline_lock.release()

    def _run_pipeline_body(
        self,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """락 보유 전제 하에 pull → 동기화 → push 실행."""
        self.maybe_backup_pull(log_callback=log_callback)
        ok = self._run_sync_pipeline_locked(log_callback, progress_callback)
        self.maybe_backup_push(log_callback=log_callback)
        return ok

    def begin_sync_pipeline_async(
        self,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """락을 선점한 뒤 백그라운드에서 파이프라인을 시작한다.

        Returns:
            True: 백그라운드 기동 수락 / False: 이미 실행 중 등으로 거부
        """
        if not self._try_acquire_pipeline_locks(log_callback):
            return False

        def _run():
            try:
                self._run_pipeline_body(log_callback, progress_callback)
            except Exception as e:
                self.logger.exception(t("pipeline.bg_sync_fail_log", error=e))
                if log_callback:
                    try:
                        log_callback(t("pipeline.bg_sync_fail", error=e))
                    except Exception:
                        pass
            finally:
                self._release_pipeline_locks()

        thread = threading.Thread(target=_run, daemon=True)
        self._pipeline_thread = thread
        thread.start()
        return True

    def run_sync_pipeline(
        self,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> bool:
        """
        동기화 파이프라인 실행 (호출 스레드에서 동기 실행).
        Returns:
            bool: True이면 성공 또는 신규 기사 없음 / False이면 오류 또는 이미 실행 중
        """
        if not self._try_acquire_pipeline_locks(log_callback):
            return False

        try:
            return self._run_pipeline_body(log_callback, progress_callback)
        finally:
            self._release_pipeline_locks()

    def _run_sync_pipeline_locked(
        self,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> bool:
        return run_sync_pipeline_locked(self, log_callback, progress_callback)

    def preview_articles(
        self,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> list[dict]:
        return run_preview_articles(self, log_callback, progress_callback)

    def sync_selected_articles(
        self,
        selected_articles: list[dict],
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> bool:
        return run_sync_selected_articles(
            self, selected_articles, log_callback, progress_callback
        )
