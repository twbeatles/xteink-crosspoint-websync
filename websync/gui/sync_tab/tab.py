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
    COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING, get_font,
    create_scrollable_frame, create_scrolled_tree, setup_dialog
)
from websync.upload.uploader import X3Uploader, normalize_device_host
from websync.config.exceptions import ConfigSaveError, ConfigLoadError

from websync.gui.sync_tab.connection import SyncConnectionMixin
from websync.gui.sync_tab.schedule import SyncScheduleMixin
from websync.gui.sync_tab.devices import SyncDevicesMixin
from websync.gui.sync_tab.sites import SyncSitesMixin
from websync.gui.sync_tab.preview import SyncPreviewMixin
from websync.i18n import t


class SyncTab(
    SyncConnectionMixin,
    SyncScheduleMixin,
    SyncDevicesMixin,
    SyncSitesMixin,
    SyncPreviewMixin,
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
        self._build_ui()

    def _build_ui(self):
        body = create_scrollable_frame(self)

        # 1. 기기 및 경로 설정 카드
        settings_card = CardFrame(body, title=t("gui.sync.card_device_title"), subtitle=t("gui.sync.card_device_sub"))
        settings_card.pack(fill="x", padx=8, pady=6)

        grid_frame = ctk.CTkFrame(settings_card, fg_color="transparent")
        grid_frame.pack(fill="x", padx=12, pady=10)
        grid_frame.columnconfigure(1, weight=1)

        ctk.CTkLabel(grid_frame, text=t("gui.sync.ip_label"), font=get_font(13), anchor="w").grid(row=0, column=0, padx=(0, 8), pady=6, sticky="w")
        self.ip_entry = ctk.CTkEntry(grid_frame, placeholder_text=t("gui.sync.ip_placeholder"), font=get_font(12), height=34)
        self.ip_entry.grid(row=0, column=1, padx=4, pady=6, sticky="we")

        self.test_conn_btn = ctk.CTkButton(grid_frame, text=t("gui.sync.test_conn"), font=get_font(12, "bold"), width=100, height=34, command=self._test_connection)
        self.test_conn_btn.grid(row=0, column=2, padx=6, pady=6)

        self.conn_status_label = ctk.CTkLabel(grid_frame, text=t("gui.sync.conn_unchecked"), text_color=COLOR_WARNING[0], font=get_font(13, "bold"))
        self.conn_status_label.grid(row=0, column=3, padx=8, pady=6, sticky="w")

        ctk.CTkLabel(grid_frame, text=t("gui.sync.output_dir_label"), font=get_font(13), anchor="w").grid(row=1, column=0, padx=(0, 8), pady=6, sticky="w")
        self.dir_entry = ctk.CTkEntry(grid_frame, font=get_font(12), height=34)
        self.dir_entry.grid(row=1, column=1, padx=4, pady=6, sticky="we")

        ctk.CTkButton(grid_frame, text=t("gui.sync.browse_folder"), font=get_font(12), width=100, height=34, command=self._browse_directory).grid(row=1, column=2, padx=6, pady=6)
        ctk.CTkButton(grid_frame, text=t("gui.sync.open_folder"), font=get_font(12), width=80, height=34, fg_color=("#e9ecef", "#343a40"), text_color=COLOR_FG, command=self._open_output_folder).grid(row=1, column=3, padx=4, pady=6)

        self.app._bind_autosave(self.ip_entry)
        self.app._bind_autosave(self.dir_entry)

        # 2. 추가 기기 관리 카드
        devices_card = CardFrame(body, title=t("gui.sync.card_devices_title"), subtitle=t("gui.sync.card_devices_sub"))
        devices_card.pack(fill="x", padx=8, pady=6)

        dev_inner = ctk.CTkFrame(devices_card, fg_color="transparent")
        dev_inner.pack(fill="x", padx=12, pady=10)
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

        dev_btn = ctk.CTkFrame(dev_inner, fg_color="transparent")
        dev_btn.grid(row=0, column=1, padx=(10, 0), sticky="n")
        ctk.CTkButton(dev_btn, text=t("gui.sync.add_device"), font=get_font(12), width=95, height=32, command=self._add_device_popup).pack(fill="x", pady=2)
        ctk.CTkButton(dev_btn, text=t("gui.sync.delete_selected"), font=get_font(12), width=95, height=32, fg_color=COLOR_DANGER[0], hover_color=COLOR_DANGER[1], command=self._remove_device).pack(fill="x", pady=2)

        # 3. 폰트 및 스타일 최적화 카드 (기본 폰트를 맑은 고딕으로 설정)
        font_card = CardFrame(body, title=t("gui.sync.card_font_title"))
        font_card.pack(fill="x", padx=8, pady=6)

        font_inner = ctk.CTkFrame(font_card, fg_color="transparent")
        font_inner.pack(fill="x", padx=12, pady=10)

        ctk.CTkLabel(font_inner, text=t("gui.sync.font_label"), font=get_font(13)).grid(row=0, column=0, padx=(0, 6), pady=6, sticky="w")
        self.font_cb = ctk.CTkOptionMenu(
            font_inner,
            values=["Malgun Gothic", "serif", "sans-serif", "KoPubWorldBatang", "NanumGothic"],
            font=get_font(12),
            width=160,
            command=lambda _v: self.app._save_ui_settings()
        )
        self.font_cb.grid(row=0, column=1, padx=4, pady=6, sticky="w")
        self.font_cb.set("Malgun Gothic")

        ctk.CTkLabel(font_inner, text=t("gui.sync.font_size_label"), font=get_font(13)).grid(row=0, column=2, padx=(16, 6), pady=6, sticky="w")
        self.font_size_sp = ctk.CTkEntry(font_inner, font=get_font(12), width=55, height=32)
        self.font_size_sp.grid(row=0, column=3, padx=4, pady=6, sticky="w")
        self.font_size_sp.insert(0, "16")
        self.app._bind_autosave(self.font_size_sp)

        ctk.CTkLabel(font_inner, text=t("gui.sync.line_height_label"), font=get_font(13)).grid(row=0, column=4, padx=(16, 6), pady=6, sticky="w")
        self.line_height_sp = ctk.CTkEntry(font_inner, font=get_font(12), width=55, height=32)
        self.line_height_sp.grid(row=0, column=5, padx=4, pady=6, sticky="w")
        self.line_height_sp.insert(0, "1.7")
        self.app._bind_autosave(self.line_height_sp)

        self.cover_var = tk.BooleanVar(value=True)
        cover_cb = ctk.CTkCheckBox(
            font_inner,
            text=t("gui.sync.cover_auto"),
            font=get_font(12),
            variable=self.cover_var,
            command=self.app._save_ui_settings
        )
        cover_cb.grid(row=1, column=0, columnspan=3, padx=4, pady=(6, 0), sticky="w")

        # 4. 사이트 관리 카드
        sites_card = CardFrame(body, title=t("gui.sync.card_sites_title"), subtitle=t("gui.sync.card_sites_sub"))
        sites_card.pack(fill="x", padx=8, pady=6)

        columns = ("name", "type", "enabled", "url")
        self.tree = create_scrolled_tree(sites_card, columns, height=7)
        self.tree.heading("name", text=t("gui.sync.col_site_name"))
        self.tree.heading("type", text=t("gui.sync.col_site_type"))
        self.tree.heading("enabled", text=t("gui.sync.col_site_enabled"))
        self.tree.heading("url", text="URL")
        self.tree.column("name", width=140, minwidth=80, anchor="w")
        self.tree.column("type", width=80, minwidth=60, anchor="center")
        self.tree.column("enabled", width=55, minwidth=45, anchor="center")
        self.tree.column("url", width=370, minwidth=120, anchor="w")
        self.tree.bind("<Double-1>", lambda _e: self._edit_site_popup())

        btn_frame = ctk.CTkFrame(sites_card, fg_color="transparent")
        btn_frame.pack(fill="x", padx=12, pady=(0, 10))

        ctk.CTkButton(btn_frame, text=t("gui.sync.add_site"), font=get_font(12), width=100, height=32, command=self._add_site_popup).pack(side="left", padx=3)
        ctk.CTkButton(btn_frame, text=t("gui.sync.edit_site"), font=get_font(12), width=100, height=32, fg_color=("#e9ecef", "#343a40"), text_color=COLOR_FG, command=self._edit_site_popup).pack(side="left", padx=3)
        ctk.CTkButton(btn_frame, text=t("gui.sync.delete_selected"), font=get_font(12), width=95, height=32, fg_color=COLOR_DANGER[0], hover_color=COLOR_DANGER[1], command=self._delete_site).pack(side="left", padx=3)
        ctk.CTkButton(btn_frame, text=t("gui.sync.toggle_enabled"), font=get_font(12), width=95, height=32, fg_color=("#e9ecef", "#343a40"), text_color=COLOR_FG, command=self._toggle_site_enabled).pack(side="left", padx=3)

        ctk.CTkButton(btn_frame, text=t("gui.sync.export_settings"), font=get_font(12), width=110, height=32, fg_color=("#e9ecef", "#343a40"), text_color=COLOR_FG, command=self._export_sites_action).pack(side="right", padx=3)
        ctk.CTkButton(btn_frame, text=t("gui.sync.import_settings"), font=get_font(12), width=110, height=32, fg_color=("#e9ecef", "#343a40"), text_color=COLOR_FG, command=self._import_sites_action).pack(side="right", padx=3)

        # 5. 하단 직접 전송 & 스케줄 설정
        bottom_row = ctk.CTkFrame(body, fg_color="transparent")
        bottom_row.pack(fill="x", padx=8, pady=6)
        bottom_row.columnconfigure(0, weight=1)
        bottom_row.columnconfigure(1, weight=1)

        upload_card = CardFrame(bottom_row, title=t("gui.sync.card_upload_title"))
        upload_card.grid(row=0, column=0, padx=(0, 4), sticky="nsew")

        upload_inner = ctk.CTkFrame(upload_card, fg_color="transparent")
        upload_inner.pack(fill="x", padx=10, pady=10)
        upload_inner.columnconfigure(0, weight=1)

        self.file_entry = ctk.CTkEntry(upload_inner, placeholder_text=t("gui.sync.file_placeholder"), font=get_font(12), height=34)
        self.file_entry.grid(row=0, column=0, padx=4, pady=8, sticky="we")
        ctk.CTkButton(upload_inner, text="...", font=get_font(12), width=40, height=34, command=self._browse_file).grid(row=0, column=1, padx=4, pady=8)
        self.direct_upload_btn = ctk.CTkButton(upload_inner, text=t("gui.sync.upload"), font=get_font(12, "bold"), width=70, height=34, command=self._direct_upload)
        self.direct_upload_btn.grid(row=0, column=2, padx=4, pady=8)

        scheduler_card = CardFrame(bottom_row, title=t("gui.schedule.card_title"))
        scheduler_card.grid(row=0, column=1, padx=(4, 0), sticky="nsew")

        sched_inner = ctk.CTkFrame(scheduler_card, fg_color="transparent")
        sched_inner.pack(fill="x", padx=10, pady=8)

        ctk.CTkLabel(sched_inner, text=t("gui.schedule.every_day"), font=get_font(13)).grid(row=0, column=0, padx=(0, 4), pady=4, sticky="w")
        self.hour_cb = ctk.CTkOptionMenu(sched_inner, values=[f"{i:02d}" for i in range(24)], font=get_font(12), width=65, height=32)
        self.hour_cb.grid(row=0, column=1, padx=2, pady=4)
        self.min_cb = ctk.CTkOptionMenu(sched_inner, values=[f"{i:02d}" for i in range(60)], font=get_font(12), width=65, height=32)
        self.min_cb.grid(row=0, column=2, padx=2, pady=4)

        ctk.CTkButton(sched_inner, text=t("gui.schedule.register"), font=get_font(12, "bold"), width=65, height=32, command=self._register_schedule).grid(row=0, column=3, padx=4, pady=4)
        ctk.CTkButton(sched_inner, text=t("gui.schedule.unregister"), font=get_font(12), width=65, height=32, fg_color=COLOR_DANGER[0], hover_color=COLOR_DANGER[1], command=self._unregister_schedule).grid(row=0, column=4, padx=2, pady=4)

        self.sched_status_label = ctk.CTkLabel(scheduler_card, text=t("gui.schedule.checking"), font=get_font(12), text_color=COLOR_SECONDARY_FG)
        self.sched_status_label.pack(fill="x", padx=10, pady=(0, 8), anchor="w")
