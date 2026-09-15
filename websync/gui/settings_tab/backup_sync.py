"""공유 데이터 폴더 (OneDrive 등) 설정 UI (CustomTkinter 카드 기반)."""
from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import customtkinter as ctk

from websync.backup.portable_cfg import (
    HISTORY_MODE_GLOBAL_URL,
    HISTORY_MODE_PER_DEVICE,
    apply_portable_cfg,
    get_portable_cfg,
    normalize_history_mode,
)
from websync.gui.widgets import (
    CardFrame, COLOR_CARD_BG, COLOR_FG, COLOR_SECONDARY_FG, COLOR_ACCENT,
    COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING, get_font
)
from websync.i18n import t


def _history_mode_labels() -> dict[str, str]:
    return {
        HISTORY_MODE_PER_DEVICE: t("gui.settings.backup.mode_per_device"),
        HISTORY_MODE_GLOBAL_URL: t("gui.settings.backup.mode_global_url"),
    }


def _label_to_mode() -> dict[str, str]:
    return {v: k for k, v in _history_mode_labels().items()}


class SettingsBackupSyncMixin:
    def _build_backup_sync_section(self, body) -> None:
        card = CardFrame(body, title=t("gui.settings.backup.card_title"), subtitle=t("gui.settings.backup.card_sub"))
        card.pack(fill="x", padx=8, pady=6)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=10)
        inner.columnconfigure(1, weight=1)

        ctk.CTkLabel(
            inner,
            text=t("gui.settings.backup.hint"),
            font=get_font(12),
            text_color=COLOR_SECONDARY_FG,
            justify="left",
        ).grid(row=0, column=0, columnspan=4, padx=4, pady=(0, 6), sticky="w")

        self.backup_enabled_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            inner,
            text=t("gui.settings.backup.enable"),
            font=get_font(12),
            variable=self.backup_enabled_var,
            command=self._save_backup_sync_settings,
        ).grid(row=1, column=0, columnspan=2, padx=4, pady=4, sticky="w")

        ctk.CTkLabel(inner, text=t("gui.settings.backup.folder_label"), font=get_font(13)).grid(row=2, column=0, padx=(0, 6), pady=6, sticky="w")
        self.backup_folder_entry = ctk.CTkEntry(inner, font=get_font(12), height=34)
        self.backup_folder_entry.grid(row=2, column=1, padx=4, pady=6, sticky="we")
        ctk.CTkButton(inner, text=t("gui.settings.backup.browse_btn"), font=get_font(12), width=90, height=34, command=self._browse_backup_folder).grid(
            row=2, column=2, padx=4, pady=6
        )
        ctk.CTkButton(inner, text=t("gui.settings.backup.open_btn"), font=get_font(12), width=90, height=34, fg_color=("#e9ecef", "#343a40"), text_color=COLOR_FG, command=self._open_backup_folder).grid(
            row=2, column=3, padx=4, pady=6
        )
        self.app._bind_autosave(self.backup_folder_entry)

        self.backup_include_history_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            inner,
            text=t("gui.settings.backup.include_history"),
            font=get_font(12),
            variable=self.backup_include_history_var,
            command=self._save_backup_sync_settings,
        ).grid(row=3, column=0, columnspan=2, padx=4, pady=2, sticky="w")

        self.backup_auto_import_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            inner,
            text=t("gui.settings.backup.auto_import"),
            font=get_font(12),
            variable=self.backup_auto_import_var,
            command=self._save_backup_sync_settings,
        ).grid(row=4, column=0, columnspan=2, padx=4, pady=2, sticky="w")

        self.backup_auto_export_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            inner,
            text=t("gui.settings.backup.auto_export"),
            font=get_font(12),
            variable=self.backup_auto_export_var,
            command=self._save_backup_sync_settings,
        ).grid(row=5, column=0, columnspan=2, padx=4, pady=2, sticky="w")

        ctk.CTkLabel(inner, text=t("gui.settings.backup.mode_label"), font=get_font(13)).grid(row=6, column=0, padx=(0, 6), pady=6, sticky="w")
        mode_labels = _history_mode_labels()
        self.backup_history_mode_cb = ctk.CTkOptionMenu(
            inner,
            values=list(mode_labels.values()),
            font=get_font(12),
            width=340,
            command=lambda _v: self._save_backup_sync_settings()
        )
        self.backup_history_mode_cb.set(mode_labels[HISTORY_MODE_PER_DEVICE])
        self.backup_history_mode_cb.grid(row=6, column=1, columnspan=2, padx=4, pady=6, sticky="w")

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkButton(
            btn_row,
            text=t("gui.settings.backup.sync_now"),
            font=get_font(13, "bold"),
            fg_color=COLOR_ACCENT[0],
            hover_color=COLOR_ACCENT[1],
            height=38,
            command=self._run_backup_sync_now,
        ).pack(side="left", padx=4)

        self.backup_status_label = ctk.CTkLabel(
            btn_row,
            text="",
            font=get_font(12),
            text_color=COLOR_SECONDARY_FG,
        )
        self.backup_status_label.pack(side="left", padx=10)

    def _browse_backup_folder(self):
        d = filedialog.askdirectory(title=t("gui.settings.backup.browse_title"))
        if d:
            self.backup_folder_entry.delete(0, tk.END)
            self.backup_folder_entry.insert(0, d)
            self._save_backup_sync_settings()

    def _open_backup_folder(self):
        folder = self.backup_folder_entry.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning(t("dialog.warning"), t("gui.settings.backup.bad_folder"))
            return
        try:
            if os.name == "nt":
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", folder])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            messagebox.showerror(t("dialog.error"), t("gui.settings.backup.open_fail", error=e))

    def _collect_backup_sync_into_config(self, config: dict) -> None:
        mode_label = ""
        if hasattr(self, "backup_history_mode_cb"):
            mode_label = self.backup_history_mode_cb.get()
        mode = _label_to_mode().get(mode_label, HISTORY_MODE_PER_DEVICE)
        apply_portable_cfg(
            config,
            {
                "enabled": bool(self.backup_enabled_var.get()),
                "folder": self.backup_folder_entry.get().strip(),
                "include_history": bool(self.backup_include_history_var.get()),
                "auto_import_on_start": bool(self.backup_auto_import_var.get()),
                "auto_export": bool(self.backup_auto_export_var.get()),
                "history_mode": normalize_history_mode(mode),
            },
        )

    def _save_backup_sync_settings(self):
        config = self.service.config
        self._collect_backup_sync_into_config(config)
        if not self.app._safe_save_config(config, reload=True):
            return
        self._refresh_backup_status_label()
        self.app._log_message(t("gui.settings.backup.log_saved"))

    def _load_backup_sync_from_config(self, config: dict) -> None:
        bs = get_portable_cfg(config)
        self.backup_enabled_var.set(bool(bs.get("enabled", False)))
        self.backup_folder_entry.delete(0, tk.END)
        self.backup_folder_entry.insert(0, bs.get("folder", "") or "")
        self.backup_include_history_var.set(bool(bs.get("include_history", True)))
        self.backup_auto_import_var.set(bool(bs.get("auto_import_on_start", True)))
        self.backup_auto_export_var.set(bool(bs.get("auto_export", True)))
        m = normalize_history_mode(bs.get("history_mode"))
        labels = _history_mode_labels()
        label = labels.get(m, labels[HISTORY_MODE_PER_DEVICE])
        if hasattr(self, "backup_history_mode_cb"):
            self.backup_history_mode_cb.set(label)
        self._refresh_backup_status_label(config)

    def _refresh_backup_status_label(self, config: dict | None = None) -> None:
        cfg = config or self.service.config
        bs = get_portable_cfg(cfg)
        hm = normalize_history_mode(bs.get("history_mode"))
        mode_label = t("gui.settings.backup.mode_short_device") if hm == HISTORY_MODE_PER_DEVICE else t("gui.settings.backup.mode_short_global")
        last = bs.get("last_sync_at") or ""

        if bs.get("enabled") and last:
            text = t("gui.settings.backup.status_last", last=last, mode=mode_label)
            color = COLOR_SUCCESS[0]
        elif bs.get("enabled") and bs.get("folder"):
            text = t("gui.settings.backup.status_enabled", mode=mode_label)
            color = COLOR_ACCENT[0]
        else:
            text = t("gui.settings.backup.status_off")
            color = COLOR_SECONDARY_FG
        self.backup_status_label.configure(text=text, text_color=color)

    def _run_backup_sync_now(self):
        self._save_backup_sync_settings()
        config = self.service.config
        bs = get_portable_cfg(config)
        if not (bs.get("folder") or "").strip():
            messagebox.showwarning(t("gui.settings.backup.folder_needed_title"), t("gui.settings.backup.folder_needed"))
            return

        self.backup_status_label.configure(text=t("gui.settings.backup.syncing"), text_color=COLOR_ACCENT[0])
        self.app._log_message(t("gui.settings.backup.log_sync"))

        def task():
            try:
                result = self.service.run_backup_sync_now(
                    log_callback=self.app._make_log_callback()
                )
                ok = bool(result.get("ok"))
                pull = result.get("pull") or {}
                push = result.get("push") or {}
                msg = f"{pull.get('message', '')} / {push.get('message', '')}".strip(" /")

                def done():
                    self.service._reload_config()
                    self._refresh_backup_status_label()
                    try:
                        self.app.tab_sync._refresh_site_tree()
                        self.app.tab_history._refresh_history()
                    except Exception:
                        pass
                    if ok:
                        messagebox.showinfo(t("gui.settings.backup.sync_ok_title"), msg or t("gui.settings.backup.sync_ok"))
                    else:
                        messagebox.showerror(
                            t("gui.settings.backup.sync_fail_title"),
                            msg or t("gui.settings.backup.sync_fail"),
                        )
                        self.backup_status_label.configure(
                            text=msg or t("gui.settings.backup.sync_fail"), text_color=COLOR_DANGER[0]
                        )

                self.app.root.after(0, done)
            except Exception as e:
                def err():
                    messagebox.showerror(t("gui.settings.backup.sync_error_title"), str(e))
                    self.backup_status_label.configure(text=str(e), text_color=COLOR_DANGER[0])

                self.app.root.after(0, err)

        threading.Thread(target=task, daemon=True).start()
