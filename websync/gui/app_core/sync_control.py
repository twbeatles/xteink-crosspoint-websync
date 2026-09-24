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
            bar = self.bottom_bar.progress_bar
            if hasattr(bar, "set"):
                bar.set(0)
            else:
                bar["value"] = 0
            message = t("pipeline.bg_sync_fail", error=error)
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

    def _request_sync_cancel(self):
        if hasattr(self, "service") and self.service:
            self.service.request_cancel()
            self._log_message(t("gui.app.cancel_requested"))

    def _run_immediate_sync(self):
        if not self._save_ui_settings():
            return
        self._set_sync_ui_busy(True)
        self.bottom_bar.progress_bar["value"] = 0
        self._log_message(t("gui.app.sync_requested"))

        def run():
            self.service.run_sync_pipeline(
                log_callback=self._make_log_callback(),
                progress_callback=self._make_progress_callback(),
            )

        self._start_pipeline_ui_task(
            run, name="sync-pipeline", on_success=self._sync_finished_ui
        )

    def _sync_finished_ui(self):
        try:
            if not self.root.winfo_exists():
                return
            bar = self.bottom_bar.progress_bar
            if hasattr(bar, "set"):
                bar.set(0)
            else:
                maximum = float(bar["maximum"] or 0)
                bar["value"] = maximum if maximum > 0 else 0
            self._set_sync_ui_busy(False)
            self._log_message(t("gui.app.sync_finished"))
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

