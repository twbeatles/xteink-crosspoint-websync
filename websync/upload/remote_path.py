"""기기 SD 원격 경로 유틸 (정규화·결합·크기 표시)."""
from __future__ import annotations

from websync.i18n import t


def normalize_remote_path(path: str | None) -> str:
    """원격 경로를 `/` 또는 `/a/b` 형태로 정규화. `..` 세그먼트 제거."""
    if not path or not str(path).strip():
        return "/"
    raw = str(path).strip().replace("\\", "/")
    parts: list[str] = []
    for seg in raw.split("/"):
        if not seg or seg == ".":
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    if not parts:
        return "/"
    return "/" + "/".join(parts)


# 업로드 대상 폴더 정규화 — 원격 경로와 동일 규칙
normalize_upload_remote_dir = normalize_remote_path


def join_remote_path(parent: str, name: str) -> str:
    """부모 디렉터리와 항목 이름을 결합."""
    parent_n = normalize_remote_path(parent)
    name = (name or "").strip().replace("\\", "/").strip("/")
    if not name or name in (".", "..") or "/" in name:
        raise ValueError(t("device.bad_name", name=repr(name)))
    if parent_n == "/":
        return f"/{name}"
    return f"{parent_n}/{name}"


def parent_remote_path(path: str) -> str:
    """상위 디렉터리 경로. 루트면 `/`."""
    p = normalize_remote_path(path)
    if p == "/":
        return "/"
    parent = p.rsplit("/", 1)[0]
    return parent if parent else "/"


def format_file_size(size: int | float | None) -> str:
    """바이트 크기를 사람이 읽기 쉬운 문자열로."""
    try:
        n = float(size or 0)
    except (TypeError, ValueError):
        return "-"
    if n < 0:
        return "-"
    units = ("B", "KB", "MB", "GB")
    idx = 0
    while n >= 1024 and idx < len(units) - 1:
        n /= 1024
        idx += 1
    if idx == 0:
        return f"{int(n)} {units[idx]}"
    return f"{n:.1f} {units[idx]}"
