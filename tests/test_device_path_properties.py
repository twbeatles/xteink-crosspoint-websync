"""Property-style checks for remote paths, hosts, filenames.

INV-09: normalization must never yield an empty string, a drive root, or
an upward escape; sanitized EPUB names stay firmware-safe.
"""
from __future__ import annotations

import pytest

from websync.upload.device_ids import build_targets_with_keys
from websync.upload.host import normalize_device_host
from websync.upload.remote_path import (
    join_remote_path,
    normalize_remote_path,
    parent_remote_path,
)
from websync.upload.uploader import X3Uploader


@pytest.mark.parametrize("raw", [
    "", "   ", None, "/", "//", "/a/../b", "a\\b\\c", "/../..",
    "C:\\Books", "http://x/", ".", "..",
])
def test_normalize_never_escapes_or_empties(raw):
    out = normalize_remote_path(raw)  # type: ignore[arg-type]
    assert out.startswith("/")
    assert ".." not in out.split("/")
    assert out != ""


def test_normalize_idempotent_and_joins_safe():
    cases = ["/Books/", "Books/Sub", "/a/./b", "/a//b"]
    for raw in cases:
        once = normalize_remote_path(raw)
        assert normalize_remote_path(once) == once
    assert join_remote_path("/Books", "a.epub") == "/Books/a.epub"
    assert parent_remote_path("/Books/a.epub") == "/Books"
    assert parent_remote_path("/") == "/"
    with pytest.raises(ValueError):
        join_remote_path("/Books", "../evil")
    with pytest.raises(ValueError):
        join_remote_path("/Books", "a/b")


@pytest.mark.parametrize("raw,expected", [
    ("http://192.168.31.54/", "192.168.31.54"),
    ("https://crosspoint.local/path?q=1", "crosspoint.local"),
    ("  10.0.0.1:8080/ ", "10.0.0.1:8080"),
    ("", ""),
    (None, ""),
    ("192.168.1.10//upload", "192.168.1.10"),
])
def test_host_normalization(raw, expected):
    assert normalize_device_host(raw) == expected


def test_sanitize_filename_properties():
    up = X3Uploader("127.0.0.1")
    names = [
        up._sanitize_filename("/tmp/한글 제목 테스트.epub"),
        up._sanitize_filename("/tmp/a b/c?.EPUB"),
        up._sanitize_filename("/tmp/___.epub"),
        up._sanitize_filename("/tmp/ok-name_1.epub"),
    ]
    for n in names:
        assert n.endswith(".epub")
        assert " " not in n and "/" not in n and "\\" not in n
    # same stem -> same name (deterministic), different stem -> different hash suffix
    assert up._sanitize_filename("/a/title.epub") == up._sanitize_filename("/b/title.epub")
    assert up._sanitize_filename("/a/one.epub") != up._sanitize_filename("/a/two.epub")


def test_build_targets_never_merges_distinct_local_readers():
    targets = build_targets_with_keys(
        "192.168.1.10",
        [{"name": "second", "ip": "192.168.1.11", "id": "dev_two"}],
        primary_id="dev_one",
    )
    keys = {t["ip"]: t["history_key"] for t in targets}
    assert keys["192.168.1.10"] == "dev_one"
    assert keys["192.168.1.11"] == "dev_two"
    assert keys["192.168.1.10"] != keys["192.168.1.11"]


def test_korean_remote_segments_survive():
    assert normalize_remote_path("/책/한글 폴더") == "/책/한글 폴더"
    assert join_remote_path("/책", "한글.epub") == "/책/한글.epub"
