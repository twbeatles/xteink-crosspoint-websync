"""Same-day EPUBs from different PCs/output folders must not share a remote path.

The fake CrossPoint replaces an existing path, so a name collision would drop a
book that history already records as delivered.
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "support"))
from fake_crosspoint_server import FakeCrosspointServer

from test_pipeline_http_integration import (
    _article,
    _epub_contains,
    _make_service,
    _run_with_articles,
    _uploaded_epub_texts,
)
from websync.epub.builder import EpubBuilder
from websync.upload.sync_epub import parse_sync_epub_date
from websync.upload.uploader import X3Uploader


def _remote(path: str) -> str:
    return X3Uploader("192.0.2.1")._sanitize_filename(path)


def test_builder_names_differ_across_output_dirs_for_different_articles(tmp_path):
    a = EpubBuilder(output_dir=str(tmp_path / "pcA"))
    b = EpubBuilder(output_dir=str(tmp_path / "pcB"))
    pa = a.build("뉴스", [{"title": "m", "content": "<p>1</p>", "url": "https://x/1"}], generate_cover=False)
    pb = b.build("뉴스", [{"title": "e", "content": "<p>2</p>", "url": "https://x/2"}], generate_cover=False)
    assert _remote(pa) != _remote(pb)
    # 기기 파일 정리 기능은 파일명의 날짜를 계속 읽을 수 있어야 한다.
    assert parse_sync_epub_date(_remote(pa)) == date.today()


def test_builder_name_is_deterministic_for_same_article_set(tmp_path):
    arts = [{"title": "t", "content": "c", "url": "https://x/1"}, {"title": "u", "content": "d", "url": "https://x/2"}]
    pa = EpubBuilder(output_dir=str(tmp_path / "pcA")).build("Site", arts, generate_cover=False)
    pb = EpubBuilder(output_dir=str(tmp_path / "pcB")).build("Site", list(reversed(arts)), generate_cover=False)
    assert os.path.basename(pa) == os.path.basename(pb)


def test_digest_names_differ_across_output_dirs(tmp_path):
    da = EpubBuilder(output_dir=str(tmp_path / "pcA")).build_digest(
        {"s": [{"title": "t", "content": "x", "url": "https://x/1", "_source_name": "s"}]}, generate_cover=False)
    db = EpubBuilder(output_dir=str(tmp_path / "pcB")).build_digest(
        {"s": [{"title": "t2", "content": "y", "url": "https://x/2", "_source_name": "s"}]}, generate_cover=False)
    assert _remote(da) != _remote(db)


@pytest.mark.parametrize("merge_mode", ["per_site", "daily_digest"])
def test_second_pc_same_day_keeps_first_book_on_device(tmp_path, merge_mode):
    srv = FakeCrosspointServer().start()
    try:
        svc_a, db, _ = _make_service(str(tmp_path / "pcA"), srv.host, merge_mode=merge_mode)
        svc_b, _db_b, _ = _make_service(str(tmp_path / "pcB"), srv.host, merge_mode=merge_mode)
        svc_b.db = db  # shared history, as after a cloud-folder pull
        first, second = _article("A"), _article("B")
        assert _run_with_articles(svc_a, [first]) is True
        assert _run_with_articles(svc_b, [first, second]) is True
        blobs = _uploaded_epub_texts(srv)
        assert len(blobs) == 2
        assert _epub_contains(blobs, first["content"][:20]) or _epub_contains(blobs, first["title"])
        assert _epub_contains(blobs, second["content"][:20]) or _epub_contains(blobs, second["title"])
    finally:
        srv.stop()
