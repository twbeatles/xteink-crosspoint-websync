from __future__ import annotations

import os
import sys
import hashlib
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from websync.gui.widgets import (
    COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING,
    create_scrollable_frame, create_scrolled_tree, setup_dialog, bind_widget_mousewheel
)
from websync.upload.uploader import X3Uploader, normalize_device_host
from websync.config.exceptions import ConfigSaveError, ConfigLoadError
from websync.i18n import t


class SyncConnectionMixin:
    def _test_connection(self):
        self.conn_status_label.configure(text=t("gui.sync.connecting"), text_color=COLOR_WARNING[0])
        self.test_conn_btn.configure(state="disabled")

        def task():
            uploader = self.app._make_uploader()
            results = []
            for dev in uploader._build_target_list():
                ok = uploader.test_connection(dev["ip"])
                results.append((dev["name"], dev["ip"], ok))
            self.master.after(0, lambda: self._test_connection_finished(results))

        self.app._start_background_task(task, name="connection-test")

    def _test_connection_finished(self, results: list[tuple[str, str, bool]]):
        if not self.app._sync_busy:
            self.test_conn_btn.configure(state="normal")
        if not results:
            self.conn_status_label.configure(text=t("gui.sync.no_devices"), text_color=COLOR_DANGER[0])
            return
        ok_count = sum(1 for _, _, ok in results if ok)
        if ok_count == len(results):
            self.conn_status_label.configure(
                text=t("gui.sync.all_connected", count=len(results)),
                text_color=COLOR_SUCCESS[0],
            )
        elif ok_count > 0:
            failed = [name for name, _, ok in results if not ok]
            self.conn_status_label.configure(
                text=t("gui.sync.partial_connected", ok=ok_count, total=len(results), failed=", ".join(failed)),
                text_color=COLOR_WARNING[0],
            )
        else:
            self.conn_status_label.configure(text=t("gui.sync.all_failed"), text_color=COLOR_DANGER[0])
        for name, ip, ok in results:
            status = "✅" if ok else "❌"
            self.app._log_message(f"   {status} [{name}] {ip}")

    def _browse_directory(self):
        d = filedialog.askdirectory(initialdir=self.dir_entry.get())
        if d:
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, d)
            self.app._save_ui_settings()

    def _browse_file(self):
        f = filedialog.askopenfilename(title=t("gui.sync.choose_file_title"), filetypes=[("eBook files", "*.epub;*.pdf;*.txt;*.mobi"), ("All files", "*.*")])
        if f:
            self.file_entry.delete(0, tk.END)
            self.file_entry.insert(0, f)

    def _open_output_folder(self):
        folder = self.dir_entry.get().strip() or "./output"
        folder = os.path.abspath(folder)
        os.makedirs(folder, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(folder)
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", folder])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            messagebox.showerror(t("dialog.error"), t("gui.sync.folder_open_failed", error=e))

    def _direct_upload(self):
        file_path = self.file_entry.get().strip()
        if not file_path or not os.path.exists(file_path):
            messagebox.showwarning(t("dialog.warning"), t("gui.sync.invalid_file_path"))
            return
        if not self.app._save_ui_settings():
            return
        self.app._log_message(t("gui.sync.log_uploading", filename=os.path.basename(file_path)))
        self.direct_upload_btn.configure(state="disabled")

        def task():
            results = self.app._make_uploader().upload_to_targets(file_path)
            self.master.after(0, lambda: self._direct_upload_finished(results, file_path))

        self.app._start_background_task(task, name="direct-upload")

    def _direct_upload_finished(self, results: dict, file_path: str):
        if not self.app._sync_busy:
            self.direct_upload_btn.configure(state="normal")
        all_ok, any_ok, summary = self.app._summarize_upload_results(results)
        basename = os.path.basename(file_path)
        if all_ok:
            self.app._log_message(t("gui.sync.log_upload_ok", filename=basename, summary=summary))
            from websync.integrations.notifier import ToastNotifier
            ToastNotifier.show_toast(
                t("gui.sync.toast_upload_ok_title"),
                t("gui.sync.toast_upload_ok_body", filename=basename),
            )
            messagebox.showinfo(t("dialog.info"), t("gui.sync.upload_all_ok", summary=summary))
        elif any_ok:
            self.app._log_message(t("gui.sync.log_upload_partial", filename=basename, summary=summary))
            from websync.integrations.notifier import ToastNotifier
            ToastNotifier.show_toast(t("gui.sync.toast_upload_partial_title"), summary, is_error=True)
            messagebox.showwarning(
                t("gui.sync.partial_success_title"),
                t("gui.sync.upload_partial", summary=summary),
            )
        else:
            self.app._log_message(t("gui.sync.log_upload_fail", filename=basename, summary=summary))
            from websync.integrations.notifier import ToastNotifier
            ToastNotifier.show_toast(
                t("gui.sync.toast_upload_fail_title"),
                t("gui.sync.toast_upload_fail_body"),
                is_error=True,
            )
            messagebox.showerror(t("dialog.error"), t("gui.sync.upload_failed"))

    # ------------------------------------------------------------------
    # 스케줄러
    # ------------------------------------------------------------------

