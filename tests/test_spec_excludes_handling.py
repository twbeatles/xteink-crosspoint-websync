import sys
from unittest.mock import patch

from websync.epub.builder import EpubBuilder
from websync.epub.cover import make_cover_image


def test_cover_image_pillow_missing_fallback():
    # Pillow (PIL) 미설치 환경(ImportError) 가상화 시 에러 없이 안전하게 None을 반환하는지 검증
    with patch.dict(sys.modules, {"PIL": None, "PIL.Image": None}):
        cover_data = make_cover_image("테스트 사이트", 5, "2026-07-31")
        assert cover_data is None


def test_builder_handles_missing_pillow(tmp_path):
    builder = EpubBuilder(output_dir=str(tmp_path))
    articles = [{"title": "기사1", "content": "<p>내용</p>", "url": "https://example.com/1"}]

    # Pillow 미설치 상태에서도 EpubBuilder.build가 크래시 없이 EPUB을 생성하는지 검증
    with patch.object(builder, "_make_cover_image", return_value=None):
        epub_file = builder.build("테스트 사이트", articles, generate_cover=True)
        assert epub_file.endswith(".epub")
