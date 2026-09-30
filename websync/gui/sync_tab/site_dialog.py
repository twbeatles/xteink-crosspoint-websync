"""사이트(소스) 등록·수정 다이얼로그.

흐름: ① 주소·유형(프리셋/자동 감지) → ② 수집 옵션 → ③ CSS 선택자(웹페이지 유형만).
전용 유형에서는 쓰지 않는 CSS 입력을 숨겨 화면을 단순하게 유지한다.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from urllib.parse import urlparse

import customtkinter as ctk

from websync.gui.widgets import (
    CardFrame, COLOR_BG, COLOR_SECONDARY_FG, COLOR_DANGER, Tooltip,
    get_font, make_button, setup_dialog,
)
from websync.scrapers.types import SCRAPER_TYPES, SPECIALIZED_TYPES
from websync.scrapers.presets import KOREAN_SITE_PRESETS, preset_display_label
from websync.gui.sync_tab.sites import site_type_label
from websync.gui.sync_tab.selector_wizard import (
    SelectorWizardPanel,
    ROLE_ITEM,
    ROLE_TITLE,
    ROLE_LINK,
    ROLE_CONTENT,
    ROLE_REMOVE,
)
from websync.i18n import t

TRANSLATE_CHOICES: tuple[str, ...] = ("", "ko", "en", "ja", "zh-cn", "zh-tw")

# 저장 시 폼이 관리하는 키. 그 밖의 키(향후 확장·다른 PC 가 쓴 키)는 수정 시 보존한다.
_FORM_KEYS = frozenset({
    "name", "type", "url", "limit", "enabled", "include_images", "translate_to",
    "fetch_detail_page", "item_selector", "title_selector", "link_selector",
    "content_selector", "remove_selectors", "_sync_updated_at",
})


def normalize_site_url(raw: str) -> str:
    """앞뒤 공백 제거, 스킴이 없으면 https:// 를 붙인다."""
    url = (raw or "").strip()
    if url and "://" not in url and not url.startswith("//"):
        url = "https://" + url
    return url


def suggest_site_name(url: str) -> str:
    """URL 에서 기본 이름 추천 (호스트 + 첫 경로 조각)."""
    try:
        parsed = urlparse(normalize_site_url(url))
    except ValueError:
        return ""
    host = (parsed.hostname or "").removeprefix("www.").removeprefix("m.")
    if not host:
        return ""
    first = next((p for p in parsed.path.split("/") if p), "")
    if first and len(first) <= 30 and first.lower() not in ("rss", "feed", "index.html", "rss.xml", "feed.xml"):
        return f"{host}/{first}"
    return host


def _translate_label(code: str) -> str:
    return t("gui.site_dialog.translate_none") if not code else code


