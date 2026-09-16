from __future__ import annotations

from tkinter import messagebox, filedialog

from websync.i18n import t


class SyncSitesMixin:
    def _refresh_site_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for idx, site in enumerate(self.service.config.get("sites", [])):
            self.tree.insert("", "end", iid=str(idx), values=(
                site.get("name"), site.get("type", "css").upper(),
                "V" if site.get("enabled", True) else "-",
                site.get("url")
            ))

    def _toggle_site_enabled(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning(t("dialog.warning"), t("gui.sync.select_target"))
            return
        config = self.service.config
        idx = int(selected[0])
        config["sites"][idx]["enabled"] = not config["sites"][idx].get("enabled", True)
        from websync.backup.format import now_iso
        config["sites"][idx]["_sync_updated_at"] = now_iso()
        if not self.app._safe_save_config(config):
            return
        self._refresh_site_tree()
        self.service.schedule_backup_push()

    def _delete_site(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning(t("dialog.warning"), t("gui.sync.select_to_delete"))
            return
        if not messagebox.askyesno(t("dialog.confirm"), t("gui.sync.confirm_delete")):
            return
        from websync.backup.format import merge_site_tombstones, now_iso
        from websync.backup.portable_cfg import apply_portable_cfg, get_portable_cfg

        config = self.service.config
        removed = config["sites"].pop(int(selected[0]))
        url = (removed.get("url") or "").strip().lower()
        portable = get_portable_cfg(config)
        portable["deleted_sites"] = merge_site_tombstones(
            portable.get("deleted_sites", []),
            [{"url": url, "deleted_at": now_iso()}] if url else [],
        )
        apply_portable_cfg(config, portable)
        if not self.app._safe_save_config(config):
            return
        self._refresh_site_tree()
        self.service.schedule_backup_push()

    def _add_site_popup(self):
        self._open_site_dialog(t("gui.sync.dialog_add_title"), None)

    def _edit_site_popup(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning(t("dialog.warning"), t("gui.sync.select_to_edit"))
            return
        idx = int(selected[0])
        self._open_site_dialog(t("gui.sync.dialog_edit_title"), idx, self.service.config["sites"][idx])

    # ------------------------------------------------------------------
    # M5: Import / Export 구현부
    # ------------------------------------------------------------------

    def _export_sites_action(self):
        selected = self.tree.selection()
        # 선택된 인덱스 계산
        indices = [int(i) for i in selected] if selected else None
        
        file_path = filedialog.asksaveasfilename(
            title=t("gui.sync.export_title"),
            defaultextension=".json",
            filetypes=[("JSON", "*.json")]
        )
        if not file_path:
            return
        
        try:
            self.config_manager.export_sites(file_path, indices)
            messagebox.showinfo(t("dialog.info"), t("gui.sync.export_ok"))
        except Exception as e:
            messagebox.showerror(t("dialog.error"), t("gui.sync.export_failed", error=e))

    def _import_sites_action(self):
        file_path = filedialog.askopenfilename(
            title=t("gui.sync.import_title"),
            filetypes=[("JSON", "*.json")]
        )
        if not file_path:
            return
        
        try:
            added_sites = self.config_manager.import_sites(file_path)
            if added_sites:
                # import_sites는 파일에 저장하지만 self.service.config(메모리)는 갱신하지 않으므로
                # 명시적으로 config를 리로드하여 _refresh_site_tree가 최신 사이트를 반영하도록 함
                self.service._reload_config()
                self._refresh_site_tree()
                self.service.schedule_backup_push()
                names = ", ".join([s.get("name", "") for s in added_sites])
                messagebox.showinfo(
                    t("dialog.info"),
                    t("gui.sync.import_ok", count=len(added_sites), names=names),
                )
            else:
                messagebox.showinfo(t("dialog.info"), t("gui.sync.import_none"))
        except Exception as e:
            messagebox.showerror(t("dialog.error"), t("gui.sync.import_failed", error=e))
