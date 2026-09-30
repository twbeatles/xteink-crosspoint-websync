from __future__ import annotations

import os
import hashlib
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

from websync.integrations.calibre import CalibreManager
from websync.core.paths import resolve_path
from websync.upload.uploader import X3Uploader, normalize_device_host
from websync.scheduler.manager import SchedulerManager
from websync.integrations.notifier import ToastNotifier
from websync.pipeline.service import SyncService
from websync.core.logger import get_log_dir
from websync.config.exceptions import ConfigSaveError
from websync.gui.widgets import (
    BG_COLOR, FG_COLOR, ACCENT_COLOR, SECONDARY_BG, TEXT_BG, GREEN_COLOR, RED_COLOR, YELLOW_COLOR, HINT_COLOR,
    center_window, setup_dialog
)
from websync.gui.tab_sync import SyncTab
from websync.gui.tab_calibre import CalibreTab
from websync.gui.tab_history import HistoryTab
from websync.gui.tab_device_files import DeviceFilesTab
from websync.gui.tab_settings import SettingsTab
from websync.gui.bottom_bar import BottomBar
from websync.i18n import t


class AppSyncControlMixin:
    def _make_background_thread(self, target, *, kwargs=None, name=None, daemon=True):
        """Create a tracked GUI worker that unregisters itself on completion."""
        holder = {}

        def tracked_target():
            try:
                target(**(kwargs or {}))
            finally:
                thread = holder.get("thread")
                lock = getattr(self, "_background_threads_lock", None)
                threads = getattr(self, "_background_threads", None)
                if thread is not None and lock is not None and threads is not None:
                    with lock:
                        threads.discard(thread)

        worker = threading.Thread(target=tracked_target, name=name, daemon=daemon)
        holder["thread"] = worker
        with self._background_threads_lock:
            self._background_threads.add(worker)
        return worker

    def _start_background_task(self, target, *, kwargs=None, name=None, daemon=True):
        worker = self._make_background_thread(
            target, kwargs=kwargs, name=name, daemon=daemon
        )
        worker.start()
        return worker

    def _start_pipeline_ui_task(self, task, *, name, on_success):
        """Run a pipeline worker and always restore the GUI after it finishes."""
        def run():
            error = None
            try:
                task()
            except Exception as exc:
                error = str(exc)
                self.service.logger.exception(
                    t("pipeline.bg_sync_fail_log", error=exc)
                )
            finally:
                callback = (
                    on_success if error is None
                    else lambda message=error: self._pipeline_failed_ui(message)
                )
                try:
                    self.root.after(0, callback)
                except (tk.TclError, RuntimeError):
                    pass  # The window has already closed.

        worker = self._make_background_thread(run, name=name)
        self.service.attach_pipeline_thread(worker)
        worker.start()
        return worker

    def _pipeline_failed_ui(self, error: str) -> None:
        try:
            if not self.root.winfo_exists():
                return
            self._set_sync_ui_busy(False)
            self._reset_progress()
            message = t("pipeline.bg_sync_fail", error=error)
            self._set_status(t("gui.bottom.status_failed"), "error")
            self._log_message(message)
            messagebox.showerror(t("dialog.error"), message, parent=self.root)
        except tk.TclError:
            return

    def _wait_for_background_tasks(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        current = threading.current_thread()
        while True:
            with self._background_threads_lock:
                workers = [
                    worker for worker in self._background_threads
                    if worker is not current and worker.is_alive()
                ]
            if not workers:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            workers[0].join(min(0.2, remaining))

    def _set_status(self, text: str, kind: str = "idle") -> None:
        """하단 상태 줄 갱신 (busy / ok / warn / error / idle)."""
        bar = getattr(self, "bottom_bar", None)
        if bar is not None and hasattr(bar, "set_status"):
            bar.set_status(text, kind)

    def _reset_progress(self) -> None:
        bar = getattr(self, "bottom_bar", None)
        if bar is None:
            return
        if hasattr(bar, "reset_progress"):
            bar.reset_progress()
            return
        progress = getattr(bar, "progress_bar", None)
        if hasattr(progress, "set"):
            progress.set(0)
        elif progress is not None:
            progress["value"] = 0

    def _request_sync_cancel(self):
        if hasattr(self, "service") and self.service:
            self.service.request_cancel()
            self._log_message(t("gui.app.cancel_requested"))
            self._set_status(t("gui.bottom.status_cancelling"), "warn")

    def _has_enabled_sites(self) -> bool:
        sites = (self.service.config or {}).get("sites") or []
        return any(s.get("enabled", True) for s in sites if isinstance(s, dict))

    def _ensure_sites_ready(self) -> bool:
        """활성 소스가 없으면 안내하고 소스 추가로 유도한다."""
        if self._has_enabled_sites():
            return True
        has_any = bool((self.service.config or {}).get("sites"))
        key = "gui.app.no_enabled_sites" if has_any else "gui.app.no_sites_yet"
        self._show_tab(0)
        if messagebox.askyesno(t("dialog.info"), t(key), parent=self.root):
            if has_any:
                self.tab_sync.focus_site_list()
            else:
                self.tab_sync._add_site_popup()
        return False

    def _show_tab(self, index: int) -> None:
        try:
            names = list(getattr(self.tabview, "_name_list", []))
            if 0 <= index < len(names):
                self.tabview.set(names[index])
        except Exception:
            pass

    def _run_immediate_sync(self):
        if not self._ensure_sites_ready():
            return
        if not self._save_ui_settings():
            return
        self._set_sync_ui_busy(True)
        self._reset_progress()
        self._set_status(t("gui.bottom.status_syncing"), "busy")
        self._log_message(t("gui.app.sync_requested"))

        def run():
            self.service.run_sync_pipeline(
                log_callback=self._make_log_callback(),
                progress_callback=self._make_progress_callback(),
            )

        self._start_pipeline_ui_task(
            run, name="sync-pipeline", on_success=self._sync_finished_ui
        )

    def _describe_last_result(self) -> tuple[str, str]:
        """마지막 파이프라인 결과를 (상태 문구, 종류)로 변환."""
        try:
            result = self.service.get_last_pipeline_result() or {}
        except Exception:
            result = {}
        status = result.get("status") or ""
        stamp = time.strftime("%H:%M")
        if status == "no_new":
            return t("gui.bottom.result_no_new", time=stamp), "ok"
        if status == "completed":
            if result.get("success"):
                return t("gui.bottom.result_ok", time=stamp), "ok"
            return t("gui.bottom.result_partial", time=stamp), "warn"
        if status == "cancelled":
            return t("gui.bottom.result_cancelled", time=stamp), "warn"
        if status == "no_targets":
            return t("gui.bottom.result_no_targets"), "error"
        if status == "no_sites":
            return t("gui.bottom.result_no_sites"), "warn"
        if status in ("errors", "empty_fetch", "db_error", "backup_pull_failed", "backup_push_failed", "failed"):
            return t("gui.bottom.result_error", time=stamp), "error"
        return t("gui.bottom.result_done", time=stamp), "ok"

    def _sync_finished_ui(self):
        try:
            if not self.root.winfo_exists():
                return
            self._reset_progress()
            self._set_sync_ui_busy(False)
            self._log_message(t("gui.app.sync_finished"))
            text, kind = self._describe_last_result()
            self._set_status(text, kind)
            self.tab_history._refresh_history()
        except tk.TclError:
            return

    # ------------------------------------------------------------------
    # 종료 처리
    # ------------------------------------------------------------------

    def _on_close(self):
        self._closing = True
        if hasattr(self, "service") and self.service:
            self.service.request_cancel()
        if self._opds_server:
            self._opds_server.stop()
        if self._web_dashboard:
            self._web_dashboard.stop()
        if self._calibre_watcher:
            self._calibre_watcher.stop()
        try:
            self.tab_settings._stop_watch_worker(wait_timeout=3.0)
        except Exception:
            pass
        try:
            if hasattr(self, "service") and self.service:
                self.service.shutdown_pipeline(timeout=5.0)
                self.service.flush_backup_push()
        except Exception:
            pass
        self._wait_for_background_tasks(timeout=5.0)
        self.root.destroy()

    def run(self):
        self.root.mainloop()

