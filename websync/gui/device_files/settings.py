from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from websync.gui.widgets import (
    HINT_COLOR,
    YELLOW_COLOR,
    GREEN_COLOR,
    RED_COLOR,
    create_scrollable_frame,
    create_scrolled_tree,
)
from websync.upload.device_client import (
    X3DeviceClient,
    DeviceClientError,
    normalize_remote_path,
    parent_remote_path,
    format_file_size,
    filter_old_sync_epubs,
)
from websync.upload.uploader import X3Uploader, normalize_upload_remote_dir
from websync.i18n import t


class DeviceFilesSettingsMixin:
    def _device_files_conf(self) -> dict:
        conf = self.service.config.get("device_files")
        return conf if isinstance(conf, dict) else {}

    def load_settings_from_config(self) -> None:
        df = self._device_files_conf()
        browse = normalize_remote_path(df.get("default_browse_path", "/"))
        upload = normalize_remote_path(df.get("default_upload_path", "/"))
        self.upload_path_var.set(upload)
        self.warn_overwrite_var.set(bool(df.get("warn_overwrite", True)))
        days = df.get("cleanup_older_days", 14)
        try:
            days = int(days)
        except (TypeError, ValueError):
            days = 14
        self.cleanup_days_var.set(str(max(1, days)))
        self._current_path = browse
        self.path_var.set(browse)

    def _set_upload_path_current(self) -> None:
        self.upload_path_var.set(normalize_remote_path(self._current_path))

    def _save_device_files_settings(self) -> None:
        config = self.service.config
        df = dict(config.get("device_files") or {})
        df["default_upload_path"] = normalize_upload_remote_dir(self.upload_path_var.get())
        df["default_browse_path"] = normalize_remote_path(self.path_var.get() or self._current_path)
        df["warn_overwrite"] = bool(self.warn_overwrite_var.get())
        try:
            df["cleanup_older_days"] = max(1, int(self.cleanup_days_var.get()))
        except (TypeError, ValueError):
            df["cleanup_older_days"] = 14
        config["device_files"] = df
        self.upload_path_var.set(df["default_upload_path"])
        if self.app._safe_save_config(config, reload=True):
            self.app._log_message(
                t(
                    "gui.device.log_settings_saved",
                    upload=df["default_upload_path"],
                    days=df["cleanup_older_days"],
                )
            )

    # ------------------------------------------------------------------
    # 클라이언트 / 기기 선택
    # ------------------------------------------------------------------

