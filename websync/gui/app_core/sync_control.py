from __future__ import annotations

import os
import hashlib
import subprocess
import threading
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
    def _request_sync_cancel(self):
        if hasattr(self, "service") and self.service:
            self.service.request_cancel()
            self._log_message(t("gui.app.cancel_requested"))

    def _run_immediate_sync(self):
        self._save_ui_settings()
        self._set_sync_ui_busy(True)
        self.bottom_bar.progress_bar["value"] = 0
        self._log_message(t("gui.app.sync_requested"))

        def run():
            self.service.run_sync_pipeline(
                log_callback=self._make_log_callback(),
                progress_callback=self._make_progress_callback(),
            )
            try:
                self.root.after(0, self._sync_finished_ui)
            except tk.TclError:
                return

        worker = threading.Thread(target=run, daemon=True)
        self.service.attach_pipeline_thread(worker)
        worker.start()

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
        try:
            if hasattr(self, "service") and self.service:
                self.service.shutdown_pipeline(timeout=5.0)
                self.service.flush_backup_push()
        except Exception:
            pass
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
        self.root.destroy()

    def run(self):
        self.root.mainloop()

