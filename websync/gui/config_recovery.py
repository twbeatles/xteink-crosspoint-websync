"""Explicit startup recovery; cancel leaves rejected settings untouched."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox

from websync.i18n import t


def offer_config_recovery(manager, error) -> bool:
    root = tk.Tk()
    root.withdraw()
    try:
        backup = f"{manager.config_path}.bak"
        if not messagebox.askyesno(t("config.recovery_title"), t("config.recovery_prompt", error=error), parent=root):
            return False
        source = None
        if os.path.isfile(backup) and messagebox.askyesno(t("config.recovery_title"), t("config.recovery_backup", path=backup), parent=root):
            source = backup
        if source is None:
            source = filedialog.askopenfilename(title=t("config.recovery_choose"), filetypes=[("JSON", "*.json"), ("All files", "*.*")], parent=root)
        if not source:
            return False
        try:
            preserved = manager.restore_config(source)
        except Exception as exc:
            messagebox.showerror(t("config.recovery_title"), str(exc), parent=root)
            return False
        messagebox.showinfo(t("config.recovery_title"), t("config.recovery_done", path=preserved or ""), parent=root)
        return True
    finally:
        root.destroy()
