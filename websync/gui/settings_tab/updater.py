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


class SettingsUpdaterMixin:
    """설정 탭용 소프트웨어 업데이트 Mixin"""

    def _build_updater_card(self, parent):
        self._download_cancel_event: threading.Event | None = None

        update_card = CardFrame(
            parent,
            title="🔄 소프트웨어 업데이트",
            subtitle="GitHub Releases 기반 디지털 서명 무결성 검증 업데이트",
        )
        update_card.pack(fill="x", padx=8, pady=6)

        inner = ctk.CTkFrame(update_card, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=10)
        inner.columnconfigure(1, weight=1)

        # 0행: 현재 버전 및 버튼들
        ctk.CTkLabel(
            inner,
            text="현재 버전:",
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
            text="최신 버전 확인",
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
            text="취소",
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
            text="프로그램 시작 시 최신 버전 자동 확인",
            font=get_font(12),
            variable=self.auto_check_update_var,
            command=self._save_updater_settings,
        ).grid(row=1, column=0, columnspan=2, padx=4, pady=(2, 4), sticky="w")

        # 릴리즈 페이지 링크 버튼
        self.view_releases_btn = ctk.CTkButton(
            inner,
            text="🔗 릴리즈 노트(Changelog) 보기",
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
            text="최신 버전 여부를 확인하려면 [최신 버전 확인] 버튼을 누르세요.",
            font=get_font(12),
            text_color=COLOR_SECONDARY_FG,
        )
        self.update_status_lbl.grid(row=2, column=0, columnspan=3, padx=4, pady=(4, 6), sticky="w")

    def _save_updater_settings(self):
        """업데이터 관련 사용자 설정 저장"""
        self.service.config["auto_check_update"] = self.auto_check_update_var.get()
        try:
            self.service.config_manager.save_config(self.service.config)
        except Exception:
            pass

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
            text="최신 버전 릴리즈 매니페스트 확인 중...",
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

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_check_latest(self):
        self.check_update_btn.configure(state="normal")
        self.update_status_lbl.configure(
            text=f"✓ 현재 최신 버전(v{__version__})을 사용 중입니다.",
            text_color=COLOR_SUCCESS,
        )
        messagebox.showinfo("업데이트 확인", f"현재 최신 버전(v{__version__})을 사용하고 있습니다.")

    def _on_update_check_failed(self, error_msg: str):
        self.check_update_btn.configure(state="normal")
        self.update_status_lbl.configure(
            text=f"⚠️ 업데이트 확인 실패: {error_msg}",
            text_color=COLOR_WARNING,
        )
        messagebox.showwarning("업데이트 확인 실패", f"업데이트 서버에 연결할 수 없습니다:\n{error_msg}")

    def _on_update_found(self, manifest: ReleaseManifest, service: UpdateService):
        self.check_update_btn.configure(state="normal")
        self.update_status_lbl.configure(
            text=f"🚀 새 버전 v{manifest.version} 사용 가능! (다운로드 준비 완료)",
            text_color=COLOR_ACCENT[0],
        )
        proceed = messagebox.askyesno(
            "새 업데이트 발견",
            f"새로운 버전 v{manifest.version}이 출시되었습니다.\n\n"
            f"크기: {manifest.artifact_size / (1024 * 1024):.1f} MB\n"
            f"유효 만료일: {manifest.expires_at.strftime('%Y-%m-%d')}\n\n"
            f"지금 다운로드하여 업데이트를 적용하시겠습니까?",
        )
        if proceed:
            self._start_update_download(manifest, service)

    def _start_update_download(self, manifest: ReleaseManifest, service: UpdateService):
        self.check_update_btn.configure(state="disabled")
        self.cancel_download_btn.pack(side="left")
        self._download_cancel_event = threading.Event()
        self.update_status_lbl.configure(
            text="새 버전을 다운로드하고 검증하는 중...",
            text_color=COLOR_ACCENT[0],
        )

        def download_worker():
            cancel_event = self._download_cancel_event
            try:
                staged = service.download_and_stage(
                    manifest,
                    progress_callback=lambda curr, total: self._safe_ui(
                        lambda: self.update_status_lbl.configure(
                            text=f"다운로드 중... ({curr / (1024 * 1024):.1f}MB / {total / (1024 * 1024):.1f}MB)"
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

        threading.Thread(target=download_worker, daemon=True).start()

    def _on_cancel_download_clicked(self):
        if self._download_cancel_event:
            self._download_cancel_event.set()
        self.cancel_download_btn.pack_forget()
        self.update_status_lbl.configure(
            text="업데이트 다운로드 취소 요청 중...",
            text_color=COLOR_WARNING,
        )

    def _on_download_cancelled(self):
        self.check_update_btn.configure(state="normal")
        self.cancel_download_btn.pack_forget()
        self.update_status_lbl.configure(
            text="업데이트 다운로드가 취소되었습니다.",
            text_color=COLOR_SECONDARY_FG,
        )

    def _on_download_complete(self, staged_path, manifest: ReleaseManifest, service: UpdateService):
        self.check_update_btn.configure(state="normal")
        self.cancel_download_btn.pack_forget()
        self.update_status_lbl.configure(
            text=f"✓ v{manifest.version} 검증 완료. 재시작하여 적용합니다.",
            text_color=COLOR_SUCCESS,
        )
        is_frozen = getattr(sys, "frozen", False)
        if not is_frozen:
            messagebox.showinfo(
                "다운로드 완료 (개발 모드)",
                f"v{manifest.version} 바이너리 다운로드 및 디지털 서명 검증이 완료되었습니다.\n\n"
                f"파일 위치: {staged_path}\n\n"
                f"※ 개발 환경(Python 소스 실행)에서는 실행 파일 자동 교체가 지원되지 않습니다.",
            )
            return

        apply_now = messagebox.askyesno(
            "업데이트 준비 완료",
            f"v{manifest.version} 다운로드 및 디지털 서명 검증이 완료되었습니다.\n\n"
            f"프로그램을 재시작하여 업데이트를 적용하시겠습니까?",
        )
        if apply_now:
            try:
                service.launch_update_and_exit(staged_path, manifest)
            except Exception as exc:
                messagebox.showerror("업데이트 적용 실패", f"업데이터 기동 실패:\n{exc}")

    def _on_download_failed(self, error_msg: str):
        self.check_update_btn.configure(state="normal")
        self.cancel_download_btn.pack_forget()
        self.update_status_lbl.configure(
            text=f"❌ 업데이트 다운로드 실패: {error_msg}",
            text_color=COLOR_WARNING,
        )
        messagebox.showerror("업데이트 실패", f"업데이트 다운로드 또는 무결성 검증에 실패했습니다:\n{error_msg}")
