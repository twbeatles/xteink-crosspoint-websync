"""첫 실행 공유 데이터 폴더 연결 마법사 (CustomTkinter 기반 모달)."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import customtkinter as ctk
from typing import TYPE_CHECKING, Callable, Optional

from websync.backup.format import MANIFEST_FILENAME, SITES_FILENAME
from websync.backup.portable_cfg import apply_portable_cfg, get_portable_cfg
from websync.gui.widgets import (
    CardFrame, COLOR_CARD_BG, COLOR_FG, COLOR_SECONDARY_FG, COLOR_ACCENT, get_font, setup_dialog
)
from websync.i18n import t

if TYPE_CHECKING:
    from websync.pipeline.service import SyncService


def should_show_portable_wizard(config: dict) -> bool:
    """마법사 표시 여부."""
    pd = get_portable_cfg(config)
    if pd.get("wizard_completed"):
        return False
    # 이미 폴더가 설정·활성화되어 있으면 스킵
    if pd.get("enabled") and (pd.get("folder") or "").strip():
        return False
    return True


class PortableDataWizard:
    """공유 데이터 폴더 연결/생성 또는 이 PC만 사용 모달 마법사."""

    def __init__(
        self,
        parent: ctk.CTk,
        service: "SyncService",
        *,
        on_done: Optional[Callable[[], None]] = None,
    ):
        self.parent = parent
        self.service = service
        self.on_done = on_done
        self.result: str | None = None  # local | connect | create | None

        self.dialog = ctk.CTkToplevel(parent)
        self.dialog.title(t("gui.wizard.title"))
        self.dialog.transient(parent)
        setup_dialog(self.dialog, parent, 580, 420)
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_local_only)

        outer = ctk.CTkFrame(self.dialog, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(
            outer,
            text=t("gui.wizard.question"),
            font=get_font(15, "bold"),
            text_color=COLOR_FG,
        ).pack(anchor="w", pady=(0, 8))

        ctk.CTkLabel(
            outer,
            text=t("gui.wizard.body"),
            font=get_font(12),
            text_color=COLOR_SECONDARY_FG,
            justify="left",
        ).pack(anchor="w", pady=(0, 14))

        btn_card = CardFrame(outer)
        btn_card.pack(fill="x", pady=6)

        ctk.CTkButton(
            btn_card,
            text=t("gui.wizard.connect"),
            font=get_font(13, "bold"),
            fg_color=COLOR_ACCENT[0],
            hover_color=COLOR_ACCENT[1],
            height=38,
            command=self._connect_existing,
        ).pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkButton(
            btn_card,
            text=t("gui.wizard.create"),
            font=get_font(13),
            height=38,
            command=self._create_new,
        ).pack(fill="x", padx=12, pady=4)

        ctk.CTkButton(
            btn_card,
            text=t("gui.wizard.local_only"),
            font=get_font(13),
            fg_color=("#e9ecef", "#343a40"),
            text_color=COLOR_FG,
            height=38,
            command=self._on_local_only,
        ).pack(fill="x", padx=12, pady=(4, 10))

        ctk.CTkLabel(
            outer,
            text=t("gui.wizard.hint"),
            font=get_font(12),
            text_color=COLOR_SECONDARY_FG,
        ).pack(anchor="w", pady=(12, 0))

    def show(self) -> None:
        self.dialog.wait_window()

    def _finish(self, result: str) -> None:
        self.result = result
        try:
            self.dialog.grab_release()
        except Exception:
            pass
        self.dialog.destroy()
        if self.on_done:
            try:
                self.on_done()
            except Exception:
                pass

    def _mark_wizard_done(self, **portable_updates) -> bool:
        updates = {"wizard_completed": True, **portable_updates}

        def mutate(cfg: dict) -> None:
            apply_portable_cfg(cfg, updates)

        try:
            self.service.config = self.service.config_manager.update_config(mutate)
            return True
        except Exception as e:
            messagebox.showerror(t("gui.wizard.save_fail"), str(e), parent=self.dialog)
            return False

    def _on_local_only(self) -> None:
        if not self._mark_wizard_done(enabled=False):
            return
        self._finish("local")

    def _connect_existing(self) -> None:
        path = filedialog.askdirectory(
            parent=self.dialog,
            title=t("gui.wizard.select_existing"),
        )
        if not path:
            return
        sites = os.path.join(path, SITES_FILENAME)
        manifest = os.path.join(path, MANIFEST_FILENAME)
        if not (os.path.isfile(sites) or os.path.isfile(manifest)):
            if not messagebox.askyesno(
                t("gui.wizard.folder_check_title"),
                t("gui.wizard.folder_check", sites=SITES_FILENAME, manifest=manifest),
                parent=self.dialog,
            ):
                return

        if not self._mark_wizard_done(
            enabled=True,
            folder=path,
            auto_import_on_start=True,
            auto_export=True,
            include_history=True,
        ):
            return

        try:
            result = self.service.maybe_backup_pull(force=True)
            msg = result.get("message") or t("gui.wizard.import_done")
            if result.get("ok") or result.get("skipped"):
                messagebox.showinfo(t("gui.wizard.connect_ok_title"), t("gui.wizard.connect_ok", msg=msg), parent=self.parent)
            else:
                messagebox.showwarning(
                    t("gui.wizard.connect_warn_title"),
                    t("gui.wizard.connect_warn", msg=msg),
                    parent=self.parent,
                )
        except Exception as e:
            messagebox.showwarning(t("gui.wizard.connect_saved_title"), t("gui.wizard.connect_saved", error=e), parent=self.parent)
        self._finish("connect")

    def _create_new(self) -> None:
        path = filedialog.askdirectory(
            parent=self.dialog,
            title=t("gui.wizard.select_new"),
        )
        if not path:
            return
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            messagebox.showerror(t("dialog.error"), t("gui.wizard.mkdir_fail", error=e), parent=self.dialog)
            return

        if not self._mark_wizard_done(
            enabled=True,
            folder=path,
            auto_import_on_start=True,
            auto_export=True,
            include_history=True,
        ):
            return

        try:
            result = self.service.maybe_backup_push(force=True)
            msg = result.get("message") or t("gui.wizard.export_done")
            if result.get("ok"):
                messagebox.showinfo(
                    t("gui.wizard.create_ok_title"),
                    t("gui.wizard.create_ok", msg=msg),
                    parent=self.parent,
                )
            else:
                messagebox.showwarning(
                    t("gui.wizard.folder_set_title"),
                    t("gui.wizard.folder_set_warn", msg=msg),
                    parent=self.parent,
                )
        except Exception as e:
            messagebox.showwarning(t("gui.wizard.folder_set_title"), t("gui.wizard.folder_set_saved", error=e), parent=self.parent)
        self._finish("create")
