from __future__ import annotations

import os
import hashlib
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from websync.integrations.calibre import CalibreManager
from websync.core.paths import resolve_path
from websync.upload.uploader import X3Uploader, normalize_device_host
from websync.scheduler.manager import SchedulerManager
from websync.integrations.notifier import ToastNotifier
from websync.pipeline.service import SyncService
from websync.core.logger import get_log_dir
from websync.config.exceptions import ConfigSaveError
from websync.gui.widgets import (
    BG_COLOR, FG_COLOR, ACCENT_COLOR, SECONDARY_BG, TEXT_BG, GREEN_COLOR, RED_COLOR, YELLOW_COLOR, HINT_COLOR,
    center_window, setup_dialog
)
from websync.gui.tab_sync import SyncTab
from websync.gui.tab_calibre import CalibreTab
from websync.gui.tab_history import HistoryTab
from websync.gui.tab_device_files import DeviceFilesTab
from websync.gui.tab_settings import SettingsTab
from websync.gui.bottom_bar import BottomBar


def _set_entry_val(widget, val):
    if hasattr(widget, "delete"):
        widget.delete(0, "end")
    if hasattr(widget, "insert"):
        widget.insert(0, str(val))
    elif hasattr(widget, "set"):
        widget.set(str(val))


class AppConfigSyncMixin:
    def _load_config_to_ui(self):
        config = self.service.config
        
        # 1. SyncTab 설정 로드
        _set_entry_val(self.tab_sync.ip_entry, config.get("x3_ip", "crosspoint.local"))
        _set_entry_val(self.tab_sync.dir_entry, config.get("output_dir", "./output"))
        self.tab_sync.font_cb.set(config.get("font_family", "serif"))
        _set_entry_val(self.tab_sync.font_size_sp, config.get("font_size", 16))
        _set_entry_val(self.tab_sync.line_height_sp, config.get("line_height", 1.7))
        self.tab_sync.cover_var.set(config.get("epub_cover", True))

        sched_conf = config.get("schedule", {})
        self.tab_sync.hour_cb.set(sched_conf.get("hour", "07"))
        self.tab_sync.min_cb.set(sched_conf.get("minute", "00"))
        
        self.tab_sync._refresh_devices_tree()
        self.tab_sync._refresh_site_tree()
        self.tab_sync._refresh_schedule_status()

        # 2. CalibreTab 설정 로드
        _set_entry_val(self.tab_calibre.calibre_entry, config.get("calibre_path", "C:\\Program Files\\Calibre2\\calibredb.exe"))
        _set_entry_val(self.tab_calibre.calibre_lib_entry, config.get("calibre_library_path", ""))
        self._start_background_task(
            self.tab_calibre._test_and_load_calibre,
            kwargs={"silent": True},
            name="calibre-initial-load",
        )

        # 3. HistoryTab 로드
        self.tab_history._refresh_history()

        # 3b. 기기 파일 탭 — 설정 로드 + 기기 목록 (목록 로드는 사용자가 새로고침)
        self.tab_device_files.load_settings_from_config()
        self.tab_device_files.refresh_device_list()

        # 4. SettingsTab 설정 로드
        # M4 & M7 설정 로드
        self.tab_settings.merge_mode_var.set(config.get("epub_merge_mode", "per_site"))
        self.tab_settings.epub_theme_cb.set(config.get("epub_theme", "default"))
        _set_entry_val(self.tab_settings.custom_css_entry, config.get("epub_custom_css", ""))
        self.tab_settings._on_theme_changed()

        opds_conf = config.get("opds_server", {})
        _set_entry_val(self.tab_settings.opds_port_sp, opds_conf.get("port", 8765))
        self.tab_settings.opds_allow_lan_var.set(opds_conf.get("allow_lan", False))
        # N5: 마스킹 표시는 _refresh_opds_key_display 헬퍼로 통일 (기존 token[:8] 노출 제거)
        self.tab_settings.opds_key_show_var.set(False)
        self.tab_settings._refresh_opds_key_display()

        web_conf = config.get("web_dashboard", {})
        _set_entry_val(self.tab_settings.web_port_sp, web_conf.get("port", 8766))
        self.tab_settings.web_allow_lan_var.set(web_conf.get("allow_lan", False))
        self.tab_settings.web_token_show_var.set(False)
        self.tab_settings._refresh_web_token_display()

        watch_conf = config.get("calibre_watch", {})
        _set_entry_val(self.tab_settings.watch_dir_entry, watch_conf.get("watch_dir", ""))

        ai_conf = config.get("ai_summary", {})
        self.tab_settings.ai_enabled_var.set(ai_conf.get("enabled", False))
        self.tab_settings.ai_provider_cb.set(ai_conf.get("provider", "openai"))
        _set_entry_val(self.tab_settings.ai_key_entry, ai_conf.get("api_key", ""))

        trans_conf = config.get("translation", {})
        self.tab_settings.trans_enabled_var.set(trans_conf.get("enabled", False))
        self.tab_settings.trans_provider_cb.set(trans_conf.get("provider", "googletrans"))
        # N5: libretranslate API Key Entry 채우기
        self.tab_settings.trans_key_entry.delete(0, tk.END)
        self.tab_settings.trans_key_entry.insert(0, trans_conf.get("libretranslate_api_key", ""))
        self.tab_settings._update_trans_key_state()

        # 클라우드 백업 동기화
        self.tab_settings._load_backup_sync_from_config(config)

    def _save_ui_settings(self):
        config = self.service.config
        
        # 1. SyncTab에서 정보 가져옴
        config["x3_ip"] = normalize_device_host(self.tab_sync.ip_entry.get())
        config["output_dir"] = self.tab_sync.dir_entry.get().strip()
        config["font_family"] = self.tab_sync.font_cb.get()
        config["epub_cover"] = self.tab_sync.cover_var.get()
        try:
            config["font_size"] = int(self.tab_sync.font_size_sp.get())
        except ValueError:
            config["font_size"] = 16
        try:
            config["line_height"] = float(self.tab_sync.line_height_sp.get())
        except ValueError:
            config["line_height"] = 1.7
        
        config.setdefault("schedule", {})
        config["schedule"]["hour"] = self.tab_sync.hour_cb.get()
        config["schedule"]["minute"] = self.tab_sync.min_cb.get()

        # 2. CalibreTab에서 정보 가져옴
        config["calibre_path"] = self.tab_calibre.calibre_entry.get().strip()
        config["calibre_library_path"] = self.tab_calibre.calibre_lib_entry.get().strip()

        # 3. SettingsTab에서 정보 가져옴
        # M4 & M7 가져옴
        config["epub_merge_mode"] = self.tab_settings.merge_mode_var.get()
        config["epub_theme"] = self.tab_settings.epub_theme_cb.get()
        config["epub_custom_css"] = self.tab_settings.custom_css_entry.get().strip()

        try:
            config.setdefault("opds_server", {})["port"] = int(self.tab_settings.opds_port_sp.get())
            config["opds_server"]["allow_lan"] = self.tab_settings.opds_allow_lan_var.get()
        except ValueError:
            pass
        try:
            config.setdefault("web_dashboard", {})["port"] = int(self.tab_settings.web_port_sp.get())
            config["web_dashboard"]["allow_lan"] = self.tab_settings.web_allow_lan_var.get()
        except ValueError:
            pass
        
        config.setdefault("calibre_watch", {})["watch_dir"] = self.tab_settings.watch_dir_entry.get().strip()

        # 클라우드 백업 동기화
        if hasattr(self.tab_settings, "_collect_backup_sync_into_config"):
            self.tab_settings._collect_backup_sync_into_config(config)

        # 저장 실행
        if not self._safe_save_config(config, reload=True):
            return
        
        self.calibre.calibre_path = config["calibre_path"]
        self.calibre.library_path = config["calibre_library_path"]
        if hasattr(self.tab_settings, "_refresh_backup_status_label"):
            self.tab_settings._refresh_backup_status_label()

    # ------------------------------------------------------------------
    # 즉시 동기화 실행
    # ------------------------------------------------------------------

