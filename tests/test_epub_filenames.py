"""생성 EPUB 파일명 규칙 정본과 OPDS 표시 제목 (2026-11-02 감사 ISSUE-003)."""

from __future__ import annotations

import os
import re

import pytest

from websync.epub.builder import EpubBuilder
from websync.epub.filenames import batch_digest, display_title, epub_basename
from websync.upload.sync_epub import parse_sync_epub_date


@pytest.mark.parametrize(
    "name, title",
    [
        ("뉴스_2026-11-02_c070adea.epub", "뉴스 (2026-11-02)"),
        ("뉴스_2026-11-02_c070adea_174547_653761.epub", "뉴스 (2026-11-02)"),
        ("Daily_Digest_2026-11-02_1a2b3c4d.epub", "Daily Digest (2026-11-02)"),
        ("My_Site_2026-10-01.epub", "My Site (2026-10-01)"),
        ("뉴스_2026-11-02_c070adea_a1b2c3.epub", "뉴스 (2026-11-02)"),
        ("Some Book.epub", "Some Book"),
    ],
)
def test_display_title(name, title):
    assert display_title(name) == title


def test_builder_names_follow_shared_format(tmp_path):
    builder = EpubBuilder(output_dir=str(tmp_path))
    arts = [{"title": "a", "content": "<p>x</p>", "url": "https://e.x/1"}]
    first = os.path.basename(builder.build("테크 뉴스", arts, generate_cover=False))
    second = os.path.basename(builder.build("테크 뉴스", arts, generate_cover=False))
    digest = batch_digest(arts)
    assert first.startswith("테크_뉴스_") and first.endswith(f"_{digest}.epub")
    assert re.fullmatch(
        rf"테크_뉴스_\d{{4}}-\d{{2}}-\d{{2}}_{digest}_\d{{6}}_\d{{6}}\.epub", second
    )
    for name in (first, second):
        assert display_title(name).startswith("테크 뉴스 (")
        assert parse_sync_epub_date(name) is not None


def test_epub_basename_plain():
    assert (
        epub_basename("Daily_Digest", "2026-11-02", "deadbeef")
        == "Daily_Digest_2026-11-02_deadbeef.epub"
    )


def test_opds_catalog_uses_display_title(tmp_path):
    from websync.servers.opds import OPDSServer

    (tmp_path / "뉴스_2026-11-02_c070adea.epub").write_bytes(b"x")
    server = OPDSServer(output_dir=str(tmp_path), port=0, bind_host="127.0.0.1")
    assert server.start()
    try:
        import urllib.request

        with urllib.request.urlopen(
            f"http://127.0.0.1:{server.port}/opds", timeout=5
        ) as resp:
            body = resp.read().decode("utf-8")
    finally:
        server.stop()
    assert "<summary>뉴스 (2026-11-02) (0 KB)</summary>" in body
