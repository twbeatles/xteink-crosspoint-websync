"""WebSync 동기화 EPUB 파일명 날짜 파싱·오래된 파일 필터."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

# WebSync가 생성하는 EPUB: 사이트_YYYY-MM-DD_hash8.epub, Daily_Digest_YYYY-MM-DD_hash8.epub
# (형식 정본은 websync/epub/filenames.py). 옛 사이트_YYYY-MM-DD.epub도 같은 규칙으로 읽는다.
_SYNC_DATE_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})")


def parse_sync_epub_date(filename: str) -> date | None:
    """파일명에서 WebSync 스타일 날짜(YYYY-MM-DD)를 파싱. 없으면 None."""
    if not filename or not str(filename).lower().endswith(".epub"):
        return None
    matches = _SYNC_DATE_IN_NAME.findall(str(filename))
    if not matches:
        return None
    # 여러 날짜가 있으면 마지막(보통 파일명 끝 날짜) 사용
    for token in reversed(matches):
        try:
            return datetime.strptime(token, "%Y-%m-%d").date()
        except ValueError:
            continue
    return None


def filter_old_sync_epubs(
    items: list[dict[str, Any]],
    older_than_days: int,
    *,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """목록에서 N일보다 오래된 동기화 EPUB 후보만 반환 (폴더 제외)."""
    if older_than_days < 0:
        older_than_days = 0
    ref = today or date.today()
    cutoff = ref - timedelta(days=older_than_days)
    result: list[dict[str, Any]] = []
    for item in items:
        if item.get("isDirectory"):
            continue
        name = item.get("name") or ""
        d = parse_sync_epub_date(name)
        if d is None:
            continue
        if d < cutoff:
            enriched = dict(item)
            enriched["sync_date"] = d.isoformat()
            result.append(enriched)
    result.sort(key=lambda x: x.get("sync_date") or "")
    return result
