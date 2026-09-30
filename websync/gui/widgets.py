"""공통 CustomTkinter 위젯, 테마 색상 상수 및 헬퍼 함수."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
import customtkinter as ctk

# CustomTkinter 기본 설정
ctk.set_appearance_mode("System")  # "System", "Dark", "Light"
ctk.set_default_color_theme("blue")  # "blue", "green", "dark-blue"

FONT_FAMILY = "Malgun Gothic"

def get_font(size: int = 12, weight: str = "normal") -> ctk.CTkFont:
    """맑은 고딕 기반 CustomTkinter 폰트 생성 헬퍼."""
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)

# 테마 색상 정의 (Light, Dark 튜플)
COLOR_BG            = ("#f8f9fa", "#1a1d20")  # 메인 창 배경
COLOR_CARD_BG       = ("#ffffff", "#24282d")  # 카드 및 서브 패널 배경
COLOR_CARD_BORDER   = ("#e9ecef", "#343a40")  # 카드 테두리
COLOR_FG            = ("#212529", "#f8f9fa")  # 주 텍스트
COLOR_SECONDARY_FG  = ("#6c757d", "#adb5bd")  # 보조 텍스트
COLOR_ACCENT        = ("#0d6efd", "#3d8bfd")  # 포인트 파랑
COLOR_SUCCESS       = ("#198754", "#20c997")  # 성공/초록
COLOR_DANGER        = ("#dc3545", "#ea868f")  # 에러/빨강
COLOR_WARNING       = ("#fd7e14", "#ff922b")  # 경고/주황
COLOR_NEUTRAL       = ("#e9ecef", "#343a40")  # 보조 버튼 배경
COLOR_NEUTRAL_HOVER = ("#ced4da", "#495057")  # 보조 버튼 hover
COLOR_DANGER_HOVER  = ("#bb2d3b", "#d16b74")
COLOR_ACCENT_SOFT   = ("#e7f1ff", "#1f2d44")  # 안내 배너 배경

# 기존 호환성용 단일 값 상수
BG_COLOR      = "#f8f9fa"
FG_COLOR      = "#212529"
ACCENT_COLOR  = "#0d6efd"
SECONDARY_BG  = "#e9ecef"
TEXT_BG       = "#ffffff"
GREEN_COLOR   = "#198754"
RED_COLOR     = "#dc3545"
YELLOW_COLOR  = "#fd7e14"
HINT_COLOR    = "#6c757d"


def center_window(window: tk.Misc, width: int | None = None, height: int | None = None) -> None:
    """창을 화면 중앙에 배치합니다."""
    window.update_idletasks()
    w = width or window.winfo_width()
    h = height or window.winfo_height()
    x = max(0, (window.winfo_screenwidth() - w) // 2)
    y = max(0, (window.winfo_screenheight() - h) // 2)
    if width and height:
        window.geometry(f"{width}x{height}+{x}+{y}")
    else:
        window.geometry(f"+{x}+{y}")


def setup_dialog(dialog: tk.Toplevel | ctk.CTkToplevel, root: tk.Misc, width: int, height: int, *, resizable: bool = True) -> None:
    """모달 다이얼로그 초기 설정."""
    dialog.transient(root)
    if hasattr(dialog, "grab_set"):
        dialog.grab_set()
    dialog.resizable(resizable, resizable)
    dialog.minsize(min(width, 460), min(height, 260))
    center_window(dialog, width, height)


def bind_widget_mousewheel(widget: tk.Misc, handler) -> None:
    """마우스휠 스크롤 이벤트 재귀 바인딩."""
    widget.bind("<MouseWheel>", handler, add="+")
    for child in widget.winfo_children():
        if child.winfo_class() in ("Treeview", "Text", "TCombobox", "TSpinbox", "CTkTextbox", "CTkScrollableFrame"):
            continue
        bind_widget_mousewheel(child, handler)


def bind_text_mousewheel(text_widget: tk.Text | ctk.CTkTextbox) -> None:
    """텍스트 위젯 스크롤 바인딩."""
    def _on_mousewheel(event):
        text_widget.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"
    text_widget.bind("<MouseWheel>", _on_mousewheel)


class CardFrame(ctk.CTkFrame):
    """현대적인 둥근 모서리와 가독성이 높은 카드 패널 컴포넌트."""
    def __init__(self, master, title: str | None = None, subtitle: str | None = None, **kwargs):
        kwargs.setdefault("fg_color", COLOR_CARD_BG)
        kwargs.setdefault("border_color", COLOR_CARD_BORDER)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("corner_radius", 10)
        super().__init__(master, **kwargs)
        self.header_right: ctk.CTkFrame | None = None

        if title:
            title_frame = ctk.CTkFrame(self, fg_color="transparent")
            title_frame.pack(fill="x", padx=14, pady=(12, 6))
            
            title_lbl = ctk.CTkLabel(
                title_frame,
                text=title,
                font=get_font(16, "bold"),
                text_color=COLOR_FG,
                anchor="w"
            )
            title_lbl.pack(side="left")

            if subtitle:
                sub_lbl = ctk.CTkLabel(
                    title_frame,
                    text=subtitle,
                    font=get_font(12),
                    text_color=COLOR_SECONDARY_FG,
                    anchor="w"
                )
                sub_lbl.pack(side="left", padx=(10, 0))
            # 제목 줄 오른쪽 슬롯 (요약 배지·보조 버튼 배치용)
            self.header_right = ctk.CTkFrame(title_frame, fg_color="transparent", width=1, height=1)
            self.header_right.pack(side="right")


def make_button(
    parent,
    text: str,
    command=None,
    *,
    kind: str = "primary",
    width: int = 100,
    height: int = 32,
    bold: bool = False,
    **kwargs,
) -> ctk.CTkButton:
    """일관된 스타일의 버튼 (kind: primary / secondary / danger)."""
    if kind == "secondary":
        kwargs.setdefault("fg_color", COLOR_NEUTRAL)
        kwargs.setdefault("hover_color", COLOR_NEUTRAL_HOVER)
        kwargs.setdefault("text_color", COLOR_FG)
    elif kind == "danger":
        kwargs.setdefault("fg_color", COLOR_DANGER)
        kwargs.setdefault("hover_color", COLOR_DANGER_HOVER)
    else:
        kwargs.setdefault("fg_color", COLOR_ACCENT)
    return ctk.CTkButton(
        parent,
        text=text,
        command=command,
        font=get_font(12, "bold" if bold else "normal"),
        width=width,
        height=height,
        corner_radius=kwargs.pop("corner_radius", 6),
        **kwargs,
    )


class Tooltip:
    """마우스를 올리면 짧은 도움말을 띄우는 가벼운 툴팁."""

    def __init__(self, widget: tk.Misc, text: str, *, delay_ms: int = 450):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id: str | None = None
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        try:
            self._after_id = self.widget.after(self.delay_ms, self._show)
        except tk.TclError:
            self._after_id = None

    def _cancel(self) -> None:
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _show(self) -> None:
        self._after_id = None
        if self._tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            tip = tk.Toplevel(self.widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            tk.Label(
                tip,
                text=self.text,
                justify="left",
                background="#333a40",
                foreground="#ffffff",
                padx=8,
                pady=5,
                wraplength=360,
                font=(FONT_FAMILY, 10),
            ).pack()
            self._tip = tip
        except tk.TclError:
            self._tip = None

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


def apply_treeview_style(tree: ttk.Treeview) -> None:
    """ttk.Treeview를 맑은 고딕 및 가독성 높인 커스텀 스타일로 적용합니다."""
    style = ttk.Style()
    
    # 다크/라이트 모드 판단
    mode = ctk.get_appearance_mode()
    is_dark = (mode == "Dark")

    bg = "#24282d" if is_dark else "#ffffff"
    fg = "#f8f9fa" if is_dark else "#212529"
    head_bg = "#1a1d20" if is_dark else "#e9ecef"
    select_bg = "#0d6efd"

    style.theme_use("clam")
    style.configure(
        "CTk.Treeview",
        background=bg,
        fieldbackground=bg,
        foreground=fg,
        rowheight=34,
        borderwidth=0,
        font=(FONT_FAMILY, 12)
    )
    style.map(
        "CTk.Treeview",
        background=[("selected", select_bg)],
        foreground=[("selected", "#ffffff")]
    )
    style.configure(
        "CTk.Treeview.Heading",
        background=head_bg,
        foreground=fg,
        relief="flat",
        font=(FONT_FAMILY, 12, "bold")
    )


def create_scrolled_tree(
    parent,
    columns,
    show: str = "headings",
    height: int = 10,
    *,
    padx: int = 10,
    pady: int = 8,
    **tree_kwargs,
) -> ttk.Treeview:
    """CustomTkinter 스타일의 스크롤 Treeview를 생성합니다."""
    wrapper = ctk.CTkFrame(parent, fg_color="transparent")
    wrapper.pack(fill="both", expand=True, padx=padx, pady=pady)
    wrapper.grid_rowconfigure(0, weight=1)
    wrapper.grid_columnconfigure(0, weight=1)

    tree = ttk.Treeview(wrapper, columns=columns, show=show, height=height, style="CTk.Treeview", **tree_kwargs)
    apply_treeview_style(tree)

    vsb = ttk.Scrollbar(wrapper, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(wrapper, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    return tree


def create_scrollable_frame(parent) -> ctk.CTkScrollableFrame:
    """CustomTkinter 세로 스크롤 가능 프레임을 생성합니다."""
    scrollable_frame = ctk.CTkScrollableFrame(
        parent,
        fg_color="transparent",
        corner_radius=0
    )
    scrollable_frame.pack(fill="both", expand=True)
    return scrollable_frame
