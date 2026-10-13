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

    # 2. ASCII-safe transfer names retain the date and original-name hash.
    assert "2026-07-31" in sanitized1
    assert sanitized1.isascii() and sanitized2.isascii()
    assert "2026-07-31" in sanitized2
    assert "2026-07-31" in sanitized3

    # 3. 고유한 파일명이 생성되어 파일명 중복 덮어씌우기가 방지되는지 검증
    assert sanitized1 != sanitized2
    assert sanitized1 != sanitized3
    assert sanitized2 != sanitized3
