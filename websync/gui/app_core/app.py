"""메인 GUI 컨트롤러 (조립)."""
from __future__ import annotations

import os
import hashlib
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk

from websync.integrations.calibre import CalibreManager
from websync.core.paths import resolve_path
from websync.upload.uploader import X3Uploader, normalize_device_host
from websync.scheduler.manager import SchedulerManager
from websync.integrations.notifier import ToastNotifier
from websync.pipeline.service import SyncService
from websync.core.logger import get_log_dir
from websync.config.exceptions import ConfigSaveError
from websync.gui.widgets import (
    COLOR_BG, COLOR_CARD_BG, COLOR_FG, COLOR_ACCENT, FONT_FAMILY, get_font,
    center_window, setup_dialog
)
from websync.gui.tab_sync import SyncTab
from websync.gui.tab_calibre import CalibreTab
from websync.gui.tab_history import HistoryTab
from websync.gui.tab_device_files import DeviceFilesTab
from websync.gui.tab_settings import SettingsTab
from websync.gui.bottom_bar import BottomBar

from websync.gui.app_core.layout import AppLayoutMixin
from websync.gui.app_core.helpers import AppHelpersMixin
from websync.gui.app_core.config_sync import AppConfigSyncMixin
from websync.gui.app_core.sync_control import AppSyncControlMixin


class SyncAppGui(
    AppLayoutMixin,
    AppHelpersMixin,
    AppConfigSyncMixin,
    AppSyncControlMixin,
):
    """CustomTkinter 기반 현대적 GUI 컨트롤러"""
    def __init__(self, service: SyncService):
        self.service = service
        self.scheduler = SchedulerManager()
        self.calibre = CalibreManager(
            self.service.config.get("calibre_path", "C:\\Program Files\\Calibre2\\calibredb.exe"),
            self.service.config.get("calibre_library_path", ""),
        )

        # 서버 인스턴스
        self._opds_server = None
        self._web_dashboard = None
        self._calibre_watcher = None

        self.root = ctk.CTk()
        self.root.title("Xteink X3 WebSync Manager")

        # 테마 모드 설정 (config에서 불러온 값 또는 System)
        appearance_mode = self.service.config.get("appearance_mode", "System")
        ctk.set_appearance_mode(appearance_mode)
        ctk.set_default_color_theme("blue")

        # 고 DPI 대응 창 크기
        init_w, init_h = self._preferred_window_size()
        self.root.geometry(f"{init_w}x{init_h}")
        self.root.minsize(780, 640)
        self.root.resizable(True, True)


        self._sync_busy = False
        self._bottom_pane_adjusted = False

        # CustomTkinter 전역 기본 폰트를 맑은 고딕으로 오버라이드
        ctk.FontManager.init_font_manager()
        if hasattr(ctk.FontManager, 'windows_default_font'):
            ctk.FontManager.windows_default_font = FONT_FAMILY
        if hasattr(ctk.FontManager, 'linux_default_font'):
            ctk.FontManager.linux_default_font = FONT_FAMILY
        # tkinter 기본 폰트도 맑은 고딕으로 설정
        import tkinter.font as tkfont
        for fname in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkFixedFont"):
            try:
                f = tkfont.nametofont(fname)
                f.configure(family=FONT_FAMILY, size=12)
            except Exception:
                pass

        self._setup_styles()
        self._build_ui()
        self._load_config_to_ui()

        self.root.after(0, lambda w=init_w, h=init_h: self._finalize_layout(w, h))
        self.root.after(200, self._maybe_show_portable_wizard)
        self.root.after(400, self._start_backup_pull_if_enabled)
        self.root.after(700, self.tab_settings._start_watch_if_enabled)
        self.root.after(1500, self._start_auto_update_check_if_enabled)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _start_auto_update_check_if_enabled(self):
        """시작 시 백그라운드로 최신 버전 존재 여부를 조용히 확인합니다."""
        cfg = self.service.config if isinstance(self.service.config, dict) else {}
        if not cfg.get("auto_check_update", True):
            return

        def update_task():
            from websync.core.update_service import UpdateService
            from websync import __version__

            try:
                service = UpdateService(current_version=__version__)
                manifest = service.check_for_update()
                if manifest:
                    def notify():
                        try:
                            self._log_message(
                                f"🚀 [업데이트] 새 버전 v{manifest.version}이 출시되었습니다! "
                                f"(고급 설정 탭 → 소프트웨어 업데이트에서 확인)"
                            )
                        except Exception:
                            pass
                    self.root.after(0, notify)
            except Exception:
                pass

        threading.Thread(target=update_task, daemon=True).start()

    def _maybe_show_portable_wizard(self):
        """첫 실행 시 공유 데이터 폴더 연결 마법사."""
        from websync.gui.portable_wizard import PortableDataWizard, should_show_portable_wizard

        cfg = self.service.config if isinstance(self.service.config, dict) else {}
        if not should_show_portable_wizard(cfg):
            return

        def after_wizard():
            try:
                self._load_config_to_ui()
                self.tab_sync._refresh_site_tree()
                self.tab_history._refresh_history()
                if hasattr(self.tab_settings, "_refresh_backup_status_label"):
                    self.tab_settings._refresh_backup_status_label()
            except Exception:
                pass

        wizard = PortableDataWizard(self.root, self.service, on_done=after_wizard)
        wizard.show()

    def _start_backup_pull_if_enabled(self):
        """시작 시 공유 데이터 폴더에서 사이트/이력을 백그라운드로 가져옵니다."""
        from websync.backup.portable_cfg import get_portable_cfg

        bs = get_portable_cfg(self.service.config if isinstance(self.service.config, dict) else {})
        if not (bs.get("enabled") and bs.get("auto_import_on_start", True) and (bs.get("folder") or "").strip()):
            return

        def task():
            try:
                result = self.service.maybe_backup_pull()
                if result.get("skipped"):
                    return

                def done():
                    try:
                        self.tab_sync._refresh_site_tree()
                        self.tab_history._refresh_history()
                        if hasattr(self.tab_settings, "_refresh_backup_status_label"):
                            self.tab_settings._refresh_backup_status_label()
                    except Exception:
                        pass
                    msg = result.get("message") or ""
                    if msg and (result.get("sites_changed") or result.get("history_changed")):
                        self._log_message(f"☁ 시작 시 공유 데이터 가져오기: {msg}")

                self.root.after(0, done)
            except Exception as e:
                self.root.after(0, lambda: self._log_message(f"☁ 시작 시 공유 데이터 가져오기 실패: {e}"))

        threading.Thread(target=task, daemon=True).start()

