"""클라우드 폴더용 원자적 JSON 읽기/쓰기."""
from __future__ import annotations

import json
import os
import shutil
from typing import Any


class JsonReadError(ValueError):
    """An existing JSON file could not be read completely and safely."""


def write_json_atomic(path: str, data: Any, *, indent: int = 2) -> None:
    """tmp 작성 후 replace로 원자적 저장 (OneDrive 등 클라우드 폴더 친화)."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def read_json_safe(path: str) -> dict | list | None:
    """JSON 파일을 안전하게 읽습니다.

    없거나 0바이트, 파싱 실패 시 None (OneDrive 동기화 중 부분 파일 방어).
    """
    try:
        return read_json_checked(path)
    except JsonReadError:
        return None


def read_json_checked(path: str) -> dict | list | None:
    """Read JSON while distinguishing a missing file from a damaged one.

    ``None`` means the file does not exist.  An existing empty, partially
    synced, malformed, unreadable, or non-container JSON file raises
    :class:`JsonReadError` so callers cannot mistake data loss for an empty
    backup.
    """
    if not path or not os.path.isfile(path):
        return None
    try:
        if os.path.getsize(path) <= 0:
            raise JsonReadError(f"JSON file is empty: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except JsonReadError:
        raise
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise JsonReadError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(data, (dict, list)):
        raise JsonReadError(f"JSON root must be an object or array: {path}")
    return data


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def copy_if_exists(src: str, dst: str) -> bool:
    if not os.path.isfile(src):
        return False
    directory = os.path.dirname(dst) or "."
    os.makedirs(directory, exist_ok=True)
    shutil.copy2(src, dst)
    return True
