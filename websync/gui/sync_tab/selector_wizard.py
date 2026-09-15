"""사이트 등록 다이얼로그용 CSS 선택자 도우미 패널.

순수 로직은 websync.scrapers.selector_assistant 에 두고,
이 모듈은 Treeview·버튼·스레드 콜백만 담당한다.

스레드 규약:
- 네트워크 작업만 daemon 스레드에서 수행
- self._html / _analysis / 위젯 갱신은 메인 스레드(after 콜백)에서만
- 다이얼로그 파괴 시 after 콜백은 no-op, _busy 는 항상 해제
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Any, Callable, Optional

from websync.gui.widgets import HINT_COLOR, GREEN_COLOR
from websync.scrapers.selector_assistant import (
    PageAnalysis,
    analyze_page,
    parse_html,
    evaluate_selector,
    is_private_or_local_url,
)
from websync.i18n import t


# 선택자 필드 역할 키
ROLE_ITEM = "item"
ROLE_TITLE = "title"
ROLE_LINK = "link"
ROLE_CONTENT = "content"
ROLE_REMOVE = "remove"

_ROLE_I18N = {
    ROLE_ITEM: "gui.selector.role.item",
    ROLE_TITLE: "gui.selector.role.title",
    ROLE_LINK: "gui.selector.role.link",
    ROLE_CONTENT: "gui.selector.role.content",
    ROLE_REMOVE: "gui.selector.role.remove",
}


def _role_label(role: str) -> str:
    key = _ROLE_I18N.get(role)
    return t(key) if key else role


class SelectorWizardPanel:
    """CSS 선택자 분석/테스트/DOM 픽 패널."""

    def __init__(
        self,
        parent: tk.Misc,
        dialog: tk.Toplevel,
        *,
        get_url: Callable[[], str],
        get_entries: Callable[[], dict[str, Any]],
        set_entry: Callable[[str, str], None],
        set_type: Callable[[str], None],
        set_url: Callable[[str], None],
        get_site_snapshot: Callable[[], dict],
        on_type_change: Optional[Callable[[], None]] = None,
        apply_site_config: Optional[Callable[[dict], None]] = None,
        is_pipeline_running: Optional[Callable[[], bool]] = None,
    ):
        self.parent = parent
        self.dialog = dialog
        self.get_url = get_url
        self.get_entries = get_entries
        self.set_entry = set_entry
        self.set_type = set_type
        self.set_url = set_url
        self.get_site_snapshot = get_site_snapshot
        self.on_type_change = on_type_change
        self.apply_site_config = apply_site_config
        self.is_pipeline_running = is_pipeline_running

        self._html: str = ""
        self._base_url: str = ""
        self._busy = False
        self._req_gen = 0  # stale after 콜백 폐기용
        self._analysis: Optional[PageAnalysis] = None
        self._outline_iid_to_path: dict[str, str] = {}

        self.role_var = tk.StringVar(value=ROLE_ITEM)

        self.frame = ttk.LabelFrame(parent, text=t("gui.selector.frame_title"))
        self._build()

    # ------------------------------------------------------------------
    # 스레드/다이얼로그 안전 헬퍼
    # ------------------------------------------------------------------

    def _dialog_alive(self) -> bool:
        try:
            return bool(self.dialog.winfo_exists())
        except tk.TclError:
            return False

    def _ui_call(self, gen: int, fn: Callable[[], None]) -> None:
        """메인 스레드에서만 호출. 파괴·stale 요청이면 _busy 만 정리."""
        if gen != self._req_gen:
            return
        if not self._dialog_alive():
            self._busy = False
            return
        try:
            fn()
        except tk.TclError:
            self._busy = False
        except Exception:
            self._busy = False
            raise

    def _schedule(self, gen: int, fn: Callable[[], None]) -> None:
        """워커 → 메인 스레드 스케줄. 다이얼로그가 없으면 no-op."""
        def _run():
            self._ui_call(gen, fn)

        if not self._dialog_alive():
            # 이미 닫힘 — gen 무효화는 메인에서 busy 정리
            try:
                self.dialog.after(0, lambda: self._ui_call(gen, lambda: None))
            except tk.TclError:
                self._busy = False
            return
        try:
            self.dialog.after(0, _run)
        except tk.TclError:
            self._busy = False

    def _begin_work(self, status: str) -> Optional[int]:
        if self._busy:
            return None
        if not self._dialog_alive():
            return None
        self._busy = True
        self._req_gen += 1
        gen = self._req_gen
        try:
            self._set_status(status)
        except tk.TclError:
            self._busy = False
            return None
        return gen

    def pack(self, **kwargs) -> None:
        self.frame.pack(**kwargs)

    def grid(self, **kwargs) -> None:
        self.frame.grid(**kwargs)

    def set_css_widgets_state(self, enabled: bool) -> None:
        # 비CSS일 때도 분석(RSS/전용 제안)은 유용하므로 패널은 유지
        pass

    def _set_status(self, msg: str, *, ok: bool = False) -> None:
        if not self._dialog_alive():
            return
        try:
            self.status_label.configure(
                text=msg,
                foreground=GREEN_COLOR if ok else HINT_COLOR,
            )
        except tk.TclError:
            pass

    def _set_result(self, text: str) -> None:
        if not self._dialog_alive():
            return
        try:
            self.result_text.configure(state="normal")
            self.result_text.delete("1.0", tk.END)
            self.result_text.insert(tk.END, text)
            self.result_text.configure(state="disabled")
        except tk.TclError:
            pass

    def _clear_hint_buttons(self) -> None:
        if not self._dialog_alive():
            return
        try:
            for w in self.hint_frame.winfo_children():
                w.destroy()
        except tk.TclError:
            pass

    def _build(self) -> None:
        top = ttk.Frame(self.frame)
        top.pack(fill="x", padx=8, pady=6)

        ttk.Button(top, text=t("gui.selector.analyze"), command=self._on_analyze).pack(side="left", padx=2)
        ttk.Button(top, text=t("gui.selector.test"), command=self._on_test).pack(side="left", padx=2)
        ttk.Button(top, text=t("gui.selector.preview_scrape"), command=self._on_preview_scrape).pack(side="left", padx=2)
        ttk.Button(top, text=t("gui.selector.apply_suggestions"), command=self._on_apply_suggestions).pack(side="left", padx=2)
        ttk.Button(top, text=t("gui.selector.apply_recommended"), command=self._on_apply_recommended).pack(side="left", padx=2)

        self.status_label = ttk.Label(
            self.frame,
            text=t("gui.selector.status_hint"),
            font=("Malgun Gothic", 10),
            foreground=HINT_COLOR,
            wraplength=520,
            justify="left",
        )
        self.status_label.pack(fill="x", padx=10, pady=(0, 4))

        role_row = ttk.Frame(self.frame)
        role_row.pack(fill="x", padx=8, pady=2)
        ttk.Label(role_row, text=t("gui.selector.role_prompt")).pack(side="left")
        for key in _ROLE_I18N:
            ttk.Radiobutton(
                role_row, text=_role_label(key), value=key, variable=self.role_var
            ).pack(side="left", padx=3)

        self.hint_frame = ttk.Frame(self.frame)
        self.hint_frame.pack(fill="x", padx=8, pady=2)

        paned = ttk.Panedwindow(self.frame, orient=tk.HORIZONTAL)
        paned.pack(fill="both", expand=True, padx=8, pady=4)

        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        ttk.Label(left, text=t("gui.selector.dom_tree")).pack(anchor="w")
        tree_wrap = ttk.Frame(left)
        tree_wrap.pack(fill="both", expand=True)
        self.dom_tree = ttk.Treeview(tree_wrap, show="tree", height=10, selectmode="browse")
        ys = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.dom_tree.yview)
        self.dom_tree.configure(yscrollcommand=ys.set)
        self.dom_tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        self.dom_tree.bind("<<TreeviewSelect>>", self._on_dom_select)

        ttk.Label(right, text=t("gui.selector.result_panel")).pack(anchor="w")
        self.result_text = tk.Text(right, height=10, width=36, wrap="word", font=("Consolas", 9))
        rsb = ttk.Scrollbar(right, orient="vertical", command=self.result_text.yview)
        self.result_text.configure(yscrollcommand=rsb.set)
        self.result_text.pack(side="left", fill="both", expand=True)
        rsb.pack(side="right", fill="y")
        self.result_text.configure(state="disabled")

    def _warn_private_url(self, url: str) -> bool:
        """사설/로컬 URL이면 사용자 확인. 진행하면 True."""
        if not is_private_or_local_url(url):
            return True
        return bool(
            messagebox.askyesno(
                t("gui.selector.private_url_title"),
                t("gui.selector.private_url_body"),
                parent=self.dialog,
            )
        )

    def _on_analyze(self) -> None:
        url = self.get_url().strip()
        if not url:
            messagebox.showwarning(t("dialog.warning"), t("gui.selector.url_required"), parent=self.dialog)
            return
        if not (url.startswith("http://") or url.startswith("https://")):
            messagebox.showerror(t("dialog.error"), t("gui.selector.url_http_required"), parent=self.dialog)
            return
        if not self._warn_private_url(url):
            return
        gen = self._begin_work(t("gui.selector.loading_page"))
        if gen is None:
            return
        try:
            self._set_result("")
        except tk.TclError:
            self._busy = False
            return

        def work():
            try:
                analysis = analyze_page(url)
            except Exception as e:
                analysis = PageAnalysis(url=url, base_url=url, error=t("gui.selector.analyze_exception", error=e))
            self._schedule(gen, lambda: self._apply_analysis(analysis, gen))

        threading.Thread(target=work, daemon=True).start()

    def _apply_analysis(self, analysis: PageAnalysis, gen: int) -> None:
        if gen != self._req_gen:
            return
        self._busy = False
        if not self._dialog_alive():
            return

        self._analysis = analysis
        self._html = analysis.html or ""
        self._base_url = analysis.base_url or analysis.url

        if analysis.error:
            self._set_status(analysis.error)
            self._set_result(analysis.error)
            return

        try:
            self.dom_tree.delete(*self.dom_tree.get_children())
        except tk.TclError:
            return
        self._outline_iid_to_path.clear()
        iid_map: dict[int, str] = {}
        for node in analysis.outline:
            parent = "" if node.parent_index < 0 else iid_map.get(node.parent_index, "")
            try:
                iid = self.dom_tree.insert(parent, "end", text=node.label)
            except tk.TclError:
                return
            iid_map[node.index] = iid
            self._outline_iid_to_path[iid] = node.css_path

        self._clear_hint_buttons()
        if analysis.platform:
            p = analysis.platform
            ttk.Button(
                self.hint_frame,
                text=t("gui.selector.hint_platform", platform=p),
                command=lambda pt=p: self._switch_platform(pt),
            ).pack(side="left", padx=2, pady=2)
        for feed in analysis.feeds[:3]:
            label = feed.url if len(feed.url) <= 52 else feed.url[:50] + "…"
            ttk.Button(
                self.hint_frame,
                text=t("gui.selector.hint_rss", label=label),
                command=lambda f=feed: self._switch_rss(f.url),
            ).pack(side="left", padx=2, pady=2)
        if analysis.recommended_site:
            ttk.Button(
                self.hint_frame,
                text=t("gui.selector.apply_recommended"),
                command=self._on_apply_recommended,
            ).pack(side="left", padx=2, pady=2)

        lines = [
            t("gui.selector.result_title", title=analysis.title or t("gui.selector.none")),
            t("gui.selector.result_url", url=analysis.base_url),
            t("gui.selector.result_mode", mode=analysis.recommend_mode),
        ]
        for note in (analysis.notes or [])[:6]:
            lines.append(t("gui.selector.result_note", note=note))
        if analysis.platform:
            lines.append(t("gui.selector.result_platform", platform=analysis.platform))
        if analysis.feeds:
            lines.append(t("gui.selector.result_feeds", count=len(analysis.feeds)))
            for f in analysis.feeds[:3]:
                lines.append(f"  - {f.url}")
        sug = analysis.suggestions or {}
        for role_key, key in ((ROLE_ITEM, "item"), (ROLE_TITLE, "title"), (ROLE_LINK, "link"), (ROLE_CONTENT, "content")):
            items = sug.get(key) or []
            if items:
                top = items[0]
                lines.append(
                    t(
                        "gui.selector.suggest_role",
                        role=_role_label(role_key),
                        selector=top.get("selector"),
                        score=top.get("score"),
                        count=top.get("count"),
                        sample=(top.get("sample", "") or "")[:40],
                    )
                )
        if analysis.fetch_detail_recommended:
            lines.append(t("gui.selector.fetch_detail_recommended"))
        rec = analysis.recommended_site or {}
        if rec:
            lines.append(
                t(
                    "gui.selector.best_settings",
                    type=rec.get("type"),
                    fetch_detail=rec.get("fetch_detail_page"),
                    note=rec.get("_recommend_note", ""),
                )
            )
        self._set_result("\n".join(lines))
        self._set_status(
            t("gui.selector.analyze_done"),
            ok=True,
        )

    def _switch_platform(self, platform: str) -> None:
        self.set_type(platform)
        if self.on_type_change:
            self.on_type_change()
        self._set_status(t("gui.selector.switched_platform", platform=platform), ok=True)

    def _switch_rss(self, feed_url: str) -> None:
        self.set_type("rss")
        self.set_url(feed_url)
        if self.on_type_change:
            self.on_type_change()
        self._set_status(t("gui.selector.switched_rss"), ok=True)

    def _on_dom_select(self, _event=None) -> None:
        sel = self.dom_tree.selection()
        if not sel:
            return
        path = self._outline_iid_to_path.get(sel[0], "")
        if not path:
            return
        role = self.role_var.get()
        self.set_entry(role, path)
        self._set_status(t("gui.selector.inserted_selector", role=_role_label(role), path=path), ok=True)

    def _on_apply_suggestions(self) -> None:
        if not self._analysis or not self._analysis.suggestions:
            messagebox.showinfo(
                t("gui.selector.info_title"),
                t("gui.selector.analyze_first"),
                parent=self.dialog,
            )
            return
        if self._analysis.recommend_mode in ("rss", "platform"):
            if not messagebox.askyesno(
                t("dialog.confirm"),
                t("gui.selector.css_vs_recommended", mode=self._analysis.recommend_mode),
                parent=self.dialog,
            ):
                return
        sug = self._analysis.suggestions
        applied = []
        mapping = [
            (ROLE_ITEM, "item"),
            (ROLE_TITLE, "title"),
            (ROLE_LINK, "link"),
            (ROLE_CONTENT, "content"),
        ]
        for role, key in mapping:
            items = sug.get(key) or []
            if items:
                sel = items[0].get("selector") or ""
                if sel == ".":
                    sel = "a" if role == ROLE_TITLE else ("a[href]" if role == ROLE_LINK else sel)
                if sel and sel != ".":
                    self.set_entry(role, sel)
                    applied.append(f"{_role_label(role)}={sel}")
        if self.apply_site_config and self._analysis.fetch_detail_recommended:
            self.apply_site_config({"fetch_detail_page": True, "type": "css"})
            applied.append(t("gui.selector.applied_detail_on"))
        if applied:
            self._set_status(t("gui.selector.suggestions_applied", items=", ".join(applied)), ok=True)
        else:
            self._set_status(t("gui.selector.no_suggestions"))

    def _on_apply_recommended(self) -> None:
        if not self._analysis or not self._analysis.recommended_site:
            messagebox.showinfo(
                t("gui.selector.info_title"),
                t("gui.selector.analyze_first"),
                parent=self.dialog,
            )
            return
        rec = dict(self._analysis.recommended_site)
        note = rec.pop("_recommend_note", "") or ""
        rec.pop("_notes", None)
        if self.apply_site_config:
            self.apply_site_config(rec)
        else:
            self.set_type(rec.get("type") or "css")
            if rec.get("url"):
                self.set_url(rec["url"])
            if (rec.get("type") or "") == "css":
                for role, key in (
                    (ROLE_ITEM, "item_selector"),
                    (ROLE_TITLE, "title_selector"),
                    (ROLE_LINK, "link_selector"),
                    (ROLE_CONTENT, "content_selector"),
                    (ROLE_REMOVE, "remove_selectors"),
                ):
                    if rec.get(key):
                        self.set_entry(role, rec[key])
            if self.on_type_change:
                self.on_type_change()
        self._set_status(t("gui.selector.recommended_applied", note=note), ok=True)
        lines = [
            t("gui.selector.recommended_applied_result"),
            f"type={rec.get('type')}",
            f"url={rec.get('url', '')}",
            f"item={rec.get('item_selector', '-')}",
            f"title={rec.get('title_selector', '-')}",
            f"link={rec.get('link_selector', '-')}",
            f"content={rec.get('content_selector', '-')}",
            f"fetch_detail={rec.get('fetch_detail_page')}",
            note,
        ]
        self._set_result("\n".join(lines))

    def _run_selector_test(self, html: str, base: str, entries: dict, field: str, selector: str) -> str:
        soup = parse_html(html, base)
        if field in ("title", "link") and (entries.get("item") or "").strip():
            item_sel = entries["item"].strip()
            try:
                items = soup.select(item_sel)
            except Exception as e:
                return t("gui.selector.item_selector_error", error=e)
            if not items:
                return t("gui.selector.item_no_match", selector=item_sel)
            lines = [t("gui.selector.item_relative", count=len(items), selector=selector)]
            hit = 0
            for i, it in enumerate(items[:8]):
                r = evaluate_selector(soup, selector, limit=1, root=it)
                if r.error:
                    lines.append(t("gui.selector.test_row_error", index=i + 1, error=r.error))
                elif r.count:
                    hit += 1
                    sample = r.samples[0].text if r.samples else ""
                    lines.append(t("gui.selector.test_row_ok", index=i + 1, sample=sample))
                else:
                    lines.append(t("gui.selector.test_row_none", index=i + 1))
            lines.append(t("gui.selector.test_summary", shown=min(8, len(items)), hit=hit))
            return "\n".join(lines)
        r = evaluate_selector(soup, selector, limit=8)
        if r.error:
            return r.error
        lines = [t("gui.selector.test_selector", selector=selector), t("gui.selector.test_match_count", count=r.count)]
        for i, s in enumerate(r.samples, 1):
            lines.append(f"  {i}. {s.text}")
        return "\n".join(lines)

    def _on_test(self) -> None:
        entries = self.get_entries()
        role = self.role_var.get()
        key_map = {
            ROLE_ITEM: "item",
            ROLE_TITLE: "title",
            ROLE_LINK: "link",
            ROLE_CONTENT: "content",
            ROLE_REMOVE: "remove",
        }
        field = key_map.get(role, "item")
        selector = (entries.get(field) or "").strip()
        if not selector:
            messagebox.showwarning(t("dialog.warning"), t("gui.selector.empty_selector"), parent=self.dialog)
            return

        if self._html:
            msg = self._run_selector_test(self._html, self._base_url, entries, field, selector)
            self._set_result(msg)
            self._set_status(t("gui.selector.test_done_cached"), ok=True)
            return

        url = self.get_url().strip()
        if not url:
            messagebox.showwarning(t("dialog.warning"), t("gui.selector.url_needed"), parent=self.dialog)
            return
        if not self._warn_private_url(url):
            return
        gen = self._begin_work(t("gui.selector.testing"))
        if gen is None:
            return

        def work():
            analysis: Optional[PageAnalysis] = None
            try:
                analysis = analyze_page(url)
                if analysis.error:
                    msg = analysis.error
                else:
                    msg = self._run_selector_test(
                        analysis.html, analysis.base_url, entries, field, selector
                    )
            except Exception as e:
                msg = t("gui.selector.test_failed", error=e)
            # 상태 갱신은 메인 스레드에서만
            self._schedule(
                gen,
                lambda: self._finish_test(msg, analysis, gen),
            )

        threading.Thread(target=work, daemon=True).start()

    def _finish_test(
        self,
        msg: str,
        analysis: Optional[PageAnalysis],
        gen: int,
    ) -> None:
        if gen != self._req_gen:
            return
        self._busy = False
        if not self._dialog_alive():
            return
        if analysis is not None and not analysis.error:
            self._html = analysis.html or ""
            self._base_url = analysis.base_url or analysis.url
            self._analysis = analysis
        self._set_result(msg)
        self._set_status(t("gui.selector.test_done"), ok=True)

    def _on_preview_scrape(self) -> None:
        snap = self.get_site_snapshot()
        if (snap.get("type") or "css") != "css":
            messagebox.showinfo(
                t("gui.selector.info_title"),
                t("gui.selector.preview_css_only"),
                parent=self.dialog,
            )
            return
        if not snap.get("url"):
            messagebox.showwarning(t("dialog.warning"), t("gui.selector.url_required"), parent=self.dialog)
            return
        if self.is_pipeline_running and self.is_pipeline_running():
            if not messagebox.askyesno(
                t("gui.selector.pipeline_busy_title"),
                t("gui.selector.pipeline_busy_body"),
                parent=self.dialog,
            ):
                return
        if not self._warn_private_url(snap["url"]):
            return
        gen = self._begin_work(t("gui.selector.preview_running"))
        if gen is None:
            return
        snap = dict(snap)
        try:
            snap["limit"] = min(int(snap.get("limit") or 3), 3)
        except (TypeError, ValueError):
            snap["limit"] = 3
        snap["type"] = "css"

        def work():
            stats_note = ""
            try:
                from websync.scrapers.css import CssSelectorScraper

                scraper = CssSelectorScraper()
                arts = scraper.fetch_articles(snap)
                stats = getattr(scraper, "last_fetch_stats", {}) or {}
                if stats.get("content_fallback_count"):
                    stats_note = t(
                        "gui.selector.content_fallback_note",
                        count=stats["content_fallback_count"],
                    )
                lines = [t("gui.selector.preview_success", count=len(arts))]
                for i, a in enumerate(arts, 1):
                    title = (a.get("title") or "")[:60]
                    url = (a.get("url") or "")[:80]
                    body = (a.get("content") or "")
                    plain = body[:120].replace("\n", " ")
                    flag = t("gui.selector.list_fallback_flag") if a.get("_content_fallback") else ""
                    lines.append(
                        t("gui.selector.preview_item", index=i, flag=flag, title=title, url=url, plain=plain)
                    )
                msg = ("\n".join(lines) if arts else t("gui.selector.preview_empty")) + stats_note
            except Exception as e:
                msg = t("gui.selector.preview_failed", error=e)
            self._schedule(gen, lambda: self._finish_preview(msg, gen))

        threading.Thread(target=work, daemon=True).start()

    def _finish_preview(self, msg: str, gen: int) -> None:
        if gen != self._req_gen:
            return
        self._busy = False
        if not self._dialog_alive():
            return
        self._set_result(msg)
        fail_prefix = t("gui.selector.preview_failed", error="").rstrip()
        ok = not msg.startswith(fail_prefix)
        warn = (
            t("gui.selector.list_fallback_flag").strip() in msg
            or t("gui.selector.content_mismatch_marker") in msg
        )
        if ok and warn:
            self._set_status(
                t("gui.selector.preview_done_fallback"),
                ok=False,
            )
        else:
            self._set_status(
                t("gui.selector.preview_done") if ok else t("gui.selector.preview_failed_status"),
                ok=ok,
            )
