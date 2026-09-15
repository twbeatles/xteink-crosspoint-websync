from __future__ import annotations

import tkinter as tk
from tkinter import ttk
import customtkinter as ctk

from websync.gui.widgets import (
    COLOR_BG, COLOR_CARD_BG, COLOR_FG, COLOR_ACCENT, FONT_FAMILY, get_font,
    center_window, apply_treeview_style
)
from websync.gui.tab_sync import SyncTab
from websync.gui.tab_calibre import CalibreTab
from websync.gui.tab_history import HistoryTab
from websync.gui.tab_device_files import DeviceFilesTab
from websync.gui.tab_settings import SettingsTab
from websync.gui.bottom_bar import BottomBar
from websync.i18n import t


class AppLayoutMixin:
    def _preferred_window_size(self) -> tuple[int, int]:
        """디스플레이 배율/해상도에 맞는 초기 창 크기."""
        try:
            sw = int(self.root.winfo_screenwidth())
            sh = int(self.root.winfo_screenheight())
        except Exception:
            return 1020, 880
        width = max(940, min(1240, int(sw * 0.64)))
        height = max(820, min(1040, int(sh * 0.86)))
        return width, height

    def _finalize_layout(self, width: int, height: int) -> None:
        """창 배치 후 하단 패널 최소 높이를 보장한다."""
        center_window(self.root, width, height)
        self.root.update_idletasks()

    def _setup_styles(self):
        """TTK 호환 위젯(Treeview, Entry, Combobox 등) 전역 폰트 설정."""
        style = ttk.Style()
        _font = (FONT_FAMILY, 12)
        _font_bold = (FONT_FAMILY, 12, "bold")
        # 전역 기본
        style.configure(".", font=_font)
        # 개별 위젯 — "." 상속이 불완전한 위젯에 명시 지정
        style.configure("TLabel", font=_font)
        style.configure("TButton", font=_font)
        style.configure("TEntry", font=_font)
        style.configure("TCheckbutton", font=_font)
        style.configure("TRadiobutton", font=_font)
        style.configure("TCombobox", font=_font)
        style.configure("TLabelframe.Label", font=_font_bold)
        style.configure("TSpinbox", font=_font)
        # Treeview (별도 함수에서 행 높이, 색상 등도 설정)
        apply_treeview_style(style)

    def _build_ui(self):
        """CustomTkinter 기반 애플리케이션 프레임워크 구축."""
        self.main_container = ctk.CTkFrame(self.root, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=12, pady=12)

        # 상단/중앙 탭 영역 (CTkTabview)
        self.tabview = ctk.CTkTabview(
            self.main_container,
            corner_radius=10,
            segmented_button_selected_color=COLOR_ACCENT[0],
            segmented_button_selected_hover_color=COLOR_ACCENT[1]
        )
        if hasattr(self.tabview, "_segmented_button"):
            self.tabview._segmented_button.configure(font=get_font(13, "bold"))
        self.tabview.pack(fill="both", expand=True, pady=(0, 10))

        # 하위 호환성을 위해 self.notebook 래퍼 지정
        self.notebook = self.tabview

        # 탭 생성
        tab_sync_frame = self.tabview.add(f" {t('gui.tabs.sync')} ")
        tab_calibre_frame = self.tabview.add(f" {t('gui.tabs.calibre')} ")
        tab_history_frame = self.tabview.add(f" {t('gui.tabs.history')} ")
        tab_device_frame = self.tabview.add(f" {t('gui.tabs.device')} ")
        tab_settings_frame = self.tabview.add(f" {t('gui.tabs.settings')} ")

        # 탭 컴포넌트 실체화 — 반드시 pack()으로 부모 프레임에 배치해야 보임
        self.tab_sync = SyncTab(tab_sync_frame, self)
        self.tab_sync.pack(fill="both", expand=True)

        self.tab_calibre = CalibreTab(tab_calibre_frame, self)
        self.tab_calibre.pack(fill="both", expand=True)

        self.tab_history = HistoryTab(tab_history_frame, self)
        self.tab_history.pack(fill="both", expand=True)

        self.tab_device_files = DeviceFilesTab(tab_device_frame, self)
        self.tab_device_files.pack(fill="both", expand=True)

        self.tab_settings = SettingsTab(tab_settings_frame, self)
        self.tab_settings.pack(fill="both", expand=True)

        # 하단 동기화 컨트롤 및 로그 바 (BottomBar)
        self.bottom_container = ctk.CTkFrame(
            self.main_container,
            fg_color="transparent",
            height=230
        )
        self.bottom_container.pack(fill="x", side="bottom")

        self.bottom_bar = BottomBar(self.bottom_container, self)
        self.bottom_bar.pack(fill="both", expand=True)
