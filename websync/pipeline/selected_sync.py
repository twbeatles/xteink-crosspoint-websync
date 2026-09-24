"""선택 기사 동기화 파이프라인."""
from __future__ import annotations

import copy
import os
from typing import Callable, Optional

from websync.pipeline.summarizer import Summarizer
from websync.pipeline.translator import Translator
from websync.pipeline.upload_results import (
    collect_mark_entries,
    collect_mark_entries_from_triples,
    upload_all_ok,
    upload_any_ok,
)
from websync.i18n import t


def sync_selected_articles(
    service,
    selected_articles: list[dict],
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> bool:
    """
    사용자가 선택한 기사만 EPUB으로 빌드하여 기기로 전송합니다.
    
    Args:
        selected_articles: [{"site_name": str, "title": str, "url": str, "content": str}]
    """
    def log(msg: str):
        service.logger.info(msg)
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    if not selected_articles:
        log(t("pipeline.selected.none"))
        return False

    # 락 헬퍼 통일 (N7) — preview와 동일하게 service 헬퍼 사용
    if not service._try_acquire_pipeline_locks(log):
        return False

    try:
        # 공유 데이터 폴더 pull — 본 파이프라인과 동일하게 정본 반영 (N3)
        pull_result = service.maybe_backup_pull(log_callback=log)
        if pull_result.get("ok") is False:
            service._last_pipeline_result = {
                "status": "backup_pull_failed",
                "success": False,
                "message": pull_result.get("message", ""),
            }
            return False
        service._reload_config()
        config = copy.deepcopy(service.config)
        uploader = service.uploader
        epub_builder = service.epub_builder
        db = service.db
        generate_cover = config.get("epub_cover", True)
        upload_targets = uploader._build_target_list()
        target_ips = [d["ip"] for d in upload_targets]
        ip_to_name = {d["ip"]: d["name"] for d in upload_targets}
        from websync.backup.portable_cfg import get_portable_cfg
        from websync.upload.device_ids import (
            group_articles_by_pending_targets,
            ip_to_history_key_map,
        )

        ip_hist_map = ip_to_history_key_map(upload_targets)
        history_mode = get_portable_cfg(config).get("history_mode", "per_device")
        epub_merge_mode = config.get("epub_merge_mode", "per_site")

        if not target_ips:
            log(t("pipeline.no_targets"))
            service._last_pipeline_result = {"status": "no_targets", "success": False}
            return False

        summarizer = Summarizer(config, logger=service.logger)
        translator = Translator(config, logger=service.logger)

        # site_name → translate_to 매핑 구성 (config sites에서 조회)
        site_translate_map: dict[str, str] = {}
        for site_cfg in config.get("sites", []):
            sname = site_cfg.get("name", "")
            if sname:
                site_translate_map[sname] = site_cfg.get("translate_to", "").strip()

        # site_name 별로 기사 그룹화
        articles_by_site = {}
        for art in selected_articles:
            site_name = art.get("site_name", t("pipeline.selected.other_site"))
            articles_by_site.setdefault(site_name, []).append(art)

        # 사이트별 번역 적용 (run_sync_pipeline과 일관성 유지)
        for site_name, arts in articles_by_site.items():
            translate_to = site_translate_map.get(site_name, "")
            if translate_to and translator.is_available_for_site(translate_to):
                log(t("pipeline.selected.translate", site=site_name, lang=translate_to))
                for art in arts:
                    art["content"] = translator.translate_html(art["content"], target_lang=translate_to)

        # AI 요약 후처리 적용
        if summarizer.is_available():
            log(t("pipeline.selected.summarize"))
            for site_name, arts in articles_by_site.items():
                for art in arts:
                    if "summary_html" not in art:
                        art["summary_html"] = summarizer.summarize(art.get("title", ""), art.get("content", ""))

        success_count = 0
        partial_count = 0
        actual_work = len(articles_by_site)

        if epub_merge_mode == "daily_digest":
            log(t("pipeline.selected.digest_start"))
            all_urls = []
            for site_name, arts in articles_by_site.items():
                for art in arts:
                    all_urls.append((art["url"], site_name, art.get("title", "")))

            digest_flat = []
            for digest_site_name, arts in articles_by_site.items():
                for art in arts:
                    item = dict(art)
                    item["_digest_site_name"] = digest_site_name
                    digest_flat.append(item)
            upload_batches = group_articles_by_pending_targets(
                db.is_synced_for_device,
                db.is_synced,
                digest_flat,
                upload_targets,
                history_mode=history_mode,
            )
            pending_ips = [ip for ips, _articles in upload_batches for ip in ips]

            if pending_ips:
                upload_results: dict[str, bool] = {}
                if getattr(service, "is_cancel_requested", lambda: False)():
                    log(t("pipeline.cancelled"))
                    service._last_pipeline_result = {"status": "cancelled", "success": False}
                    return False
                for batch_ips, batch_articles in upload_batches:
                    if getattr(service, "is_cancel_requested", lambda: False)():
                        log(t("pipeline.cancelled"))
                        service._last_pipeline_result = {"status": "cancelled", "success": False}
                        return False
                    batch_by_site: dict[str, list[dict]] = {}
                    batch_urls: list[tuple[str, str, str]] = []
                    for art in batch_articles:
                        site_name = art.get("_digest_site_name") or ""
                        clean_art = {k: v for k, v in art.items() if k != "_digest_site_name"}
                        batch_by_site.setdefault(site_name, []).append(clean_art)
                        batch_urls.append(
                            (art.get("url") or "", site_name, art.get("title") or "")
                        )
                    epub_path = epub_builder.build_digest(
                        batch_by_site, generate_cover=generate_cover
                    )
                    log(t("pipeline.file_created", filename=os.path.basename(epub_path)))
                    batch_results = uploader.upload_to_targets(epub_path, only_ips=batch_ips)
                    upload_results.update(batch_results)
                    mark_batch = collect_mark_entries_from_triples(
                        batch_results,
                        batch_urls,
                        is_synced_for_device=db.is_synced_for_device,
                        ip_to_history_key=ip_hist_map,
                    )
                    if mark_batch:
                        db.mark_synced_many(mark_batch)
                any_ok = upload_any_ok(upload_results)
                all_ok = upload_all_ok(upload_results, pending_ips)

                if any_ok:
                    if all_ok:
                        log(t("pipeline.selected.upload_ok"))
                        success_count = actual_work
                    else:
                        failed = [ip_to_name.get(ip, ip) for ip, ok in upload_results.items() if not ok]
                        log(t("pipeline.selected.partial", names=", ".join(failed)))
                        partial_count = 1
                else:
                    log(t("pipeline.selected.upload_fail"))
            else:
                log(t("pipeline.selected.already_sent_all"))
                success_count = actual_work
        else:
            # 사이트별 빌드
            for idx, (site_name, arts) in enumerate(articles_by_site.items()):
                if getattr(service, "is_cancel_requested", lambda: False)():
                    log(t("pipeline.cancelled"))
                    service._last_pipeline_result = {"status": "cancelled", "success": False}
                    return False
                if progress_callback:
                    progress_callback(idx, actual_work)

                upload_batches = group_articles_by_pending_targets(
                    db.is_synced_for_device,
                    db.is_synced,
                    arts,
                    upload_targets,
                    history_mode=history_mode,
                )
                pending_ips = [ip for ips, _articles in upload_batches for ip in ips]

                if not pending_ips:
                    log(t("pipeline.selected.already_sent_site", site=site_name))
                    success_count += 1
                    continue

                log(t("pipeline.selected.building", site=site_name))
                upload_results: dict[str, bool] = {}
                if getattr(service, "is_cancel_requested", lambda: False)():
                    log(t("pipeline.cancelled"))
                    service._last_pipeline_result = {"status": "cancelled", "success": False}
                    return False
                for batch_ips, batch_articles in upload_batches:
                    if getattr(service, "is_cancel_requested", lambda: False)():
                        log(t("pipeline.cancelled"))
                        service._last_pipeline_result = {"status": "cancelled", "success": False}
                        return False
                    epub_path = epub_builder.build(
                        site_name, batch_articles, generate_cover=generate_cover
                    )
                    batch_results = uploader.upload_to_targets(epub_path, only_ips=batch_ips)
                    upload_results.update(batch_results)
                    mark_batch = collect_mark_entries(
                        batch_results,
                        batch_articles,
                        site_name=site_name,
                        is_synced_for_device=db.is_synced_for_device,
                        ip_to_history_key=ip_hist_map,
                    )
                    if mark_batch:
                        db.mark_synced_many(mark_batch)

                any_ok = upload_any_ok(upload_results)
                all_ok = upload_all_ok(upload_results, pending_ips)

                if any_ok:
                    if all_ok:
                        log(t("pipeline.selected.site_ok", site=site_name))
                        success_count += 1
                    else:
                        failed = [ip_to_name.get(ip, ip) for ip, ok in upload_results.items() if not ok]
                        log(t("pipeline.selected.site_partial", site=site_name, names=", ".join(failed)))
                        partial_count += 1
                else:
                    log(t("pipeline.selected.site_fail", site=site_name))

        if progress_callback:
            progress_callback(actual_work, actual_work)

        overall_ok = success_count == actual_work and partial_count == 0
        service._last_pipeline_result = {
            "status": "completed",
            "success": overall_ok,
            "success_count": success_count,
            "partial_count": partial_count,
            "actual_work_sites": actual_work,
            "site_errors": 0,
        }
        try:
            push_result = service.maybe_backup_push(log_callback=log_callback)
            if push_result.get("ok") is False:
                service._last_pipeline_result = {
                    **service._last_pipeline_result,
                    "status": "backup_push_failed",
                    "success": False,
                    "backup_push": push_result,
                }
                return False
        except Exception as e:
            service.logger.warning(t("pipeline.selected.backup_push_fail", error=e))
            service._last_pipeline_result = {
                **service._last_pipeline_result,
                "status": "backup_push_failed",
                "success": False,
                "message": str(e),
            }
            return False
        return overall_ok
    finally:
        service._release_pipeline_locks()
