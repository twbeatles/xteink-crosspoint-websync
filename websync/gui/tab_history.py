"""동기화 이력 탭 컴포넌트 (CustomTkinter 기반)"""
from __future__ import annotations

import hashlib
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import customtkinter as ctk

from websync.gui.widgets import (
    CardFrame, COLOR_CARD_BG, COLOR_FG, COLOR_SECONDARY_FG, COLOR_ACCENT,
    COLOR_DANGER, COLOR_WARNING, get_font, create_scrollable_frame, create_scrolled_tree
)
from websync.db.history import SyncHistoryDbError
from websync.backup.atomic_io import read_json_safe, write_json_atomic
from websync.backup.format import build_history_payload, extract_deleted_posts, extract_posts
from websync.i18n import t


class HistoryTab(ctk.CTkFrame):
    """동기화 이력 조회를 담당하는 탭 패널"""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.service = app.service
        self.db = app.service.db
        
        self._history_url_by_iid: dict[str, str] = {}
        self._build_ui()

    def _build_ui(self):
        body = create_scrollable_frame(self)

        ctrl_card = CardFrame(body)
        ctrl_card.pack(fill="x", padx=8, pady=6)

        btn_row = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=10)

        ctk.CTkButton(btn_row, text=t("gui.history.refresh"), font=get_font(12, "bold"), width=105, height=34, command=self._refresh_history).pack(side="left", padx=3)
        ctk.CTkButton(btn_row, text=t("gui.history.delete_selected"), font=get_font(12), width=165, height=34, fg_color=("#e9ecef", "#343a40"), text_color=COLOR_FG, command=self._delete_history_entry).pack(side="left", padx=3)
        ctk.CTkButton(btn_row, text=t("gui.history.clear_all"), font=get_font(12, "bold"), width=120, height=34, fg_color=COLOR_DANGER[0], hover_color=COLOR_DANGER[1], command=self._clear_all_history).pack(side="left", padx=3)

        ctk.CTkButton(btn_row, text=t("gui.history.export_json"), font=get_font(12), width=120, height=34, fg_color=("#e9ecef", "#343a40"), text_color=COLOR_FG, command=self._export_history_json).pack(side="right", padx=3)
        ctk.CTkButton(btn_row, text=t("gui.history.import_json"), font=get_font(12), width=120, height=34, fg_color=("#e9ecef", "#343a40"), text_color=COLOR_FG, command=self._import_history_json).pack(side="right", padx=3)

        self.history_count_label = ctk.CTkLabel(ctrl_card, text="", font=get_font(13, "bold"), text_color=COLOR_WARNING[0])
        self.history_count_label.pack(anchor="e", padx=12, pady=(0, 8))

        hist_card = CardFrame(body, title=t("gui.history.card_title"), subtitle=t("gui.history.card_sub"))
        hist_card.pack(fill="x", padx=8, pady=6)

        h_columns = ("site", "title", "synced_at", "url")
        self.hist_tree = create_scrolled_tree(
            hist_card, h_columns, height=10, selectmode="extended"
        )
        self.hist_tree.heading("site", text=t("gui.history.col_site"))
        self.hist_tree.heading("title", text=t("gui.history.col_title"))
        self.hist_tree.heading("synced_at", text=t("gui.history.col_synced_at"))
        self.hist_tree.heading("url", text="URL")
        self.hist_tree.column("site", width=130, minwidth=80, anchor="w")
        self.hist_tree.column("title", width=300, minwidth=120, anchor="w")
        self.hist_tree.column("synced_at", width=150, minwidth=100, anchor="center")
        self.hist_tree.column("url", width=250, minwidth=120, anchor="w")
        self.hist_tree.bind("<Double-1>", self._on_history_double_click)

    def _on_history_double_click(self, _event=None):
        selected = self.hist_tree.selection()
        if not selected:
            return
        url = self._history_url_by_iid.get(selected[0], "")
        if not url:
            return
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(url)
        self.app._log_message(t("gui.history.log_url_copied", url=url[:80], ellipsis="..." if len(url) > 80 else ""))

    def _refresh_history(self):
        for item in self.hist_tree.get_children():
            self.hist_tree.delete(item)
        self._history_url_by_iid.clear()
        try:
            rows = self.db.get_history(limit=200)
            count = self.db.get_count()
        except SyncHistoryDbError as e:
            messagebox.showerror(t("gui.history.load_fail_title"), str(e))
            self.history_count_label.configure(text=t("gui.history.load_fail"))
            return
        for row in rows:
            url = row[0]
            site_name = row[1] if len(row) > 1 else ""
            title = row[2] if len(row) > 2 else ""
            synced_at = row[3] if len(row) > 3 else ""
            devices = row[4] if len(row) > 4 else ""
            iid = hashlib.sha256((url or "").encode("utf-8")).hexdigest()[:24]
            self._history_url_by_iid[iid] = url
            display_title = title or ""
            if devices:
                display_title = f"{display_title} [{devices}]" if display_title else f"[{devices}]"
            self.hist_tree.insert("", "end", iid=iid, values=(
                site_name or "", display_title, synced_at or "", url or ""
            ))
        self.history_count_label.configure(text=t("gui.history.count", count=count))

    def _delete_history_entry(self):
        selected = self.hist_tree.selection()
        if not selected:
            messagebox.showwarning(t("dialog.warning"), t("gui.history.select_delete"))
            return
        if not messagebox.askyesno(t("dialog.confirm"), t("gui.history.delete_confirm", count=len(selected))):
            return
        try:
            for iid in selected:
                url = self._history_url_by_iid.get(iid, iid)
                self.db.delete_entry(url)
        except SyncHistoryDbError as e:
            messagebox.showerror(t("gui.history.delete_fail_title"), str(e))
            self.app._log_message(t("gui.history.log_delete_fail", error=e))
            return
        self._refresh_history()
        self.app._log_message(t("gui.history.log_deleted", count=len(selected)))
        self.service.schedule_backup_push()

    def _clear_all_history(self):
        if not messagebox.askyesno(t("gui.history.clear_confirm_title"), t("gui.history.clear_confirm")):
            return
        try:
            self.db.clear_all()
        except SyncHistoryDbError as e:
            messagebox.showerror(t("gui.history.clear_fail_title"), str(e))
            self.app._log_message(t("gui.history.log_clear_fail", error=e))
            return
        self._refresh_history()
        self.app._log_message(t("gui.history.log_cleared"))
        self.service.schedule_backup_push()

    def _export_history_json(self):
        file_path = filedialog.asksaveasfilename(
            title=t("gui.history.export_title"),
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile="synced_posts.json",
        )
        if not file_path:
            return
        try:
            posts = self.db.export_all_posts()
            deleted_posts = self.db.export_deleted_posts()
            write_json_atomic(file_path, build_history_payload(posts, deleted_posts=deleted_posts))
            messagebox.showinfo(t("dialog.info"), t("gui.history.export_ok", count=len(posts)))
            self.app._log_message(t("gui.history.log_export", count=len(posts), path=file_path))
        except Exception as e:
            messagebox.showerror(t("gui.history.export_fail_title"), str(e))

    def _import_history_json(self):
        file_path = filedialog.askopenfilename(
            title=t("gui.history.import_title"),
            filetypes=[("JSON", "*.json")],
        )
        if not file_path:
            return
        try:
            payload = read_json_safe(file_path)
            posts, _ = extract_posts(payload)
            deleted_posts = extract_deleted_posts(payload)
            if not posts and not deleted_posts:
                messagebox.showwarning(
                    t("gui.history.import_bad_title"),
                    t("gui.history.import_bad"),
                )
                return
            changed = self.db.import_deleted_posts(deleted_posts)
            changed += self.db.import_posts_union(posts)
            self._refresh_history()
            self.service.schedule_backup_push()
            messagebox.showinfo(
                t("dialog.info"),
                t("gui.history.import_ok", count=len(posts), changed=changed),
            )
            self.app._log_message(t("gui.history.log_import", changed=changed, path=file_path))
        except Exception as e:
            messagebox.showerror(t("gui.history.import_fail_title"), str(e))
