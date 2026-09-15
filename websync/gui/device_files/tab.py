"""기기 SD 카드 파일 관리 탭 (CustomTkinter 기반)"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import customtkinter as ctk

from websync.gui.widgets import (
    CardFrame, COLOR_CARD_BG, COLOR_FG, COLOR_SECONDARY_FG, COLOR_ACCENT,
    COLOR_DANGER, COLOR_WARNING, get_font, create_scrollable_frame, create_scrolled_tree
)
from websync.upload.device_client import (
    X3DeviceClient,
    DeviceClientError,
    normalize_remote_path,
    parent_remote_path,
    format_file_size,
    filter_old_sync_epubs,
)
from websync.upload.uploader import X3Uploader, normalize_upload_remote_dir

from websync.gui.device_files.settings import DeviceFilesSettingsMixin
from websync.gui.device_files.browser import DeviceFilesBrowserMixin
from websync.gui.device_files.actions import DeviceFilesActionsMixin
from websync.gui.device_files.cleanup import DeviceFilesCleanupMixin
from websync.i18n import t


class DeviceFilesTab(
    DeviceFilesSettingsMixin,
    DeviceFilesBrowserMixin,
    DeviceFilesActionsMixin,
    DeviceFilesCleanupMixin,
    ctk.CTkFrame,
):
    """등록된 X3 기기의 파일 목록·삭제·이름변경·이동·업로드·정리."""
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.service = app.service

        self._current_path = "/"
        self._items_by_iid: dict[str, dict] = {}
        self._busy = False
        self._device_choices: list[tuple[str, str]] = []  # (label, ip)
        self._all_items: list[dict] = []

        self._build_ui()

    def _build_ui(self):
        body = create_scrollable_frame(self)

        hint_card = CardFrame(body)
        hint_card.pack(fill="x", padx=8, pady=4)
        
        hint = ctk.CTkLabel(
            hint_card,
            text=t("gui.device.hint"),
            font=get_font(12),
            text_color=COLOR_SECONDARY_FG,
            justify="left"
        )
        hint.pack(fill="x", padx=12, pady=8)

        # 상단 기기 선택 & 상태
        top_card = CardFrame(body)
        top_card.pack(fill="x", padx=8, pady=4)

        top_inner = ctk.CTkFrame(top_card, fg_color="transparent")
        top_inner.pack(fill="x", padx=12, pady=8)

        ctk.CTkLabel(top_inner, text=t("gui.device.device_label"), font=get_font(13)).pack(side="left", padx=(0, 6))
        self.device_cb = ctk.CTkOptionMenu(top_inner, font=get_font(12), width=230, command=lambda _v: self._on_device_changed())
        self.device_cb.pack(side="left", padx=4)

        self.refresh_btn = ctk.CTkButton(top_inner, text=t("gui.device.refresh"), font=get_font(12, "bold"), width=100, height=32, command=self.refresh)
        self.refresh_btn.pack(side="left", padx=6)

        self.status_label = ctk.CTkLabel(top_inner, text=t("gui.device.disconnected"), font=get_font(13, "bold"), text_color=COLOR_WARNING[0])
        self.status_label.pack(side="left", padx=8)

        # 기본 전송·탐색 경로 설정 카드
        settings_card = CardFrame(body, title=t("gui.device.settings_title"))
        settings_card.pack(fill="x", padx=8, pady=4)

        set_inner = ctk.CTkFrame(settings_card, fg_color="transparent")
        set_inner.pack(fill="x", padx=12, pady=8)

        ctk.CTkLabel(set_inner, text=t("gui.device.upload_path"), font=get_font(13)).grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)
        self.upload_path_var = tk.StringVar(value="/")
        self.upload_path_entry = ctk.CTkEntry(set_inner, textvariable=self.upload_path_var, font=get_font(12), width=240, height=32)
        self.upload_path_entry.grid(row=0, column=1, sticky="w", padx=4, pady=4)

        ctk.CTkButton(set_inner, text=t("gui.device.use_current"), font=get_font(12), width=90, height=32, command=self._set_upload_path_current).grid(row=0, column=2, padx=3, pady=4)
        ctk.CTkButton(set_inner, text=t("gui.device.save"), font=get_font(12, "bold"), width=65, height=32, command=self._save_device_files_settings).grid(row=0, column=3, padx=3, pady=4)

        self.warn_overwrite_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            set_inner,
            text=t("gui.device.warn_overwrite"),
            font=get_font(12),
            variable=self.warn_overwrite_var,
            command=self._save_device_files_settings,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # 경로 및 설정 카드
        path_card = CardFrame(body, title=t("gui.device.browser_title"))
        path_card.pack(fill="x", padx=8, pady=4)

        path_inner = ctk.CTkFrame(path_card, fg_color="transparent")
        path_inner.pack(fill="x", padx=12, pady=8)

        ctk.CTkLabel(path_inner, text=t("gui.device.current_path"), font=get_font(13)).pack(side="left", padx=(0, 6))
        self.path_var = tk.StringVar(value="/")
        self.path_entry = ctk.CTkEntry(path_inner, textvariable=self.path_var, font=get_font(12), height=34)
        self.path_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.path_entry.bind("<Return>", lambda _e: self._go_to_path())

        ctk.CTkButton(path_inner, text=t("gui.device.go"), font=get_font(12, "bold"), width=70, height=34, command=self._go_to_path).pack(side="left", padx=3)
        self.up_btn = ctk.CTkButton(path_inner, text=t("gui.device.parent"), font=get_font(12), width=80, height=34, fg_color=("#e9ecef", "#343a40"), text_color=COLOR_FG, command=self._go_parent)
        self.up_btn.pack(side="left", padx=3)

        # 필터 행
        filter_inner = ctk.CTkFrame(path_card, fg_color="transparent")
        filter_inner.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(filter_inner, text=t("gui.device.filter"), font=get_font(13)).pack(side="left", padx=(0, 6))
        self.filter_var = tk.StringVar()
        filter_entry = ctk.CTkEntry(filter_inner, textvariable=self.filter_var, font=get_font(12), width=180, height=32)
        filter_entry.pack(side="left", padx=4)
        filter_entry.bind("<KeyRelease>", lambda _e: self._apply_filter_to_tree())

        self.epub_only_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            filter_inner,
            text=t("gui.device.epub_only"),
            font=get_font(12),
            variable=self.epub_only_var,
            command=self._apply_filter_to_tree,
        ).pack(side="left", padx=10)

        self.summary_label = ctk.CTkLabel(filter_inner, text="", font=get_font(12), text_color=COLOR_SECONDARY_FG)
        self.summary_label.pack(side="right", padx=4)

        # 파일 목록 트리
        columns = ("kind", "name", "size")
        self.file_tree = create_scrolled_tree(
            path_card, columns, height=10, selectmode="extended"
        )
        self.file_tree.heading("kind", text=t("gui.device.col_kind"))
        self.file_tree.heading("name", text=t("gui.device.col_name"))
        self.file_tree.heading("size", text=t("gui.device.col_size"))
        self.file_tree.column("kind", width=70, minwidth=50, anchor="center")
        self.file_tree.column("name", width=420, minwidth=160, anchor="w")
        self.file_tree.column("size", width=100, minwidth=70, anchor="e")
        self.file_tree.bind("<Double-1>", self._on_double_click)

        # 동작 버튼
        actions_card = CardFrame(body)
        actions_card.pack(fill="x", padx=8, pady=4)

        act_inner = ctk.CTkFrame(actions_card, fg_color="transparent")
        act_inner.pack(fill="x", padx=12, pady=10)

        self.delete_btn = ctk.CTkButton(act_inner, text=t("gui.device.delete"), font=get_font(12, "bold"), width=100, height=34, fg_color=COLOR_DANGER[0], hover_color=COLOR_DANGER[1], command=self._delete_selected)
        self.delete_btn.pack(side="left", padx=3)

        self.mkdir_btn = ctk.CTkButton(act_inner, text=t("gui.device.mkdir"), font=get_font(12), width=100, height=34, fg_color=("#e9ecef", "#343a40"), text_color=COLOR_FG, command=self._mkdir)
        self.mkdir_btn.pack(side="left", padx=3)

        self.rename_btn = ctk.CTkButton(act_inner, text=t("gui.device.rename"), font=get_font(12), width=100, height=34, fg_color=("#e9ecef", "#343a40"), text_color=COLOR_FG, command=self._rename_selected)
        self.rename_btn.pack(side="left", padx=3)

        self.move_btn = ctk.CTkButton(act_inner, text=t("gui.device.move"), font=get_font(12), width=85, height=34, fg_color=("#e9ecef", "#343a40"), text_color=COLOR_FG, command=self._move_selected)
        self.move_btn.pack(side="left", padx=3)

        self.download_btn = ctk.CTkButton(act_inner, text=t("gui.device.download"), font=get_font(12), width=115, height=34, command=self._download_selected)
        self.download_btn.pack(side="left", padx=3)

        self.upload_btn = ctk.CTkButton(act_inner, text=t("gui.device.upload"), font=get_font(12), width=115, height=34, command=self._upload_to_current)
        self.upload_btn.pack(side="left", padx=3)

        # 오래된 EPUB 정리 구역
        cleanup_card = CardFrame(body, title=t("gui.device.cleanup_title"))
        cleanup_card.pack(fill="x", padx=8, pady=4)

        clean_inner = ctk.CTkFrame(cleanup_card, fg_color="transparent")
        clean_inner.pack(fill="x", padx=12, pady=10)

        ctk.CTkLabel(clean_inner, text=t("gui.device.old_epub"), font=get_font(13)).pack(side="left", padx=(0, 4))
        self.cleanup_days_var = tk.StringVar(value="14")
        self.cleanup_days_sp = ctk.CTkEntry(clean_inner, font=get_font(12), width=55, height=32, textvariable=self.cleanup_days_var)
        self.cleanup_days_sp.pack(side="left", padx=4)

        ctk.CTkLabel(clean_inner, text=t("gui.device.days_suffix"), font=get_font(13)).pack(side="left", padx=(2, 8))

        self.select_old_btn = ctk.CTkButton(clean_inner, text=t("gui.device.select_old"), font=get_font(12), width=95, height=32, command=self._select_old_sync_epubs)
        self.select_old_btn.pack(side="left", padx=4)

        self.cleanup_old_btn = ctk.CTkButton(clean_inner, text=t("gui.device.cleanup_old"), font=get_font(12, "bold"), width=150, height=32, fg_color=COLOR_DANGER[0], hover_color=COLOR_DANGER[1], command=self._cleanup_old_sync_epubs)
        self.cleanup_old_btn.pack(side="left", padx=4)

        self._action_buttons = (
            self.refresh_btn,
            self.up_btn,
            self.delete_btn,
            self.mkdir_btn,
            self.rename_btn,
            self.move_btn,
            self.download_btn,
            self.upload_btn,
            self.select_old_btn,
            self.cleanup_old_btn,
        )
