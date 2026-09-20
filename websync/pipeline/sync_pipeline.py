"""전체 사이트 동기화 파이프라인 실행."""
from __future__ import annotations

import copy
import os
from typing import Callable, Optional

from websync.scrapers import ScraperFactory
from websync.scrapers.base import is_allowed_fetch_url
from websync.integrations.notifier import ToastNotifier
from websync.db.history import SyncHistoryDbError
from websync.pipeline.summarizer import Summarizer
from websync.pipeline.translator import Translator
from websync.pipeline.article_keys import article_sync_key
from websync.backup.portable_cfg import get_portable_cfg
from websync.upload.device_ids import (
    alias_key_groups,
    group_articles_by_pending_targets,
    history_keys_from_targets,
    ip_to_history_key_map,
)
from websync.pipeline.upload_results import (
    collect_mark_entries,
    collect_mark_entries_from_triples,
    upload_all_ok,
    upload_any_ok,
)
from websync.i18n import t

def run_sync_pipeline_locked(
    service,
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> bool:
    def log(msg: str):
        service.logger.info(msg)
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    log(t("pipeline.start"))
    if hasattr(service, "clear_cancel"):
        service.clear_cancel()
    service._reload_config()

    # 한 번의 실행은 시작 시점의 설정과 구성요소를 일관되게 사용합니다.
    config = copy.deepcopy(service.config)
    uploader = service.uploader
    epub_builder = service.epub_builder
    db = service.db

    summarizer = Summarizer(config, logger=service.logger)
    translator = Translator(config, logger=service.logger)

    enabled_sites = [s for s in config.get("sites", []) if s.get("enabled", True)]
    if not enabled_sites:
        log(t("pipeline.no_enabled_sites"))
        ToastNotifier.show_toast(t("toast.fail_title"), t("toast.no_sites"), is_error=True)
        service._last_pipeline_result = {"status": "no_sites", "success": False}
        return False

    total_sites = len(enabled_sites)
    success_count = 0
    partial_count = 0
    actual_work_sites = 0
    site_errors = 0
    empty_fetch_sites = 0
    generate_cover = config.get("epub_cover", True)
    upload_targets = uploader._build_target_list()
    target_ips = [d["ip"] for d in upload_targets]
    target_history_keys = history_keys_from_targets(upload_targets)
    key_aliases = alias_key_groups(upload_targets)
    ip_to_name = {d["ip"]: d["name"] for d in upload_targets}
    ip_hist_map = ip_to_history_key_map(upload_targets)
    history_mode = get_portable_cfg(config).get("history_mode", "per_device")
    log(t("pipeline.history_mode", mode=history_mode))

    if not target_ips:
        log(t("pipeline.no_targets"))
        ToastNotifier.show_toast(
            t("toast.fail_title"),
            t("toast.no_targets"),
            is_error=True,
        )
        service._last_pipeline_result = {"status": "no_targets", "success": False}
        return False

    # 레거시 device_ip='*' 이력을 기본 기기 이력 키로 1회 이관
    try:
        legacy_key = target_history_keys[0] if target_history_keys else target_ips[0]
        remapped = db.remap_legacy_star_to_device(legacy_key)
        if remapped:
            log(t(
                "pipeline.legacy_remap",
                n=remapped,
                device=ip_to_name.get(target_ips[0], target_ips[0]),
            ))
    except SyncHistoryDbError as e:
        log(t("pipeline.legacy_remap_fail", error=e))

    epub_merge_mode = config.get("epub_merge_mode", "per_site")
    digest_articles = {}  # {site_name: [new_articles]}
    # 합본(daily_digest) 모드 전용 결과 플래그 — per_site 카운터와 분리 (N1)
    digest_success = False
    digest_partial = False
    digest_attempted = False

    for site_idx, site in enumerate(enabled_sites):
        name = site.get("name", t("pipeline.unnamed_site"))
        scraper_type = site.get("type", "css")
        base_url = site.get("url", "")
        translate_to = site.get("translate_to", "").strip()

        if getattr(service, "is_cancel_requested", lambda: False)():
            log(t("pipeline.cancelled"))
            service._last_pipeline_result = {"status": "cancelled", "success": False}
            ToastNotifier.show_toast(t("toast.cancel_title"), t("toast.cancelled"), is_error=True)
            return False

        if not is_allowed_fetch_url(base_url):
            site_errors += 1
            log(t("pipeline.skip_bad_url", site=name, url=(base_url or "")[:80]))
            continue

        if progress_callback:
            progress_callback(site_idx, total_sites)

        log(t("pipeline.scraping", site=name, type=scraper_type.upper()))
        try:
            scraper = ScraperFactory.get_scraper(scraper_type)
            articles = scraper.fetch_articles(site)

            fetch_stats = getattr(scraper, "last_fetch_stats", None) or {}
            skipped_items = int(fetch_stats.get("skipped", 0) or 0)
            if skipped_items:
                log(t("pipeline.skip_items", n=skipped_items))

            if not articles:
                empty_fetch_sites += 1
                log(t("pipeline.no_articles", site=name))
                continue

            for art in articles:
                art["url"] = article_sync_key(art, name, base_url)

            new_articles = []
            for art in articles:
                url = art.get("url")
                if not url:
                    continue
                if db.needs_sync(
                    url,
                    target_history_keys,
                    history_mode=history_mode,
                    key_aliases=key_aliases,
                ):
                    new_articles.append(art)

            skipped = len(articles) - len(new_articles)
            if skipped:
                log(t("pipeline.dup_skip", n=skipped))

            if not new_articles:
                log(t("pipeline.no_new_posts", site=name))
                continue

            actual_work_sites += 1
            log(t("pipeline.new_posts", site=name, n=len(new_articles)))

            if translate_to and translator.is_available_for_site(translate_to):
                log(t("pipeline.translate_site", site=name, lang=translate_to))
                for art in new_articles:
                    art["content"] = translator.translate_html(art["content"], target_lang=translate_to)

            if summarizer.is_available():
                log(t("pipeline.summarize_site", site=name))
                for art in new_articles:
                    art["summary_html"] = summarizer.summarize(art.get("title", ""), art.get("content", ""))

            if epub_merge_mode == "daily_digest":
                # 일간 합본을 위해 기사를 축적
                digest_articles[name] = new_articles
                log(t("pipeline.digest_queued", site=name, n=len(new_articles)))
            else:
                # 기존 방식: 사이트별 개별 빌드 및 전송
                # 이번 배치 중 하나라도 미전송인 기기만 업로드 대상
                upload_batches = group_articles_by_pending_targets(
                    db.is_synced_for_device,
                    db.is_synced,
                    new_articles,
                    upload_targets,
                    history_mode=history_mode,
                )
                pending_ips = [ip for ips, _articles in upload_batches for ip in ips]

                if not pending_ips:
                    log(t("pipeline.no_pending_devices", site=name))
                    continue

                if len(pending_ips) < len(target_ips):
                    names = [ip_to_name.get(ip, ip) for ip in pending_ips]
                    log(t("pipeline.pending_devices_only", names=", ".join(names)))

                upload_results: dict[str, bool] = {}
                for batch_ips, batch_articles in upload_batches:
                    log(t("pipeline.building_epub", site=name))
                    epub_path = epub_builder.build(
                        name, batch_articles, generate_cover=generate_cover
                    )
                    log(t("pipeline.file_created", filename=os.path.basename(epub_path)))
                    batch_results = uploader.upload_to_targets(epub_path, only_ips=batch_ips)
                    upload_results.update(batch_results)
                    mark_batch = collect_mark_entries(
                        batch_results,
                        batch_articles,
                        site_name=name,
                        is_synced_for_device=db.is_synced_for_device,
                        ip_to_history_key=ip_hist_map,
                    )
                    if mark_batch:
                        db.mark_synced_many(mark_batch)
                for ip, ok in upload_results.items():
                    status = "✅" if ok else "❌"
                    detail = ""
                    if not ok:
                        err = getattr(uploader, "last_errors", {}).get(ip)
                        if err:
                            detail = t("pipeline.upload_detail", error=err)
                    log(t(
                        "pipeline.upload_result",
                        status=status,
                        device=ip_to_name.get(ip, ip),
                        ip=ip,
                        detail=detail,
                    ))

                any_ok = upload_any_ok(upload_results)
                all_ok = upload_all_ok(upload_results, pending_ips)

                if any_ok:
                    if all_ok:
                        log(t("pipeline.site_sync_ok", site=name))
                        success_count += 1
                    else:
                        failed = [ip_to_name.get(ip, ip) for ip, ok in upload_results.items() if not ok]
                        log(t("pipeline.site_partial", site=name, names=", ".join(failed)))
                        partial_count += 1
                else:
                    log(t("pipeline.site_upload_fail", site=name))

        except SyncHistoryDbError as e:
            service.logger.error(str(e))
            log(t("pipeline.db_error", site=name, error=e))
            service._last_pipeline_result = {"status": "db_error", "success": False, "message": str(e)}
            ToastNotifier.show_toast(t("toast.db_error_title"), str(e), is_error=True)
            return False
        except Exception as e:
            site_errors += 1
            service.logger.exception(t("pipeline.site_error_log", site=name, error=e))
            log(t("pipeline.site_error", site=name, error=e))

    # 일간 합본 처리 진행 (epub_merge_mode == "daily_digest" 일 경우)
    if epub_merge_mode == "daily_digest" and digest_articles:
        log(t("pipeline.digest.start"))
        digest_attempted = True
        try:
            # 모든 축적된 기사의 URL 목록
            all_new_urls = []
            for site_name, arts in digest_articles.items():
                for art in arts:
                    all_new_urls.append((art["url"], site_name, art.get("title", "")))

            # 이번 배치 기사 중 미전송된 기기가 있는 기기 추출
            digest_flat = []
            for digest_site_name, arts in digest_articles.items():
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
                log(t(
                    "pipeline.digest.building",
                    sites=len(digest_articles),
                    articles=len(all_new_urls),
                ))
                upload_results: dict[str, bool] = {}
                for batch_ips, batch_articles in upload_batches:
                    batch_by_site: dict[str, list[dict]] = {}
                    batch_triples: list[tuple[str, str, str]] = []
                    for art in batch_articles:
                        site_name = art.get("_digest_site_name") or ""
                        clean_art = {k: v for k, v in art.items() if k != "_digest_site_name"}
                        batch_by_site.setdefault(site_name, []).append(clean_art)
                        batch_triples.append(
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
                        batch_triples,
                        is_synced_for_device=db.is_synced_for_device,
                        ip_to_history_key=ip_hist_map,
                    )
                    if mark_batch:
                        db.mark_synced_many(mark_batch)
                for ip, ok in upload_results.items():
                    status = "✅" if ok else "❌"
                    detail = ""
                    if not ok:
                        err = getattr(uploader, "last_errors", {}).get(ip)
                        if err:
                            detail = t("pipeline.upload_detail", error=err)
                    log(t(
                        "pipeline.upload_result",
                        status=status,
                        device=ip_to_name.get(ip, ip),
                        ip=ip,
                        detail=detail,
                    ))

                any_ok = upload_any_ok(upload_results)
                all_ok = upload_all_ok(upload_results, pending_ips)

                if any_ok:
                    if all_ok:
                        log(t("pipeline.digest.ok"))
                        digest_success = True
                    else:
                        failed = [ip_to_name.get(ip, ip) for ip, ok in upload_results.items() if not ok]
                        log(t("pipeline.digest.partial", names=", ".join(failed)))
                        digest_partial = True
                else:
                    log(t("pipeline.digest.upload_fail"))
            else:
                # target_ips 는 위에서 비어 있지 않음 → pending 없음 = 이미 전 기기 전송 완료
                log(t("pipeline.digest.already_sent"))
                digest_success = True

        except Exception as e:
            service.logger.exception(t("pipeline.digest.error_log", error=e))
            log(t("pipeline.digest.error", error=e))
            site_errors += 1

    if progress_callback:
        progress_callback(total_sites, total_sites)

    # 합본 모드는 단일 업로드 결과로 성공 판정 (N1 — per_site 카운터와 분리)
    if epub_merge_mode == "daily_digest" and digest_attempted:
        overall_ok = digest_success and site_errors == 0
        service._last_pipeline_result = {
            "status": "completed",
            "success": overall_ok,
            "merge_mode": "daily_digest",
            "digest_success": digest_success,
            "digest_partial": digest_partial,
            "site_count": len(digest_articles),
            "site_errors": site_errors,
        }
        if overall_ok:
            ToastNotifier.show_toast(
                t("toast.done_title"),
                t("toast.digest_done", n=len(digest_articles)),
            )
        elif digest_partial:
            ToastNotifier.show_toast(
                t("toast.partial_title"),
                t("toast.digest_partial"),
                is_error=True,
            )
        else:
            ToastNotifier.show_toast(
                t("toast.fail_sync_title"),
                t("toast.digest_fail"),
                is_error=True,
            )
        return overall_ok

    if actual_work_sites == 0:
        if site_errors > 0:
            log(t("pipeline.summary.errors", n=site_errors))
            ToastNotifier.show_toast(
                t("toast.fail_sync_title"),
                t("toast.sites_error", n=site_errors),
                is_error=True,
            )
            service._last_pipeline_result = {"status": "errors", "success": False, "site_errors": site_errors}
            return False
        if empty_fetch_sites == total_sites:
            log(t("pipeline.summary.empty_fetch", n=total_sites))
            ToastNotifier.show_toast(
                t("toast.fail_sync_title"),
                t("toast.empty_fetch"),
                is_error=True,
            )
            service._last_pipeline_result = {
                "status": "empty_fetch",
                "success": False,
                "empty_fetch_sites": empty_fetch_sites,
            }
            return False
        log(t("pipeline.summary.no_new"))
        ToastNotifier.show_toast(
            t("toast.status_title"),
            t("toast.no_new"),
        )
        service._last_pipeline_result = {"status": "no_new", "success": True}
        return True

    log(t("pipeline.summary.done", ok=success_count, total=actual_work_sites) +
        (t("pipeline.summary.partial_suffix", n=partial_count) if partial_count else ""))

    overall_ok = success_count == actual_work_sites and site_errors == 0
    service._last_pipeline_result = {
        "status": "completed",
        "success": overall_ok,
        "merge_mode": "per_site",
        "success_count": success_count,
        "partial_count": partial_count,
        "actual_work_sites": actual_work_sites,
        "site_errors": site_errors,
    }

    if success_count > 0 and overall_ok:
        ToastNotifier.show_toast(
            t("toast.done_title"),
            t("toast.sites_done", n=success_count),
        )
    elif partial_count > 0:
        ToastNotifier.show_toast(
            t("toast.partial_title"),
            t("toast.partial", n=partial_count),
            is_error=True,
        )
    else:
        ToastNotifier.show_toast(
            t("toast.fail_sync_title"),
            t("toast.sync_fail"),
            is_error=True,
        )

    return overall_ok
