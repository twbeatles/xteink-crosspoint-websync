"""뉴스 동기화 탭 (CustomTkinter 현대적 카드 UI 적용)."""
from __future__ import annotations

import os
import sys
import hashlib
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import customtkinter as ctk

from websync.gui.widgets import (
    CardFrame, COLOR_CARD_BG, COLOR_FG, COLOR_SECONDARY_FG, COLOR_ACCENT,
    COLOR_ACCENT_SOFT, COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING, Tooltip, get_font,
    create_scrollable_frame, create_scrolled_tree, make_button, setup_dialog
)
from websync.upload.uploader import X3Uploader, normalize_device_host
from websync.config.exceptions import ConfigSaveError, ConfigLoadError

from websync.gui.sync_tab.connection import SyncConnectionMixin
from websync.gui.sync_tab.schedule import SyncScheduleMixin
from websync.gui.sync_tab.devices import SyncDevicesMixin
from websync.gui.sync_tab.sites import SyncSitesMixin
from websync.gui.sync_tab.site_dialog import SiteDialogMixin
from websync.gui.sync_tab.preview import SyncPreviewMixin
from websync.gui.sync_tab.epub_options import SyncEpubOptionsMixin
from websync.i18n import t


class SyncTab(
    SyncConnectionMixin,
    SyncScheduleMixin,
    SyncDevicesMixin,
    SyncSitesMixin,
    SiteDialogMixin,
    SyncPreviewMixin,
    SyncEpubOptionsMixin,
    ctk.CTkFrame,
):
    """뉴스 동기화 및 일반 설정을 담당하는 탭 패널"""
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.service = app.service
        self.config_manager = app.service.config_manager
        self.scheduler = app.scheduler

        self._preview_data = []  # 프리뷰 기사 데이터 임시 저장
        self._conn_ok: bool | None = None  # 마지막 연결 확인 결과 (시작 안내용)
        self._build_ui()

    def _build_ui(self):
        body = create_scrollable_frame(self)
        self._body = body

        # 0. 시작 안내 (소스가 없거나 설정이 덜 된 첫 실행에서만 표시)
        self._build_getting_started(body)

        # 1. 소스(사이트) 관리 — 가장 자주 쓰는 카드를 맨 위에
        self._build_sites_card(body)

        # 2. EPUB 만들기 옵션 (글꼴·테마·병합·표지)
        self.epub_card = self._build_epub_card(body)
        self.epub_card.pack(fill="x", padx=8, pady=6)

        # 3. 기기 및 경로
        self._build_device_card(body)

        # 4. 추가 기기
        self._build_devices_card(body)

        # 5. 직접 전송 & 스케줄
        self._build_upload_schedule_row(body)

    # ------------------------------------------------------------------
    # 카드 빌더
    # ------------------------------------------------------------------

    def _build_getting_started(self, body):
        self.getting_started = CardFrame(
            body, fg_color=COLOR_ACCENT_SOFT, border_color=COLOR_ACCENT, border_width=1,
        )
        inner = ctk.CTkFrame(self.getting_started, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=10)
        inner.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            inner, text=t("gui.start.title"), font=get_font(15, "bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w")
        make_button(
            inner, t("gui.start.dismiss"), self._dismiss_getting_started,
            kind="secondary", width=70, height=26,
        ).grid(row=0, column=1, sticky="e")

        self._start_step_labels: list[ctk.CTkLabel] = []
        for i in range(3):
            lbl = ctk.CTkLabel(inner, text="", font=get_font(12), anchor="w", justify="left")
            lbl.grid(row=i + 1, column=0, sticky="w", pady=(4 if i == 0 else 0, 0))
            self._start_step_labels.append(lbl)

        btns = ctk.CTkFrame(inner, fg_color="transparent")
        btns.grid(row=1, column=1, rowspan=3, sticky="e")
        make_button(btns, t("gui.start.btn_test"), self._test_connection, kind="secondary", width=120).pack(fill="x", pady=2)
        make_button(btns, t("gui.start.btn_add"), self._add_site_popup, width=120, bold=True).pack(fill="x", pady=2)
        self._start_dismissed = False

    def _build_sites_card(self, body):
        sites_card = CardFrame(body, title=t("gui.sync.card_sites_title"), subtitle=t("gui.sync.card_sites_sub"))
        sites_card.pack(fill="x", padx=8, pady=6)
        self.sites_card = sites_card

        self.sites_summary_label = ctk.CTkLabel(
            sites_card.header_right, text="", font=get_font(12, "bold"), text_color=COLOR_SECONDARY_FG,
        )
        self.sites_summary_label.pack(side="right")

        btn_frame = ctk.CTkFrame(sites_card, fg_color="transparent")
        btn_frame.pack(fill="x", padx=12, pady=(0, 2))

        make_button(btn_frame, t("gui.sync.add_site"), self._add_site_popup, width=110, bold=True).pack(side="left", padx=(0, 4))
        self.edit_site_btn = make_button(btn_frame, t("gui.sync.edit_site"), self._edit_site_popup, kind="secondary", width=80)
        self.edit_site_btn.pack(side="left", padx=4)
        self.toggle_site_btn = make_button(btn_frame, t("gui.sync.toggle_enabled"), self._toggle_site_enabled, kind="secondary", width=100)
        self.toggle_site_btn.pack(side="left", padx=4)
        self.duplicate_site_btn = make_button(btn_frame, t("gui.sync.duplicate_site"), self._duplicate_site, kind="secondary", width=70)
        self.duplicate_site_btn.pack(side="left", padx=4)
        self.delete_site_btn = make_button(btn_frame, t("gui.sync.delete_selected"), self._delete_site, kind="secondary", width=70, text_color=COLOR_DANGER)
        self.delete_site_btn.pack(side="left", padx=4)

        export_btn = make_button(btn_frame, t("gui.sync.export_settings"), self._export_sites_action, kind="secondary", width=90)
        export_btn.pack(side="right", padx=(4, 0))
        Tooltip(export_btn, t("gui.sync.export_tip"))
        import_btn = make_button(btn_frame, t("gui.sync.import_settings"), self._import_sites_action, kind="secondary", width=90)
        import_btn.pack(side="right", padx=4)

        tree_host = ctk.CTkFrame(sites_card, fg_color="transparent")
        tree_host.pack(fill="x")
        columns = ("enabled", "name", "type", "limit", "url")
        self.tree = create_scrolled_tree(tree_host, columns, height=7)
        self.tree.heading("enabled", text=t("gui.sync.col_site_enabled"))
        self.tree.heading("name", text=t("gui.sync.col_site_name"))
        self.tree.heading("type", text=t("gui.sync.col_site_type"))
        self.tree.heading("limit", text=t("gui.sync.col_site_limit"))
        self.tree.heading("url", text="URL")
        self.tree.column("enabled", width=70, minwidth=60, anchor="center", stretch=False)
        self.tree.column("name", width=170, minwidth=90, anchor="w")
        self.tree.column("type", width=120, minwidth=80, anchor="w")
        self.tree.column("limit", width=60, minwidth=50, anchor="center", stretch=False)
        self.tree.column("url", width=340, minwidth=120, anchor="w")
        self.tree.tag_configure("disabled", foreground="#9aa0a6")
        self.tree.bind("<Double-1>", self._on_site_double_click)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_site_buttons())
        self.tree.bind("<Delete>", lambda _e: self._delete_site())
        self.tree.bind("<Return>", lambda _e: self._edit_site_popup())
        self.tree.bind("<space>", lambda _e: self._toggle_site_enabled())
        self.tree.bind("<Button-3>", self._show_site_menu)
        self.tree.bind("<Control-Button-1>", self._show_site_menu_mac, add="+")

        # 목록이 비었을 때 안내 문구 (트리 위에 겹쳐 표시)
        self.sites_empty_label = ctk.CTkLabel(
            tree_host, text=t("gui.sync.sites_empty"), font=get_font(13),
            text_color=COLOR_SECONDARY_FG, fg_color="transparent",
        )

        ctk.CTkLabel(
            sites_card, text=t("gui.sync.sites_hint"), font=get_font(11),
            text_color=COLOR_SECONDARY_FG, anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 10))

    def _build_device_card(self, body):
        settings_card = CardFrame(body, title=t("gui.sync.card_device_title"), subtitle=t("gui.sync.card_device_sub"))
        settings_card.pack(fill="x", padx=8, pady=6)

        grid_frame = ctk.CTkFrame(settings_card, fg_color="transparent")
        grid_frame.pack(fill="x", padx=12, pady=(4, 10))
        grid_frame.columnconfigure(1, weight=1)

        ctk.CTkLabel(grid_frame, text=t("gui.sync.ip_label"), font=get_font(13), anchor="w").grid(row=0, column=0, padx=(0, 8), pady=6, sticky="w")
        self.ip_entry = ctk.CTkEntry(grid_frame, placeholder_text=t("gui.sync.ip_placeholder"), font=get_font(12), height=34)
        self.ip_entry.grid(row=0, column=1, padx=4, pady=6, sticky="we")
        Tooltip(self.ip_entry, t("gui.sync.ip_tip"))

        self.test_conn_btn = make_button(grid_frame, t("gui.sync.test_conn"), self._test_connection, width=100, height=34, bold=True)
        self.test_conn_btn.grid(row=0, column=2, padx=6, pady=6)

        self.conn_status_label = ctk.CTkLabel(grid_frame, text=t("gui.sync.conn_unchecked"), text_color=COLOR_WARNING, font=get_font(13, "bold"), anchor="w")
        self.conn_status_label.grid(row=0, column=3, padx=8, pady=6, sticky="w")

        ctk.CTkLabel(grid_frame, text=t("gui.sync.output_dir_label"), font=get_font(13), anchor="w").grid(row=1, column=0, padx=(0, 8), pady=6, sticky="w")
        self.dir_entry = ctk.CTkEntry(grid_frame, font=get_font(12), height=34)
        self.dir_entry.grid(row=1, column=1, padx=4, pady=6, sticky="we")

        make_button(grid_frame, t("gui.sync.browse_folder"), self._browse_directory, kind="secondary", width=100, height=34).grid(row=1, column=2, padx=6, pady=6)
        make_button(grid_frame, t("gui.sync.open_folder"), self._open_output_folder, kind="secondary", width=80, height=34).grid(row=1, column=3, padx=4, pady=6, sticky="w")

        self.app._bind_autosave(self.ip_entry)
        self.app._bind_autosave(self.dir_entry)
        self.ip_entry.bind("<Return>", lambda _e: self._test_connection())
        # 주소를 바꾸면 이전 연결 확인 결과는 더 이상 유효하지 않다
        self.ip_entry.bind("<KeyRelease>", self._on_ip_edited, add="+")

    def _build_devices_card(self, body):
        devices_card = CardFrame(body, title=t("gui.sync.card_devices_title"), subtitle=t("gui.sync.card_devices_sub"))
        devices_card.pack(fill="x", padx=8, pady=6)

        dev_inner = ctk.CTkFrame(devices_card, fg_color="transparent")
        dev_inner.pack(fill="x", padx=12, pady=(4, 10))
        dev_inner.columnconfigure(0, weight=1)

        tree_holder = ctk.CTkFrame(dev_inner, fg_color="transparent")
        tree_holder.grid(row=0, column=0, sticky="nsew")

        self.devices_tree = create_scrolled_tree(
            tree_holder, ("name", "ip"), height=3, padx=0, pady=0
        )
        self.devices_tree.heading("name", text=t("gui.sync.col_device_name"))
        self.devices_tree.heading("ip", text=t("gui.sync.col_device_ip"))
        self.devices_tree.column("name", width=180, minwidth=100)
        self.devices_tree.column("ip", width=220, minwidth=120)
        self.devices_tree.bind("<Delete>", lambda _e: self._remove_device())

        dev_btn = ctk.CTkFrame(dev_inner, fg_color="transparent")
        dev_btn.grid(row=0, column=1, padx=(10, 0), sticky="n")
        make_button(dev_btn, t("gui.sync.add_device"), self._add_device_popup, width=95).pack(fill="x", pady=2)
        make_button(dev_btn, t("gui.sync.delete_selected"), self._remove_device, kind="secondary", width=95, text_color=COLOR_DANGER).pack(fill="x", pady=2)

    def _build_upload_schedule_row(self, body):
        bottom_row = ctk.CTkFrame(body, fg_color="transparent")
        bottom_row.pack(fill="x", padx=8, pady=6)
        bottom_row.columnconfigure(0, weight=1)
        bottom_row.columnconfigure(1, weight=1)

        upload_card = CardFrame(bottom_row, title=t("gui.sync.card_upload_title"))
        upload_card.grid(row=0, column=0, padx=(0, 4), sticky="nsew")

        upload_inner = ctk.CTkFrame(upload_card, fg_color="transparent")
        upload_inner.pack(fill="x", padx=10, pady=(4, 10))
        upload_inner.columnconfigure(0, weight=1)

        self.file_entry = ctk.CTkEntry(upload_inner, placeholder_text=t("gui.sync.file_placeholder"), font=get_font(12), height=34)
        self.file_entry.grid(row=0, column=0, padx=4, pady=4, sticky="we")
        make_button(upload_inner, "...", self._browse_file, kind="secondary", width=40, height=34).grid(row=0, column=1, padx=4, pady=4)
        self.direct_upload_btn = make_button(upload_inner, t("gui.sync.upload"), self._direct_upload, width=70, height=34, bold=True)
        self.direct_upload_btn.grid(row=0, column=2, padx=4, pady=4)

        scheduler_card = CardFrame(bottom_row, title=t("gui.schedule.card_title"))
        scheduler_card.grid(row=0, column=1, padx=(4, 0), sticky="nsew")

        sched_inner = ctk.CTkFrame(scheduler_card, fg_color="transparent")
        sched_inner.pack(fill="x", padx=10, pady=(4, 4))

        ctk.CTkLabel(sched_inner, text=t("gui.schedule.every_day"), font=get_font(13)).grid(row=0, column=0, padx=(0, 4), pady=4, sticky="w")
        self.hour_cb = ctk.CTkOptionMenu(sched_inner, values=[f"{i:02d}" for i in range(24)], font=get_font(12), width=65, height=32)
        self.hour_cb.grid(row=0, column=1, padx=2, pady=4)
        ctk.CTkLabel(sched_inner, text=":", font=get_font(13, "bold")).grid(row=0, column=2)
        self.min_cb = ctk.CTkOptionMenu(sched_inner, values=[f"{i:02d}" for i in range(0, 60, 5)], font=get_font(12), width=65, height=32)
        self.min_cb.grid(row=0, column=3, padx=2, pady=4)

        make_button(sched_inner, t("gui.schedule.register"), self._register_schedule, width=65, bold=True).grid(row=0, column=4, padx=(8, 2), pady=4)
        make_button(sched_inner, t("gui.schedule.unregister"), self._unregister_schedule, kind="secondary", width=65).grid(row=0, column=5, padx=2, pady=4)

        self.sched_status_label = ctk.CTkLabel(scheduler_card, text=t("gui.schedule.checking"), font=get_font(12), text_color=COLOR_SECONDARY_FG, anchor="w")
        self.sched_status_label.pack(fill="x", padx=12, pady=(0, 10))

    # ------------------------------------------------------------------
    # 시작 안내
    # ------------------------------------------------------------------

    def _dismiss_getting_started(self):
        self._start_dismissed = True
        self.getting_started.pack_forget()

    def _on_ip_edited(self, _event=None):
        if self._conn_ok is not None:
            self._conn_ok = None
            self.conn_status_label.configure(text=t("gui.sync.conn_unchecked"), text_color=COLOR_WARNING)
            self._refresh_getting_started()

    def _refresh_getting_started(self):
        """시작 안내 체크리스트를 현재 상태에 맞춰 갱신하고, 준비가 끝나면 숨긴다."""
        if not hasattr(self, "getting_started"):
            return
        sites = self.service.config.get("sites", []) or []
        enabled = [s for s in sites if s.get("enabled", True)]
        addr = (self.service.config.get("x3_ip") or "").strip()
        steps = [
            (self._conn_ok is True, t("gui.start.step_device", address=addr or "-")),
            (bool(enabled), t("gui.start.step_sources", count=len(enabled))),
            (False, t("gui.start.step_run")),
        ]
        for lbl, (done, text) in zip(self._start_step_labels, steps):
            lbl.configure(
                text=("✅ " if done else "○ ") + text,
                text_color=COLOR_SUCCESS if done else COLOR_FG,
            )
        should_show = not self._start_dismissed and not enabled
        if should_show and not self.getting_started.winfo_manager():
            self.getting_started.pack(fill="x", padx=8, pady=(6, 2), before=self.sites_card)
        elif not should_show and self.getting_started.winfo_manager():
            self.getting_started.pack_forget()
