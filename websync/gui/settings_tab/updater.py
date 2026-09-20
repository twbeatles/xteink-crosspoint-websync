"""설정 탭 내 소프트웨어 업데이트 관련 서브패널 (CustomTkinter 기반)."""
from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

from websync import __version__
from websync.core.update_constants import UPDATE_RELEASES_URL
from websync.core.update_installer import UpdateCancelledError
from websync.core.update_manifest import ReleaseManifest
from websync.core.update_service import UpdateService
from websync.gui.widgets import (
    CardFrame,
    COLOR_ACCENT,
    COLOR_DANGER,
    COLOR_FG,
    COLOR_SECONDARY_FG,
    COLOR_SUCCESS,
    COLOR_WARNING,
    get_font,
)
from websync.i18n import t


class SettingsUpdaterMixin:
    """설정 탭용 소프트웨어 업데이트 Mixin"""

    def _build_updater_card(self, parent):
        self._download_cancel_event: threading.Event | None = None

        update_card = CardFrame(
            parent,
            title=t("gui.settings.update.card_title"),
            subtitle=t("gui.settings.update.card_sub"),
        )
        update_card.pack(fill="x", padx=8, pady=6)

        inner = ctk.CTkFrame(update_card, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=10)
        inner.columnconfigure(1, weight=1)

        # 0행: 현재 버전 및 버튼들
        ctk.CTkLabel(
            inner,
            text=t("gui.settings.update.current"),
            font=get_font(13),
        ).grid(row=0, column=0, padx=(0, 8), pady=6, sticky="w")

        self.current_version_lbl = ctk.CTkLabel(
            inner,
            text=f"v{__version__}",
            font=get_font(13, "bold"),
            text_color=COLOR_ACCENT[0],
        )
        self.current_version_lbl.grid(row=0, column=1, padx=4, pady=6, sticky="w")

        btn_box = ctk.CTkFrame(inner, fg_color="transparent")
        btn_box.grid(row=0, column=2, padx=4, pady=6, sticky="e")

        self.check_update_btn = ctk.CTkButton(
            btn_box,
            text=t("gui.settings.update.check"),
            font=get_font(12, "bold"),
            width=120,
            height=32,
            fg_color=COLOR_ACCENT[0],
            hover_color=COLOR_ACCENT[1],
            command=self._on_check_update_clicked,
        )
        self.check_update_btn.pack(side="left", padx=(0, 6))

        self.cancel_download_btn = ctk.CTkButton(
            btn_box,
            text=t("gui.settings.update.cancel"),
            font=get_font(12),
            width=65,
            height=32,
            fg_color=COLOR_DANGER[0],
            hover_color=COLOR_DANGER[1],
            command=self._on_cancel_download_clicked,
        )
        # 초기에는 취소 버튼 숨김

        # 1행: 시작 시 자동 확인 옵션
        self.auto_check_update_var = tk.BooleanVar(
            value=bool(self.service.config.get("auto_check_update", True))
        )
        ctk.CTkCheckBox(
            inner,
            text=t("gui.settings.update.auto_check"),
            font=get_font(12),
            variable=self.auto_check_update_var,
            command=self._save_updater_settings,
        ).grid(row=1, column=0, columnspan=2, padx=4, pady=(2, 4), sticky="w")

        # 릴리즈 페이지 링크 버튼
        self.view_releases_btn = ctk.CTkButton(
            inner,
            text=t("gui.settings.update.changelog"),
            font=get_font(11),
            width=160,
            height=26,
            fg_color="transparent",
            text_color=COLOR_ACCENT[0],
            hover_color=("#e9ecef", "#343a40"),
            command=lambda: self.app._open_url(UPDATE_RELEASES_URL),
        )
        self.view_releases_btn.grid(row=1, column=2, padx=4, pady=(2, 4), sticky="e")

        # 2행: 상태 안내 레이블
        self.update_status_lbl = ctk.CTkLabel(
            inner,
            text=t("gui.settings.update.hint"),
            font=get_font(12),
            text_color=COLOR_SECONDARY_FG,
        )
        self.update_status_lbl.grid(row=2, column=0, columnspan=3, padx=4, pady=(4, 6), sticky="w")

    def _save_updater_settings(self):
        """업데이터 관련 사용자 설정 저장"""
        value = bool(self.auto_check_update_var.get())
        try:
            self.service.config = self.service.config_manager.patch_fields(auto_check_update=value)
        except Exception as e:
            messagebox.showerror(t("gui.app.save_fail_title"), str(e))

    def _safe_ui(self, callback):
        """위젯이 생존해 있을 때만 메인 스레드 after 콜백 실행"""
        try:
            if self.winfo_exists():
                self.after(0, callback)
        except (tk.TclError, RuntimeError):
            pass

    def _on_check_update_clicked(self):
        self.check_update_btn.configure(state="disabled")
        self.update_status_lbl.configure(
            text=t("gui.settings.update.checking"),
            text_color=COLOR_FG,
        )

        def worker():
            service = UpdateService(current_version=__version__)
            try:
                manifest = service.check_for_update()
                if manifest is None:
                    self._safe_ui(self._on_update_check_latest)
                else:
                    self._safe_ui(lambda: self._on_update_found(manifest, service))
            except Exception as exc:
                error_msg = str(exc)
                self._safe_ui(lambda msg=error_msg: self._on_update_check_failed(msg))

        starter = getattr(getattr(self, "app", None), "_start_background_task", None)
        if starter:
            starter(worker, name="update-check")
        else:
            threading.Thread(target=worker, daemon=True).start()

    def _on_update_check_latest(self):
        self.check_update_btn.configure(state="normal")
        self.update_status_lbl.configure(
            text=t("gui.settings.update.latest_status", version=__version__),
            text_color=COLOR_SUCCESS,
        )
        messagebox.showinfo(t("gui.settings.update.check_title"), t("gui.settings.update.latest_msg", version=__version__))

    def _on_update_check_failed(self, error_msg: str):
        self.check_update_btn.configure(state="normal")
        self.update_status_lbl.configure(
            text=t("gui.settings.update.check_fail_status", error=error_msg),
            text_color=COLOR_WARNING,
        )
        messagebox.showwarning(t("gui.settings.update.check_fail_title"), t("gui.settings.update.check_fail_body", error=error_msg))

    def _on_update_found(self, manifest: ReleaseManifest, service: UpdateService):
        self.check_update_btn.configure(state="normal")
        self.update_status_lbl.configure(
            text=t("gui.settings.update.found_status", version=manifest.version),
            text_color=COLOR_ACCENT[0],
        )
        proceed = messagebox.askyesno(
            t("gui.settings.update.found_title"),
            t(
                "gui.settings.update.found_body",
                version=manifest.version,
                size=f"{manifest.artifact_size / (1024 * 1024):.1f}",
                expires=manifest.expires_at.strftime("%Y-%m-%d"),
            ),
        )
        if proceed:
            self._start_update_download(manifest, service)

    def _start_update_download(self, manifest: ReleaseManifest, service: UpdateService):
        self.check_update_btn.configure(state="disabled")
        self.cancel_download_btn.pack(side="left")
        self._download_cancel_event = threading.Event()
        self.update_status_lbl.configure(
            text=t("gui.settings.update.downloading_verify"),
            text_color=COLOR_ACCENT[0],
        )

        def download_worker():
            cancel_event = self._download_cancel_event
            try:
                staged = service.download_and_stage(
                    manifest,
                    progress_callback=lambda curr, total: self._safe_ui(
                        lambda: self.update_status_lbl.configure(
                            text=t(
                                "gui.settings.update.downloading",
                                curr=f"{curr / (1024 * 1024):.1f}",
                                total=f"{total / (1024 * 1024):.1f}",
                            )
                        )
                    ),
                    cancel_event=cancel_event,
                )
                self._safe_ui(
                    lambda: self._on_download_complete(staged, manifest, service)
                )
            except UpdateCancelledError:
                self._safe_ui(self._on_download_cancelled)
            except Exception as exc:
                error_msg = str(exc)
                self._safe_ui(lambda msg=error_msg: self._on_download_failed(msg))

        starter = getattr(getattr(self, "app", None), "_start_background_task", None)
        if starter:
            starter(download_worker, name="update-download")
        else:
            threading.Thread(target=download_worker, daemon=True).start()

    def _on_cancel_download_clicked(self):
        if self._download_cancel_event:
            self._download_cancel_event.set()
        self.cancel_download_btn.pack_forget()
        self.update_status_lbl.configure(
            text=t("gui.settings.update.cancel_pending"),
            text_color=COLOR_WARNING,
        )

    def _on_download_cancelled(self):
        self.check_update_btn.configure(state="normal")
        self.cancel_download_btn.pack_forget()
        self.update_status_lbl.configure(
            text=t("gui.settings.update.cancelled"),
            text_color=COLOR_SECONDARY_FG,
        )

    def _on_download_complete(self, staged_path, manifest: ReleaseManifest, service: UpdateService):
        self.check_update_btn.configure(state="normal")
        self.cancel_download_btn.pack_forget()
        self.update_status_lbl.configure(
            text=t("gui.settings.update.verified", version=manifest.version),
            text_color=COLOR_SUCCESS,
        )
        is_frozen = getattr(sys, "frozen", False)
        if not is_frozen:
            messagebox.showinfo(
                t("gui.settings.update.dev_done_title"),
                t("gui.settings.update.dev_done_body", version=manifest.version, path=staged_path),
            )
            return

        apply_now = messagebox.askyesno(
            t("gui.settings.update.ready_title"),
            t("gui.settings.update.ready_body", version=manifest.version),
        )
        if apply_now:
            try:
                service.launch_update_and_exit(staged_path, manifest)
            except Exception as exc:
                messagebox.showerror(t("gui.settings.update.apply_fail_title"), t("gui.settings.update.apply_fail", error=exc))

    def _on_download_failed(self, error_msg: str):
        self.check_update_btn.configure(state="normal")
        self.cancel_download_btn.pack_forget()
        self.update_status_lbl.configure(
            text=t("gui.settings.update.dl_fail_status", error=error_msg),
            text_color=COLOR_WARNING,
        )
        messagebox.showerror(t("gui.settings.update.fail_title"), t("gui.settings.update.fail_body", error=error_msg))
