"""EPUB 만들기 옵션 카드 (글꼴·크기·줄 간격·표지·테마·병합 방식).

예전에는 글꼴은 뉴스 동기화 탭, 테마·병합 방식은 고급 설정 탭에 흩어져 있었다.
EPUB 결과물에 영향을 주는 옵션을 한 카드에 모아 흐름을 단순화한다.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

from websync.gui.widgets import (
    CardFrame, COLOR_SECONDARY_FG, Tooltip, get_font, make_button,
)
from websync.i18n import t

EPUB_THEMES: tuple[str, ...] = ("default", "serif_classic", "sans_modern", "dark_eink", "custom")
FONT_CHOICES: tuple[str, ...] = ("serif", "sans-serif", "Malgun Gothic", "KoPubWorldBatang", "NanumGothic")
FONT_SIZE_CHOICES: tuple[str, ...] = tuple(str(v) for v in (12, 14, 15, 16, 17, 18, 20, 22, 24))
LINE_HEIGHT_CHOICES: tuple[str, ...] = ("1.4", "1.5", "1.6", "1.7", "1.8", "2.0")

FONT_SIZE_RANGE = (8, 48)
LINE_HEIGHT_RANGE = (1.0, 3.0)


def parse_font_size(raw: object, default: int = 16) -> int:
    """글자 크기 입력을 허용 범위로 보정한다 (숫자가 아니면 기본값)."""
    try:
        value = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return default
    lo, hi = FONT_SIZE_RANGE
    return max(lo, min(hi, value))


def parse_line_height(raw: object, default: float = 1.7) -> float:
    """줄 간격 입력을 허용 범위로 보정한다 (숫자가 아니면 기본값)."""
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return default
    lo, hi = LINE_HEIGHT_RANGE
    return round(max(lo, min(hi, value)), 2)


def theme_label(key: str) -> str:
    return t(f"gui.epub.theme.{key}")


class SyncEpubOptionsMixin:
    """뉴스 동기화 탭에 EPUB 옵션 카드를 붙이는 믹스인."""

    def _build_epub_card(self, body) -> CardFrame:
        card = CardFrame(body, title=t("gui.epub.card_title"), subtitle=t("gui.epub.card_sub"))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=(4, 10))
        inner.columnconfigure(5, weight=1)

        # 1행: 글꼴 / 크기 / 줄 간격
        ctk.CTkLabel(inner, text=t("gui.sync.font_label"), font=get_font(13)).grid(
            row=0, column=0, padx=(0, 6), pady=6, sticky="w"
        )
        self.font_cb = ctk.CTkComboBox(
            inner, values=list(FONT_CHOICES), font=get_font(12), width=170, height=32,
            command=lambda _v: self._save_epub_settings(),
        )
        self.font_cb.grid(row=0, column=1, padx=4, pady=6, sticky="w")
        self.font_cb.set("serif")
        self.app._bind_autosave(self.font_cb)
        Tooltip(self.font_cb, t("gui.epub.font_tip"))

        ctk.CTkLabel(inner, text=t("gui.sync.font_size_label"), font=get_font(13)).grid(
            row=0, column=2, padx=(14, 6), pady=6, sticky="w"
        )
        self.font_size_sp = ctk.CTkComboBox(
            inner, values=list(FONT_SIZE_CHOICES), font=get_font(12), width=80, height=32,
            command=lambda _v: self._save_epub_settings(),
        )
        self.font_size_sp.grid(row=0, column=3, padx=4, pady=6, sticky="w")
        self.font_size_sp.set("16")
        self.app._bind_autosave(self.font_size_sp)

        ctk.CTkLabel(inner, text=t("gui.sync.line_height_label"), font=get_font(13)).grid(
            row=0, column=4, padx=(14, 6), pady=6, sticky="w"
        )
        self.line_height_sp = ctk.CTkComboBox(
            inner, values=list(LINE_HEIGHT_CHOICES), font=get_font(12), width=80, height=32,
            command=lambda _v: self._save_epub_settings(),
        )
        self.line_height_sp.grid(row=0, column=5, padx=4, pady=6, sticky="w")
        self.line_height_sp.set("1.7")
        self.app._bind_autosave(self.line_height_sp)

        # 2행: 테마 / 사용자 CSS
        ctk.CTkLabel(inner, text=t("gui.settings.epub.theme_label"), font=get_font(13)).grid(
            row=1, column=0, padx=(0, 6), pady=6, sticky="w"
        )
        self._theme_label_to_key = {theme_label(k): k for k in EPUB_THEMES}
        self.epub_theme_cb = ctk.CTkOptionMenu(
            inner,
            values=[theme_label(k) for k in EPUB_THEMES],
            font=get_font(12),
            width=170,
            command=self._on_theme_changed,
        )
        self.epub_theme_cb.grid(row=1, column=1, padx=4, pady=6, sticky="w")
        self.epub_theme_cb.set(theme_label("default"))

        css_row = ctk.CTkFrame(inner, fg_color="transparent")
        css_row.grid(row=1, column=2, columnspan=4, padx=(14, 0), pady=6, sticky="we")
        css_row.columnconfigure(0, weight=1)
        self.custom_css_entry = ctk.CTkEntry(
            css_row, font=get_font(12), height=32,
            placeholder_text=t("gui.epub.custom_css_placeholder"),
        )
        self.custom_css_entry.grid(row=0, column=0, sticky="we")
        self.custom_css_btn = make_button(
            css_row, t("gui.settings.epub.browse"), self._browse_custom_css,
            kind="secondary", width=80,
        )
        self.custom_css_btn.grid(row=0, column=1, padx=(6, 0))
        self.app._bind_autosave(self.custom_css_entry)

        # 3행: 묶는 방식
        ctk.CTkLabel(inner, text=t("gui.settings.epub.merge_label"), font=get_font(13)).grid(
            row=2, column=0, padx=(0, 6), pady=6, sticky="w"
        )
        merge_row = ctk.CTkFrame(inner, fg_color="transparent")
        merge_row.grid(row=2, column=1, columnspan=5, sticky="w", pady=6)
        self.merge_mode_var = tk.StringVar(value="per_site")
        self.per_site_rb = ctk.CTkRadioButton(
            merge_row, text=t("gui.settings.epub.per_site"), font=get_font(12),
            variable=self.merge_mode_var, value="per_site", command=self._save_epub_settings,
        )
        self.per_site_rb.pack(side="left", padx=(4, 16))
        self.digest_rb = ctk.CTkRadioButton(
            merge_row, text=t("gui.settings.epub.digest"), font=get_font(12),
            variable=self.merge_mode_var, value="daily_digest", command=self._save_epub_settings,
        )
        self.digest_rb.pack(side="left")
        Tooltip(self.digest_rb, t("gui.epub.digest_tip"))

        # 4행: 표지
        self.cover_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            inner,
            text=t("gui.sync.cover_auto"),
            font=get_font(12),
            variable=self.cover_var,
            command=self._save_epub_settings,
        ).grid(row=3, column=0, columnspan=4, padx=4, pady=(6, 0), sticky="w")

        ctk.CTkLabel(
            card, text=t("gui.epub.hint"), font=get_font(11),
            text_color=COLOR_SECONDARY_FG, anchor="w", justify="left",
        ).pack(fill="x", padx=14, pady=(0, 10))

        self._apply_theme_state()
        return card

    # ------------------------------------------------------------------
    # 값 접근 (config_sync 에서 사용)
    # ------------------------------------------------------------------

    def get_epub_theme(self) -> str:
        label = self.epub_theme_cb.get()
        return self._theme_label_to_key.get(label, label if label in EPUB_THEMES else "default")

    def set_epub_theme(self, key: str) -> None:
        key = key if key in EPUB_THEMES else "default"
        self.epub_theme_cb.set(theme_label(key))
        self._apply_theme_state()

    def set_font_family(self, family: str) -> None:
        family = (family or "serif").strip() or "serif"
        values = list(FONT_CHOICES)
        if family not in values:
            values.append(family)
            self.font_cb.configure(values=values)
        self.font_cb.set(family)

    # ------------------------------------------------------------------
    # 이벤트
    # ------------------------------------------------------------------

    def _save_epub_settings(self) -> None:
        self.app._save_ui_settings()

    def _apply_theme_state(self) -> None:
        state = "normal" if self.get_epub_theme() == "custom" else "disabled"
        self.custom_css_entry.configure(state=state)
        self.custom_css_btn.configure(state=state)

    def _on_theme_changed(self, _choice=None) -> None:
        self._apply_theme_state()
        self._save_epub_settings()

    def _browse_custom_css(self) -> None:
        f = filedialog.askopenfilename(
            title=t("gui.settings.epub.browse_title"),
            filetypes=[("CSS files", "*.css"), ("All files", "*.*")],
        )
        if not f:
            return
        self.set_epub_theme("custom")
        self.custom_css_entry.configure(state="normal")
        self.custom_css_entry.delete(0, tk.END)
        self.custom_css_entry.insert(0, f)
        self._save_epub_settings()
