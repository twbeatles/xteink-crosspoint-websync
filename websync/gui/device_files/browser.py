from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from websync.gui.widgets import (
    COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING, COLOR_SECONDARY_FG,
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


class DeviceFilesBrowserMixin:
    def _make_client(self) -> X3DeviceClient:
        config = self.service.config
        ip = (config.get("x3_ip") or "").strip()
        if not ip and hasattr(self.app, "tab_sync"):
            ip = self.app.tab_sync.ip_entry.get().strip()
        return X3DeviceClient(ip, config.get("x3_devices", []))

    def refresh_device_list(self) -> None:
        """설정에 등록된 기기 콤보 갱신."""
        client = self._make_client()
        targets = client._build_target_list()
        self._device_choices = [(f"{tgt['name']} ({tgt['ip']})", tgt["ip"]) for tgt in targets]
        labels = [label for label, _ in self._device_choices]
        prev_ip = self._selected_ip()
        if hasattr(self.device_cb, "configure"):
            self.device_cb.configure(values=labels)
        else:
            self.device_cb["values"] = labels

        if not labels:
            self.device_cb.set("")
            self.status_label.configure(text=t("gui.device.no_devices"), text_color=COLOR_DANGER[0])
            return
        idx = 0
        if prev_ip:
            for i, (_, ip) in enumerate(self._device_choices):
                if ip == prev_ip:
                    idx = i
                    break
        if labels and idx < len(labels):
            self.device_cb.set(labels[idx])

    def _selected_ip(self) -> str:
        sel = self.device_cb.get()
        for label, ip in self._device_choices:
            if label == sel:
                return ip
        if self._device_choices:
            return self._device_choices[0][1]
        return ""

    def _on_device_changed(self) -> None:
        df = self._device_files_conf()
        browse = normalize_remote_path(df.get("default_browse_path", "/"))
        self._current_path = browse
        self.path_var.set(browse)
        self.refresh()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for btn in self._action_buttons:
            btn.configure(state=state)
        self.device_cb.configure(state="disabled" if busy else "normal")

    # ------------------------------------------------------------------
    # 목록 로드
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        if self._busy:
            return
        self.refresh_device_list()
        ip = self._selected_ip()
        if not ip:
            messagebox.showwarning(
                t("dialog.warning"), t("gui.device.no_devices_warn")
            )
            return

        path = normalize_remote_path(self.path_var.get() or self._current_path)
        self._current_path = path
        self.path_var.set(path)
        self._set_busy(True)
        self.status_label.configure(text=t("gui.device.loading"), text_color=COLOR_WARNING[0])
        self.app._log_message(t("gui.device.log_list_request", ip=ip, path=path))

        def task():
            client = self._make_client()
            status_text = ""
            status_ok = False
            err: str | None = None
            items: list[dict] = []
            try:
                try:
                    st = client.get_status(ip)
                    status_text = X3DeviceClient.format_status_summary(st)
                    status_ok = True
                except DeviceClientError as e:
                    status_text = t("gui.device.status_fail", error=e)
                items = client.list_files(path, ip=ip)
            except DeviceClientError as e:
                err = str(e)
            self.app.root.after(
                0,
                lambda ip=ip, path=path, items=items, status_text=status_text, status_ok=status_ok, err=err: self._refresh_finished(
                    ip, path, items, status_text, status_ok, err
                ),
            )

        threading.Thread(target=task, daemon=True).start()

    def _refresh_finished(
        self,
        ip: str,
        path: str,
        items: list[dict],
        status_text: str,
        status_ok: bool,
        err: str | None,
    ) -> None:
        self._set_busy(False)
        if err:
            self.status_label.configure(text=t("gui.device.connect_fail"), text_color=COLOR_DANGER[0])
            self._all_items = []
            self._fill_tree([])
            self.summary_label.configure(text="")
            self.app._log_message(t("gui.device.log_list_fail", ip=ip, err=err))
            messagebox.showerror(
                t("gui.device.list_fail_title"),
                t("gui.device.list_fail_body", ip=ip, err=err),
            )
            return

        self._current_path = path
        self.path_var.set(path)
        self._all_items = items
        self._apply_filter_to_tree()
        if status_ok:
            self.status_label.configure(text=status_text, text_color=COLOR_SUCCESS[0])
        else:
            self.status_label.configure(
                text=status_text or t("gui.device.connected_no_status"), text_color=COLOR_WARNING[0]
            )
        self.app._log_message(t("gui.device.log_list_ok", ip=ip, path=path, count=len(items)))

    def _apply_filter_to_tree(self) -> None:
        q = (self.filter_var.get() or "").strip().lower()
        epub_only = self.epub_only_var.get()
        filtered: list[dict] = []
        for item in self._all_items:
            if epub_only and not item.get("isDirectory") and not item.get("isEpub"):
                continue
            if q and q not in (item.get("name") or "").lower():
                continue
            filtered.append(item)
        self._fill_tree(filtered)

        file_count = sum(1 for i in filtered if not i.get("isDirectory"))
        dir_count = sum(1 for i in filtered if i.get("isDirectory"))
        total_size = sum(int(i.get("size") or 0) for i in filtered if not i.get("isDirectory"))
        self.summary_label.configure(
            text=t("gui.device.summary", dirs=dir_count, files=file_count, size=format_file_size(total_size))
        )

    def _fill_tree(self, items: list[dict]) -> None:
        for child in self.file_tree.get_children():
            self.file_tree.delete(child)
        self._items_by_iid.clear()
        for idx, item in enumerate(items):
            iid = str(idx)
            self._items_by_iid[iid] = item
            if item.get("isDirectory"):
                kind = t("gui.device.kind_folder")
                size_s = "-"
            elif item.get("isEpub"):
                kind = t("gui.device.kind_epub")
                size_s = format_file_size(item.get("size"))
            else:
                kind = t("gui.device.kind_file")
                size_s = format_file_size(item.get("size"))
            self.file_tree.insert(
                "", "end", iid=iid, values=(kind, item.get("name", ""), size_s)
            )

    # ------------------------------------------------------------------
    # 탐색
    # ------------------------------------------------------------------

    def _go_to_path(self) -> None:
        self.path_var.set(normalize_remote_path(self.path_var.get()))
        self.refresh()

    def _go_parent(self) -> None:
        parent = parent_remote_path(self._current_path)
        self.path_var.set(parent)
        self.refresh()

    def _on_double_click(self, _event=None) -> None:
        selected = self.file_tree.selection()
        if not selected:
            return
        item = self._items_by_iid.get(selected[0])
        if not item:
            return
        if item.get("isDirectory"):
            self.path_var.set(item["path"])
            self.refresh()

    def _selected_items(self) -> list[dict]:
        result = []
        for iid in self.file_tree.selection():
            item = self._items_by_iid.get(iid)
            if item:
                result.append(item)
        return result

    def _cleanup_days(self) -> int:
        try:
            return max(1, int(self.cleanup_days_var.get()))
        except (TypeError, ValueError):
            return 14

    # ------------------------------------------------------------------
    # 삭제 / 폴더 / 이름변경 / 이동
    # ------------------------------------------------------------------
