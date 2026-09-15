"""ko/en 카탈로그 키 집합이 같고 빈 값이 없는지 검증."""
from __future__ import annotations

from websync.i18n.catalog import flatten, load_catalog


def test_en_and_ko_keys_match():
    ko = load_catalog("ko")
    en = load_catalog("en")
    assert ko, "ko catalog failed to load"
    assert en, "en catalog failed to load"
    assert set(ko) == set(en)
    assert all(v.strip() for v in ko.values())
    assert all(v.strip() for v in en.values())


def test_flatten_nested():
    flat = flatten({"a": {"b": "x"}, "c": "y"})
    assert flat == {"a.b": "x", "c": "y"}
