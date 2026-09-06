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

        ctk.CTkButton(btn_row, text="🔄 새로고침", font=get_font(12, "bold"), width=105, height=34, command=self._refresh_history).pack(side="left", padx=3)
        ctk.CTkButton(btn_row, text="🗑 선택 삭제 (재전송 허용)", font=get_font(12), width=165, height=34, fg_color=("#e9ecef", "#343a40"), text_color=COLOR_FG, command=self._delete_history_entry).pack(side="left", padx=3)
        ctk.CTkButton(btn_row, text="⚠️ 전체 초기화", font=get_font(12, "bold"), width=120, height=34, fg_color=COLOR_DANGER[0], hover_color=COLOR_DANGER[1], command=self._clear_all_history).pack(side="left", padx=3)

        ctk.CTkButton(btn_row, text="JSON 내보내기", font=get_font(12), width=120, height=34, fg_color=("#e9ecef", "#343a40"), text_color=COLOR_FG, command=self._export_history_json).pack(side="right", padx=3)
        ctk.CTkButton(btn_row, text="JSON 가져오기", font=get_font(12), width=120, height=34, fg_color=("#e9ecef", "#343a40"), text_color=COLOR_FG, command=self._import_history_json).pack(side="right", padx=3)

        self.history_count_label = ctk.CTkLabel(ctrl_card, text="", font=get_font(13, "bold"), text_color=COLOR_WARNING[0])
        self.history_count_label.pack(anchor="e", padx=12, pady=(0, 8))

        hist_card = CardFrame(body, title="📋 전송 완료 포스트 이력", subtitle="더블 클릭 시 해당 기사 URL 복사")
        hist_card.pack(fill="x", padx=8, pady=6)

        h_columns = ("site", "title", "synced_at", "url")
        self.hist_tree = create_scrolled_tree(
            hist_card, h_columns, height=10, selectmode="extended"
        )
        self.hist_tree.heading("site", text="사이트")
        self.hist_tree.heading("title", text="제목")
        self.hist_tree.heading("synced_at", text="전송 시각")
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
        self.app._log_message(f"📋 URL 복사됨: {url[:80]}{'...' if len(url) > 80 else ''}")

    def _refresh_history(self):
        for item in self.hist_tree.get_children():
            self.hist_tree.delete(item)
        self._history_url_by_iid.clear()
        try:
            rows = self.db.get_history(limit=200)
            count = self.db.get_count()
        except SyncHistoryDbError as e:
            messagebox.showerror("이력 조회 실패", str(e))
            self.history_count_label.configure(text="이력 조회 실패")
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
        self.history_count_label.configure(text=f"총 {count}건 기록됨")

    def _delete_history_entry(self):
        selected = self.hist_tree.selection()
        if not selected:
            messagebox.showwarning("경고", "삭제할 항목을 선택해 주세요.")
            return
        if not messagebox.askyesno("확인", f"{len(selected)}개 항목을 삭제하면 다음 동기화 시 재수집됩니다. 계속할까요?"):
            return
        try:
            for iid in selected:
                url = self._history_url_by_iid.get(iid, iid)
                self.db.delete_entry(url)
        except SyncHistoryDbError as e:
            messagebox.showerror("이력 삭제 실패", str(e))
            self.app._log_message(f"❌ 이력 삭제 실패: {e}")
            return
        self._refresh_history()
        self.app._log_message(f"🗑 이력 {len(selected)}건 삭제 완료 (재전송 허용)")
        self.service.schedule_backup_push()

    def _clear_all_history(self):
        if not messagebox.askyesno("전체 초기화 확인", "모든 동기화 이력을 삭제합니다.\n다음 동기화 시 모든 기사가 재수집됩니다. 계속할까요?"):
            return
        try:
            self.db.clear_all()
        except SyncHistoryDbError as e:
            messagebox.showerror("이력 초기화 실패", str(e))
            self.app._log_message(f"❌ 이력 초기화 실패: {e}")
            return
        self._refresh_history()
        self.app._log_message("⚠️ 동기화 이력 전체 초기화 완료")
        self.service.schedule_backup_push()

    def _export_history_json(self):
        file_path = filedialog.asksaveasfilename(
            title="동기화 이력 JSON 내보내기",
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
            messagebox.showinfo("완료", f"이력 {len(posts)}건을 내보냈습니다.")
            self.app._log_message(f"☁ 이력 JSON 내보내기: {len(posts)}건 → {file_path}")
        except Exception as e:
            messagebox.showerror("내보내기 실패", str(e))

    def _import_history_json(self):
        file_path = filedialog.askopenfilename(
            title="동기화 이력 JSON 가져오기",
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
                    "형식 오류",
                    "올바른 이력 JSON이 아닙니다. (kind=synced_posts 또는 posts 배열 필요)",
                )
                return
            changed = self.db.import_deleted_posts(deleted_posts)
            changed += self.db.import_posts_union(posts)
            self._refresh_history()
            self.service.schedule_backup_push()
            messagebox.showinfo(
                "완료",
                f"이력 {len(posts)}건 중 {changed}건을 신규/갱신 반영했습니다. (합집합 병합)",
            )
            self.app._log_message(f"☁ 이력 JSON 가져오기: {changed}건 반영 ← {file_path}")
        except Exception as e:
            messagebox.showerror("가져오기 실패", str(e))
