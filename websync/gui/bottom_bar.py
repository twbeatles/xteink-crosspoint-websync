"""하단 바 및 프로그램 로그 영역 컴포넌트 (CustomTkinter 기반)"""
from __future__ import annotations

import tkinter as tk
import customtkinter as ctk

from websync.gui.widgets import (
    CardFrame, COLOR_ACCENT, COLOR_CARD_BG, COLOR_FG, COLOR_SECONDARY_FG, get_font
)
from websync.i18n import t


class BottomBar(ctk.CTkFrame):
    """즉시 동기화, 프리뷰 제어, 진행도 표시, 로그 출력을 담당하는 하단 패널"""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._build_ui()

    def _build_ui(self):
        # 버튼 실행 구역 (CardFrame 적용)
        action_card = CardFrame(self, fg_color=COLOR_CARD_BG)
        action_card.pack(fill="x", pady=(0, 6))

        btn_row = ctk.CTkFrame(action_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=8)

        self.sync_now_btn = ctk.CTkButton(
            btn_row,
            text=t("gui.bottom.sync_now"),
            font=get_font(15, "bold"),
            fg_color=COLOR_ACCENT[0],
            hover_color=COLOR_ACCENT[1],
            height=42,
            corner_radius=8,
            command=self.app._run_immediate_sync,
        )
        self.sync_now_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.cancel_sync_btn = ctk.CTkButton(
            btn_row,
            text=t("gui.bottom.cancel"),
            font=get_font(13, "bold"),
            fg_color=("#dc3545", "#ea868f"),
            hover_color=("#bb2d3b", "#d16b74"),
            height=42,
            width=90,
            corner_radius=8,
            state="disabled",
            command=self.app._request_sync_cancel,
        )
        self.cancel_sync_btn.pack(side="left", padx=(0, 6))

        self.preview_btn = ctk.CTkButton(
            btn_row,
            text=t("gui.bottom.preview"),
            font=get_font(13, "bold"),
            fg_color=("#e9ecef", "#343a40"),
            text_color=COLOR_FG,
            hover_color=("ced4da", "#495057"),
            height=42,
            corner_radius=8,
            command=self.app.tab_sync.open_preview_window,
        )
        self.preview_btn.pack(side="right", fill="x", expand=True, padx=(6, 0))

        # 진행률 표시바 (CTkProgressBar)
        self.progress_bar = ctk.CTkProgressBar(
            self,
            orientation="horizontal",
            mode="determinate",
            height=10,
            corner_radius=5,
            progress_color=COLOR_ACCENT[0]
        )
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", pady=(0, 6))

        # 로그 출력 구역 (CardFrame + CTkTextbox)
        log_card = CardFrame(self, title=t("gui.bottom.log_title"))
        log_card.pack(fill="both", expand=True)

        self.log_txt = ctk.CTkTextbox(
            log_card,
            font=get_font(12),
            corner_radius=6,
            wrap="word",
            activate_scrollbars=True
        )
        self.log_txt.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.log_txt.configure(state="disabled")

        # Tkinter Text 호환 래퍼 메서드 지원
        self._wrap_log_txt_methods()

    def _wrap_log_txt_methods(self):
        """Tkinter Text의 config(state=...) 호환성을 위한 래퍼 메소드."""
        orig_config = self.log_txt.configure
        def compat_config(**kwargs):
            if "state" in kwargs:
                val = kwargs["state"]
                if val == "normal":
                    orig_config(state="normal")
                elif val == "disabled":
                    orig_config(state="disabled")
            else:
                orig_config(**kwargs)
        self.log_txt.config = compat_config
