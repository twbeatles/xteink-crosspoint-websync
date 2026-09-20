import json
import os
import tempfile
import pytest

from websync.backup.atomic_io import JsonReadError, read_json_checked, read_json_safe, write_json_atomic


def test_write_and_read_json_atomic():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "data.json")
        write_json_atomic(path, {"a": 1, "b": "한글"})
        data = read_json_safe(path)
        assert data == {"a": 1, "b": "한글"}
        assert not os.path.exists(path + ".tmp")


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
