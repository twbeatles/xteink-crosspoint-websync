from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from websync.gui.widgets import (
    RED_COLOR, GREEN_COLOR, ACCENT_COLOR, HINT_COLOR, BG_COLOR,
    create_scrollable_frame, setup_dialog
)
from websync.core.paths import resolve_path
from websync.core.logger import get_log_dir
from websync.servers.opds import OPDSServer
from websync.servers.web_dashboard import WebDashboard
from websync.watch.calibre import CalibreWatcher


class SettingsWatchMixin:
    def _remember_watch_file(self, fpath: str) -> None:
        path = os.path.abspath(fpath)

        def apply(cfg: dict) -> None:
            watch = cfg.setdefault("calibre_watch", {})
            pending = watch.get("pending_files")
            pending = list(pending) if isinstance(pending, list) else []
            if path not in pending:
                pending.append(path)
            watch["pending_files"] = pending

        self.service.config = self.service.config_manager.update_config(apply)

    def _forget_watch_file(self, fpath: str) -> None:
        path = os.path.abspath(fpath)

        def apply(cfg: dict) -> None:
            watch = cfg.setdefault("calibre_watch", {})
            pending = watch.get("pending_files")
            if isinstance(pending, list):
                watch["pending_files"] = [p for p in pending if os.path.abspath(p) != path]

        self.service.config = self.service.config_manager.update_config(apply)

    def _stop_watch_worker(self, wait_timeout: float = 0.0) -> None:
        watch_queue = getattr(self, "_watch_queue", None)
        worker = getattr(self, "_watch_worker_thread", None)
        self._watch_queue = None
        self._watch_worker_thread = None
        if watch_queue is not None:
            watch_queue.put(None)
        if worker and worker is not threading.current_thread() and wait_timeout > 0:
            worker.join(timeout=wait_timeout)

    def _start_watch_if_enabled(self) -> None:
        watch = self.service.config.get("calibre_watch", {})
        if isinstance(watch, dict) and watch.get("enabled"):
            self._toggle_watch()

    def _toggle_watch(self):
        if self.app._calibre_watcher and self.app._calibre_watcher.is_running:
            self.app._calibre_watcher.stop()
            self.app._calibre_watcher = None
            self._stop_watch_worker()
            def disable(cfg: dict) -> None:
                cfg.setdefault("calibre_watch", {})["enabled"] = False
            self.service.config = self.service.config_manager.update_config(disable)
            self.watch_start_btn.configure(text="▶ 감시 시작")
            self.watch_status_label.configure(text="감시 중지됨", text_color=RED_COLOR)
        else:
            watch_dir = self.watch_dir_entry.get().strip()
            if not watch_dir or not os.path.isdir(watch_dir):
                messagebox.showerror("오류", "유효한 감시 폴더를 선택해 주세요.")
                return

            # 단일 워커 스레드 + 큐 기반 직렬 처리 (스레드 누적 방지)
            watch_queue: queue.Queue = queue.Queue()
            self._watch_queue = watch_queue

            def _upload_worker():
                """큐에서 파일을 순차적으로 꺼내 업로드. None sentinel 시 종료."""
                while True:
                    fpath = watch_queue.get()
                    if fpath is None:
                        break
                    try:
                        if self._upload_single_file(fpath):
                            self._forget_watch_file(fpath)
                    except Exception as e:
                        name = os.path.basename(fpath)
                        self.app.root.after(
                            0, lambda m=e, n=name: self.app._log_message(f"❌ Watch 업로드 오류 ({n}): {m}")
                        )
                    finally:
                        watch_queue.task_done()

            def on_new_file(fpath: str):
                name = os.path.basename(fpath)
                self._remember_watch_file(fpath)
                self.app.root.after(
                    0,
                    lambda n=name: self.app._log_message(f"👁 새 파일 감지: {n} → 전송 큐 대기 중"),
                )
                watch_queue.put(fpath)

            # 워커 스레드 시작
            self._watch_worker_thread = threading.Thread(target=_upload_worker, daemon=True)
            self._watch_worker_thread.start()

            self.app._calibre_watcher = CalibreWatcher(watch_dir, on_new_file)
            if self.app._calibre_watcher.start():
                self.watch_start_btn.configure(text="■ 감시 중지")
                self.watch_status_label.configure(text=f"✅ 감시 중: {watch_dir}", text_color=GREEN_COLOR)
                self.app._log_message(f"👁 Calibre Watch 시작: {watch_dir}")
                def enable(cfg: dict) -> None:
                    watch = cfg.setdefault("calibre_watch", {})
                    watch.update({"enabled": True, "watch_dir": watch_dir})
                self.service.config = self.service.config_manager.update_config(enable)
                pending = self.service.config.get("calibre_watch", {}).get("pending_files", [])
                for path in pending if isinstance(pending, list) else []:
                    if os.path.isfile(path):
                        watch_queue.put(path)
                    else:
                        self._forget_watch_file(path)
            else:
                self._stop_watch_worker()
                self.app._calibre_watcher = None
                messagebox.showerror("오류", "파일 감시 시작 실패. watchdog 패키지가 설치되어 있는지 확인하세요.")

    def _upload_single_file(self, fpath: str) -> bool:
        """Watch 감지 파일 1건을 파이프라인 락 획득 후 업로드 (타임아웃 30초)."""
        pipeline_acquired = False
        process_acquired = False
        try:
            pipeline_acquired = self.service._pipeline_lock.acquire(blocking=True, timeout=30.0)
            if not pipeline_acquired:
                self.app.root.after(
                    0,
                    lambda: self.app._log_message(
                        f"⚠️ 자동 전송 대기 타임아웃 (30초 초과, 파이프라인 락): {os.path.basename(fpath)} — 스킵"
                    ),
                )
                return False
            process_acquired = self.service._process_lock.acquire(blocking=True, timeout=30.0)
            if not process_acquired:
                self.app.root.after(
                    0,
                    lambda: self.app._log_message(
                        f"⚠️ 자동 전송 대기 타임아웃 (30초 초과, 프로세스 락): {os.path.basename(fpath)} — 스킵"
                    ),
                )
                return False

            self.app.root.after(
                0, lambda: self.app._log_message(f"📡 자동 전송 시작: {os.path.basename(fpath)}")
            )
            results = self.app._make_uploader().upload_to_targets(fpath)
            all_ok, any_ok, summary = self.app._summarize_upload_results(results)
            if all_ok:
                msg = f"🎉 자동 전송 성공: {os.path.basename(fpath)} ({summary})"
            elif any_ok:
                msg = f"⚠️ 자동 부분 전송: {os.path.basename(fpath)} ({summary})"
            else:
                msg = f"❌ 자동 전송 실패: {os.path.basename(fpath)} ({summary})"
            self.app.root.after(0, lambda m=msg: self.app._log_message(m))
            return all_ok
        finally:
            if process_acquired:
                self.service._process_lock.release()
            if pipeline_acquired:
                self.service._pipeline_lock.release()

    def _browse_watch_dir(self):
        d = filedialog.askdirectory(title="감시할 Calibre 라이브러리 폴더 선택")
        if d:
            self.watch_dir_entry.delete(0, tk.END)
            self.watch_dir_entry.insert(0, d)
            self.app._save_ui_settings()

