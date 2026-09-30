"""뉴스 미리보기 → 기사 선택 → 전송 / EPUB 만 만들기."""
from __future__ import annotations

import os
import re
import html as html_lib
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from websync.gui.widgets import (
    COLOR_BG, COLOR_SECONDARY_FG, create_scrolled_tree, get_font, make_button, setup_dialog,
)
from websync.i18n import t

CHECKED = "☑"
UNCHECKED = "☐"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def html_excerpt(content: str, limit: int = 600) -> str:
    """본문 HTML → 미리보기용 짧은 평문."""
    text = _TAG_RE.sub(" ", content or "")
    text = _WS_RE.sub(" ", html_lib.unescape(text)).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + " …"
    return text


class SyncPreviewMixin:
    def open_preview_window(self):
        """프리뷰 실행 후 결과를 새 윈도우에 체크박스와 함께 표시합니다."""
        ensure = getattr(self.app, "_ensure_sites_ready", None)
        if callable(ensure) and not ensure():
            return
        self.app._log_message(t("gui.preview.log_start"))
        self.app._set_sync_ui_busy(True)
        self.app._reset_progress()
        self.app._set_status(t("gui.bottom.status_previewing"), "busy")

        def run():
            log_cb = self.app._make_log_callback()
            prog_cb = self.app._make_progress_callback()
            self._preview_data = self.service.preview_articles(log_callback=log_cb, progress_callback=prog_cb)

        self.app._start_pipeline_ui_task(
            run, name="sync-preview", on_success=self._show_preview_results
        )

    def _show_preview_results(self):
        self.app._set_sync_ui_busy(False)
        self.app._reset_progress()
        self.app._log_message(t("gui.preview.log_done"))

        if not self._preview_data:
            self.app._set_status(t("gui.bottom.result_preview_empty"), "ok")
            messagebox.showinfo(t("gui.preview.result_title"), t("gui.preview.no_articles"))
            return
        self.app._set_status(t("gui.bottom.result_preview", count=len(self._preview_data)), "ok")

        articles = list(self._preview_data)
        dialog = ctk.CTkToplevel(self.app.root)
        dialog.title(t("gui.preview.window_title"))
        dialog.configure(fg_color=COLOR_BG)
        setup_dialog(dialog, self.app.root, 900, 640)

        # 하단 버튼 바를 먼저 배치
        btn_bar = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_bar.pack(side="bottom", fill="x", padx=14, pady=(4, 12))

        top = ctk.CTkFrame(dialog, fg_color="transparent")
        top.pack(side="top", fill="x", padx=14, pady=(12, 0))
        ctk.CTkLabel(top, text=t("gui.preview.hint"), font=get_font(12), anchor="w", justify="left").pack(side="left")
        count_label = ctk.CTkLabel(top, text="", font=get_font(12, "bold"))
        count_label.pack(side="right")

        # 기사 목록(위) + 선택한 기사 본문 미리보기(아래)
        detail_host = ctk.CTkFrame(dialog, fg_color="transparent")
        detail_host.pack(side="bottom", fill="x", padx=14, pady=(0, 4))
        list_host = ctk.CTkFrame(dialog, fg_color="transparent")
        list_host.pack(side="top", fill="both", expand=True, padx=14, pady=8)

        columns = ("selected", "site", "title", "url")
        tree = create_scrolled_tree(list_host, columns, height=12, padx=0, pady=0)
        tree.heading("selected", text=CHECKED, command=lambda: toggle_all())
        tree.heading("site", text=t("gui.preview.col_site"))
        tree.heading("title", text=t("gui.preview.col_title"))
        tree.heading("url", text="URL")
        tree.column("selected", width=44, anchor="center", stretch=False)
        tree.column("site", width=140, anchor="w")
        tree.column("title", width=420, anchor="w")
        tree.column("url", width=220, anchor="w")
        tree.tag_configure("unchecked", foreground="#9aa0a6")

        detail_title = ctk.CTkLabel(detail_host, text="", font=get_font(13, "bold"), anchor="w", justify="left")
        detail_title.pack(fill="x", pady=(2, 2))
        detail_txt = ctk.CTkTextbox(detail_host, font=get_font(12), wrap="word", height=110)
        detail_txt.pack(fill="both", expand=True)
        detail_txt.configure(state="disabled")

        checked_state = {i: True for i in range(len(articles))}

        def update_count() -> None:
            n = sum(1 for v in checked_state.values() if v)
            count_label.configure(text=t("gui.preview.selected_count", selected=n, total=len(articles)))
            state = "normal" if n else "disabled"
            send_btn.configure(state=state)
            build_btn.configure(state=state)

        def render_row(idx: int) -> None:
            art = articles[idx]
            on = checked_state[idx]
            values = (CHECKED if on else UNCHECKED, art.get("site_name", ""), art.get("title", ""), art.get("url", ""))
            iid = str(idx)
            if tree.exists(iid):
                tree.item(iid, values=values, tags=() if on else ("unchecked",))
            else:
                tree.insert("", "end", iid=iid, values=values, tags=() if on else ("unchecked",))

        for i in range(len(articles)):
            render_row(i)

        def toggle(indices: list[int]) -> None:
            if not indices:
                return
            new_val = not all(checked_state[i] for i in indices)
            for i in indices:
                checked_state[i] = new_val
                render_row(i)
            update_count()

        def toggle_all() -> None:
            toggle(list(checked_state.keys()))

        def show_detail(_event=None) -> None:
            sel = tree.selection()
            if not sel:
                return
            art = articles[int(sel[0])]
            detail_title.configure(text=art.get("title", ""))
            detail_txt.configure(state="normal")
            detail_txt.delete("1.0", tk.END)
            detail_txt.insert(tk.END, html_excerpt(art.get("content", "")) or t("gui.preview.no_content"))
            detail_txt.configure(state="disabled")

        def on_click(event):
            # 체크 칸을 누르면 선택/해제, 다른 칸은 행 선택(본문 미리보기)만
            if tree.identify_region(event.x, event.y) != "cell":
                return None
            row = tree.identify_row(event.y)
            if row and tree.identify_column(event.x) == "#1":
                toggle([int(row)])
            return None

        def on_double(event):
            row = tree.identify_row(event.y)
            if row and tree.identify_column(event.x) != "#1":
                self.app._open_url(articles[int(row)].get("url", ""))

        tree.bind("<Button-1>", on_click, add="+")
        tree.bind("<Double-1>", on_double)
        tree.bind("<space>", lambda _e: (toggle([int(i) for i in tree.selection()]), "break")[1])
        tree.bind("<<TreeviewSelect>>", show_detail)

        def selected_articles() -> list[dict]:
            return [articles[i] for i, checked in checked_state.items() if checked]

        def run_selected_sync():
            chosen = selected_articles()
            if not chosen:
                messagebox.showwarning(t("gui.preview.none_selected_title"), t("gui.preview.none_selected"), parent=dialog)
                return
            dialog.destroy()
            self._run_selected_sync_task(chosen)

        def run_build_only():
            chosen = selected_articles()
            if not chosen:
                messagebox.showwarning(t("gui.preview.none_selected_title"), t("gui.preview.none_selected"), parent=dialog)
                return
            self._run_build_only_task(chosen)

        make_button(btn_bar, t("gui.preview.toggle_all"), toggle_all, kind="secondary", width=110, height=36).pack(side="left")
        ctk.CTkLabel(
            btn_bar, text=t("gui.preview.keys_hint"), font=get_font(11), text_color=COLOR_SECONDARY_FG,
        ).pack(side="left", padx=10)
        send_btn = make_button(btn_bar, t("gui.preview.send_selected"), run_selected_sync, width=150, height=36, bold=True)
        send_btn.pack(side="right", padx=(6, 0))
        build_btn = make_button(btn_bar, t("gui.preview.build_only"), run_build_only, kind="secondary", width=150, height=36)
        build_btn.pack(side="right", padx=(6, 0))
        make_button(btn_bar, t("gui.sync.cancel"), dialog.destroy, kind="secondary", width=80, height=36).pack(side="right")

        update_count()
        first = tree.get_children()
        if first:
            tree.selection_set(first[0])
            tree.focus(first[0])
            show_detail()
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        dialog.after(150, tree.focus_set)

    def _run_selected_sync_task(self, selected_articles):
        if getattr(self.app, "_sync_busy", False) is True or self.service.is_pipeline_running():
            messagebox.showwarning(t("gui.preview.busy_title"), t("gui.preview.busy"))
            return

        self.app._set_sync_ui_busy(True)
        self.app._reset_progress()
        self.app._set_status(t("gui.bottom.status_syncing"), "busy")
        self.app._log_message(t("gui.preview.log_selected", count=len(selected_articles)))

        def task():
            log_cb = self.app._make_log_callback()
            prog_cb = self.app._make_progress_callback()
            self.service.sync_selected_articles(selected_articles, log_callback=log_cb, progress_callback=prog_cb)

        self.app._start_pipeline_ui_task(
            task, name="selected-sync", on_success=self.app._sync_finished_ui
        )

    def _run_build_only_task(self, selected_articles):
        """선택 기사로 EPUB 만 만들고 (전송·이력 기록 없음) 출력 폴더를 안내한다."""
        if getattr(self.app, "_sync_busy", False) is True or self.service.is_pipeline_running():
            messagebox.showwarning(t("gui.preview.busy_title"), t("gui.preview.busy"))
            return
        if not self.app._save_ui_settings():
            return
        self.app._set_sync_ui_busy(True)
        self.app._reset_progress()
        self.app._set_status(t("gui.bottom.status_building"), "busy")
        self.app._log_message(t("gui.preview.log_build_only", count=len(selected_articles)))
        result: dict = {"paths": []}

        def task():
            result["paths"] = self.service.build_selected_epubs(
                [dict(a) for a in selected_articles],
                log_callback=self.app._make_log_callback(),
                progress_callback=self.app._make_progress_callback(),
            )

        def done():
            self.app._set_sync_ui_busy(False)
            self.app._reset_progress()
            paths = result["paths"] or []
            if not paths:
                self.app._set_status(t("gui.bottom.result_error", time=""), "error")
                return
            self.app._set_status(t("gui.bottom.result_built", count=len(paths)), "ok")
            names = "\n".join(f"• {os.path.basename(p)}" for p in paths[:8])
            if messagebox.askyesno(
                t("gui.preview.build_done_title"),
                t("gui.preview.build_done_body", count=len(paths), names=names),
            ):
                self._open_output_folder()

        self.app._start_pipeline_ui_task(task, name="build-only", on_success=done)
