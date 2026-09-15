from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from websync.gui.widgets import (
    RED_COLOR, GREEN_COLOR, ACCENT_COLOR, HINT_COLOR, BG_COLOR,
    create_scrollable_frame, setup_dialog
)
from websync.core.paths import resolve_path
from websync.core.logger import get_log_dir
from websync.servers.opds import OPDSServer
from websync.servers.web_dashboard import WebDashboard
from websync.watch.calibre import CalibreWatcher
from websync.i18n import t


class SettingsEpubMixin:
    def _save_epub_settings(self):
        config = self.service.config
        config["epub_merge_mode"] = self.merge_mode_var.get()
        config["epub_theme"] = self.epub_theme_cb.get()
        config["epub_custom_css"] = self.custom_css_entry.get().strip()
        self.app._safe_save_config(config, reload=True)

    def _on_theme_changed(self, event=None):
        theme = self.epub_theme_cb.get()
        if theme == "custom":
            self.custom_css_entry.configure(state="normal")
            self.custom_css_btn.configure(state="normal")
        else:
            self.custom_css_entry.configure(state="disabled")
            self.custom_css_btn.configure(state="disabled")
        self._save_epub_settings()

    def _browse_custom_css(self):
        f = filedialog.askopenfilename(title=t("gui.settings.epub.browse_title"), filetypes=[("CSS files", "*.css"), ("All files", "*.*")])
        if f:
            self.custom_css_entry.configure(state="normal")
            self.custom_css_entry.delete(0, tk.END)
            self.custom_css_entry.insert(0, f)
            self._save_epub_settings()
            if self.epub_theme_cb.get() != "custom":
                self.epub_theme_cb.set("custom")
                self._save_epub_settings()

    # ------------------------------------------------------------------
    # 서버 제어
    # ------------------------------------------------------------------

