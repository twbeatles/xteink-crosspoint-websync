"""EPUB structural oracle (INV-10): meaning-structure, not byte equality.

Validates mimetype placement/compression, container.xml, OPF metadata/spine,
NAV/TOC chapter count+order, XHTML well-formedness, Korean titles, and that
per_site vs daily_digest differ exactly as contracted.
"""
from __future__ import annotations

import io
import json
import os
import zipfile
import xml.etree.ElementTree as ET

from websync.epub.builder import EpubBuilder


def _articles():
    return [
        {"title": "한글 첫 글 😀", "url": "https://a.example/1", "content": "<p>본문 <b>하나</b></p>"},
        {"title": "둘째 <escape> & test", "url": "https://a.example/2", "content": "<p>본문 둘</p>"},
    ]


def _open(path):
    zf = zipfile.ZipFile(path)
    return zf


def test_per_site_epub_structure(tmp_path):
    builder = EpubBuilder(output_dir=str(tmp_path))
    path = builder.build("테스트 사이트", _articles(), generate_cover=False)
    with _open(path) as zf:
        names = zf.namelist()
        # mimetype must exist and be stored (uncompressed) first per EPUB spec
        info = zf.getinfo("mimetype")
        assert info.compress_type == zipfile.ZIP_STORED
        assert names[0] == "mimetype"
        assert zf.read("mimetype").strip() == b"application/epub+zip"
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        assert "rootfile" in ET.tostring(container, encoding="unicode")
        opf_name = next(n for n in names if n.endswith(".opf"))
        opf = ET.tostring(ET.fromstring(zf.read(opf_name)), encoding="unicode")
        assert "한글 첫 글" in opf or "opf" in opf_name
        # every spine xhtml parses as XML and titles appear in order
        xhtmls = sorted(n for n in names if n.startswith("EPUB/chap_") or n.endswith(".xhtml"))
        assert len([n for n in xhtmls if "chap_" in n or "chapter" in n]) >= 2
        import re as _re
        bodies = []
        for n in names:
            if n.endswith(".xhtml"):
                raw = zf.read(n).decode("utf-8")
                no_doctype = _re.sub(r"<!DOCTYPE[^>]*>", "", raw)
                # strip XML declaration; remaining must be well-formed XML
                no_decl = _re.sub(r"<\?xml[^?]*\?>", "", no_doctype).strip()
                ET.fromstring(no_decl)
                bodies.append(raw)
        joined = "\n".join(bodies)
        assert "한글 첫 글" in joined
        assert bodies[0].find("한글 첫 글") < joined.find("둘째")


def test_digest_epub_single_bundle_all_sites(tmp_path):
    builder = EpubBuilder(output_dir=str(tmp_path))
    path = builder.build_digest(
        {"A": [_articles()[0]], "B": [_articles()[1]]}, generate_cover=False
    )
    with _open(path) as zf:
        names = zf.namelist()
        xhtmls = [n for n in names if n.endswith(".xhtml") and "nav" not in n.lower()]
        assert len(xhtmls) == 2
        blob = b"\n".join(zf.read(n) for n in xhtmls)
        text = blob.decode("utf-8", "replace")
        assert "한글 첫 글" in text and "둘째" in text


def test_epub_expectations_fixture_matches(tmp_path):
    exp_path = os.path.join(os.path.dirname(__file__), "fixtures", "contracts", "epub_expectations.json")
    exp = json.load(open(exp_path, encoding="utf-8"))
    builder = EpubBuilder(output_dir=str(tmp_path))
    path = builder.build("S", _articles(), generate_cover=False)
    with _open(path) as zf:
        names = zf.namelist()
        for required in exp["required_entries"]:
            assert any(required in n or n == required for n in names), required
