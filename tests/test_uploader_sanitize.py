import os
import pytest
from websync.upload.uploader import X3Uploader


def test_sanitize_filename_korean_and_uniqueness():
    uploader = X3Uploader("192.168.1.100")
    
    path1 = "d:/output/네이버뉴스_2026-07-31.epub"
    path2 = "d:/output/티스토리_2026-07-31.epub"
    path3 = "d:/output/!!!_2026-07-31.epub"

    sanitized1 = uploader._sanitize_filename(path1)
    sanitized2 = uploader._sanitize_filename(path2)
    sanitized3 = uploader._sanitize_filename(path3)

    # 1. 파일 확장자 유지
    assert sanitized1.endswith(".epub")
    assert sanitized2.endswith(".epub")
    assert sanitized3.endswith(".epub")

    # 2. Transfer names retain the original blog name, the date and original-name hash.
    assert "2026-07-31" in sanitized1
    assert "네이버뉴스_2026-07-31" in sanitized1
    assert "티스토리_2026-07-31" in sanitized2
    assert "2026-07-31" in sanitized2
    assert "2026-07-31" in sanitized3

    # 3. 고유한 파일명이 생성되어 파일명 중복 덮어씌우기가 방지되는지 검증
    assert sanitized1 != sanitized2
    assert sanitized1 != sanitized3
    assert sanitized2 != sanitized3


def test_sanitize_filename_keeps_original_site_name():
    """앱에서 지정한 원본 블로그명(한글)이 기기 전송 파일명에 그대로 남는다."""
    from websync.upload.romanize import romanize_for_filename

    uploader = X3Uploader("192.168.1.100")

    sanitized = uploader._sanitize_filename("d:/output/네이버뉴스_2026-07-31.epub")
    assert sanitized.startswith("네이버뉴스_2026-07-31_")
    assert sanitized.endswith(".epub")

    other = uploader._sanitize_filename("d:/output/티스토리_2026-07-31.epub")
    assert other.startswith("티스토리_2026-07-31_")
    assert sanitized != other

    assert romanize_for_filename("네이버뉴스") == "neibeonyuseu"
    assert romanize_for_filename("한글") == "hangeul"
    assert romanize_for_filename("ABC-123_가") == "ABC-123_ga"


@pytest.mark.parametrize("first,second", [
    ("가", "ga"), ("낫", "낮"), ("café", "cafe"),
])
def test_original_name_survives_collision(first, second):
    uploader = X3Uploader("localhost")
    a = uploader._sanitize_filename(f"{first}_2026-10-15.EPUB")
    b = uploader._sanitize_filename(f"{second}_2026-10-15.EPUB")
    assert a != b
    assert a.endswith(".epub") and b.endswith(".epub")
    assert "2026-10-15" in a and "2026-10-15" in b
    assert a == uploader._sanitize_filename(f"{first}_2026-10-15.EPUB")


def test_batch_rejects_same_basename_in_different_directories():
    uploader = X3Uploader("localhost")
    with pytest.raises(ValueError):
        uploader.check_batch_filenames(["a/book.epub", "b/book.epub"])
    uploader.check_batch_filenames(["가.epub", "ga.epub"])


def test_ascii_filename_remains_compatible():
    assert X3Uploader("localhost")._sanitize_filename("ga.epub") == "ga_32d750.epub"


def test_batch_compares_resulting_names_case_insensitively(monkeypatch):
    uploader = X3Uploader("localhost")
    monkeypatch.setattr(uploader, "_sanitize_filename", lambda path: path)
    with pytest.raises(ValueError):
        uploader.check_batch_filenames(["Book.epub", "book.epub"])
