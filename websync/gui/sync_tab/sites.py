from __future__ import annotations

import copy
import tkinter as tk
from tkinter import messagebox, filedialog

from websync.i18n import t


def site_type_label(site_type: str) -> str:
    """스크래퍼 타입 키 → 사람이 읽는 이름 (카탈로그에 없으면 대문자 키)."""
    key = f"gui.site_types.{site_type}"
    label = t(key)
    return label if label != key else (site_type or "css").upper()


class SyncSitesMixin:
    # ------------------------------------------------------------------
    # 목록 표시
    # ------------------------------------------------------------------

    def _refresh_site_tree(self):
        prev_selection = set(self.tree.selection())
        for item in self.tree.get_children():
            self.tree.delete(item)
        sites = self.service.config.get("sites", []) or []
        for idx, site in enumerate(sites):
            enabled = site.get("enabled", True)
            self.tree.insert("", "end", iid=str(idx), values=(
                t("gui.sync.site_on") if enabled else t("gui.sync.site_off"),
                site.get("name"),
                site_type_label(site.get("type", "css")),
                site.get("limit", 5),
                site.get("url"),
            ), tags=() if enabled else ("disabled",))
        keep = [iid for iid in prev_selection if self.tree.exists(iid)]
        if keep:
            self.tree.selection_set(keep)

        enabled_count = sum(1 for s in sites if s.get("enabled", True))
        if hasattr(self, "sites_summary_label"):
            self.sites_summary_label.configure(
                text=t("gui.sync.sites_summary", enabled=enabled_count, total=len(sites))
            )
        if hasattr(self, "sites_empty_label"):
            if sites:
                self.sites_empty_label.place_forget()
            else:
                self.sites_empty_label.place(relx=0.5, rely=0.55, anchor="center")
                self.sites_empty_label.lift()
        self._update_site_buttons()
        if hasattr(self, "_refresh_getting_started"):
            self._refresh_getting_started()

    def _update_site_buttons(self):
        """선택이 없으면 선택 대상 버튼을 비활성화한다."""
        if not hasattr(self, "edit_site_btn"):
            return
        count = len(self.tree.selection())
        single = "normal" if count == 1 else "disabled"
        multi = "normal" if count >= 1 else "disabled"
        self.edit_site_btn.configure(state=single)
        self.duplicate_site_btn.configure(state=single)
        self.toggle_site_btn.configure(state=multi)
        self.delete_site_btn.configure(state=multi)

    def focus_site_list(self):
        try:
            self.tree.focus_set()
            children = self.tree.get_children()
            if children and not self.tree.selection():
                self.tree.selection_set(children[0])
                self.tree.focus(children[0])
        except tk.TclError:
            pass

    def _selected_site_indices(self) -> list[int]:
        out = []
        for iid in self.tree.selection():
            try:
                out.append(int(iid))
            except ValueError:
                continue
        return sorted(out)

    def _on_site_double_click(self, event):
        # 헤더 더블클릭(열 너비 조정 등)은 편집으로 취급하지 않는다
        if self.tree.identify_region(event.x, event.y) not in ("cell", "tree"):
            return
        if not self.tree.identify_row(event.y):
            return
        self._edit_site_popup()

    def _show_site_menu_mac(self, event):
        self._show_site_menu(event)
        return "break"

    def _show_site_menu(self, event):
        row = self.tree.identify_row(event.y)
        if row and row not in self.tree.selection():
            self.tree.selection_set(row)
            self.tree.focus(row)
        menu = tk.Menu(self.tree, tearoff=0)
        has_sel = bool(self.tree.selection())
        single = len(self.tree.selection()) == 1
        menu.add_command(label=t("gui.sync.add_site"), command=self._add_site_popup)
        menu.add_separator()
        menu.add_command(label=t("gui.sync.edit_site"), command=self._edit_site_popup,
                         state="normal" if single else "disabled")
        menu.add_command(label=t("gui.sync.toggle_enabled"), command=self._toggle_site_enabled,
                         state="normal" if has_sel else "disabled")
        menu.add_command(label=t("gui.sync.duplicate_site"), command=self._duplicate_site,
                         state="normal" if single else "disabled")
        menu.add_command(label=t("gui.sync.open_site_url"), command=self._open_selected_site_url,
                         state="normal" if single else "disabled")
        menu.add_separator()
        menu.add_command(label=t("gui.sync.delete_selected"), command=self._delete_site,
                         state="normal" if has_sel else "disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _open_selected_site_url(self):
        indices = self._selected_site_indices()
        sites = self.service.config.get("sites", [])
        if len(indices) == 1 and 0 <= indices[0] < len(sites):
            self.app._open_url(sites[indices[0]].get("url") or "")

    # ------------------------------------------------------------------
    # 편집 동작
    # ------------------------------------------------------------------

    def _toggle_site_enabled(self):
        indices = self._selected_site_indices()
        if not indices:
            messagebox.showwarning(t("dialog.warning"), t("gui.sync.select_target"))
            return
        config = self.service.config
        sites = config.get("sites", [])
        from websync.backup.format import now_iso
        stamp = now_iso()
        # 여러 개를 고르면 하나라도 꺼져 있으면 모두 켜고, 전부 켜져 있으면 모두 끈다
        targets = [sites[i] for i in indices if 0 <= i < len(sites)]
        new_state = not all(s.get("enabled", True) for s in targets)
        for site in targets:
            site["enabled"] = new_state
            site["_sync_updated_at"] = stamp
        if not self.app._safe_save_config(config):
            return
        self._refresh_site_tree()
        self.service.schedule_backup_push()

    def _delete_site(self):
        indices = self._selected_site_indices()
        if not indices:
            messagebox.showwarning(t("dialog.warning"), t("gui.sync.select_to_delete"))
            return
        config = self.service.config
        sites = config.get("sites", [])
        names = [str(sites[i].get("name") or "") for i in indices if 0 <= i < len(sites)]
        preview = ", ".join(names[:5]) + (" …" if len(names) > 5 else "")
        if not messagebox.askyesno(
            t("dialog.confirm"), t("gui.sync.confirm_delete_named", count=len(names), names=preview)
        ):
            return
        from websync.backup.format import merge_site_tombstones, now_iso
        from websync.backup.portable_cfg import apply_portable_cfg, get_portable_cfg

        stamp = now_iso()
        tombstones = []
        for idx in sorted(indices, reverse=True):
            if not (0 <= idx < len(sites)):
                continue
            removed = sites.pop(idx)
            url = (removed.get("url") or "").strip().lower()
            if url:
                tombstones.append({"url": url, "deleted_at": stamp})
        portable = get_portable_cfg(config)
        portable["deleted_sites"] = merge_site_tombstones(
            portable.get("deleted_sites", []), tombstones,
        )
        apply_portable_cfg(config, portable)
        if not self.app._safe_save_config(config):
            return
        self.tree.selection_set(())
        self._refresh_site_tree()
        self.service.schedule_backup_push()

    def _duplicate_site(self):
        """선택한 소스를 복사해 편집 창을 연다 (URL 을 바꿔 비슷한 소스를 빠르게 추가)."""
        indices = self._selected_site_indices()
        sites = self.service.config.get("sites", [])
        if len(indices) != 1 or not (0 <= indices[0] < len(sites)):
            messagebox.showwarning(t("dialog.warning"), t("gui.sync.select_to_edit"))
            return
        src = copy.deepcopy(sites[indices[0]])
        src.pop("_sync_updated_at", None)
        src["name"] = t("gui.sync.copy_name", name=src.get("name") or "")
        self._open_site_dialog(t("gui.sync.dialog_add_title"), None, src)

    def _add_site_popup(self):
        self._open_site_dialog(t("gui.sync.dialog_add_title"), None)

    def _edit_site_popup(self):
        indices = self._selected_site_indices()
        if not indices:
            messagebox.showwarning(t("dialog.warning"), t("gui.sync.select_to_edit"))
            return
        idx = indices[0]
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
