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


class DeviceFilesActionsMixin:
    def _delete_selected(self) -> None:
        if self._busy:
            return
        items = self._selected_items()
        if not items:
            messagebox.showwarning(t("dialog.warning"), t("gui.device.select_delete"))
            return
        names = ", ".join(i.get("name", "") for i in items[:5])
        if len(items) > 5:
            names += t("gui.device.and_more", count=len(items) - 5)
        if not messagebox.askyesno(
            t("gui.device.delete_confirm_title"),
            t("gui.device.delete_confirm", count=len(items), names=names),
        ):
            return

        ip = self._selected_ip()
        paths = [i["path"] for i in items]
        self._set_busy(True)
        self.app._log_message(t("gui.device.log_delete_request", ip=ip, count=len(paths)))

        def task():
            err: str | None = None
            try:
                self._make_client().delete_paths(paths, ip=ip)
            except DeviceClientError as e:
                err = str(e)
            self.app.root.after(
                0, lambda ip=ip, count=len(paths), err=err: self._delete_finished(ip, count, err)
            )

        self.app._start_background_task(task, name="device-delete")

    def _delete_finished(self, ip: str, count: int, err: str | None) -> None:
        self._set_busy(False)
        if err:
            self.app._log_message(t("gui.device.log_delete_fail", ip=ip, err=err))
            messagebox.showerror(
                t("gui.device.delete_fail_title"),
                t("gui.device.delete_fail_body", err=err),
            )
            return
        self.app._log_message(t("gui.device.log_delete_ok", ip=ip, count=count))
        self.refresh()

    def _mkdir(self) -> None:
        if self._busy:
            return
        ip = self._selected_ip()
        if not ip:
            messagebox.showwarning(t("dialog.warning"), t("gui.device.select_device"))
            return
        name = simpledialog.askstring(t("gui.device.mkdir_title"), t("gui.device.mkdir_prompt"), parent=self.app.root)
        if not name:
            return
        name = name.strip()
        if not name or "/" in name or "\\" in name:
            messagebox.showerror(t("dialog.error"), t("gui.device.mkdir_bad_name"))
            return

        path = self._current_path
        self._set_busy(True)
        self.app._log_message(t("gui.device.log_mkdir", ip=ip, path=path, name=name))

        def task():
            err: str | None = None
            try:
                self._make_client().mkdir(name, path=path, ip=ip)
            except DeviceClientError as e:
                err = str(e)
            self.app.root.after(
                0, lambda ip=ip, name=name, err=err: self._mkdir_finished(ip, name, err)
            )

        self.app._start_background_task(task, name="device-mkdir")

    def _mkdir_finished(self, ip: str, name: str, err: str | None) -> None:
        self._set_busy(False)
        if err:
            self.app._log_message(t("gui.device.log_mkdir_fail", ip=ip, err=err))
            messagebox.showerror(t("gui.device.mkdir_fail_title"), err)
            return
        self.app._log_message(t("gui.device.log_mkdir_ok", ip=ip, name=name))
        self.refresh()

    def _rename_selected(self) -> None:
        if self._busy:
            return
        items = self._selected_items()
        if len(items) != 1:
            messagebox.showwarning(t("dialog.warning"), t("gui.device.select_one_file"))
            return
        item = items[0]
        if item.get("isDirectory"):
            messagebox.showwarning(
                t("dialog.warning"), t("gui.device.rename_folder_unsupported")
            )
            return
        new_name = simpledialog.askstring(
            t("gui.device.rename_title"),
            t("gui.device.rename_prompt"),
            initialvalue=item.get("name", ""),
            parent=self.app.root,
        )
        if not new_name or new_name.strip() == item.get("name"):
            return
        new_name = new_name.strip()
        if "/" in new_name or "\\" in new_name:
            messagebox.showerror(t("dialog.error"), t("gui.device.rename_bad_name"))
            return

        ip = self._selected_ip()
        self._set_busy(True)
        self.app._log_message(t("gui.device.log_rename", ip=ip, path=item["path"], name=new_name))

        def task():
            err: str | None = None
            try:
                self._make_client().rename(item["path"], new_name, ip=ip)
            except DeviceClientError as e:
                err = str(e)
            self.app.root.after(
                0, lambda ip=ip, err=err: self._op_finished(ip, t("gui.device.op_rename"), err)
            )

        self.app._start_background_task(task, name="device-rename")

    def _move_selected(self) -> None:
        if self._busy:
            return
        items = [i for i in self._selected_items() if not i.get("isDirectory")]
        if not items:
            messagebox.showwarning(
                t("dialog.warning"), t("gui.device.select_move")
            )
            return
        dest = simpledialog.askstring(
            t("gui.device.move_title"),
            t("gui.device.move_prompt"),
            initialvalue="/",
            parent=self.app.root,
        )
        if dest is None:
            return
        dest = normalize_remote_path(dest)
        ip = self._selected_ip()
        self._set_busy(True)
        self.app._log_message(t("gui.device.log_move", ip=ip, count=len(items), dest=dest))

        def task():
            client = self._make_client()
            ok = 0
            errors: list[str] = []
            for item in items:
                try:
                    client.move(item["path"], dest, ip=ip)
                    ok += 1
                except DeviceClientError as e:
                    errors.append(f"{item.get('name')}: {e}")
            self.app.root.after(
                0,
                lambda ip=ip, ok=ok, errors=errors: self._multi_op_finished(
                    ip, t("gui.device.op_move"), ok, errors
                ),
            )

        self.app._start_background_task(task, name="device-move")

    def _op_finished(self, ip: str, label: str, err: str | None) -> None:
        self._set_busy(False)
        if err:
            self.app._log_message(t("gui.device.log_op_failed", ip=ip, label=label, err=err))
            messagebox.showerror(t("gui.device.op_failed_title", label=label), err)
            return
        self.app._log_message(t("gui.device.log_op_ok", ip=ip, label=label))
        self.refresh()

    def _multi_op_finished(
        self, ip: str, label: str, ok: int, errors: list[str]
    ) -> None:
        self._set_busy(False)
        if errors:
            self.app._log_message(
                t("gui.device.log_op_partial", ip=ip, label=label, ok=ok, fail=len(errors))
            )
            messagebox.showwarning(
                t("gui.device.op_result_title", label=label),
                t("gui.device.op_result_body", ok=ok, fail=len(errors), errors="\n".join(errors[:8])),
            )
        else:
            self.app._log_message(t("gui.device.log_op_ok_count", ip=ip, label=label, ok=ok))
        self.refresh()

    # ------------------------------------------------------------------
    # 다운로드 / 업로드
    # ------------------------------------------------------------------

    def _download_selected(self) -> None:
        if self._busy:
            return
        items = [i for i in self._selected_items() if not i.get("isDirectory")]
        if not items:
            messagebox.showwarning(
                t("dialog.warning"), t("gui.device.select_download")
            )
            return

        dest_dir = filedialog.askdirectory(title=t("gui.device.save_folder"))
        if not dest_dir:
            return

        ip = self._selected_ip()
        self._set_busy(True)
        self.app._log_message(t("gui.device.log_download_start", ip=ip, count=len(items), dest=dest_dir))

        def task():
            client = self._make_client()
            ok = 0
            errors: list[str] = []
            for item in items:
                local = os.path.join(dest_dir, item["name"])
                try:
                    client.download(item["path"], local, ip=ip)
                    ok += 1
                except DeviceClientError as e:
                    errors.append(f"{item['name']}: {e}")
            self.app.root.after(
                0,
                lambda ip=ip, ok=ok, errors=errors: self._download_finished(ip, ok, errors),
            )

        self.app._start_background_task(task, name="device-download")

    def _download_finished(self, ip: str, ok: int, errors: list[str]) -> None:
        self._set_busy(False)
        if errors:
            self.app._log_message(
                t("gui.device.log_download_partial", ip=ip, ok=ok, fail=len(errors))
            )
            messagebox.showwarning(
                t("gui.device.download_result_title"),
                t("gui.device.op_result_body", ok=ok, fail=len(errors), errors="\n".join(errors[:8])),
            )
        else:
            self.app._log_message(t("gui.device.log_download_ok", ip=ip, ok=ok))
            messagebox.showinfo(t("gui.device.download_ok_title"), t("gui.device.download_ok", ok=ok))

    def _upload_to_current(self) -> None:
        if self._busy:
            return
        ip = self._selected_ip()
        if not ip:
            messagebox.showwarning(t("dialog.warning"), t("gui.device.select_device"))
            return
        paths = filedialog.askopenfilenames(
            title=t("gui.device.upload_title"),
            filetypes=[
                (t("gui.device.filetype_ebooks"), "*.epub;*.pdf;*.mobi;*.txt"),
                (t("gui.device.filetype_all"), "*.*"),
            ],
        )
        if not paths:
            return

        remote_dir = self._current_path
        client = self._make_client()
        uploader = X3Uploader(ip)
        warn = bool(self.warn_overwrite_var.get())

        # 덮어쓰기 경고 (선택 시)
        if warn:
            collisions = []
            try:
                for p in paths:
                    safe = uploader._sanitize_filename(p)
                    if client.remote_file_exists(remote_dir, safe, ip=ip):
                        collisions.append(safe)
            except DeviceClientError as e:
                if not messagebox.askyesno(
                    t("dialog.confirm"),
                    t("gui.device.list_check_fail", error=e),
                ):
                    return
            if collisions:
                if not messagebox.askyesno(
                    t("gui.device.overwrite_title"),
                    t(
                        "gui.device.overwrite_body",
                        names="\n".join(collisions[:12]),
                        more="\n…" if len(collisions) > 12 else "",
                    ),
                ):
                    return

        self._set_busy(True)
        self.app._log_message(
            t("gui.device.log_upload", ip=ip, count=len(paths), dir=remote_dir)
        )

        def task():
            ok = 0
            errors: list[str] = []
            c = self._make_client()
            for p in paths:
                try:
                    c.upload_to_path(p, remote_dir=remote_dir, ip=ip)
                    ok += 1
                except DeviceClientError as e:
                    errors.append(f"{os.path.basename(p)}: {e}")
            self.app.root.after(
                0,
                lambda ip=ip, ok=ok, errors=errors: self._multi_op_finished(
                    ip, t("gui.device.op_upload"), ok, errors
                ),
            )

        self.app._start_background_task(task, name="device-upload")

    # ------------------------------------------------------------------
    # 오래된 동기화 EPUB 정리
    # ------------------------------------------------------------------
