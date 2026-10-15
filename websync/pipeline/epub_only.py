"""선택 기사로 EPUB 파일만 만든다 (기기 전송·이력 기록 없음).

프리뷰 창의 "EPUB만 만들기" — 전송 전에 결과물(글꼴·테마·표지)을 확인하는 용도.
번역·AI 요약은 외부 API 비용이 드므로 실제 전송 시에만 적용한다.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from websync.i18n import t
from websync.pipeline.sources import selected_source_groups


def build_selected_epubs(
    service,
    selected_articles: list[dict],
    log_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> list[str]:
    """선택 기사를 현재 EPUB 설정(병합 방식·테마·표지)으로 빌드하고 파일 경로 목록을 반환."""

    def log(msg: str) -> None:
        service.logger.info(msg)
        if log_callback:
            log_callback(msg)

    if not selected_articles:
        log(t("pipeline.selected.none"))
        return []

    if not service._try_acquire_pipeline_locks(log):
        return []
    try:
        service._reload_config()
        config = service.config
        builder = service.epub_builder
        generate_cover = bool(config.get("epub_cover", True))

        articles_by_site, _options = selected_source_groups(
            selected_articles, config.get("sites", []), t("pipeline.selected.other_site")
        )
        for arts in articles_by_site.values():
            for art in arts:
                art.pop("site_name", None)
                art.pop("scraper_type", None)

        paths: list[str] = []
        cancelled = False
        if service.is_cancel_requested():
            cancelled = True
        elif config.get("epub_merge_mode", "per_site") == "daily_digest":
            if progress_callback:
                progress_callback(0, 1)
            paths.append(builder.build_digest(articles_by_site, generate_cover=generate_cover))
            if progress_callback:
                progress_callback(1, 1)
        else:
            total = len(articles_by_site)
            for idx, (_source_key, arts) in enumerate(articles_by_site.items()):
                site_name = arts[0]["_source_name"]
                if getattr(service, "is_cancel_requested", lambda: False)():
                    log(t("pipeline.cancelled"))
                    cancelled = True
                    break
                if progress_callback:
                    progress_callback(idx, total)
                paths.append(builder.build(site_name, arts, generate_cover=generate_cover))
            if progress_callback:
                progress_callback(total, total)

        for path in paths:
            log(t("pipeline.file_created", filename=os.path.basename(path)))
        log(t("pipeline.epub_only.done", count=len(paths), folder=os.path.dirname(paths[0]) if paths else ""))
        service._last_pipeline_result = {
            "status": "cancelled" if cancelled else "completed",
            "success": not cancelled, "paths": paths,
        }
        return paths
    except Exception as error:
        service.record_job_failure(error)
        raise
    finally:
        service._release_pipeline_locks()
