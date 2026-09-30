"""하단 바 및 프로그램 로그 영역 컴포넌트 (CustomTkinter 기반)"""
from __future__ import annotations

import os
import sys
import tkinter as tk
import customtkinter as ctk

from websync.gui.widgets import (
    CardFrame, COLOR_ACCENT, COLOR_CARD_BG, COLOR_DANGER, COLOR_DANGER_HOVER,
    COLOR_NEUTRAL, COLOR_NEUTRAL_HOVER, COLOR_FG, COLOR_SECONDARY_FG, COLOR_SUCCESS,
    COLOR_WARNING, Tooltip, get_font, make_button,
)
from websync.i18n import t

# 상태 표시 색상 (kind → 색상 튜플)
_STATUS_COLORS = {
    "idle": COLOR_SECONDARY_FG,
    "busy": COLOR_ACCENT,
    "ok": COLOR_SUCCESS,
    "warn": COLOR_WARNING,
    "error": COLOR_DANGER,
}

LOG_HEIGHT_EXPANDED = 120


class BottomBar(ctk.CTkFrame):
    """즉시 동기화, 프리뷰 제어, 진행도 표시, 로그 출력을 담당하는 하단 패널"""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._log_visible = True
        self._build_ui()

    def _build_ui(self):
        # 실행 버튼 + 상태 표시 카드
        action_card = CardFrame(self, fg_color=COLOR_CARD_BG)
        action_card.pack(fill="x", pady=(0, 6))

        btn_row = ctk.CTkFrame(action_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=(10, 4))

        self.sync_now_btn = ctk.CTkButton(
            btn_row,
            text=t("gui.bottom.sync_now"),
            font=get_font(15, "bold"),
            fg_color=COLOR_ACCENT,
            height=42,
            corner_radius=8,
            command=self.app._run_immediate_sync,
        )
        self.sync_now_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        Tooltip(self.sync_now_btn, t("gui.bottom.sync_now_tip"))

        self.preview_btn = ctk.CTkButton(
            btn_row,
            text=t("gui.bottom.preview"),
            font=get_font(13, "bold"),
            fg_color=COLOR_NEUTRAL,
            text_color=COLOR_FG,
            hover_color=COLOR_NEUTRAL_HOVER,
            height=42,
            corner_radius=8,
            command=self.app.tab_sync.open_preview_window,
        )
        self.preview_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        Tooltip(self.preview_btn, t("gui.bottom.preview_tip"))

        # 취소 버튼은 작업 중에만 보인다 (대기 중 빨간 버튼이 눈에 띄지 않도록)
        self.cancel_sync_btn = ctk.CTkButton(
            btn_row,
            text=t("gui.bottom.cancel"),
            font=get_font(13, "bold"),
            fg_color=COLOR_DANGER,
            hover_color=COLOR_DANGER_HOVER,
            height=42,
            width=90,
            corner_radius=8,
            state="disabled",
            command=self.app._request_sync_cancel,
        )

        status_row = ctk.CTkFrame(action_card, fg_color="transparent")
        status_row.pack(fill="x", padx=12, pady=(2, 8))

        self.status_label = ctk.CTkLabel(
            status_row,
            text=t("gui.bottom.status_idle"),
            font=get_font(12, "bold"),
            text_color=COLOR_SECONDARY_FG,
            anchor="w",
        )
        self.status_label.pack(side="left")

        self.log_toggle_btn = make_button(
            status_row, t("gui.bottom.log_hide"), self.toggle_log,
            kind="secondary", width=96, height=26,
        )
        self.log_toggle_btn.pack(side="right")
        make_button(
            status_row, t("gui.bottom.log_clear"), self.clear_log,
            kind="secondary", width=60, height=26,
        ).pack(side="right", padx=(0, 6))
        make_button(
            status_row, t("gui.bottom.log_folder"), self._open_log_folder,
            kind="secondary", width=110, height=26,
        ).pack(side="right", padx=(0, 6))

        self.progress_bar = ctk.CTkProgressBar(
            status_row,
            orientation="horizontal",
            mode="determinate",
            height=8,
            corner_radius=4,
            progress_color=COLOR_ACCENT,
        )
        self.progress_bar.set(0)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=(12, 12))

        # 로그 출력 구역 (접기/펼치기 가능 — 조작 버튼은 상태 줄에 있다)
        self.log_card = CardFrame(self)
        self.log_card.pack(fill="both", expand=True)

        self.log_txt = ctk.CTkTextbox(
            self.log_card,
            font=get_font(12),
            corner_radius=6,
            wrap="word",
            height=LOG_HEIGHT_EXPANDED,
            activate_scrollbars=True
        )
        self.log_txt.pack(fill="both", expand=True, padx=6, pady=6)
        self.log_txt.configure(state="disabled")

        # Tkinter Text 호환 래퍼 메서드 지원
        self._wrap_log_txt_methods()

    # ------------------------------------------------------------------
    # 상태·진행 표시
    # ------------------------------------------------------------------

    def set_busy(self, busy: bool) -> None:
        """작업 중에는 취소 버튼을 보이고 실행 버튼을 잠근다."""
        state = "disabled" if busy else "normal"
        self.sync_now_btn.configure(state=state)
        self.preview_btn.configure(state=state)
        if busy:
            self.cancel_sync_btn.configure(state="normal")
            if not self.cancel_sync_btn.winfo_ismapped():
                self.cancel_sync_btn.pack(side="left")
        else:
            self.cancel_sync_btn.configure(state="disabled")
            self.cancel_sync_btn.pack_forget()

    def set_status(self, text: str, kind: str = "idle") -> None:
        color = _STATUS_COLORS.get(kind, COLOR_SECONDARY_FG)
        try:
            self.status_label.configure(text=text, text_color=color)
        except tk.TclError:
            pass

    def reset_progress(self) -> None:
        try:
            self.progress_bar.set(0)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # 로그 영역
    # ------------------------------------------------------------------

    def toggle_log(self) -> None:
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.log_card.pack(fill="both", expand=True)
            self.log_toggle_btn.configure(text=t("gui.bottom.log_hide"))
        else:
            self.log_card.pack_forget()
            self.log_toggle_btn.configure(text=t("gui.bottom.log_show"))

    def clear_log(self) -> None:
        try:
            self.log_txt.configure(state="normal")
            self.log_txt.delete("1.0", tk.END)
            self.log_txt.configure(state="disabled")
        except tk.TclError:
            pass

    def _open_log_folder(self) -> None:
        from websync.core.logger import get_log_dir

        folder = get_log_dir()
        try:
            os.makedirs(folder, exist_ok=True)
            if os.name == "nt":
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", folder])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            self.app._log_message(t("gui.sync.folder_open_failed", error=e))

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
