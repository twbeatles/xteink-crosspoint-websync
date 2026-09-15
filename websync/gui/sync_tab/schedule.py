from __future__ import annotations

import os
import sys
import hashlib
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from websync.gui.widgets import (
    BG_COLOR, TEXT_BG, SECONDARY_BG, HINT_COLOR, YELLOW_COLOR, GREEN_COLOR, RED_COLOR,
    create_scrollable_frame, create_scrolled_tree, setup_dialog, bind_widget_mousewheel
)
from websync.upload.uploader import X3Uploader, normalize_device_host
from websync.config.exceptions import ConfigSaveError, ConfigLoadError
from websync.i18n import t


class SyncScheduleMixin:
    def _register_schedule(self):
        self.app._save_ui_settings()
        h, m = self.hour_cb.get(), self.min_cb.get()
        if self.scheduler.register_daily_task(h, m):
            messagebox.showinfo(t("gui.schedule.title"), t("gui.schedule.registered", hour=h, minute=m))
            config = self.service.config
            config["schedule"]["enabled"] = True
            self.app._safe_save_config(config)
        else:
            messagebox.showerror(t("gui.schedule.title"), t("gui.schedule.register_failed"))
        self._refresh_schedule_status()

    def _unregister_schedule(self):
        if self.scheduler.unregister_task():
            messagebox.showinfo(t("gui.schedule.title"), t("gui.schedule.unregistered"))
            config = self.service.config
            config["schedule"]["enabled"] = False
            self.app._safe_save_config(config)
        else:
            messagebox.showwarning(t("gui.schedule.title"), t("gui.schedule.unregister_failed"))
        self._refresh_schedule_status()

    def _refresh_schedule_status(self):
        status = self.scheduler.get_task_status()
        self.sched_status_label.configure(text=t("gui.schedule.status", status=status))

    # ------------------------------------------------------------------
    # 추가 기기 관리 팝업
    # ------------------------------------------------------------------

