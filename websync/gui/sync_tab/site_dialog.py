"""사이트 등록·수정 다이얼로그."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from websync.gui.widgets import (
    BG_COLOR, HINT_COLOR,
    create_scrollable_frame, setup_dialog,
)
from websync.scrapers.types import SCRAPER_TYPES, SPECIALIZED_TYPES
from websync.scrapers.presets import preset_labels, get_preset_by_label
from websync.gui.sync_tab.selector_wizard import (
    SelectorWizardPanel,
    ROLE_ITEM,
    ROLE_TITLE,
    ROLE_LINK,
    ROLE_CONTENT,
    ROLE_REMOVE,
)
from websync.i18n import t


class SiteDialogMixin:
    def _open_site_dialog(self, title: str, idx: int = None, site_data: dict = None):
        dialog = tk.Toplevel(self.app.root)
        dialog.title(title)
        dialog.configure(bg=BG_COLOR)
        setup_dialog(dialog, self.app.root, 720, 780)

        content = ttk.Frame(dialog)
        content.pack(fill="both", expand=True)

        frame = create_scrollable_frame(content)
        form = ttk.Frame(frame)
        form.pack(fill="both", expand=True, padx=20, pady=20)

        # 한국 추천 프리셋
        ttk.Label(form, text=t("gui.sync.preset_label")).grid(row=0, column=0, sticky="w", pady=8)
        preset_cb = ttk.Combobox(
            form,
            values=preset_labels(),
            state="readonly",
            width=38,
        )
        preset_cb.grid(row=0, column=1, sticky="w", pady=8)
        preset_cb.set(t("gui.sync.presets.direct"))
        ttk.Label(
            form,
            text=t("gui.sync.preset_hint"),
            font=("Malgun Gothic", 11),
            foreground=HINT_COLOR,
        ).grid(row=1, column=1, sticky="w")

        ttk.Label(form, text=t("gui.sync.site_name_label")).grid(row=2, column=0, sticky="w", pady=8)
        name_entry = ttk.Entry(form, width=40)
        name_entry.grid(row=2, column=1, sticky="w", pady=8)

        ttk.Label(form, text=t("gui.sync.site_type_label")).grid(row=3, column=0, sticky="w", pady=8)
        type_cb = ttk.Combobox(
            form,
            values=list(SCRAPER_TYPES),
            state="readonly",
            width=15
        )
        type_cb.grid(row=3, column=1, sticky="w", pady=8)
        type_cb.set("css")

        ttk.Label(form, text=t("gui.sync.site_url_label")).grid(row=4, column=0, sticky="w", pady=8)
        url_entry = ttk.Entry(form, width=40)
        url_entry.grid(row=4, column=1, sticky="w", pady=8)

        css_frame = ttk.LabelFrame(form, text=t("gui.sync.css_frame"))
        css_frame.grid(row=5, column=0, columnspan=2, sticky="we", pady=10, ipady=5)

        ttk.Label(css_frame, text=t("gui.sync.item_container")).grid(row=0, column=0, sticky="w", padx=10, pady=5)
        item_entry = ttk.Entry(css_frame, width=28)
        item_entry.grid(row=0, column=1, sticky="w", pady=5)
        item_entry.insert(0, ".post-item")

        ttk.Label(css_frame, text=t("gui.sync.title_selector")).grid(row=1, column=0, sticky="w", padx=10, pady=5)
        title_entry = ttk.Entry(css_frame, width=28)
        title_entry.grid(row=1, column=1, sticky="w", pady=5)
        title_entry.insert(0, ".post-title")

        ttk.Label(css_frame, text=t("gui.sync.link_selector")).grid(row=2, column=0, sticky="w", padx=10, pady=5)
        link_entry = ttk.Entry(css_frame, width=28)
        link_entry.grid(row=2, column=1, sticky="w", pady=5)
        link_entry.insert(0, "a[href]")

        ttk.Label(css_frame, text=t("gui.sync.content_selector")).grid(row=3, column=0, sticky="w", padx=10, pady=5)
        content_entry = ttk.Entry(css_frame, width=28)
        content_entry.grid(row=3, column=1, sticky="w", pady=5)
        content_entry.insert(0, ".post-content")

        ttk.Label(
            css_frame,
            text=t("gui.sync.relative_hint"),
            font=("Malgun Gothic", 10),
            foreground=HINT_COLOR,
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 4))

        ttk.Label(form, text=t("gui.sync.remove_css")).grid(row=6, column=0, sticky="w", pady=8)
        remove_entry = ttk.Entry(form, width=40)
        remove_entry.grid(row=6, column=1, sticky="w", pady=8)

        ttk.Label(form, text=t("gui.sync.max_count")).grid(row=7, column=0, sticky="w", pady=8)
        limit_entry = ttk.Entry(form, width=10)
        limit_entry.grid(row=7, column=1, sticky="w", pady=8)
        limit_entry.insert(0, "5")

        # 이미지 포함 / 번역 / 상세 페이지 옵션
        opt_frame = ttk.Frame(form)
        opt_frame.grid(row=8, column=0, columnspan=2, sticky="we", pady=5)
        include_img_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_frame, text=t("gui.sync.include_images"), variable=include_img_var).pack(side="left", padx=5)
        fetch_detail_var = tk.BooleanVar(value=False)
        detail_cb = ttk.Checkbutton(
            opt_frame, text=t("gui.sync.fetch_detail"), variable=fetch_detail_var
        )
        detail_cb.pack(side="left", padx=5)

        ttk.Label(opt_frame, text=t("gui.sync.translate")).pack(side="left", padx=(15, 3))
        translate_cb = ttk.Combobox(opt_frame, values=["", "ko", "en", "ja", "zh-cn", "zh-tw"], width=6)
        translate_cb.pack(side="left")
        translate_cb.set("")
        ttk.Label(opt_frame, text=t("gui.sync.translate_hint"), font=("Malgun Gothic", 11), foreground=HINT_COLOR).pack(side="left", padx=3)

        def _fill_entry(entry: ttk.Entry, value: str) -> None:
            entry.configure(state="normal")
            entry.delete(0, tk.END)
            entry.insert(0, value)

        def set_selector_entry(role: str, value: str) -> None:
            mapping = {
                ROLE_ITEM: item_entry,
                ROLE_TITLE: title_entry,
                ROLE_LINK: link_entry,
                ROLE_CONTENT: content_entry,
                ROLE_REMOVE: remove_entry,
            }
            ent = mapping.get(role)
            if ent is not None:
                _fill_entry(ent, value)

        def get_selector_entries() -> dict:
            return {
                "item": item_entry.get().strip(),
                "title": title_entry.get().strip(),
                "link": link_entry.get().strip(),
                "content": content_entry.get().strip(),
                "remove": remove_entry.get().strip(),
            }

        def get_site_snapshot() -> dict:
            try:
                lim = int(limit_entry.get().strip() or "3")
            except ValueError:
                lim = 3
            return {
                "name": name_entry.get().strip() or "preview",
                "type": type_cb.get() or "css",
                "url": url_entry.get().strip(),
                "item_selector": item_entry.get().strip(),
                "title_selector": title_entry.get().strip(),
                "link_selector": link_entry.get().strip() or "a[href]",
                "content_selector": content_entry.get().strip(),
                "remove_selectors": remove_entry.get().strip(),
                "limit": lim,
                "include_images": bool(include_img_var.get()),
                "fetch_detail_page": bool(fetch_detail_var.get()),
            }

        def apply_site_config(cfg: dict) -> None:
            """분석 추천 결과를 폼에 반영."""
            if not cfg:
                return
            if cfg.get("name") and not name_entry.get().strip():
                name_entry.delete(0, tk.END)
                name_entry.insert(0, cfg.get("name") or "")
            if cfg.get("type"):
                type_cb.set(cfg["type"])
            if cfg.get("url"):
                _fill_entry(url_entry, cfg["url"])
            if cfg.get("limit") is not None:
                limit_entry.delete(0, tk.END)
                limit_entry.insert(0, str(cfg.get("limit", 5)))
            if "fetch_detail_page" in cfg:
                fetch_detail_var.set(bool(cfg.get("fetch_detail_page")))
            if "include_images" in cfg:
                include_img_var.set(bool(cfg.get("include_images")))
            if (cfg.get("type") or type_cb.get()) == "css":
                if cfg.get("item_selector"):
                    _fill_entry(item_entry, cfg["item_selector"])
                if cfg.get("title_selector"):
                    _fill_entry(title_entry, cfg["title_selector"])
                if cfg.get("link_selector"):
                    _fill_entry(link_entry, cfg["link_selector"])
                if cfg.get("content_selector"):
                    _fill_entry(content_entry, cfg["content_selector"])
                if cfg.get("remove_selectors") is not None:
                    _fill_entry(remove_entry, cfg.get("remove_selectors") or "")
            on_type_change()

        def on_type_change(event=None):
            site_type = type_cb.get()
            state = "disabled" if site_type in SPECIALIZED_TYPES else "normal"
            for w in (item_entry, title_entry, link_entry, content_entry, remove_entry):
                if hasattr(w, "configure"):
                    w.configure(state=state)
                elif hasattr(w, "config"):
                    w.config(state=state)
            if hasattr(detail_cb, "configure"):
                detail_cb.configure(state="normal" if site_type == "css" else "disabled")
            elif hasattr(detail_cb, "config"):
                detail_cb.config(state="normal" if site_type == "css" else "disabled")
            if site_type != "css":
                fetch_detail_var.set(False)

        def on_preset_change(event=None):
            preset = get_preset_by_label(preset_cb.get())
            if not preset:
                return
            # 직접 입력은 폼 유지
            if preset.get("label") == t("gui.sync.presets.direct") or not preset.get("url"):
                return
            name_entry.delete(0, tk.END)
            name_entry.insert(0, preset.get("name") or "")
            type_cb.set(preset.get("type") or "rss")
            url_entry.delete(0, tk.END)
            url_entry.insert(0, preset.get("url") or "")
            limit_entry.delete(0, tk.END)
            limit_entry.insert(0, str(preset.get("limit", 5)))
            include_img_var.set(bool(preset.get("include_images", False)))
            on_type_change()

        type_cb.bind("<<ComboboxSelected>>", on_type_change)
        preset_cb.bind("<<ComboboxSelected>>", on_preset_change)

        # 선택자 도우미 (페이지 분석 / DOM 픽 / 테스트 / 미리보기)
        def _pipeline_running() -> bool:
            try:
                return bool(self.service.is_pipeline_running())
            except Exception:
                return False

        wizard = SelectorWizardPanel(
            form,
            dialog,
            get_url=lambda: url_entry.get(),
            get_entries=get_selector_entries,
            set_entry=set_selector_entry,
            set_type=lambda t: type_cb.set(t),
            set_url=lambda u: (_fill_entry(url_entry, u)),
            get_site_snapshot=get_site_snapshot,
            on_type_change=on_type_change,
            apply_site_config=apply_site_config,
            is_pipeline_running=_pipeline_running,
        )
        wizard.grid(row=9, column=0, columnspan=2, sticky="nsew", pady=10)
        form.rowconfigure(9, weight=1)

        if site_data:
            name_entry.insert(0, site_data.get("name", ""))
            type_cb.set(site_data.get("type", "css"))
            url_entry.insert(0, site_data.get("url", ""))
            item_entry.delete(0, tk.END); item_entry.insert(0, site_data.get("item_selector", ".post-item"))
            title_elem = site_data.get("title_selector", ".post-title")
            title_entry.delete(0, tk.END); title_entry.insert(0, title_elem)
            link_entry.delete(0, tk.END)
            link_entry.insert(0, site_data.get("link_selector", "a[href]"))
            content_entry.delete(0, tk.END); content_entry.insert(0, site_data.get("content_selector", ".post-content"))
            remove_entry.delete(0, tk.END); remove_entry.insert(0, site_data.get("remove_selectors", ""))
            limit_entry.delete(0, tk.END); limit_entry.insert(0, str(site_data.get("limit", 5)))
            include_img_var.set(site_data.get("include_images", False))
            fetch_detail_var.set(site_data.get("fetch_detail_page", False))
            translate_cb.set(site_data.get("translate_to", ""))
            on_type_change()

        def save_site():
            name = name_entry.get().strip()
            url = url_entry.get().strip()
            if not name or not url:
                messagebox.showerror(t("dialog.error"), t("gui.sync.name_url_required"), parent=dialog)
                return
            if not (url.startswith("http://") or url.startswith("https://")):
                messagebox.showerror(t("dialog.error"), t("gui.sync.url_http_required"), parent=dialog)
                return
            try:
                limit = int(limit_entry.get().strip())
            except ValueError:
                messagebox.showerror(t("dialog.error"), t("gui.sync.limit_must_be_number"), parent=dialog)
                return
            if not (1 <= limit <= 100):
                messagebox.showerror(t("dialog.error"), t("gui.sync.limit_range"), parent=dialog)
                return
            config = self.service.config
            new_site = {
                "name": name, "type": type_cb.get(), "url": url, "limit": limit,
                "enabled": site_data.get("enabled", True) if site_data else True,
                "include_images": include_img_var.get(),
                "translate_to": translate_cb.get().strip(),
                "fetch_detail_page": bool(fetch_detail_var.get()) if type_cb.get() == "css" else False,
            }
            from websync.backup.format import merge_site_tombstones, now_iso
            updated_at = now_iso()
            new_site["_sync_updated_at"] = updated_at
            if type_cb.get() == "css":
                item_sel = item_entry.get().strip()
                title_sel = title_entry.get().strip()
                content_sel = content_entry.get().strip()
                if not item_sel:
                    messagebox.showerror(
                        t("dialog.error"),
                        t("gui.sync.css_item_required"),
                        parent=dialog,
                    )
                    return
                if not title_sel:
                    messagebox.showerror(
                        t("dialog.error"),
                        t("gui.sync.css_title_required"),
                        parent=dialog,
                    )
                    return
                if not content_sel and not fetch_detail_var.get():
                    if not messagebox.askyesno(
                        t("gui.sync.content_confirm_title"),
                        t("gui.sync.content_confirm"),
                        parent=dialog,
                    ):
                        return
                # 문법 사전 검사
                from websync.config.validator import _css_selector_syntax_error

                for label, sel in (
                    (t("gui.selector.role.item"), item_sel),
                    (t("gui.selector.role.title"), title_sel),
                    (t("gui.selector.role.link"), link_entry.get().strip() or "a[href]"),
                    (t("gui.selector.role.content"), content_sel),
                ):
                    if not sel:
                        continue
                    err = _css_selector_syntax_error(sel)
                    if err:
                        messagebox.showerror(
                            t("dialog.error"),
                            t("gui.sync.selector_error", label=label, error=err),
                            parent=dialog,
                        )
                        return
                new_site["item_selector"] = item_sel
                new_site["title_selector"] = title_sel
                new_site["link_selector"] = link_entry.get().strip() or "a[href]"
                new_site["content_selector"] = content_sel
                new_site["remove_selectors"] = remove_entry.get().strip()
            if idx is None:
                config["sites"].append(new_site)
            else:
                config["sites"][idx] = new_site
            from websync.backup.portable_cfg import apply_portable_cfg, get_portable_cfg
            portable = get_portable_cfg(config)
            old_url = (site_data.get("url") or "").strip().lower() if site_data else ""
            if old_url and old_url != url.lower():
                portable["deleted_sites"] = merge_site_tombstones(
                    portable.get("deleted_sites", []),
                    [{"url": old_url, "deleted_at": updated_at}],
                )
            portable["deleted_sites"] = [
                item for item in portable.get("deleted_sites", [])
                if (item.get("url") or "").strip().lower() != url.lower()
            ]
            apply_portable_cfg(config, portable)
            if not self.app._safe_save_config(config, parent=dialog):
                return
            self._refresh_site_tree()
            self.service.schedule_backup_push()
            dialog.destroy()

        dlg_btn_frame = ttk.Frame(dialog)
        dlg_btn_frame.pack(side="bottom", fill="x", pady=10)
        ttk.Button(dlg_btn_frame, text=t("gui.sync.save"), command=save_site).pack(side="right", padx=10)
        ttk.Button(dlg_btn_frame, text=t("gui.sync.cancel"), command=dialog.destroy).pack(side="right", padx=10)
