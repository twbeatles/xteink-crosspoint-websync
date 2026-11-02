"""생성 EPUB 파일명 규칙의 정본 (빌더·OPDS·기기 정리가 공유).

형식: ``{사이트}_{YYYY-MM-DD}_{hash8}[_{HHMMSS_ffffff}].epub``
합본: ``Daily_Digest_{YYYY-MM-DD}_{hash8}[_{HHMMSS_ffffff}].epub``
기기 전송명은 여기에 원본 basename MD5 6자리가 더 붙는다(``upload/uploader.py``).
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

DIGEST_PREFIX = "Daily_Digest"

# hash8·시각·전송 hash는 각각 선택 — 옛 형식(`사이트_날짜.epub`)도 읽는다.
_GENERATED = re.compile(
    r"^(?P<prefix>.+?)_(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:_(?P<batch>[0-9a-f]{8}))?"
    r"(?:_(?P<time>\d{6}(?:_\d{6})?))?"
    r"(?:_(?P<transfer>[0-9a-f]{6}))?"
    r"\.epub$",
    re.IGNORECASE,
)


def batch_digest(articles) -> str:
    """기사 집합의 짧은 결정적 식별자.

    파일명은 날짜만으로는 PC·출력 폴더 사이에서 고유하지 않다. 같은 날 다른 PC가
    다른 새 글로 만든 EPUB이 기기의 같은 경로를 덮어쓰지 않도록 내용 집합을 반영한다.
    같은 기사 집합의 재빌드는 같은 값을 가진다.
    """
    keys = sorted(
        (art.get("url") or "").strip() or f"{art.get('title', '')}\n{art.get('content', '')}"
        for art in articles
    )
    return hashlib.sha256("\n".join(keys).encode("utf-8", errors="replace")).hexdigest()[:8]


def safe_site_component(site_name: str) -> str:
    """파일명에 쓰는 사이트 이름 (영숫자·한글·공백·_·-만, 공백은 _)."""
    kept = "".join(c for c in site_name if c.isalnum() or c in (" ", "_", "-")).strip()
    return kept.replace(" ", "_")


def epub_basename(prefix: str, day: str, batch_id: str, *, time_suffix: bool = False) -> str:
    """빌더가 쓰는 파일명. time_suffix=True면 로컬 충돌 회피용 시각을 붙인다."""
    name = f"{prefix}_{day}_{batch_id}"
    if time_suffix:
        name += "_" + datetime.now().strftime("%H%M%S_%f")
    return name + ".epub"


def display_title(filename: str) -> str:
    """카탈로그 표시용 제목: ``뉴스_2026-11-02_c070adea.epub`` → ``뉴스 (2026-11-02)``."""
    match = _GENERATED.match(filename or "")
    if match:
        prefix = match.group("prefix").replace("_", " ").strip()
        return f"{prefix} ({match.group('date')})"
    stem = re.sub(r"\.epub$", "", filename or "", flags=re.IGNORECASE)
    return stem.replace("_", " ").strip()
