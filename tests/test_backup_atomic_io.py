import json
import os
import tempfile

import pytest

from websync.backup.atomic_io import (
    JsonReadError,
    read_json_checked,
    read_json_safe,
    write_json_atomic,
)


def test_write_and_read_json_atomic():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "data.json")
        write_json_atomic(path, {"a": 1, "b": "한글"})
        data = read_json_safe(path)
        assert data == {"a": 1, "b": "한글"}
        assert not os.path.exists(path + ".tmp")


def test_write_json_atomic_tmp_paths_are_unique(tmp_path, monkeypatch):
    """동일 경로 연속 쓰기도 서로 다른 tmp를 써야 다중 프로세스 경합을 막는다."""
    import websync.backup.atomic_io as atomic_io

    seen: list[str] = []
    real_replace = os.replace

    def spy_replace(src, dst):
        seen.append(src)
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    target = str(tmp_path / "sites.json")
    atomic_io.write_json_atomic(target, {"n": 1})
    atomic_io.write_json_atomic(target, {"n": 2})
    assert len(seen) == 2
    assert seen[0] != seen[1]
    assert all(s.endswith(".tmp") for s in seen)
    assert not list(tmp_path.glob("*.tmp"))


def test_write_json_atomic_concurrent_writes_stay_valid(tmp_path):
    """동시 쓰기 후 최종본은 입력 중 하나와 완전히 일치하고 tmp 잔재가 없다.

    현실적인 경합 수준(공유 폴더 락이 직렬화하므로 2 writer)을 검증한다.
    극한 경합(4+ writer 동시 replace)은 Windows에서 OS/AV 잠금으로
    PermissionError가 날 수 있어 폴더 락이 1차 방어로 남는다.
    """
    from concurrent.futures import ThreadPoolExecutor

    import websync.backup.atomic_io as atomic_io

    target = str(tmp_path / "sites.json")
    payloads = [{"n": i, "pad": "x" * 20000} for i in range(8)]

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda p: atomic_io.write_json_atomic(target, p), payloads))

    with open(target, encoding="utf-8") as f:
        assert json.load(f) in payloads
    assert not list(tmp_path.glob("*.tmp"))


def test_read_json_safe_missing_and_corrupt():
    with tempfile.TemporaryDirectory() as tmp:
        missing = os.path.join(tmp, "nope.json")
        assert read_json_safe(missing) is None

        empty = os.path.join(tmp, "empty.json")
        with open(empty, "w", encoding="utf-8") as f:
            f.write("")
        assert read_json_safe(empty) is None

        corrupt = os.path.join(tmp, "bad.json")
        with open(corrupt, "w", encoding="utf-8") as f:
            f.write("{not json")
        assert read_json_safe(corrupt) is None

        ok = os.path.join(tmp, "ok.json")
        with open(ok, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)
        assert read_json_safe(ok) == [1, 2, 3]


def test_read_json_checked_distinguishes_missing_from_corrupt():
    with tempfile.TemporaryDirectory() as tmp:
        missing = os.path.join(tmp, "missing.json")
        corrupt = os.path.join(tmp, "corrupt.json")
        assert read_json_checked(missing) is None
        with open(corrupt, "w", encoding="utf-8") as f:
            f.write('{"partial":')
        with pytest.raises(JsonReadError):
            read_json_checked(corrupt)
