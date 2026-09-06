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
    history_keys_from_targets,
    ip_to_history_key_map,
    resolve_pending_upload_ips,
)
from websync.pipeline.upload_results import (
    collect_mark_entries,
    collect_mark_entries_from_triples,
    upload_all_ok,
    upload_any_ok,
)

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

    log("✨ 동기화 프로세스를 실행합니다...")
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
        log("⚠️ 활성화된 수집 대상 사이트가 설정에 없습니다.")
        ToastNotifier.show_toast("X3 WebSync 실패", "동기화가 중단되었습니다. 활성화된 사이트가 없습니다.", is_error=True)
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
    log(f"📋 이력 모드: {history_mode}")

    if not target_ips:
        log("⚠️ 등록된 전송 기기가 없습니다. X3 주소 또는 추가 기기를 설정해 주세요.")
        ToastNotifier.show_toast(
            "X3 WebSync 실패",
            "전송 대상 기기가 없습니다. 기기 주소를 확인해 주세요.",
            is_error=True,
        )
        service._last_pipeline_result = {"status": "no_targets", "success": False}
        return False

    # 레거시 device_ip='*' 이력을 기본 기기 이력 키로 1회 이관
    try:
        legacy_key = target_history_keys[0] if target_history_keys else target_ips[0]
        remapped = db.remap_legacy_star_to_device(legacy_key)
        if remapped:
            log(f"🔄 레거시 동기화 이력 {remapped}건을 [{ip_to_name.get(target_ips[0], target_ips[0])}]로 이관했습니다.")
    except SyncHistoryDbError as e:
        log(f"⚠️ 레거시 이력 이관 실패(계속 진행): {e}")

    epub_merge_mode = config.get("epub_merge_mode", "per_site")
    digest_articles = {}  # {site_name: [new_articles]}
    # 합본(daily_digest) 모드 전용 결과 플래그 — per_site 카운터와 분리 (N1)
    digest_success = False
    digest_partial = False
    digest_attempted = False

    for site_idx, site in enumerate(enabled_sites):
        name = site.get("name", "무명 사이트")
        scraper_type = site.get("type", "css")
        base_url = site.get("url", "")
        translate_to = site.get("translate_to", "").strip()

        if getattr(service, "is_cancel_requested", lambda: False)():
            log("⏹ 사용자에 의해 동기화가 취소되었습니다.")
            service._last_pipeline_result = {"status": "cancelled", "success": False}
            ToastNotifier.show_toast("X3 WebSync 취소", "동기화가 취소되었습니다.", is_error=True)
            return False

        if not is_allowed_fetch_url(base_url):
            site_errors += 1
            log(f"⚠️ [{name}] URL이 http(s)가 아니어서 건너뜁니다: {(base_url or '')[:80]}")
            continue

        if progress_callback:
            progress_callback(site_idx, total_sites)

        log(f"\n[📰 {name}] ({scraper_type.upper()}) 글 수집 중...")
        try:
            scraper = ScraperFactory.get_scraper(scraper_type)
            articles = scraper.fetch_articles(site)

            fetch_stats = getattr(scraper, "last_fetch_stats", None) or {}
            skipped_items = int(fetch_stats.get("skipped", 0) or 0)
            if skipped_items:
                log(f"   => ⚠️ 수집 중 개별 스킵 {skipped_items}건 (본문·자막 실패 등)")

            if not articles:
                empty_fetch_sites += 1
                log(f"⚠️ [{name}] 수집된 기사가 없어 건너뜁니다. (URL·스크래퍼 설정·네트워크를 확인하세요)")
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
                log(f"   => 💡 중복 제외 {skipped}건 (이미 전송된 포스트)")

            if not new_articles:
                log(f"   => 💡 [{name}] 전송할 신규 포스트가 없습니다.")
                continue

            actual_work_sites += 1
            log(f"📦 [{name}] 신규 포스트 {len(new_articles)}개 검출. 후처리 중...")

            if translate_to and translator.is_available_for_site(translate_to):
                log(f"   => 🌐 [{name}] '{translate_to}' 언어로 번역 중...")
                for art in new_articles:
                    art["content"] = translator.translate_html(art["content"], target_lang=translate_to)

            if summarizer.is_available():
                log(f"   => 🤖 [{name}] AI 요약 생성 중...")
                for art in new_articles:
                    art["summary_html"] = summarizer.summarize(art.get("title", ""), art.get("content", ""))

            if epub_merge_mode == "daily_digest":
                # 일간 합본을 위해 기사를 축적
                digest_articles[name] = new_articles
                log(f"   => 💡 [{name}] 합본 대기열에 추가됨 ({len(new_articles)}건)")
            else:
                # 기존 방식: 사이트별 개별 빌드 및 전송
                # 이번 배치 중 하나라도 미전송인 기기만 업로드 대상
                pending_ips = resolve_pending_upload_ips(
                    db.is_synced_for_device,
                    db.is_synced,
                    [art["url"] for art in new_articles],
                    upload_targets,
                    history_mode=history_mode,
                )

                if not pending_ips:
                    log(f"   => 💡 [{name}] 전송할 대상 기기가 없습니다.")
                    continue

                if len(pending_ips) < len(target_ips):
                    names = [ip_to_name.get(ip, ip) for ip in pending_ips]
                    log(f"   => 📡 미전송 기기만 전송: {', '.join(names)}")

                log(f"📚 [{name}] EPUB 문서 제작 중...")
                epub_path = epub_builder.build(name, new_articles, generate_cover=generate_cover)
                log(f"   => 파일 생성: {os.path.basename(epub_path)}")

                upload_results = uploader.upload_to_targets(epub_path, only_ips=pending_ips)
                for ip, ok in upload_results.items():
                    status = "✅" if ok else "❌"
                    detail = ""
                    if not ok:
                        err = getattr(uploader, "last_errors", {}).get(ip)
                        if err:
                            detail = f" — {err}"
                    log(f"   => {status} [{ip_to_name.get(ip, ip)}] ({ip}) 전송{detail}")

                any_ok = upload_any_ok(upload_results)
                all_ok = upload_all_ok(upload_results, pending_ips)

                if any_ok:
                    batch = collect_mark_entries(
                        upload_results,
                        new_articles,
                        site_name=name,
                        is_synced_for_device=db.is_synced_for_device,
                        ip_to_history_key=ip_hist_map,
                    )
                    if batch:
                        db.mark_synced_many(batch)
                    if all_ok:
                        log(f"🎉 [{name}] 동기화 완료 및 전송 성공!")
                        success_count += 1
                    else:
                        failed = [ip_to_name.get(ip, ip) for ip, ok in upload_results.items() if not ok]
                        log(
                            f"⚠️ [{name}] 일부 기기 전송 실패: {', '.join(failed)} "
                            f"(성공 기기만 이력 기록, 실패 기기는 다음 동기화에서 재시도)"
                        )
                        partial_count += 1
                else:
                    log(f"❌ [{name}] 전송 실패! 기기가 켜져 있고 Wi-Fi 상태인지 확인하세요.")

        except SyncHistoryDbError as e:
            service.logger.error(str(e))
            log(f"❌ [{name}] DB 오류로 중단: {e}")
            service._last_pipeline_result = {"status": "db_error", "success": False, "message": str(e)}
            ToastNotifier.show_toast("X3 WebSync DB 오류", str(e), is_error=True)
            return False
        except Exception as e:
            site_errors += 1
            service.logger.exception(f"[{name}] 처리 중 오류: {e}")
            log(f"❌ [{name}] 처리 중 오류 발생: {e}")

    # 일간 합본 처리 진행 (epub_merge_mode == "daily_digest" 일 경우)
    if epub_merge_mode == "daily_digest" and digest_articles:
        log("\n=== 📚 일간 합본(Daily Digest) 빌드 및 전송 시작 ===")
        digest_attempted = True
        try:
            # 모든 축적된 기사의 URL 목록
            all_new_urls = []
            for site_name, arts in digest_articles.items():
                for art in arts:
                    all_new_urls.append((art["url"], site_name, art.get("title", "")))

            # 이번 배치 기사 중 미전송된 기기가 있는 기기 추출
            pending_ips = resolve_pending_upload_ips(
                db.is_synced_for_device,
                db.is_synced,
                [url for url, _, _ in all_new_urls],
                upload_targets,
                history_mode=history_mode,
            )

            if pending_ips:
                log(f"📚 합본 문서 제작 중... (총 {len(digest_articles)}개 사이트, {len(all_new_urls)}개 기사)")
                epub_path = epub_builder.build_digest(digest_articles, generate_cover=generate_cover)
                log(f"   => 파일 생성: {os.path.basename(epub_path)}")

                upload_results = uploader.upload_to_targets(epub_path, only_ips=pending_ips)
                for ip, ok in upload_results.items():
                    status = "✅" if ok else "❌"
                    detail = ""
                    if not ok:
                        err = getattr(uploader, "last_errors", {}).get(ip)
                        if err:
                            detail = f" — {err}"
                    log(f"   => {status} [{ip_to_name.get(ip, ip)}] ({ip}) 전송{detail}")

                any_ok = upload_any_ok(upload_results)
                all_ok = upload_all_ok(upload_results, pending_ips)

                if any_ok:
                    batch = collect_mark_entries_from_triples(
                        upload_results,
                        all_new_urls,
                        is_synced_for_device=db.is_synced_for_device,
                        ip_to_history_key=ip_hist_map,
                    )
                    if batch:
                        db.mark_synced_many(batch)
                    if all_ok:
                        log("🎉 일간 합본 동기화 완료 및 전송 성공!")
                        digest_success = True
                    else:
                        failed = [ip_to_name.get(ip, ip) for ip, ok in upload_results.items() if not ok]
                        log(f"⚠️ 일간 합본 일부 기기 전송 실패: {', '.join(failed)}")
                        digest_partial = True
                else:
                    log("❌ 일간 합본 전송 실패! 기기 상태를 확인하세요.")
            else:
                # target_ips 는 위에서 비어 있지 않음 → pending 없음 = 이미 전 기기 전송 완료
                log("💡 합본 대상 기사가 이미 모든 기기에 전송되어 합본 생성을 건너뜁니다.")
                digest_success = True

        except Exception as e:
            service.logger.exception(f"일간 합본 처리 중 오류: {e}")
            log(f"❌ 일간 합본 처리 중 오류 발생: {e}")
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
                "X3 WebSync 동기화 완료",
                f"{len(digest_articles)}개 사이트 소식이 일간 합본으로 무선 전송되었습니다."
            )
        elif digest_partial:
            ToastNotifier.show_toast(
                "X3 WebSync 부분 완료",
                "일간 합본이 일부 기기에만 전송되었습니다. 로그를 확인하세요.",
                is_error=True,
            )
        else:
            ToastNotifier.show_toast(
                "X3 WebSync 동기화 실패",
                "일간 합본 전송 과정에 오류가 발생했습니다. (기기 연결 상태 확인 요망)",
                is_error=True,
            )
        return overall_ok

    if actual_work_sites == 0:
        if site_errors > 0:
            log(f"\n📊 작업 결과 요약: {site_errors}개 사이트에서 오류 발생. 로그를 확인하세요.")
            ToastNotifier.show_toast(
                "X3 WebSync 동기화 실패",
                f"{site_errors}개 사이트 처리 중 오류가 발생했습니다.",
                is_error=True,
            )
            service._last_pipeline_result = {"status": "errors", "success": False, "site_errors": site_errors}
            return False
        if empty_fetch_sites == total_sites:
            log(
                f"\n📊 작업 결과 요약: 활성 사이트 {total_sites}개 모두 수집 결과가 비었습니다. "
                "스크래퍼 설정·네트워크·의존성 패키지를 확인하세요."
            )
            ToastNotifier.show_toast(
                "X3 WebSync 동기화 실패",
                "모든 사이트에서 기사를 수집하지 못했습니다. 로그를 확인하세요.",
                is_error=True,
            )
            service._last_pipeline_result = {
                "status": "empty_fetch",
                "success": False,
                "empty_fetch_sites": empty_fetch_sites,
            }
            return False
        log("\n📊 작업 결과 요약: 모든 등록 사이트에 전송할 신규 포스트가 없습니다. (기기 전송 생략)")
        ToastNotifier.show_toast(
            "X3 WebSync 상태",
            "모든 뉴스 사이트/블로그에 새로 업로드된 신규 기사가 없어 전송을 생략했습니다."
        )
        service._last_pipeline_result = {"status": "no_new", "success": True}
        return True

    log(f"\n📊 작업 결과 요약: {success_count} / {actual_work_sites} 개 사이트 전체 전송 완료" +
        (f", {partial_count}개 부분 성공" if partial_count else ""))

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
            "X3 WebSync 동기화 완료",
            f"신규 업데이트된 {success_count}개 사이트 소식이 무선 전송되었습니다."
        )
    elif partial_count > 0:
        ToastNotifier.show_toast(
            "X3 WebSync 부분 완료",
            f"{partial_count}개 사이트가 일부 기기에만 전송되었습니다. 로그를 확인하세요.",
            is_error=True,
        )
    else:
        ToastNotifier.show_toast(
            "X3 WebSync 동기화 실패",
            "신규 포스트 전송 과정에 오류가 발생했습니다. (기기 연결 상태 확인 요망)",
            is_error=True
        )

    return overall_ok
