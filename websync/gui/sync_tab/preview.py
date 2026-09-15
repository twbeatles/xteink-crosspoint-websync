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


class SyncPreviewMixin:
    def open_preview_window(self):
        """프리뷰 실행 후 결과를 새 윈도우에 체크박스와 함께 표시합니다."""
        self.app._log_message(t("gui.preview.log_start"))
        self.app._set_sync_ui_busy(True)
        self.app.bottom_bar.progress_bar["value"] = 0

        def run():
            log_cb = self.app._make_log_callback()
            prog_cb = self.app._make_progress_callback()
            self._preview_data = self.service.preview_articles(log_callback=log_cb, progress_callback=prog_cb)
            
            try:
                self.master.after(0, self._show_preview_results)
            except tk.TclError:
                return

        worker = threading.Thread(target=run, daemon=True)
        self.service.attach_pipeline_thread(worker)
        worker.start()

    def _show_preview_results(self):
        self.app._set_sync_ui_busy(False)
        self.app.bottom_bar.progress_bar["value"] = 0
        self.app._log_message(t("gui.preview.log_done"))

        if not self._preview_data:
            messagebox.showinfo(t("gui.preview.result_title"), t("gui.preview.no_articles"))
            return

        dialog = tk.Toplevel(self.app.root)
        dialog.title(t("gui.preview.window_title"))
        dialog.geometry("700x500")
        setup_dialog(dialog, self.app.root, 700, 500)

        # 안내
        lbl = ttk.Label(dialog, text=t("gui.preview.hint"))
        lbl.pack(fill="x", padx=15, pady=10)

        # 테이블
        columns = ("selected", "site", "title", "url")
        tree = create_scrolled_tree(dialog, columns, height=12)
        tree.heading("selected", text=t("gui.preview.col_select"))
        tree.heading("site", text=t("gui.preview.col_site"))
        tree.heading("title", text=t("gui.preview.col_title"))
        tree.heading("url", text="URL")
        
        tree.column("selected", width=50, anchor="center")
        tree.column("site", width=120, anchor="w")
        tree.column("title", width=320, anchor="w")
        tree.column("url", width=180, anchor="w")

        # 체크 상태 저장
        checked_state = {i: True for i in range(len(self._preview_data))}

        def refresh_tree():
            for item in tree.get_children():
                tree.delete(item)
            for idx, art in enumerate(self._preview_data):
                chk = "☑" if checked_state[idx] else "☐"
                tree.insert("", "end", iid=str(idx), values=(
                    chk, art["site_name"], art["title"], art["url"]
                ))

        refresh_tree()

        # 체크 클릭 핸들링
        def on_click(event):
            item = tree.identify_row(event.y)
            if not item:
                return
            idx = int(item)
            checked_state[idx] = not checked_state[idx]
            refresh_tree()

        tree.bind("<Button-1>", on_click)

        # 전체 토글
        def toggle_all():
            val = not all(checked_state.values())
            for k in checked_state:
                checked_state[k] = val
            refresh_tree()

        # 동기화 실행
        def run_selected_sync():
            selected_arts = [self._preview_data[i] for i, checked in checked_state.items() if checked]
            if not selected_arts:
                messagebox.showwarning(t("gui.preview.none_selected_title"), t("gui.preview.none_selected"), parent=dialog)
                return
            
            dialog.destroy()
            self._run_selected_sync_task(selected_arts)

        btn_bar = ttk.Frame(dialog)
        btn_bar.pack(fill="x", side="bottom", pady=10, padx=15)
        
        ttk.Button(btn_bar, text=t("gui.preview.toggle_all"), command=toggle_all).pack(side="left")
        ttk.Button(btn_bar, text=t("gui.sync.cancel"), command=dialog.destroy).pack(side="right", padx=5)
        ttk.Button(btn_bar, text=t("gui.preview.send_selected"), command=run_selected_sync).pack(side="right")

    def _run_selected_sync_task(self, selected_articles):
        if self.service.is_pipeline_running():
            messagebox.showwarning(t("gui.preview.busy_title"), t("gui.preview.busy"))
            return

        self.app._set_sync_ui_busy(True)
        self.app.bottom_bar.progress_bar["value"] = 0
        self.app._log_message(t("gui.preview.log_selected", count=len(selected_articles)))

        def task():
            log_cb = self.app._make_log_callback()
            prog_cb = self.app._make_progress_callback()
            self.service.sync_selected_articles(selected_articles, log_callback=log_cb, progress_callback=prog_cb)
            try:
                self.master.after(0, self.app._sync_finished_ui)
            except tk.TclError:
                return

        worker = threading.Thread(target=task, daemon=True)
        self.service.attach_pipeline_thread(worker)
        worker.start()

