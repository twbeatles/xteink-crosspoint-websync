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


class SettingsServersMixin:
    def _toggle_opds(self):
        if self.app._opds_server and self.app._opds_server.is_running:
            self.app._opds_server.stop()
            self.app._opds_server = None
            self.opds_start_btn.configure(text=t("gui.settings.server_start"))
            self.opds_status_label.configure(text=t("gui.settings.stopped"), text_color=RED_COLOR)
            self.opds_url_label.configure(text="")
        else:
            try:
                port = int(self.opds_port_sp.get())
            except ValueError:
                port = 8765
            output_dir = resolve_path(self.app.tab_sync.dir_entry.get().strip() or "./output")
            allow_lan = self.opds_allow_lan_var.get()
            bind_host = "0.0.0.0" if allow_lan else "127.0.0.1"
            config = self.config_manager.load_config()
            opds_conf = config.get("opds_server", {})
            api_key = opds_conf.get("api_key", "")
            self.app._opds_server = OPDSServer(
                output_dir=output_dir,
                port=port,
                bind_host=bind_host,
                api_key=api_key,
                require_auth=allow_lan,
            )
            if self.app._opds_server.start():
                self.opds_start_btn.configure(text=t("gui.settings.server_stop"))
                self.opds_status_label.configure(text=t("gui.settings.running"), text_color=GREEN_COLOR)
                url = self.app._opds_server.get_url()
                self.opds_url_label.configure(text=url)
                self.app._log_message(t("gui.settings.opds.log_start", url=url))
                self._refresh_opds_key_display()
            else:
                messagebox.showerror(t("dialog.error"), t("gui.settings.opds.start_fail", port=port))

    def _toggle_web(self):
        if self.app._web_dashboard and self.app._web_dashboard.is_running:
            self.app._web_dashboard.stop()
            self.app._web_dashboard = None
            self.web_start_btn.configure(text=t("gui.settings.server_start"))
            self.web_status_label.configure(text=t("gui.settings.stopped"), text_color=RED_COLOR)
            self.web_url_label.configure(text="")
        else:
            try:
                port = int(self.web_port_sp.get())
            except ValueError:
                port = 8766

            config = self.config_manager.load_config()
            web_conf = config.get("web_dashboard", {})
            api_token = web_conf.get("api_token", "")
            bind_host = "0.0.0.0" if self.web_allow_lan_var.get() else "127.0.0.1"

            def sync_cb():
                # 락을 선점한 뒤 백그라운드 기동 — False 면 이미 실행 중(핸들러가 409)
                return self.service.begin_sync_pipeline_async(
                    log_callback=self.app._make_log_callback()
                )

            def cancel_cb():
                self.service.request_cancel()
                return True

            self.app._web_dashboard = WebDashboard(
                port=port,
                bind_host=bind_host,
                api_token=api_token,
                sync_callback=sync_cb,
                get_log_callback=self.app._get_log_for_web,
                pipeline_busy_callback=self.service.is_pipeline_running,
                get_status_callback=self.service.get_last_pipeline_result,
                allow_lan=self.web_allow_lan_var.get(),
                cancel_callback=cancel_cb,
            )
            if self.web_allow_lan_var.get():
                if not messagebox.askyesno(
                    t("gui.settings.web.lan_warn_title"),
                    t("gui.settings.web.lan_warn"),
                    icon="warning",
                ):
                    return
            if self.app._web_dashboard.start():
                self.web_start_btn.configure(text=t("gui.settings.server_stop"))
                self.web_status_label.configure(text=t("gui.settings.running"), text_color=GREEN_COLOR)
                url = self.app._web_dashboard.get_url()
                self.web_url_label.configure(text=url)
                self.app._log_message(t("gui.settings.web.log_start", url=url))
                self._refresh_web_token_display()
            else:
                messagebox.showerror(t("dialog.error"), t("gui.settings.web.start_fail", port=port))

