from __future__ import annotations

import os
import sys
import hashlib
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from websync.gui.widgets import (
    BG_COLOR, TEXT_BG, SECONDARY_BG, HINT_COLOR, YELLOW_COLOR, GREEN_COLOR, RED_COLOR,
    create_scrollable_frame, create_scrolled_tree, setup_dialog, bind_widget_mousewheel
)
from websync.upload.uploader import X3Uploader, normalize_device_host
from websync.config.exceptions import ConfigSaveError, ConfigLoadError
from websync.i18n import t


class SyncDevicesMixin:
    def _refresh_devices_tree(self):
        for item in self.devices_tree.get_children():
            self.devices_tree.delete(item)
        for idx, dev in enumerate(self.service.config.get("x3_devices", [])):
            self.devices_tree.insert("", "end", iid=str(idx), values=(
                dev.get("name", ""), dev.get("ip", "")
            ))

    def _add_device_popup(self):
        import customtkinter as ctk
        from websync.gui.widgets import COLOR_BG, COLOR_SECONDARY_FG, get_font, make_button

        dialog = ctk.CTkToplevel(self.app.root)
        dialog.title(t("gui.sync.add_device_title"))
        dialog.configure(fg_color=COLOR_BG)
        setup_dialog(dialog, self.app.root, 440, 230)
        frame = ctk.CTkFrame(dialog, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=18, pady=(16, 4))
        frame.columnconfigure(1, weight=1)
        ctk.CTkLabel(frame, text=t("gui.sync.device_name_label"), font=get_font(13)).grid(row=0, column=0, sticky="w", pady=6, padx=(0, 8))
        name_entry = ctk.CTkEntry(frame, font=get_font(12), height=32, placeholder_text=t("gui.sync.device_name_placeholder"))
        name_entry.grid(row=0, column=1, sticky="we", pady=6)
        ctk.CTkLabel(frame, text=t("gui.sync.device_ip_label"), font=get_font(13)).grid(row=1, column=0, sticky="w", pady=6, padx=(0, 8))
        ip_entry = ctk.CTkEntry(frame, font=get_font(12), height=32, placeholder_text=t("gui.sync.ip_placeholder"))
        ip_entry.grid(row=1, column=1, sticky="we", pady=6)
        ctk.CTkLabel(
            frame, text=t("gui.sync.device_add_hint"), font=get_font(11), text_color=COLOR_SECONDARY_FG,
            anchor="w", justify="left", wraplength=380,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))

        def save():
            from websync.upload.uploader import normalize_device_host

            name = name_entry.get().strip()
            ip = normalize_device_host(ip_entry.get())
            if not name or not ip:
                messagebox.showerror(t("dialog.error"), t("gui.sync.name_ip_required"), parent=dialog)
                return
            config = self.service.config
            devices = config.setdefault("x3_devices", [])
            primary = normalize_device_host(config.get("x3_ip") or "")
            if ip == primary:
                messagebox.showwarning(t("gui.sync.duplicate_title"), t("gui.sync.duplicate_primary_ip"), parent=dialog)
                return
            if any(normalize_device_host(d.get("ip")) == ip for d in devices):
                messagebox.showwarning(t("gui.sync.duplicate_title"), t("gui.sync.duplicate_ip"), parent=dialog)
                return
            if name == t("device.default_name") or any(d.get("name") == name for d in devices):
                messagebox.showwarning(t("gui.sync.duplicate_title"), t("gui.sync.duplicate_name"), parent=dialog)
                return
            from websync.upload.device_ids import new_device_id

            devices.append({"name": name, "ip": ip, "id": new_device_id()})
            if not self.app._safe_save_config(config, parent=dialog, reload=True):
                return
            self._refresh_devices_tree()
            dialog.destroy()

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=18, pady=(4, 14))
        make_button(btn_frame, t("gui.sync.save"), save, width=90, bold=True).pack(side="right", padx=(6, 0))
        make_button(btn_frame, t("gui.sync.cancel"), dialog.destroy, kind="secondary", width=80).pack(side="right")
        dialog.bind("<Return>", lambda _e: save())
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        dialog.after(150, name_entry.focus_set)

    def _remove_device(self):
        selected = self.devices_tree.selection()
        if not selected:
            messagebox.showwarning(t("dialog.warning"), t("gui.sync.select_device_to_delete"))
            return
        if not messagebox.askyesno(t("dialog.confirm"), t("gui.sync.confirm_delete_device")):
            return
        config = self.service.config
        devices = config.get("x3_devices", [])
        indices = sorted([int(i) for i in selected], reverse=True)
        for idx in indices:
            if 0 <= idx < len(devices):
                devices.pop(idx)
        config["x3_devices"] = devices
        if not self.app._safe_save_config(config, reload=True):
            return
        self._refresh_devices_tree()

    # ------------------------------------------------------------------
    # 사이트 관리
    # ------------------------------------------------------------------

