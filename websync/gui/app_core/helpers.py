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
from websync.config.exceptions import ConfigSaveError, ConfigConflictError
from websync.backup.format import merge_sites
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


class AppHelpersMixin:
    def _bind_autosave(self, widget: tk.Misc) -> None:
        widget.bind("<FocusOut>", lambda _e: self._save_ui_settings())

    def _set_sync_ui_busy(self, busy: bool) -> None:
        self._sync_busy = busy
        state = "disabled" if busy else "normal"
        
        # 각 탭의 활성 버튼 상태 제어
        self.bottom_bar.sync_now_btn.configure(state=state)
        if hasattr(self.bottom_bar, "cancel_sync_btn"):
            self.bottom_bar.cancel_sync_btn.configure(state="normal" if busy else "disabled")
        self.bottom_bar.preview_btn.configure(state=state)
        self.tab_sync.direct_upload_btn.configure(state=state)
        self.tab_sync.test_conn_btn.configure(state=state)
        self.tab_calibre.calibre_send_btn.configure(state=state)
        self.tab_calibre.calibre_conn_btn.configure(state=state)

    def _log_message(self, message: str):
        try:
            if not getattr(self, "root", None) or not self.root.winfo_exists():
                return
            self.bottom_bar.log_txt.configure(state="normal")
            self.bottom_bar.log_txt.insert(tk.END, message + "\n")
            self.bottom_bar.log_txt.see(tk.END)
            self.bottom_bar.log_txt.configure(state="disabled")
        except tk.TclError:
            return

    def _update_progress(self, current: int, total: int):
        try:
            if not getattr(self, "root", None) or not self.root.winfo_exists():
                return
            if total > 0:
                if hasattr(self.bottom_bar.progress_bar, "set"):
                    self.bottom_bar.progress_bar.set(min(1.0, max(0.0, current / total)))
                else:
                    self.bottom_bar.progress_bar["maximum"] = total
                    self.bottom_bar.progress_bar["value"] = current
            else:
                if hasattr(self.bottom_bar.progress_bar, "set"):
                    self.bottom_bar.progress_bar.set(0)
                else:
                    self.bottom_bar.progress_bar["value"] = 0
        except tk.TclError:
            return

    def _open_url(self, url: str):
        if url:
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:
                pass

    def _make_log_callback(self):
        return lambda msg: self.root.after(0, lambda m=msg: self._log_message(m))

    def _make_progress_callback(self):
        return lambda cur, tot: self.root.after(0, lambda c=cur, t=tot: self._update_progress(c, t))

    def _make_uploader(self) -> X3Uploader:
        config = self.service.config
        df = config.get("device_files") or {}
        return X3Uploader(
            config.get("x3_ip", "").strip() or self.tab_sync.ip_entry.get().strip(),
            config.get("x3_devices", []),
            remote_dir=df.get("default_upload_path", "/"),
            primary_device_id=config.get("x3_primary_device_id", "") or "",
        )

    def _ip_display_name(self, ip: str) -> str:
        for d in self._make_uploader()._build_target_list():
            if d["ip"] == ip:
                return d.get("name") or ip
        return ip

    def _summarize_upload_results(self, results: dict) -> tuple[bool, bool, str]:
        if not results:
            return False, False, "등록된 기기 없음"
        ok_labels = [f"{self._ip_display_name(ip)}({ip})" for ip, ok in results.items() if ok]
        fail_labels = [f"{self._ip_display_name(ip)}({ip})" for ip, ok in results.items() if not ok]
        parts = []
        if ok_labels:
            parts.append(f"성공: {', '.join(ok_labels)}")
        if fail_labels:
            parts.append(f"실패: {', '.join(fail_labels)}")
        return all(results.values()), bool(ok_labels), " | ".join(parts)

    def _safe_save_config(self, config: dict, *, parent=None, reload: bool = False) -> bool:
        """설정을 저장합니다. revision CAS로 동시 갱신(백업 pull 등)과 충돌을 감지·재시도합니다."""
        max_conflict_retries = 3
        try:
            # 치명적 검증 오류 시 저장 거부
            errors = self.service.config_manager.get_validation_errors(config)
            fatal = [e for e in errors if self._is_fatal_config_error(e)]
            if fatal:
                msg = "설정 검증 실패:\n" + "\n".join(f"• {e}" for e in fatal[:8])
                messagebox.showerror("설정 검증 실패", msg, parent=parent)
                self._log_message(f"❌ 설정 검증 실패: {fatal[0]}")
                return False

            working = config
            last_conflict: Exception | None = None
            for attempt in range(max_conflict_retries + 1):
                expected = working.get("_config_revision")
                try:
                    expected_i = int(expected) if expected is not None else None
                except (TypeError, ValueError):
                    expected_i = None

                try:
                    self.service.config_manager.save_config(
                        working, expected_revision=expected_i
                    )
                    if working is not config:
                        config.clear()
                        config.update(working)
                    if attempt > 0:
                        self._log_message(
                            "☁ 설정 충돌을 병합해 저장했습니다 (백업/다른 작업과 동기화)."
                        )
                    last_conflict = None
                    break
                except ConfigConflictError as e:
                    last_conflict = e
                    if attempt >= max_conflict_retries:
                        break
                    disk = e.disk_config or self.service.config_manager.load_config()
                    merged = self._merge_config_on_conflict(disk, working)
                    try:
                        disk_rev = int(disk.get("_config_revision") or 0)
                    except (TypeError, ValueError):
                        disk_rev = 0
                    merged["_config_revision"] = disk_rev
                    working = merged

            if last_conflict is not None:
                raise last_conflict

            # 항상 service.config 를 디스크와 맞춤 (stale 참조 방지)
            self.service._reload_config()
            if config is not self.service.config:
                config["_config_revision"] = self.service.config.get("_config_revision")
            return True
        except ConfigConflictError as e:
            messagebox.showerror(
                "설정 저장 실패",
                "다른 작업과 설정 충돌이 반복되어 저장하지 못했습니다.\n"
                "잠시 후 다시 시도해 주세요.",
                parent=parent,
            )
            self._log_message(f"❌ 설정 충돌 재시도 한도 초과: {e}")
            return False
        except ConfigSaveError as e:
            messagebox.showerror("설정 저장 실패", str(e), parent=parent)
            self._log_message(f"❌ 설정 저장 실패: {e}")
            return False
        except Exception as e:
            messagebox.showerror("설정 저장 실패", str(e), parent=parent)
            self._log_message(f"❌ 설정 저장 실패: {e}")
            return False

    @staticmethod
    def _is_fatal_config_error(err: str) -> bool:
        """저장을 막을 검증 오류 (경고성 제외)."""
        fatal_markers = (
            "URL은 http://",
            "URL이 비어",
            "타입이 유효하지 않습니다",
            "포트 범위",
            "유효한 정수여야",
            "epub_merge_mode",
            "epub_theme",
            "limit:",
            "font_size:",
            "line_height:",
        )
        return any(m in err for m in fatal_markers)

    @staticmethod
    def _merge_config_on_conflict(disk: dict, memory: dict) -> dict:
        """충돌 시: 디스크 기반 + 메모리 top-level 덮어쓰기, sites는 URL 합집합(메모리 우선)."""
        import copy
        out = copy.deepcopy(disk)
        for key, val in memory.items():
            if key in ("sites", "_config_revision"):
                continue
            out[key] = copy.deepcopy(val)
        mem_sites = memory.get("sites") if isinstance(memory.get("sites"), list) else []
        disk_sites = out.get("sites") if isinstance(out.get("sites"), list) else []
        # memory wins same URL
        out["sites"] = merge_sites(
            disk_sites, mem_sites, remote_wins_same_url=True
        )
        from websync.backup.format import apply_site_tombstones
        from websync.backup.portable_cfg import apply_portable_cfg, get_portable_cfg
        portable = get_portable_cfg(out)
        out["sites"], deleted = apply_site_tombstones(
            out["sites"], portable.get("deleted_sites", [])
        )
        apply_portable_cfg(out, {"deleted_sites": deleted})
        return out

    def _get_log_for_web(self) -> str:
        try:
            content = self.bottom_bar.log_txt.get("1.0", "end-1c")
            if content.strip():
                lines = content.splitlines()
                return "\n".join(lines[-100:])
        except Exception:
            pass
        log_dir = get_log_dir()
        if os.path.isdir(log_dir):
            files = sorted(os.listdir(log_dir), reverse=True)
            if files:
                try:
                    with open(os.path.join(log_dir, files[0]), "r", encoding="utf-8") as f:
                        return "".join(f.readlines()[-100:])
                except Exception:
                    pass
        return ""

    # ------------------------------------------------------------------
    # 설정 동기화 및 윈도우 컨트롤
    # ------------------------------------------------------------------

