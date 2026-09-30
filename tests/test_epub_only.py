"""프리뷰 창 'EPUB만 만들기' — 전송·이력 없이 파일만 생성."""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

from websync.pipeline.epub_only import build_selected_epubs


def _service(merge_mode: str):
    builder = MagicMock()
    builder.build.side_effect = lambda name, arts, generate_cover=True: f"/out/{name}.epub"
    builder.build_digest.return_value = "/out/Daily_Digest.epub"
    service = SimpleNamespace(
        logger=logging.getLogger("test-epub-only"),
        config={"epub_merge_mode": merge_mode, "epub_cover": False},
        epub_builder=builder,
        uploader=MagicMock(),
        db=MagicMock(),
        is_cancel_requested=lambda: False,
    )
    service._reload_config = lambda: None
    return service


ARTS = [
    {"site_name": "A", "title": "a1", "url": "u1", "content": "<p>1</p>", "scraper_type": "rss"},
    {"site_name": "B", "title": "b1", "url": "u2", "content": "<p>2</p>", "scraper_type": "rss"},
    {"site_name": "A", "title": "a2", "url": "u3", "content": "<p>3</p>", "scraper_type": "rss"},
]


def test_per_site_builds_one_epub_per_site_without_upload_or_history():
    service = _service("per_site")
    paths = build_selected_epubs(service, [dict(a) for a in ARTS])
    assert paths == ["/out/A.epub", "/out/B.epub"]
    first_call = service.epub_builder.build.call_args_list[0]
    assert first_call.args[0] == "A"
    assert [a["title"] for a in first_call.args[1]] == ["a1", "a2"]
    assert "site_name" not in first_call.args[1][0]
    assert first_call.kwargs["generate_cover"] is False
    service.uploader.upload_to_targets.assert_not_called()
    service.db.mark_synced_many.assert_not_called()


def test_digest_mode_builds_single_digest():
    service = _service("daily_digest")
    paths = build_selected_epubs(service, [dict(a) for a in ARTS])
    assert paths == ["/out/Daily_Digest.epub"]
    by_site = service.epub_builder.build_digest.call_args.args[0]
    assert set(by_site) == {"A", "B"}
    service.epub_builder.build.assert_not_called()


def test_empty_selection_builds_nothing():
    service = _service("per_site")
    assert build_selected_epubs(service, []) == []
    service.epub_builder.build.assert_not_called()
