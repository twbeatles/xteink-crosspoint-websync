from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from websync.gui.widgets import (
    HINT_COLOR,
    YELLOW_COLOR,
    GREEN_COLOR,
    RED_COLOR,
    create_scrollable_frame,
    create_scrolled_tree,
)
from websync.upload.device_client import (
    X3DeviceClient,
    DeviceClientError,
    normalize_remote_path,
    parent_remote_path,
    format_file_size,
    filter_old_sync_epubs,
)
from websync.upload.uploader import X3Uploader, normalize_upload_remote_dir
from websync.i18n import t


class DeviceFilesCleanupMixin:
    def _old_candidates(self) -> list[dict]:
        days = self._cleanup_days()
        return filter_old_sync_epubs(self._all_items, days)

    def _select_old_sync_epubs(self) -> None:
        candidates = self._old_candidates()
        if not candidates:
            messagebox.showinfo(
                t("gui.device.no_candidates_title"),
                t("gui.device.no_candidates_select", days=self._cleanup_days()),
            )
            return
        # 필터 해제 후 트리에서 선택
        self.filter_var.set("")
        self.epub_only_var.set(False)
        self._apply_filter_to_tree()
        self.file_tree.selection_remove(self.file_tree.selection())
        path_set = {c["path"] for c in candidates}
        to_select = []
        for iid, item in self._items_by_iid.items():
            if item.get("path") in path_set:
                to_select.append(iid)
        if to_select:
            self.file_tree.selection_set(to_select)
            self.file_tree.see(to_select[0])
        self.app._log_message(
            t("gui.device.log_select_old", count=len(candidates), days=self._cleanup_days())
        )

    def _cleanup_old_sync_epubs(self) -> None:
        if self._busy:
            return
        candidates = self._old_candidates()
        if not candidates:
            messagebox.showinfo(
                t("gui.device.no_candidates_title"),
                t("gui.device.no_candidates_cleanup", days=self._cleanup_days()),
            )
            return
        preview = "\n".join(
            f"· {c.get('name')} ({c.get('sync_date', '?')})" for c in candidates[:15]
        )
        if len(candidates) > 15:
            preview += t("gui.device.and_more_nl", count=len(candidates) - 15)
        if not messagebox.askyesno(
            t("gui.device.cleanup_title_dialog"),
            t(
                "gui.device.cleanup_confirm",
                days=self._cleanup_days(),
                count=len(candidates),
                preview=preview,
            ),
        ):
            return

        # 설정 일수 저장
        self._save_device_files_settings()

        ip = self._selected_ip()
        paths = [c["path"] for c in candidates]
        self._set_busy(True)
        self.app._log_message(t("gui.device.log_cleanup", ip=ip, count=len(paths)))

        def task():
            err: str | None = None
            try:
                self._make_client().delete_paths(paths, ip=ip)
            except DeviceClientError as e:
                err = str(e)
            self.app.root.after(
                0, lambda ip=ip, count=len(paths), err=err: self._delete_finished(ip, count, err)
            )

        self.app._start_background_task(task, name="device-cleanup")
