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
        log("⚠️ 전송할 선택 기사가 없습니다.")
        return False

    # 락 헬퍼 통일 (N7) — preview와 동일하게 service 헬퍼 사용
    if not service._try_acquire_pipeline_locks(log):
        return False

    try:
        # 공유 데이터 폴더 pull — 본 파이프라인과 동일하게 정본 반영 (N3)
        service.maybe_backup_pull(log_callback=log)
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
        from websync.upload.device_ids import ip_to_history_key_map, resolve_pending_upload_ips

        ip_hist_map = ip_to_history_key_map(upload_targets)
        history_mode = get_portable_cfg(config).get("history_mode", "per_device")
        epub_merge_mode = config.get("epub_merge_mode", "per_site")

        if not target_ips:
            log("⚠️ 등록된 전송 기기가 없습니다. X3 주소 또는 추가 기기를 설정해 주세요.")
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
            site_name = art.get("site_name", "기타")
            articles_by_site.setdefault(site_name, []).append(art)

        # 사이트별 번역 적용 (run_sync_pipeline과 일관성 유지)
        for site_name, arts in articles_by_site.items():
            translate_to = site_translate_map.get(site_name, "")
            if translate_to and translator.is_available_for_site(translate_to):
                log(f"🌐 [{site_name}] '{translate_to}' 언어로 번역 중...")
                for art in arts:
                    art["content"] = translator.translate_html(art["content"], target_lang=translate_to)

        # AI 요약 후처리 적용
        if summarizer.is_available():
            log("🤖 AI 요약 생성 중...")
            for site_name, arts in articles_by_site.items():
                for art in arts:
                    if "summary_html" not in art:
                        art["summary_html"] = summarizer.summarize(art.get("title", ""), art.get("content", ""))

        success_count = 0
        partial_count = 0
        actual_work = len(articles_by_site)

        if epub_merge_mode == "daily_digest":
            log("\n=== 📚 선택 기사 일간 합본 빌드 및 전송 ===")
            all_urls = []
            for site_name, arts in articles_by_site.items():
                for art in arts:
                    all_urls.append((art["url"], site_name, art.get("title", "")))

            pending_ips = resolve_pending_upload_ips(
                db.is_synced_for_device,
                db.is_synced,
                [url for url, _, _ in all_urls],
                upload_targets,
                history_mode=history_mode,
            )

            if pending_ips:
                epub_path = epub_builder.build_digest(articles_by_site, generate_cover=generate_cover)
                log(f"   => 파일 생성: {os.path.basename(epub_path)}")

                upload_results = uploader.upload_to_targets(epub_path, only_ips=pending_ips)
                any_ok = upload_any_ok(upload_results)
                all_ok = upload_all_ok(upload_results, pending_ips)

                if any_ok:
                    batch = collect_mark_entries_from_triples(
                        upload_results,
                        all_urls,
                        is_synced_for_device=db.is_synced_for_device,
                        ip_to_history_key=ip_hist_map,
                    )
                    if batch:
                        db.mark_synced_many(batch)
                    if all_ok:
                        log("🎉 전송 완료!")
                        success_count = actual_work
                    else:
                        failed = [ip_to_name.get(ip, ip) for ip, ok in upload_results.items() if not ok]
                        log(f"⚠️ 일부 전송 실패: {', '.join(failed)}")
                        partial_count = 1
                else:
                    log("❌ 전송 실패!")
            else:
                log("💡 이미 모든 기기가 전송되었습니다.")
                success_count = actual_work
        else:
            # 사이트별 빌드
            for idx, (site_name, arts) in enumerate(articles_by_site.items()):
                if progress_callback:
                    progress_callback(idx, actual_work)

                pending_ips = resolve_pending_upload_ips(
                    db.is_synced_for_device,
                    db.is_synced,
                    [art["url"] for art in arts],
                    upload_targets,
                    history_mode=history_mode,
                )

                if not pending_ips:
                    log(f"💡 [{site_name}] 이미 전송 완료되어 건너뜁니다.")
                    success_count += 1
                    continue

                log(f"📚 [{site_name}] 문서 제작 및 전송 중...")
                epub_path = epub_builder.build(site_name, arts, generate_cover=generate_cover)
                upload_results = uploader.upload_to_targets(epub_path, only_ips=pending_ips)

                any_ok = upload_any_ok(upload_results)
                all_ok = upload_all_ok(upload_results, pending_ips)

                if any_ok:
                    batch = collect_mark_entries(
                        upload_results,
                        arts,
                        site_name=site_name,
                        is_synced_for_device=db.is_synced_for_device,
                        ip_to_history_key=ip_hist_map,
                    )
                    if batch:
                        db.mark_synced_many(batch)
                    if all_ok:
                        log(f"🎉 [{site_name}] 전송 성공!")
                        success_count += 1
                    else:
                        failed = [ip_to_name.get(ip, ip) for ip, ok in upload_results.items() if not ok]
                        log(f"⚠️ [{site_name}] 일부 실패: {', '.join(failed)}")
                        partial_count += 1
                else:
                    log(f"❌ [{site_name}] 전송 실패!")

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
            service.maybe_backup_push(log_callback=log_callback)
        except Exception as e:
            service.logger.warning(f"[backup] 선택 동기화 후 내보내기 실패: {e}")
        return overall_ok
    finally:
        service._release_pipeline_locks()
