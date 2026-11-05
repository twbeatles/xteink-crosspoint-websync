"""기기에서 PC로 받을 때의 로컬 파일명 정리·충돌 계획 (GUI 비의존)."""
from __future__ import annotations

import os
import re

# Windows에서 파일명에 쓸 수 없는 문자. ':'는 드라이브 상대 경로(C:x)와 ADS(a:b)도 만든다.
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def safe_local_filename(name: str, *, fallback: str = "download") -> str:
    """기기가 보고한 이름을 선택한 폴더 안에만 놓이는 안전한 파일명으로 바꾼다."""
    raw = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _FORBIDDEN.sub("_", raw).strip().rstrip(". ")
    if not cleaned or cleaned in (".", ".."):
        return fallback
    stem = cleaned.split(".", 1)[0]
    if stem.upper() in _RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned


def _numbered(name: str, n: int) -> str:
    stem, ext = os.path.splitext(name)
    return f"{stem} ({n}){ext}"


def publish_local_download(temp_path: str, local_path: str, *, overwrite: bool = False) -> None:
    """Publish a complete same-directory file, atomically enforcing overwrite policy.

    Never fall back to exists()+replace: another writer may win between them.
    Filesystems without a no-replace primitive fail safely instead.
    """
    if overwrite:
        os.replace(temp_path, local_path)
    elif os.name == "nt":
        # Windows rename fails if the destination exists (also on FAT volumes).
        os.rename(temp_path, local_path)
    else:
        os.link(temp_path, local_path)
        os.unlink(temp_path)


def plan_local_downloads(
    dest_dir: str,
    names: list[str],
    *,
    overwrite: bool,
    exists=os.path.exists,
) -> list[dict]:
    """각 이름의 저장 경로를 정한다.

    Returns: [{"name", "path", "conflict", "renamed"}] — 입력 순서 유지.
    overwrite=False면 기존 파일과 겹치는 이름을 `이름 (1).ext`로 바꾼다.
    배치 안에서 정리 후 같아지는 이름은 overwrite와 무관하게 항상 구분한다.
    """
    taken: set[str] = set()
    plan: list[dict] = []
    for original in names:
        base = safe_local_filename(original)
        candidate = base
        conflict = exists(os.path.join(dest_dir, base))
        n = 0
        while candidate.casefold() in taken or (
            not overwrite and exists(os.path.join(dest_dir, candidate))
        ):
            n += 1
            candidate = _numbered(base, n)
        taken.add(candidate.casefold())
        plan.append({
            "name": original,
            "path": os.path.join(dest_dir, candidate),
            "conflict": bool(conflict),
            "renamed": candidate != str(original),
        })
    return plan


def find_local_conflicts(dest_dir: str, names: list[str], *, exists=os.path.exists) -> list[str]:
    """선택한 폴더에 이미 있는 (정리 후) 파일명 목록."""
    return [
        safe_local_filename(n)
        for n in names
        if exists(os.path.join(dest_dir, safe_local_filename(n)))
    ]