class SiteDialogMixin:
    def _open_site_dialog(self, title: str, idx: int | None = None, site_data: dict | None = None):
        dialog = ctk.CTkToplevel(self.app.root)
        dialog.title(title)
        dialog.configure(fg_color=COLOR_BG)
        setup_dialog(dialog, self.app.root, 780, 820)
        dialog.minsize(640, 520)

        # 버튼 바를 먼저 pack — 창이 작아도 저장/취소가 잘리지 않는다
        btn_bar = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_bar.pack(side="bottom", fill="x", padx=16, pady=(6, 14))

        body = ctk.CTkScrollableFrame(dialog, fg_color="transparent")
        body.pack(side="top", fill="both", expand=True, padx=8, pady=(8, 0))

        # ------------------------------------------------------------------
        # ① 주소와 유형
        # ------------------------------------------------------------------
        src_card = CardFrame(body, title=t("gui.site_dialog.step_source"), subtitle=t("gui.site_dialog.step_source_sub"))
        src_card.pack(fill="x", padx=4, pady=(0, 8))
        src = ctk.CTkFrame(src_card, fg_color="transparent")
        src.pack(fill="x", padx=12, pady=(2, 10))
        src.columnconfigure(1, weight=1)

        ctk.CTkLabel(src, text=t("gui.sync.preset_label"), font=get_font(13)).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=5)
        preset_labels = [preset_display_label(p) for p in KOREAN_SITE_PRESETS]
        preset_by_label = {preset_display_label(p): p for p in KOREAN_SITE_PRESETS}
        preset_cb = ctk.CTkOptionMenu(
            src, values=preset_labels, font=get_font(12), dynamic_resizing=False, width=320,
        )
        preset_cb.grid(row=0, column=1, columnspan=2, sticky="w", pady=5)
        preset_cb.set(preset_labels[0] if preset_labels else "")
        preset_note = ctk.CTkLabel(
            src, text=t("gui.sync.preset_hint"), font=get_font(11), text_color=COLOR_SECONDARY_FG, anchor="w",
        )
        preset_note.grid(row=1, column=1, columnspan=2, sticky="w")

        ctk.CTkLabel(src, text=t("gui.sync.site_url_label"), font=get_font(13)).grid(row=2, column=0, sticky="w", padx=(0, 8), pady=5)
        url_entry = ctk.CTkEntry(src, font=get_font(12), height=34, placeholder_text=t("gui.site_dialog.url_placeholder"))
        url_entry.grid(row=2, column=1, sticky="we", pady=5)
        detect_btn = make_button(src, t("gui.site_dialog.detect"), None, width=110, height=34, bold=True)
        detect_btn.grid(row=2, column=2, padx=(6, 0), pady=5)
        Tooltip(detect_btn, t("gui.site_dialog.detect_tip"))

        ctk.CTkLabel(src, text=t("gui.sync.site_type_label"), font=get_font(13)).grid(row=3, column=0, sticky="w", padx=(0, 8), pady=5)
        type_labels = {k: site_type_label(k) for k in SCRAPER_TYPES}
        label_to_type = {v: k for k, v in type_labels.items()}
        type_cb = ctk.CTkOptionMenu(
            src, values=[type_labels[k] for k in SCRAPER_TYPES], font=get_font(12), width=220,
            dynamic_resizing=False,
        )
        type_cb.grid(row=3, column=1, sticky="w", pady=5)
        type_desc = ctk.CTkLabel(
            src, text="", font=get_font(11), text_color=COLOR_SECONDARY_FG, anchor="w", justify="left",
            wraplength=560,
        )
        type_desc.grid(row=4, column=1, columnspan=2, sticky="w")

        ctk.CTkLabel(src, text=t("gui.sync.site_name_label"), font=get_font(13)).grid(row=5, column=0, sticky="w", padx=(0, 8), pady=5)
        name_entry = ctk.CTkEntry(src, font=get_font(12), height=34, placeholder_text=t("gui.site_dialog.name_placeholder"))
        name_entry.grid(row=5, column=1, columnspan=2, sticky="we", pady=5)

        # ------------------------------------------------------------------
        # ② 수집 옵션
        # ------------------------------------------------------------------
        opt_card = CardFrame(body, title=t("gui.site_dialog.step_options"))
        opt_card.pack(fill="x", padx=4, pady=(0, 8))
        opt = ctk.CTkFrame(opt_card, fg_color="transparent")
        opt.pack(fill="x", padx=12, pady=(2, 10))

        ctk.CTkLabel(opt, text=t("gui.sync.max_count"), font=get_font(13)).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=5)
        limit_entry = ctk.CTkEntry(opt, font=get_font(12), width=70, height=32)
        limit_entry.grid(row=0, column=1, sticky="w", pady=5)
        limit_entry.insert(0, "5")
        ctk.CTkLabel(opt, text=t("gui.site_dialog.limit_hint"), font=get_font(11), text_color=COLOR_SECONDARY_FG).grid(
            row=0, column=2, sticky="w", padx=8
        )

        ctk.CTkLabel(opt, text=t("gui.sync.translate"), font=get_font(13)).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=5)
        trans_labels = {code: _translate_label(code) for code in TRANSLATE_CHOICES}
        trans_label_to_code = {v: k for k, v in trans_labels.items()}
        translate_cb = ctk.CTkOptionMenu(
            opt, values=[trans_labels[c] for c in TRANSLATE_CHOICES], font=get_font(12), width=140,
        )
        translate_cb.grid(row=1, column=1, columnspan=2, sticky="w", pady=5)
        translate_cb.set(trans_labels[""])

        include_img_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            opt, text=t("gui.sync.include_images"), font=get_font(12), variable=include_img_var,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 2))
        fetch_detail_var = tk.BooleanVar(value=False)
        detail_cb = ctk.CTkCheckBox(
            opt, text=t("gui.sync.fetch_detail"), font=get_font(12), variable=fetch_detail_var,
        )
        detail_cb.grid(row=3, column=0, columnspan=3, sticky="w", pady=2)
        Tooltip(detail_cb, t("gui.site_dialog.fetch_detail_tip"))

        # ------------------------------------------------------------------
        # ③ CSS 선택자 (웹페이지 유형 전용)
        # ------------------------------------------------------------------
        css_card = CardFrame(body, title=t("gui.site_dialog.step_css"), subtitle=t("gui.site_dialog.step_css_sub"))
        css = ctk.CTkFrame(css_card, fg_color="transparent")
        css.pack(fill="x", padx=12, pady=(2, 4))
        css.columnconfigure(1, weight=1)

        def _selector_row(row: int, label: str, default: str, placeholder: str = "") -> ctk.CTkEntry:
            ctk.CTkLabel(css, text=label, font=get_font(13)).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
            ent = ctk.CTkEntry(css, font=get_font(12), height=32, placeholder_text=placeholder)
            ent.grid(row=row, column=1, sticky="we", pady=4)
            if default:
                ent.insert(0, default)
            return ent

        item_entry = _selector_row(0, t("gui.sync.item_container"), ".post-item")
        title_entry = _selector_row(1, t("gui.sync.title_selector"), ".post-title")
        link_entry = _selector_row(2, t("gui.sync.link_selector"), "a[href]")
        content_entry = _selector_row(3, t("gui.sync.content_selector"), ".post-content")
        remove_entry = _selector_row(4, t("gui.sync.remove_css"), "", ".ad, #comments")
        ctk.CTkLabel(
            css, text=t("gui.sync.relative_hint"), font=get_font(11), text_color=COLOR_SECONDARY_FG, anchor="w",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(2, 0))

        # 선택자 도우미 (페이지 분석 / DOM 픽 / 테스트 / 미리보기) — 필요할 때만 펼친다
        helper_bar = ctk.CTkFrame(css_card, fg_color="transparent")
        helper_bar.pack(fill="x", padx=12, pady=(4, 10))
        helper_toggle = make_button(helper_bar, t("gui.site_dialog.helper_show"), None, kind="secondary", width=180)
        helper_toggle.pack(side="left")
        ctk.CTkLabel(
            helper_bar, text=t("gui.site_dialog.helper_hint"), font=get_font(11), text_color=COLOR_SECONDARY_FG,
        ).pack(side="left", padx=8)

        wizard_host = tk.Frame(body)
        wizard_state = {"visible": False}

        # ------------------------------------------------------------------
        # 폼 헬퍼
        # ------------------------------------------------------------------
        def _fill_entry(entry: ctk.CTkEntry, value: str) -> None:
            entry.configure(state="normal")
            entry.delete(0, tk.END)
            if value:
                entry.insert(0, value)

        def current_type() -> str:
            label = type_cb.get()
            return label_to_type.get(label, label if label in SCRAPER_TYPES else "css")

        def set_type_key(key: str) -> None:
            type_cb.set(type_labels.get(key, type_labels["css"]))

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

        def get_url() -> str:
            return normalize_site_url(url_entry.get())

        def get_site_snapshot() -> dict:
            try:
                lim = int(limit_entry.get().strip() or "3")
            except ValueError:
                lim = 3
            return {
                "name": name_entry.get().strip() or "preview",
                "type": current_type(),
                "url": get_url(),
                "item_selector": item_entry.get().strip(),
                "title_selector": title_entry.get().strip(),
                "link_selector": link_entry.get().strip() or "a[href]",
                "content_selector": content_entry.get().strip(),
                "remove_selectors": remove_entry.get().strip(),
                "limit": lim,
                "include_images": bool(include_img_var.get()),
                "fetch_detail_page": bool(fetch_detail_var.get()),
            }

        def show_wizard(visible: bool) -> None:
            wizard_state["visible"] = visible
            if visible:
                wizard_host.pack(fill="both", expand=True, padx=4, pady=(0, 8), after=css_card if css_card.winfo_manager() else opt_card)
                helper_toggle.configure(text=t("gui.site_dialog.helper_hide"))
            else:
                wizard_host.pack_forget()
                helper_toggle.configure(text=t("gui.site_dialog.helper_show"))

        def on_type_change(_choice=None) -> None:
            site_type = current_type()
            type_desc.configure(text=t(f"gui.site_types_desc.{site_type}"))
            is_css = site_type not in SPECIALIZED_TYPES
            if is_css:
                if not css_card.winfo_manager():
                    css_card.pack(fill="x", padx=4, pady=(0, 8), after=opt_card)
                detail_cb.configure(state="normal")
            else:
                css_card.pack_forget()
                detail_cb.configure(state="disabled")
                fetch_detail_var.set(False)
            if wizard_state["visible"]:
                show_wizard(True)  # css 카드 위치가 바뀌었을 수 있으니 재배치

        def apply_site_config(cfg: dict) -> None:
            """분석 추천 결과를 폼에 반영."""
            if not cfg:
                return
            if cfg.get("name") and not name_entry.get().strip():
                _fill_entry(name_entry, cfg.get("name") or "")
            if cfg.get("type"):
                set_type_key(cfg["type"])
            if cfg.get("url"):
                _fill_entry(url_entry, cfg["url"])
            if cfg.get("limit") is not None:
                _fill_entry(limit_entry, str(cfg.get("limit", 5)))
            if "fetch_detail_page" in cfg:
                fetch_detail_var.set(bool(cfg.get("fetch_detail_page")))
            if "include_images" in cfg:
                include_img_var.set(bool(cfg.get("include_images")))
            if (cfg.get("type") or current_type()) == "css":
                for key, ent in (
                    ("item_selector", item_entry),
                    ("title_selector", title_entry),
                    ("link_selector", link_entry),
                    ("content_selector", content_entry),
                ):
                    if cfg.get(key):
                        _fill_entry(ent, cfg[key])
                if cfg.get("remove_selectors") is not None:
                    _fill_entry(remove_entry, cfg.get("remove_selectors") or "")
            on_type_change()

        def on_preset_change(label: str) -> None:
            preset = preset_by_label.get(label)
            if not preset:
                return
            note_key = preset.get("note_key")
            note = t(note_key) if note_key else ""
            preset_note.configure(text=note or t("gui.sync.preset_hint"))
            # 직접 입력(URL 없음)은 폼 유지
            if not preset.get("url"):
                return
            _fill_entry(name_entry, preset.get("name") or "")
            set_type_key(preset.get("type") or "rss")
            _fill_entry(url_entry, preset.get("url") or "")
            _fill_entry(limit_entry, str(preset.get("limit", 5)))
            include_img_var.set(bool(preset.get("include_images", False)))
            on_type_change()

        def on_url_committed(_event=None) -> None:
            url = url_entry.get().strip()
            if not url:
                return
            fixed = normalize_site_url(url)
            if fixed != url:
                _fill_entry(url_entry, fixed)
            if not name_entry.get().strip():
                suggestion = suggest_site_name(fixed)
                if suggestion:
                    _fill_entry(name_entry, suggestion)

        type_cb.configure(command=on_type_change)
        preset_cb.configure(command=on_preset_change)
        url_entry.bind("<FocusOut>", on_url_committed, add="+")
        url_entry.bind("<Return>", on_url_committed, add="+")

        def _pipeline_running() -> bool:
            try:
                return bool(self.service.is_pipeline_running())
            except Exception:
                return False

        wizard = SelectorWizardPanel(
            wizard_host,
            dialog,
            get_url=get_url,
            get_entries=get_selector_entries,
            set_entry=set_selector_entry,
            set_type=set_type_key,
            set_url=lambda u: _fill_entry(url_entry, u),
            get_site_snapshot=get_site_snapshot,
            on_type_change=on_type_change,
            apply_site_config=apply_site_config,
            is_pipeline_running=_pipeline_running,
            start_background_task=self.app._start_background_task,
        )
        wizard.pack(fill="both", expand=True)

        def on_detect() -> None:
            on_url_committed()
            show_wizard(True)
            wizard._on_analyze()

        detect_btn.configure(command=on_detect)
        helper_toggle.configure(command=lambda: show_wizard(not wizard_state["visible"]))

        # ------------------------------------------------------------------
        # 기존 값 채우기 (수정 / 복제)
        # ------------------------------------------------------------------
        if site_data:
            _fill_entry(name_entry, site_data.get("name", ""))
            set_type_key(site_data.get("type", "css"))
            _fill_entry(url_entry, site_data.get("url", ""))
            _fill_entry(item_entry, site_data.get("item_selector", ".post-item"))
            _fill_entry(title_entry, site_data.get("title_selector", ".post-title"))
            _fill_entry(link_entry, site_data.get("link_selector", "a[href]"))
            _fill_entry(content_entry, site_data.get("content_selector", ".post-content"))
            _fill_entry(remove_entry, site_data.get("remove_selectors", ""))
            _fill_entry(limit_entry, str(site_data.get("limit", 5)))
            include_img_var.set(bool(site_data.get("include_images", False)))
            fetch_detail_var.set(bool(site_data.get("fetch_detail_page", False)))
            translate_cb.set(trans_labels.get(site_data.get("translate_to", "") or "", site_data.get("translate_to", "") or trans_labels[""]))
        else:
            set_type_key("css")
        on_type_change()

        # ------------------------------------------------------------------
        # 저장
        # ------------------------------------------------------------------
        def _error(key: str, **kwargs) -> None:
            messagebox.showerror(t("dialog.error"), t(key, **kwargs), parent=dialog)

        def save_site():
            on_url_committed()
            name = name_entry.get().strip()
            url = url_entry.get().strip()
            site_type = current_type()
            if not url:
                _error("gui.site_dialog.url_required")
                url_entry.focus_set()
                return
            if not (url.startswith("http://") or url.startswith("https://")):
                _error("gui.sync.url_http_required")
                url_entry.focus_set()
                return
            if not name:
                _error("gui.sync.name_url_required")
                name_entry.focus_set()
                return
            try:
                limit = int(limit_entry.get().strip())
            except ValueError:
                _error("gui.sync.limit_must_be_number")
                limit_entry.focus_set()
                return
            if not (1 <= limit <= 100):
                _error("gui.sync.limit_range")
                limit_entry.focus_set()
                return

            config = self.service.config
            sites = config.setdefault("sites", [])
            # 같은 URL 이 이미 있으면 알려준다 (중복 수집·중복 전송 방지)
            dup = next(
                (
                    s for i, s in enumerate(sites)
                    if i != idx and (s.get("url") or "").strip().lower() == url.lower()
                ),
                None,
            )
            if dup is not None and not messagebox.askyesno(
                t("gui.sync.duplicate_title"),
                t("gui.site_dialog.duplicate_url", name=dup.get("name") or ""),
                parent=dialog,
            ):
                return

            # 수정 시 폼이 모르는 키는 보존한다
            new_site: dict = {}
            if idx is not None and site_data:
                new_site.update({k: v for k, v in site_data.items() if k not in _FORM_KEYS})
            new_site.update({
                "name": name, "type": site_type, "url": url, "limit": limit,
                "enabled": site_data.get("enabled", True) if (site_data and idx is not None) else True,
                "include_images": bool(include_img_var.get()),
                "translate_to": trans_label_to_code.get(translate_cb.get(), translate_cb.get().strip()),
                "fetch_detail_page": bool(fetch_detail_var.get()) if site_type == "css" else False,
            })
            from websync.backup.format import merge_site_tombstones, now_iso
            updated_at = now_iso()
            new_site["_sync_updated_at"] = updated_at
            if site_type == "css":
                item_sel = item_entry.get().strip()
                title_sel = title_entry.get().strip()
                content_sel = content_entry.get().strip()
                if not item_sel:
                    _error("gui.sync.css_item_required")
                    item_entry.focus_set()
                    return
                if not title_sel:
                    _error("gui.sync.css_title_required")
                    title_entry.focus_set()
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
                        _error("gui.sync.selector_error", label=label, error=err)
                        return
                new_site["item_selector"] = item_sel
                new_site["title_selector"] = title_sel
                new_site["link_selector"] = link_entry.get().strip() or "a[href]"
                new_site["content_selector"] = content_sel
                new_site["remove_selectors"] = remove_entry.get().strip()
            if idx is None:
                sites.append(new_site)
            else:
                sites[idx] = new_site
            from websync.backup.portable_cfg import apply_portable_cfg, get_portable_cfg
            portable = get_portable_cfg(config)
            old_url = (site_data.get("url") or "").strip().lower() if (site_data and idx is not None) else ""
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
            new_iid = str(len(sites) - 1 if idx is None else idx)
            if self.tree.exists(new_iid):
                self.tree.selection_set(new_iid)
                self.tree.see(new_iid)
            self.service.schedule_backup_push()
            self.app._log_message(t("gui.site_dialog.saved_log", name=name))
            dialog.destroy()

        ctk.CTkLabel(
            btn_bar, text=t("gui.site_dialog.footer_hint"), font=get_font(11), text_color=COLOR_SECONDARY_FG,
        ).pack(side="left")
        make_button(btn_bar, t("gui.sync.save"), save_site, width=100, height=36, bold=True).pack(side="right", padx=(6, 0))
        make_button(btn_bar, t("gui.sync.cancel"), dialog.destroy, kind="secondary", width=90, height=36).pack(side="right")

        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        dialog.bind("<Control-s>", lambda _e: save_site())
        dialog.after(150, (name_entry if site_data else url_entry).focus_set)
