"""고급·서버 설정 탭 (CustomTkinter 카드 레이아웃 적용)."""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import customtkinter as ctk

from websync.gui.widgets import (
    CardFrame, COLOR_CARD_BG, COLOR_FG, COLOR_SECONDARY_FG, COLOR_ACCENT,
    COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING, get_font,
    create_scrollable_frame, setup_dialog
)
from websync.core.paths import resolve_path
from websync.core.logger import get_log_dir
from websync.servers.opds import OPDSServer
from websync.servers.web_dashboard import WebDashboard
from websync.watch.calibre import CalibreWatcher

from websync.gui.settings_tab.epub_settings import SettingsEpubMixin
from websync.gui.settings_tab.servers import SettingsServersMixin
from websync.gui.settings_tab.watch import SettingsWatchMixin
from websync.gui.settings_tab.ai_translation import SettingsAiTranslationMixin
from websync.gui.settings_tab.backup_sync import SettingsBackupSyncMixin
from websync.gui.settings_tab.updater import SettingsUpdaterMixin
from websync.i18n import t


class SettingsTab(
    SettingsEpubMixin,
    SettingsServersMixin,
    SettingsWatchMixin,
    SettingsAiTranslationMixin,
    SettingsBackupSyncMixin,
    SettingsUpdaterMixin,
    ctk.CTkFrame,
):
    """서버 제어 및 AI, 번역, 합본, 테마 등 고급 설정을 담당하는 탭 패널"""
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.service = app.service
        self.config_manager = app.service.config_manager

        self._build_ui()

    def _build_ui(self):
        body = create_scrollable_frame(self)

        # 0. 앱 테마 및 UI Appearance 설정 카드
        theme_card = CardFrame(body, title=t("settings.theme_card"), subtitle=t("settings.theme_sub"))
        theme_card.pack(fill="x", padx=8, pady=6)

        theme_inner = ctk.CTkFrame(theme_card, fg_color="transparent")
        theme_inner.pack(fill="x", padx=12, pady=10)

        ctk.CTkLabel(theme_inner, text=t("settings.theme_label"), font=get_font(13)).grid(row=0, column=0, padx=(0, 8), pady=4, sticky="w")
        self.app_theme_menu = ctk.CTkOptionMenu(
            theme_inner,
            values=["System", "Dark", "Light"],
            font=get_font(12),
            width=130,
            command=self._on_app_theme_changed
        )
        self.app_theme_menu.grid(row=0, column=1, padx=4, pady=4, sticky="w")
        curr_mode = self.service.config.get("appearance_mode", "System")
        self.app_theme_menu.set(curr_mode)

        ctk.CTkLabel(theme_inner, text=t("settings.language.label"), font=get_font(13)).grid(row=1, column=0, padx=(0, 8), pady=4, sticky="w")
        self._lang_codes = ("auto", "ko", "en")
        lang_labels = {code: t(f"settings.language.{code}") for code in self._lang_codes}
        self._lang_label_to_code = {label: code for code, label in lang_labels.items()}
        self.ui_lang_menu = ctk.CTkOptionMenu(
            theme_inner,
            values=[lang_labels[code] for code in self._lang_codes],
            font=get_font(12),
            width=160,
            command=self._on_ui_language_changed,
        )
        self.ui_lang_menu.grid(row=1, column=1, padx=4, pady=4, sticky="w")
        curr_lang = str(self.service.config.get("ui_language") or "auto").strip().lower()
        if curr_lang not in self._lang_codes:
            curr_lang = "auto"
        self.ui_lang_menu.set(lang_labels[curr_lang])

        # 1. EPUB 병합 모드 및 빌드 테마 카드
        epub_style_card = CardFrame(body, title=t("gui.settings.epub.card_title"), subtitle=t("gui.settings.epub.card_sub"))
        epub_style_card.pack(fill="x", padx=8, pady=6)

        epub_inner = ctk.CTkFrame(epub_style_card, fg_color="transparent")
        epub_inner.pack(fill="x", padx=12, pady=10)
        epub_inner.columnconfigure(1, weight=1)

        ctk.CTkLabel(epub_inner, text=t("gui.settings.epub.merge_label"), font=get_font(13)).grid(row=0, column=0, padx=(0, 8), pady=6, sticky="w")
        self.merge_mode_var = tk.StringVar(value="per_site")
        self.per_site_rb = ctk.CTkRadioButton(
            epub_inner, text=t("gui.settings.epub.per_site"), font=get_font(12), variable=self.merge_mode_var, value="per_site", command=self._save_epub_settings
        )
        self.per_site_rb.grid(row=0, column=1, padx=4, pady=6, sticky="w")
        self.digest_rb = ctk.CTkRadioButton(
            epub_inner, text=t("gui.settings.epub.digest"), font=get_font(12), variable=self.merge_mode_var, value="daily_digest", command=self._save_epub_settings
        )
        self.digest_rb.grid(row=0, column=2, padx=4, pady=6, sticky="w")

        ctk.CTkLabel(epub_inner, text=t("gui.settings.epub.theme_label"), font=get_font(13)).grid(row=1, column=0, padx=(0, 8), pady=6, sticky="w")
        self.epub_theme_cb = ctk.CTkOptionMenu(
            epub_inner, values=["default", "serif_classic", "sans_modern", "dark_eink", "custom"], font=get_font(12), width=160, command=self._on_theme_changed
        )
        self.epub_theme_cb.grid(row=1, column=1, padx=4, pady=6, sticky="w")
        self.epub_theme_cb.set("default")

        ctk.CTkLabel(epub_inner, text=t("gui.settings.epub.custom_css"), font=get_font(13)).grid(row=2, column=0, padx=(0, 8), pady=6, sticky="w")
        self.custom_css_entry = ctk.CTkEntry(epub_inner, font=get_font(12), height=34)
        self.custom_css_entry.grid(row=2, column=1, padx=4, pady=6, sticky="we")
        self.custom_css_btn = ctk.CTkButton(epub_inner, text=t("gui.settings.epub.browse"), font=get_font(12), width=90, height=34, command=self._browse_custom_css)
        self.custom_css_btn.grid(row=2, column=2, padx=4, pady=6)
        self.app._bind_autosave(self.custom_css_entry)

        # 2. OPDS 서버 카드
        opds_card = CardFrame(body, title=t("gui.settings.opds.card_title"), subtitle=t("gui.settings.opds.card_sub"))
        opds_card.pack(fill="x", padx=8, pady=6)

        opds_inner = ctk.CTkFrame(opds_card, fg_color="transparent")
        opds_inner.pack(fill="x", padx=12, pady=10)
        opds_inner.columnconfigure(4, weight=1)

        ctk.CTkLabel(opds_inner, text=t("gui.settings.port"), font=get_font(13)).grid(row=0, column=0, padx=(0, 6), pady=6, sticky="w")
        self.opds_port_sp = ctk.CTkEntry(opds_inner, font=get_font(12), width=75, height=32)
        self.opds_port_sp.grid(row=0, column=1, padx=4, pady=6, sticky="w")
        self.opds_port_sp.insert(0, "8765")

        self.opds_start_btn = ctk.CTkButton(opds_inner, text=t("gui.settings.server_start"), font=get_font(12, "bold"), width=105, height=32, command=self._toggle_opds)
        self.opds_start_btn.grid(row=0, column=2, padx=6, pady=6)

        self.opds_status_label = ctk.CTkLabel(opds_inner, text=t("gui.settings.stopped"), text_color=COLOR_DANGER[0], font=get_font(13, "bold"))
        self.opds_status_label.grid(row=0, column=3, padx=8, pady=6, sticky="w")

        self.opds_url_label = ctk.CTkLabel(opds_inner, text="", font=get_font(12), text_color=COLOR_ACCENT[0], cursor="hand2")
        self.opds_url_label.grid(row=1, column=0, columnspan=5, padx=4, pady=(0, 4), sticky="w")
        self.opds_url_label.bind("<Button-1>", lambda e: self.app._open_url(self.opds_url_label.cget("text")))

        self.opds_allow_lan_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(opds_inner, text=t("gui.settings.lan_public"), font=get_font(12), variable=self.opds_allow_lan_var, command=self.app._save_ui_settings).grid(row=2, column=0, columnspan=2, padx=4, pady=(0, 4), sticky="w")

        self.opds_api_key_label = ctk.CTkLabel(opds_inner, text="", font=get_font(12), text_color=COLOR_SECONDARY_FG)
        self.opds_api_key_label.grid(row=3, column=0, columnspan=4, padx=4, pady=(0, 6), sticky="w")

        self.opds_key_show_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(opds_inner, text=t("gui.settings.api_key_show"), font=get_font(12), variable=self.opds_key_show_var, command=self._refresh_opds_key_display).grid(row=3, column=4, padx=4, pady=(0, 6), sticky="e")
        self.app._bind_autosave(self.opds_port_sp)

        # 3. 웹 대시보드 카드
        web_card = CardFrame(body, title=t("gui.settings.web.card_title"), subtitle=t("gui.settings.web.card_sub"))
        web_card.pack(fill="x", padx=8, pady=6)

        web_inner = ctk.CTkFrame(web_card, fg_color="transparent")
        web_inner.pack(fill="x", padx=12, pady=10)
        web_inner.columnconfigure(4, weight=1)

        ctk.CTkLabel(web_inner, text=t("gui.settings.port"), font=get_font(13)).grid(row=0, column=0, padx=(0, 6), pady=6, sticky="w")
        self.web_port_sp = ctk.CTkEntry(web_inner, font=get_font(12), width=75, height=32)
        self.web_port_sp.grid(row=0, column=1, padx=4, pady=6, sticky="w")
        self.web_port_sp.insert(0, "8766")

        self.web_start_btn = ctk.CTkButton(web_inner, text=t("gui.settings.server_start"), font=get_font(12, "bold"), width=105, height=32, command=self._toggle_web)
        self.web_start_btn.grid(row=0, column=2, padx=6, pady=6)

        self.web_status_label = ctk.CTkLabel(web_inner, text=t("gui.settings.stopped"), text_color=COLOR_DANGER[0], font=get_font(13, "bold"))
        self.web_status_label.grid(row=0, column=3, padx=8, pady=6, sticky="w")

        self.web_url_label = ctk.CTkLabel(web_inner, text="", font=get_font(12), text_color=COLOR_ACCENT[0], cursor="hand2")
        self.web_url_label.grid(row=1, column=0, columnspan=5, padx=4, pady=(0, 4), sticky="w")
        self.web_url_label.bind("<Button-1>", lambda e: self.app._open_url(self.web_url_label.cget("text")))

        self.web_allow_lan_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(web_inner, text=t("gui.settings.lan_public"), font=get_font(12), variable=self.web_allow_lan_var, command=self.app._save_ui_settings).grid(row=2, column=0, columnspan=2, padx=4, pady=(0, 4), sticky="w")

        self.web_token_label = ctk.CTkLabel(web_inner, text="", font=get_font(12), text_color=COLOR_SECONDARY_FG)
        self.web_token_label.grid(row=3, column=0, columnspan=4, padx=4, pady=(0, 6), sticky="w")

        self.web_token_show_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(web_inner, text=t("gui.settings.token_show"), font=get_font(12), variable=self.web_token_show_var, command=self._refresh_web_token_display).grid(row=3, column=4, padx=4, pady=(0, 6), sticky="e")
        self.app._bind_autosave(self.web_port_sp)

        # 4. Calibre Watch 카드
        watch_card = CardFrame(body, title=t("gui.settings.watch.card_title"), subtitle=t("gui.settings.watch.card_sub"))
        watch_card.pack(fill="x", padx=8, pady=6)

        watch_inner = ctk.CTkFrame(watch_card, fg_color="transparent")
        watch_inner.pack(fill="x", padx=12, pady=10)
        watch_inner.columnconfigure(1, weight=1)

        ctk.CTkLabel(watch_inner, text=t("gui.settings.watch.folder_label"), font=get_font(13)).grid(row=0, column=0, padx=(0, 8), pady=6, sticky="w")
        self.watch_dir_entry = ctk.CTkEntry(watch_inner, font=get_font(12), height=34)
        self.watch_dir_entry.grid(row=0, column=1, padx=4, pady=6, sticky="we")

        ctk.CTkButton(watch_inner, text=t("gui.settings.watch.browse_btn"), font=get_font(12), width=90, height=34, command=self._browse_watch_dir).grid(row=0, column=2, padx=4, pady=6)
        self.watch_start_btn = ctk.CTkButton(watch_inner, text=t("gui.settings.watch.start_btn"), font=get_font(12, "bold"), width=105, height=34, command=self._toggle_watch)
        self.watch_start_btn.grid(row=0, column=3, padx=4, pady=6)

        self.watch_status_label = ctk.CTkLabel(watch_inner, text=t("gui.settings.watch.stopped"), text_color=COLOR_DANGER[0], font=get_font(12))
        self.watch_status_label.grid(row=1, column=0, columnspan=4, padx=4, pady=(0, 4), sticky="w")
        self.app._bind_autosave(self.watch_dir_entry)

        # 5. AI 요약 카드
        ai_card = CardFrame(body, title=t("gui.settings.ai.card_title"), subtitle=t("gui.settings.ai.card_sub"))
        ai_card.pack(fill="x", padx=8, pady=6)

        ai_inner = ctk.CTkFrame(ai_card, fg_color="transparent")
        ai_inner.pack(fill="x", padx=12, pady=10)

        self.ai_enabled_var = tk.BooleanVar()
        ctk.CTkCheckBox(ai_inner, text=t("gui.settings.ai.enable"), font=get_font(12), variable=self.ai_enabled_var).grid(row=0, column=0, padx=(0, 8), pady=6, sticky="w")

        ctk.CTkLabel(ai_inner, text=t("gui.settings.provider"), font=get_font(13)).grid(row=0, column=1, padx=(8, 4), pady=6, sticky="w")
        self.ai_provider_cb = ctk.CTkOptionMenu(ai_inner, values=["openai", "ollama"], font=get_font(12), width=120)
        self.ai_provider_cb.grid(row=0, column=2, padx=4, pady=6, sticky="w")
        self.ai_provider_cb.set("openai")

        ctk.CTkLabel(ai_inner, text=t("gui.settings.ai.key_host"), font=get_font(13)).grid(row=1, column=0, padx=(0, 8), pady=6, sticky="w")
        self.ai_key_entry = ctk.CTkEntry(ai_inner, font=get_font(12), width=280, height=34, show="*")
        self.ai_key_entry.grid(row=1, column=1, columnspan=2, padx=4, pady=6, sticky="w")

        self.ai_key_show_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(ai_inner, text=t("gui.settings.show"), font=get_font(12), variable=self.ai_key_show_var, command=self._toggle_ai_key_visibility).grid(row=1, column=3, padx=6, pady=6)
        ctk.CTkButton(ai_inner, text=t("gui.settings.save"), font=get_font(12, "bold"), width=75, height=34, command=self._save_ai_settings).grid(row=1, column=4, padx=6, pady=6)

        # 6. 번역 카드
        trans_card = CardFrame(body, title=t("gui.settings.trans.card_title"), subtitle=t("gui.settings.trans.card_sub"))
        trans_card.pack(fill="x", padx=8, pady=6)

        trans_inner = ctk.CTkFrame(trans_card, fg_color="transparent")
        trans_inner.pack(fill="x", padx=12, pady=10)

        self.trans_enabled_var = tk.BooleanVar()
        ctk.CTkCheckBox(trans_inner, text=t("gui.settings.trans.enable"), font=get_font(12), variable=self.trans_enabled_var).grid(row=0, column=0, padx=(0, 8), pady=6, sticky="w")

        ctk.CTkLabel(trans_inner, text=t("gui.settings.provider"), font=get_font(13)).grid(row=0, column=1, padx=(8, 4), pady=6, sticky="w")
        self.trans_provider_cb = ctk.CTkOptionMenu(trans_inner, values=["googletrans", "libretranslate"], font=get_font(12), width=140, command=lambda _v: self._update_trans_key_state())
        self.trans_provider_cb.grid(row=0, column=2, padx=4, pady=6, sticky="w")
        self.trans_provider_cb.set("googletrans")

        ctk.CTkButton(trans_inner, text=t("gui.settings.save"), font=get_font(12, "bold"), width=75, height=34, command=self._save_trans_settings).grid(row=0, column=3, padx=6, pady=6)

        ctk.CTkLabel(trans_inner, text=t("gui.settings.trans.libre_key"), font=get_font(13)).grid(row=1, column=0, padx=(0, 8), pady=6, sticky="w")
        self.trans_key_entry = ctk.CTkEntry(trans_inner, font=get_font(12), width=280, height=34, show="*")
        self.trans_key_entry.grid(row=1, column=1, columnspan=2, padx=4, pady=6, sticky="w")

        self.trans_key_show_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(trans_inner, text=t("gui.settings.show"), font=get_font(12), variable=self.trans_key_show_var, command=self._toggle_trans_key_visibility).grid(row=1, column=3, padx=6, pady=6)
        self._update_trans_key_state()

        # 7. 클라우드 백업 동기화
        self._build_backup_sync_section(body)

        # 8. 소프트웨어 업데이트 카드
        self._build_updater_card(body)

        # 9. 로그 폴더 카드
        log_card = CardFrame(body, title=t("gui.settings.log.card_title"))
        log_card.pack(fill="x", padx=8, pady=6)

        log_inner = ctk.CTkFrame(log_card, fg_color="transparent")
        log_inner.pack(fill="x", padx=12, pady=10)

        ctk.CTkButton(log_inner, text=t("gui.settings.log.open"), font=get_font(12), height=34, command=self._open_log_folder).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(log_inner, text=t("gui.settings.log.hint"), font=get_font(12), text_color=COLOR_SECONDARY_FG).pack(side="left", padx=4)

    def _on_app_theme_changed(self, choice: str):
        """CustomTkinter 테마 변경 콜백."""
        ctk.set_appearance_mode(choice)
        try:
            self.service.config = self.service.config_manager.patch_fields(appearance_mode=choice)
        except Exception as e:
            messagebox.showerror(t("gui.app.save_fail_title"), str(e))
            return
        self.app._setup_styles()

    def _on_ui_language_changed(self, choice: str):
        code = self._lang_label_to_code.get(choice, "auto")
        try:
            self.service.config = self.service.config_manager.patch_fields(ui_language=code)
        except Exception as e:
            messagebox.showerror(t("gui.app.save_fail_title"), str(e))
            return
        messagebox.showinfo(t("settings.language.restart_title"), t("settings.language.restart"))
