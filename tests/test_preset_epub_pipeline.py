"""프리셋 피드 → 수집 → EPUB 빌드 전 과정 회귀 테스트.

오프라인 테스트는 실제 프리셋 피드 모양(Medium·WordPress·Atom·요약형)을 본뜬 픽스처로
RssScraper + EpubBuilder 를 끝까지 돌려 EPUB 구조·본문 보존을 검증한다.
라이브 테스트는 ``WEBSYNC_LIVE_CONTRACTS=1`` 일 때만 모든 RSS 프리셋의 실제 피드를 받아 확인한다.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from websync.epub.builder import EpubBuilder
from websync.scrapers.presets import KOREAN_SITE_PRESETS, PRESET_CATEGORIES
from websync.scrapers.rss import RssScraper
from websync.scrapers.types import SCRAPER_TYPES

FIXTURES = Path(__file__).parent / "fixtures" / "scrapers" / "rss"
SUMMARY_NOTE = "preset.note.summary_feed"


def _resp(path: Path) -> MagicMock:
    raw = path.read_bytes()
    m = MagicMock()
    m.raise_for_status = MagicMock()
    m.content = raw
    m.text = raw.decode("utf-8")
    m.encoding = "utf-8"
    m.apparent_encoding = "utf-8"
    return m


def _scrape(name: str, **site) -> list[dict]:
    cfg = {"url": f"https://feed.example/{name}", "limit": 5, "include_images": False, **site}
    with patch("websync.scrapers.rss.fetch_url", return_value=_resp(FIXTURES / f"{name}.xml")):
        return RssScraper().fetch_articles(cfg)


def _xhtml_bodies(path: str) -> list[str]:
    """EPUB 안의 모든 챕터 XHTML 을 XML 로 파싱해 본문 텍스트를 돌려준다(파싱 실패 시 예외)."""
    out = []
    with zipfile.ZipFile(path) as zf:
        assert zf.namelist()[0] == "mimetype"
        assert zf.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        for n in zf.namelist():
            if not n.endswith(".xhtml"):
                continue
            raw = zf.read(n).decode("utf-8")
            raw = re.sub(r"<!DOCTYPE[^>]*>", "", raw)
            raw = re.sub(r"<\?xml[^?]*\?>", "", raw).strip()
            root = ET.fromstring(raw)
            out.append("".join(root.itertext()))
    return out


@pytest.mark.parametrize(
    "name, expected_titles, min_chars",
    [
        ("medium_shape", ["모델만 바꿨는데 비용이 3배가 된 이유", "두 번째 글"], 400),
        ("wordpress_shape", ["단풍 보며 달리기 & 트레일 코스 6"], 400),
        ("atom_shape", ["1부: 데이터도 정답도 없다"], 400),
    ],
)
def test_full_text_feed_shapes_build_valid_epub(tmp_path, name, expected_titles, min_chars):
    arts = _scrape(name)
    assert [a["title"] for a in arts] == expected_titles
    for a in arts:
        text = re.sub(r"<[^>]+>", "", a["content"])
        assert len(text) >= min_chars, f"{name}: 본문이 요약 수준으로 짧음"

    path = EpubBuilder(output_dir=str(tmp_path)).build(f"fixture_{name}", arts, generate_cover=False)
    bodies = _xhtml_bodies(path)
    joined = "\n".join(bodies)
    for title in expected_titles:
        assert title in joined
    # 본문 문단이 챕터에 실제로 들어갔는지 (제목만 있는 챕터가 아님)
    assert "1번째 문단입니다" in joined
    assert "8번째 문단입니다" in joined
    # 챕터 수 = 기사 수 (+ 목차 문서)
    chapters = [b for b in bodies if "문단입니다" in b]
    assert len(chapters) == len(expected_titles)


def test_medium_shape_drops_tracking_pixel_and_images_when_disabled(tmp_path):
    arts = _scrape("medium_shape")
    assert all("<img" not in a["content"] for a in arts)
    assert all("_/stat" not in a["content"] for a in arts)
    path = EpubBuilder(output_dir=str(tmp_path)).build("medium", arts, generate_cover=False)
    with zipfile.ZipFile(path) as zf:
        assert not [n for n in zf.namelist() if n.lower().endswith((".png", ".jpg", ".gif"))]
        assert b"medium.com/_/stat" not in b"".join(zf.read(n) for n in zf.namelist() if n.endswith(".xhtml"))


def test_code_blocks_and_entities_survive_epub_roundtrip(tmp_path):
    arts = _scrape("medium_shape")
    path = EpubBuilder(output_dir=str(tmp_path)).build("code", arts, generate_cover=False)
    joined = "\n".join(_xhtml_bodies(path))
    assert 'def hello():' in joined
    assert 'return "안녕" & 1 < 2' in joined  # 이스케이프가 두 번 풀리거나 깨지지 않음


def test_wordpress_shape_prefers_content_over_excerpt_and_strips_script(tmp_path):
    arts = _scrape("wordpress_shape")
    assert "짧은 발췌" not in arts[0]["content"]
    assert "alert(1)" not in EpubBuilder._sanitize_body_html(arts[0]["content"])
    path = EpubBuilder(output_dir=str(tmp_path)).build("wp", arts, generate_cover=False)
    joined = "\n".join(_xhtml_bodies(path))
    assert "alert(1)" not in joined
    assert "북한산" in joined and "8km" in joined  # 표 내용 보존


def test_atom_shape_uses_content_not_summary():
    arts = _scrape("atom_shape")
    assert "요약 한 줄" not in re.sub(r"<[^>]+>", "", arts[0]["content"])[:30]
    assert "def hello()" in arts[0]["content"]
    assert arts[0]["url"] == "https://blog.example/2026/part1.html"


def test_summary_only_shape_still_builds_readable_chapter(tmp_path):
    arts = _scrape("summary_only_shape")
    assert len(arts) == 1
    assert "원문 링크" in arts[0]["content"] and "https://news.example/a/1" in arts[0]["content"]
    path = EpubBuilder(output_dir=str(tmp_path)).build("summary", arts, generate_cover=False)
    assert "요약만 오는 기사 제목" in "\n".join(_xhtml_bodies(path))


def test_digest_epub_merges_multiple_preset_shapes(tmp_path):
    by_site = {
        "medium": _scrape("medium_shape"),
        "wordpress": _scrape("wordpress_shape"),
        "atom": _scrape("atom_shape"),
    }
    path = EpubBuilder(output_dir=str(tmp_path)).build_digest(by_site, generate_cover=False)
    joined = "\n".join(_xhtml_bodies(path))
    for title in ("두 번째 글", "트레일 코스", "데이터도 정답도"):
        assert title in joined


# --- 프리셋 카탈로그 계약 -------------------------------------------------


def _real_presets() -> list[dict[str, Any]]:
    return [dict(p) for p in KOREAN_SITE_PRESETS if p.get("url")]


def test_every_preset_is_wellformed_and_unique():
    presets = _real_presets()
    urls = [p["url"] for p in presets]
    assert len(urls) == len(set(urls)), "중복 프리셋 URL"
    labels = [p.get("label") for p in KOREAN_SITE_PRESETS]
    assert len(labels) == len(set(labels))
    keys = {k for k, _ in PRESET_CATEGORIES}
    for p in presets:
        assert p["url"].startswith("https://"), p["label"]
        assert p["type"] in SCRAPER_TYPES, p["label"]
        assert p["category"] in keys, f"카테고리 없음: {p['label']}"
        assert 1 <= p["limit"] <= 5


def test_presets_exclude_political_news_outlets():
    banned = ("hani.co.kr", "khan.co.kr", "chosun.com", "joins.com", "donga.com", "ohmynews", "pressian", "sisain")
    assert not [p["label"] for p in _real_presets() if any(b in p["url"] for b in banned)]


def test_english_presets_carry_translation_note():
    for p in _real_presets():
        if p.get("category") == "global":
            assert p.get("note_key") == "preset.note.english_source", p["label"]


# --- 라이브 계약 (opt-in) ---------------------------------------------------

live = pytest.mark.skipif(
    os.environ.get("WEBSYNC_LIVE_CONTRACTS") != "1",
    reason="네트워크 필요 — WEBSYNC_LIVE_CONTRACTS=1 로 실행",
)


@live
@pytest.mark.parametrize("preset", [p for p in _real_presets() if p.get("type") == "rss"], ids=lambda p: p["name"])
def test_live_rss_preset_builds_epub(tmp_path, preset):
    from websync.scrapers.factory import ScraperFactory

    arts = ScraperFactory.get_scraper("rss").fetch_articles(
        {"url": preset["url"], "limit": 2, "include_images": False, "type": "rss"}
    )
    assert arts, f"{preset['name']}: 기사 0건"
    path = EpubBuilder(output_dir=str(tmp_path)).build(preset["name"], arts, generate_cover=False)
    bodies = _xhtml_bodies(path)  # XML 파싱이 되면 구조는 유효
    text = max(len(re.sub(r"<[^>]+>", "", a["content"])) for a in arts)
    if preset.get("note_key") == SUMMARY_NOTE:
        assert text >= 40  # 요약형은 짧아도 비어 있지만 않으면 된다
    else:
        assert text >= 800, f"{preset['name']}: 전문 제공 프리셋인데 본문이 {text}자뿐"
    assert any(arts[0]["title"][:10] in b for b in bodies)
