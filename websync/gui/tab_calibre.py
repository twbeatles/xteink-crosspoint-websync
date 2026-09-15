"""Calibre 서재 연동 탭 컴포넌트 (CustomTkinter 기반)"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import customtkinter as ctk

from websync.gui.widgets import (
    CardFrame, COLOR_CARD_BG, COLOR_FG, COLOR_SECONDARY_FG, COLOR_ACCENT,
    COLOR_SUCCESS, COLOR_DANGER, get_font, create_scrollable_frame, create_scrolled_tree
)
from websync.integrations.notifier import ToastNotifier
from websync.i18n import t


class CalibreTab(ctk.CTkFrame):
    """Calibre 서재 조회를 담당하는 탭 패널"""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.service = app.service
        self.calibre = app.calibre

        self._build_ui()

    def _build_ui(self):
        body = create_scrollable_frame(self)

        calibre_top_card = CardFrame(body, title=t("gui.calibre.card_title"), subtitle=t("gui.calibre.card_sub"))
        calibre_top_card.pack(fill="x", padx=8, pady=6)

        grid_frame = ctk.CTkFrame(calibre_top_card, fg_color="transparent")
        grid_frame.pack(fill="x", padx=12, pady=10)
        grid_frame.columnconfigure(1, weight=1)

        ctk.CTkLabel(grid_frame, text=t("gui.calibre.path_label"), font=get_font(13)).grid(row=0, column=0, padx=(0, 8), pady=6, sticky="w")
        self.calibre_entry = ctk.CTkEntry(grid_frame, font=get_font(12), height=34)
        self.calibre_entry.grid(row=0, column=1, padx=4, pady=6, sticky="we")

        ctk.CTkButton(grid_frame, text=t("gui.calibre.browse"), font=get_font(12), width=90, height=34, command=self._browse_calibredb).grid(row=0, column=2, padx=4, pady=6)
        self.calibre_conn_btn = ctk.CTkButton(grid_frame, text=t("gui.calibre.connect"), font=get_font(12, "bold"), height=34, command=self._test_and_load_calibre)
        self.calibre_conn_btn.grid(row=0, column=3, padx=6, pady=6)
        self.app._bind_autosave(self.calibre_entry)

        ctk.CTkLabel(grid_frame, text=t("gui.calibre.lib_path_label"), font=get_font(13)).grid(row=1, column=0, padx=(0, 8), pady=6, sticky="w")
        self.calibre_lib_entry = ctk.CTkEntry(grid_frame, font=get_font(12), height=34)
        self.calibre_lib_entry.grid(row=1, column=1, padx=4, pady=6, sticky="we")

        ctk.CTkButton(grid_frame, text=t("gui.calibre.folder_select"), font=get_font(12), width=90, height=34, command=self._browse_calibre_library).grid(row=1, column=2, padx=4, pady=6)
        ctk.CTkLabel(
            grid_frame,
            text=t("gui.calibre.lib_hint"),
            font=get_font(12),
            text_color=COLOR_SECONDARY_FG,
        ).grid(row=1, column=3, padx=6, pady=6, sticky="w")
        self.app._bind_autosave(self.calibre_lib_entry)

        calibre_list_card = CardFrame(body, title=t("gui.calibre.list_title"), subtitle=t("gui.calibre.list_sub"))
        calibre_list_card.pack(fill="x", padx=8, pady=6)

        c_columns = ("id", "title", "authors", "formats")
        self.calibre_tree = create_scrolled_tree(
            calibre_list_card, c_columns, height=8, padx=10, pady=10
        )
        self.calibre_tree.heading("id", text="ID")
        self.calibre_tree.heading("title", text=t("gui.calibre.col_title"))
        self.calibre_tree.heading("authors", text=t("gui.calibre.col_authors"))
        self.calibre_tree.heading("formats", text=t("gui.calibre.col_formats"))
        self.calibre_tree.column("id", width=60, minwidth=40, anchor="center")
        self.calibre_tree.column("title", width=340, minwidth=120, anchor="w")
        self.calibre_tree.column("authors", width=200, minwidth=80, anchor="w")
        self.calibre_tree.column("formats", width=120, minwidth=80, anchor="center")

        calibre_action_card = CardFrame(body)
        calibre_action_card.pack(fill="x", padx=8, pady=6)

        self.calibre_send_btn = ctk.CTkButton(
            calibre_action_card,
            text=t("gui.calibre.send"),
            font=get_font(14, "bold"),
            fg_color=COLOR_ACCENT[0],
            hover_color=COLOR_ACCENT[1],
            height=42,
            command=self._send_calibre_books
        )
        self.calibre_send_btn.pack(fill="x", padx=12, pady=10)

    def _browse_calibredb(self):
        f = filedialog.askopenfilename(title=t("gui.calibre.browse_exe"), filetypes=[("Executable", "calibredb.exe"), ("All files", "*.*")])
        if f:
            self.calibre_entry.delete(0, tk.END)
            self.calibre_entry.insert(0, f)
            self.app._save_ui_settings()

    def _browse_calibre_library(self):
        d = filedialog.askdirectory(title=t("gui.calibre.browse_lib"))
        if d:
            self.calibre_lib_entry.delete(0, tk.END)
            self.calibre_lib_entry.insert(0, d)
            self.app._save_ui_settings()

    def _test_and_load_calibre(self, silent=False):
        self.app._save_ui_settings()
        self.calibre.calibre_path = self.calibre_entry.get().strip()
        self.calibre.library_path = self.calibre_lib_entry.get().strip()
        if not silent:
            self.app._log_message(t("gui.calibre.log_checking"))
            self.calibre_conn_btn.configure(state="disabled")
        if not self.calibre.test_connection():
            if not silent:
                self.app._log_message(t("gui.calibre.log_fail"))
                messagebox.showerror(t("gui.calibre.fail_title"), t("gui.calibre.fail_msg"))
                if not self.app._sync_busy:
                    self.calibre_conn_btn.configure(state="normal")
            return
        def worker():
            books = self.calibre.list_books()
            self.master.after(0, lambda: self._show_calibre_books(books, silent))

        threading.Thread(target=worker, daemon=True).start()

    def _show_calibre_books(self, books: list, silent: bool):
        if not self.app._sync_busy:
            self.calibre_conn_btn.configure(state="normal")
        for item in self.calibre_tree.get_children():
            self.calibre_tree.delete(item)
        if not books:
            if not silent:
                self.app._log_message(t("gui.calibre.log_empty"))
            return
        for bk in books:
            formats = bk.get("formats", "")
            formats_str = ", ".join(formats) if isinstance(formats, list) else str(formats)
            self.calibre_tree.insert("", "end", iid=str(bk.get("id")), values=(bk.get("id"), bk.get("title"), bk.get("authors", ""), formats_str))
        if not silent:
            self.app._log_message(t("gui.calibre.log_loaded", count=len(books)))
            ToastNotifier.show_toast(t("gui.calibre.toast_ok_title"), t("gui.calibre.toast_ok_msg", count=len(books)))

    def _send_calibre_books(self):
        selected_items = self.calibre_tree.selection()
        if not selected_items:
            messagebox.showwarning(t("gui.calibre.select_missing_title"), t("gui.calibre.select_missing"))
            return
        self.app._save_ui_settings()
        self.calibre_send_btn.configure(state="disabled")
        self.app._log_message(t("gui.calibre.log_send_start", count=len(selected_items)))

        def task():
            success_cnt = 0
            uploader = self.app._make_uploader()
            for item_id in selected_items:
                book_id = int(item_id)
                file_path = self.calibre.get_book_file_path(book_id)
                if not file_path or not os.path.exists(file_path):
                    self.master.after(0, lambda b=book_id: self.app._log_message(t("gui.calibre.log_path_fail", book_id=b)))
                    continue
                self.master.after(0, lambda p=file_path: self.app._log_message(t("gui.calibre.log_sending", name=os.path.basename(p))))
                results = uploader.upload_to_targets(file_path)
                all_ok, any_ok, summary = self.app._summarize_upload_results(results)
                if all_ok:
                    self.master.after(0, lambda p=file_path, s=summary: self.app._log_message(t("gui.calibre.log_ok", name=os.path.basename(p), summary=s)))
                    success_cnt += 1
                elif any_ok:
                    self.master.after(0, lambda p=file_path, s=summary: self.app._log_message(t("gui.calibre.log_partial", name=os.path.basename(p), summary=s)))
                    success_cnt += 1
                else:
                    self.master.after(0, lambda p=file_path, s=summary: self.app._log_message(t("gui.calibre.log_file_fail", name=os.path.basename(p), summary=s)))
            self.master.after(0, lambda: self._calibre_send_finished(success_cnt, len(selected_items)))

        threading.Thread(target=task, daemon=True).start()

    def _calibre_send_finished(self, success_cnt: int, total_cnt: int):
        if not self.app._sync_busy:
            self.calibre_send_btn.configure(state="normal")
        self.app._log_message(t("gui.calibre.log_send_end", success=success_cnt, total=total_cnt))
        if success_cnt > 0:
            ToastNotifier.show_toast(t("gui.calibre.toast_sync_title"), t("gui.calibre.toast_sync_msg", count=success_cnt))
            messagebox.showinfo(t("dialog.info"), t("gui.calibre.send_ok", count=success_cnt))
        else:
            messagebox.showerror(t("dialog.error"), t("gui.calibre.send_fail"))
