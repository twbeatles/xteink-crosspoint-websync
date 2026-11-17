import os
import tempfile
import zipfile

from websync.epub.builder import EpubBuilder


def test_build_creates_epub_with_escaped_title():
    with tempfile.TemporaryDirectory() as tmp:
        builder = EpubBuilder(
            output_dir=tmp, font_family="serif", font_size=16, line_height=1.5
        )
        path = builder.build(
            "테스트 사이트",
            [
                {
                    "title": "제목 <script>alert(1)</script>",
                    "content": "<p>본문</p><script>evil()</script>",
                    "url": "https://ex.com/1",
                }
            ],
            generate_cover=False,
        )
        assert os.path.isfile(path)
        assert path.endswith(".epub")
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
            assert any(n.endswith(".xhtml") or n.endswith(".html") for n in names)
            # 챕터 내용 확인
            chapter = next(
                n for n in names if "chap" in n.lower() or n.endswith(".xhtml")
            )
            data = zf.read(chapter).decode("utf-8", errors="ignore")
            assert "<script>" not in data
            assert "evil()" not in data


def test_build_avoids_overwrite_with_suffix():
    with tempfile.TemporaryDirectory() as tmp:
        builder = EpubBuilder(output_dir=tmp)
        p1 = builder.build(
            "Site",
            [{"title": "a", "content": "<p>1</p>", "url": "u1"}],
            generate_cover=False,
        )
        p2 = builder.build(
            "Site",
            [{"title": "b", "content": "<p>2</p>", "url": "u2"}],
            generate_cover=False,
        )
        assert p1 != p2
        assert os.path.isfile(p1) and os.path.isfile(p2)


def test_build_has_identifier():
    """build() 결과 EPUB에 고유 식별자(identifier) 메타데이터가 존재하는지 확인."""
    import xml.etree.ElementTree as ET

    with tempfile.TemporaryDirectory() as tmp:
        builder = EpubBuilder(output_dir=tmp)
        path = builder.build(
            "MySite",
            [{"title": "t", "content": "<p>x</p>", "url": "u1"}],
            generate_cover=False,
        )
        with zipfile.ZipFile(path, "r") as zf:
            opf_name = next(n for n in zf.namelist() if n.endswith(".opf"))
            opf_data = zf.read(opf_name).decode("utf-8")
        # dc:identifier 요소 존재 확인
        root = ET.fromstring(opf_data)
        identifiers = root.findall(".//{http://purl.org/dc/elements/1.1/}identifier")
        assert len(identifiers) > 0
        ident_text = identifiers[0].text or ""
        assert "x3-websync" in ident_text


def test_build_digest_uses_inline_css():
    """build_digest() 결과 챕터에 외부 CSS 참조(style/default.css)가 없는지 확인.
    두 빌드 경로(build/build_digest)가 동일한 CSS 적용 방식을 사용하는지 검증."""
    with tempfile.TemporaryDirectory() as tmp:
        builder = EpubBuilder(output_dir=tmp)
        path = builder.build_digest(
            {"SiteA": [{"title": "t1", "content": "<p>x</p>", "url": "u1"}]},
            generate_cover=False,
        )
        assert os.path.isfile(path)
        with zipfile.ZipFile(path, "r") as zf:
            chapter_names = [
                n
                for n in zf.namelist()
                if "chapter" in n.lower() and n.endswith(".xhtml")
            ]
            assert len(chapter_names) > 0
            data = zf.read(chapter_names[0]).decode("utf-8", errors="ignore")
            # 외부 CSS 파일 참조가 없어야 함 (build()와 동일한 방식)
            assert "style/default.css" not in data
            # 별도 CSS EpubItem도 생성되지 않아야 함
            assert "style/default.css" not in zf.namelist()
