from __future__ import annotations

import copy
import os
import threading
import tkinter as tk
from tkinter import messagebox, filedialog

from websync.gui.widgets import RED_COLOR, GREEN_COLOR
from websync.watch.calibre import CalibreWatcher, STABLE_SIZE_CHECKS, STABLE_CHECK_INTERVAL
from websync.watch.retry import WatchRetryQueue
from websync.upload.uploader import X3Uploader
from websync.i18n import t


class SettingsWatchMixin:
    def _save_watch_job(self, fpath: str, state: dict | None) -> None:
        path = os.path.abspath(fpath)

        def apply(cfg: dict) -> None:
            watch = cfg.setdefault("calibre_watch", {})
            pending = list(watch.get("pending_files", []))
            jobs = watch.setdefault("pending_jobs", {})
            if state is None:
                pending = [p for p in pending if os.path.abspath(p) != path]
                jobs.pop(path, None)
            else:
                if path not in pending:
                    pending.append(path)
                jobs[path] = copy.deepcopy(state)
            watch["pending_files"] = pending

        self.service.config = self.service.config_manager.update_config(apply)

    def _remember_watch_file(self, fpath: str) -> None:
        self._save_watch_job(fpath, {})

    def _forget_watch_file(self, fpath: str) -> None:
        self._save_watch_job(fpath, None)

    def _stop_watch_worker(self, wait_timeout: float = 0.0) -> None:
        retry = getattr(self, "_watch_retry", None)
        worker = getattr(self, "_watch_worker_thread", None)
        if retry is not None:
            retry.stop()
        if worker and worker is not threading.current_thread() and wait_timeout > 0:
            worker.join(timeout=wait_timeout)

    def _start_watch_if_enabled(self) -> None:
        watch = self.service.config.get("calibre_watch", {})
        if isinstance(watch, dict) and watch.get("enabled"):
            self._toggle_watch()

    def _make_watch_uploader(self):
        # Workers read only the saved configuration; never query Tk entries.
        config = self.service.config_manager.load_config()
        return X3Uploader(
            config.get("x3_ip", ""), config.get("x3_devices", []),
            remote_dir=(config.get("device_files") or {}).get("default_upload_path", "/"),
            primary_device_id=config.get("x3_primary_device_id", ""),
            primary_alias_ids=config.get("x3_primary_device_alias_ids", []),
        )

    def _toggle_watch(self):
        if self.app._calibre_watcher and self.app._calibre_watcher.is_running:
            self.app._calibre_watcher.stop()
            self.app._calibre_watcher = None
            self._stop_watch_worker()
            def disable(cfg: dict) -> None:
                cfg.setdefault("calibre_watch", {})["enabled"] = False
            self.service.config = self.service.config_manager.update_config(disable)
            self.watch_start_btn.configure(text=t("gui.settings.watch.start_btn"))
            self.watch_status_label.configure(text=t("gui.settings.watch.stopped"), text_color=RED_COLOR)
            return
        # A stopped worker can still be finishing its bounded network operation.
        # Never run a second worker against the same durable queue.
        worker = getattr(self, "_watch_worker_thread", None)
        if worker is not None and worker.is_alive():
            return
        watch_dir = self.watch_dir_entry.get().strip()
        if not watch_dir or not os.path.isdir(watch_dir):
            messagebox.showerror(t("dialog.error"), t("gui.settings.watch.invalid_dir"))
            return
        watch = self.service.config.get("calibre_watch", {})
        retry = WatchRetryQueue(
            self._make_watch_uploader, self._attempt_watch_upload, self._save_watch_job,
            pending_files=watch.get("pending_files", []),
            pending_jobs=watch.get("pending_jobs", {}),
            on_error=lambda path, error: self.service.logger.warning(
                t("gui.settings.watch.log_upload_error", name=os.path.basename(path), error=error)
            ),
        )
        self._watch_retry = retry
        self.app._calibre_watcher = CalibreWatcher(watch_dir, retry.enqueue, on_pending_file=retry.retain)
        if not self.app._calibre_watcher.start():
            retry.stop()
            self.app._calibre_watcher = None
            messagebox.showerror(t("dialog.error"), t("gui.settings.watch.start_fail"))
            return
        def enable(cfg: dict) -> None:
            cfg.setdefault("calibre_watch", {}).update({"enabled": True, "watch_dir": watch_dir})
        try:
            self.service.config = self.service.config_manager.update_config(enable)
        except Exception:
            self.app._calibre_watcher.stop()
            self.app._calibre_watcher = None
            retry.stop()
            raise
        self._watch_worker_thread = self.app._make_background_thread(retry.run, name="watch-upload")
        self._watch_worker_thread.start()
        self.watch_start_btn.configure(text=t("gui.settings.watch.stop_btn"))
        self.watch_status_label.configure(text=t("gui.settings.watch.watching", dir=watch_dir), text_color=GREEN_COLOR)
        self.app._log_message(t("gui.settings.watch.log_start", dir=watch_dir))

    def _attempt_watch_upload(self, fpath, uploader, only_ips, stop_event):
        acquired = []
        try:
            for lock in (self.service._pipeline_lock, self.service._process_lock):
                while not stop_event.is_set() and not self.service._shutting_down:
                    if lock.acquire(blocking=True, timeout=0.1):
                        acquired.append(lock)
                        break
                else:
                    return {}
            if stop_event.is_set() or self.service._shutting_down:
                return {}
            # Acquiring the shared locks can take minutes. The queue's earlier
            # stability sample is no longer sufficient after that wait.
            sample = os.stat(fpath)
            for _ in range(STABLE_SIZE_CHECKS):
                if stop_event.wait(STABLE_CHECK_INTERVAL) or self.service._shutting_down:
                    return {}
                current = os.stat(fpath)
                if (current.st_size, current.st_mtime_ns) != (sample.st_size, sample.st_mtime_ns):
                    return {}
            results = uploader.upload_to_targets(fpath, only_ips=only_ips)
            key = "log_upload_ok" if results and all(results.values()) else "log_upload_fail"
            self.service.logger.info(t("gui.settings.watch." + key, name=os.path.basename(fpath), summary=str(results)))
            return results
        finally:
            for lock in reversed(acquired):
                lock.release()

    def _upload_single_file(self, fpath: str) -> bool:
        # Compatibility entry point; normal Watch calls use the durable retry queue.
        uploader = self._make_watch_uploader()
        results = self._attempt_watch_upload(fpath, uploader, None, threading.Event())
        return bool(results) and all(results.values())

    def _browse_watch_dir(self):
        d = filedialog.askdirectory(title=t("gui.settings.watch.browse_title"))
        if d:
            self.watch_dir_entry.delete(0, tk.END)
            self.watch_dir_entry.insert(0, d)
            self.app._save_ui_settings()

