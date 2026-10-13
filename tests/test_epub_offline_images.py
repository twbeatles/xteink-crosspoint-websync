import base64
from types import SimpleNamespace
from unittest.mock import MagicMock
from zipfile import ZipFile

import pytest
from websync.epub.builder import EpubBuilder

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZ1cAAAAASUVORK5CYII=")


@pytest.mark.parametrize("digest", [False, True])
def test_images_packaged_and_deduplicated_offline(tmp_path, monkeypatch, digest):
    response = SimpleNamespace(content=PNG, raise_for_status=lambda: None, close=MagicMock())
    fetch = MagicMock(return_value=response)
    monkeypatch.setattr("websync.epub.images.fetch_url", fetch)
    monkeypatch.setattr("websync.epub.images.is_private_or_local_url", lambda url: False)
    article = {"url": "https://example.com/news/one", "title": "A", "include_images": True,
               "content": '<p>Body</p><img src="../photo.png" srcset="remote.png 2x" alt="Photo"/>'}
    builder = EpubBuilder(str(tmp_path))
    path = (builder.build_digest({"A": [article, article]}, False) if digest
            else builder.build("A", [article, article], False))
    with ZipFile(path) as archive:
        assets = [name for name in archive.namelist() if name.startswith("EPUB/images/")]
        assert len(assets) == 1
        assert archive.read(assets[0]) == PNG
        opf = archive.read("EPUB/content.opf").decode()
        assert 'media-type="image/png"' in opf
        for name in archive.namelist():
            if name.endswith(".xhtml") and "nav" not in name:
                html = archive.read(name).decode()
                assert "images/" in html and "srcset" not in html
                assert "photo.png" not in html
    fetch.assert_called_once_with("https://example.com/photo.png", timeout=5)
    response.close.assert_called_once()


@pytest.mark.parametrize("content", [b"<svg><script>bad</script></svg>", b"x" * (4 * 1024 * 1024 + 1)], ids=["svg", "oversize"])
def test_bad_images_become_alt_text(tmp_path, monkeypatch, content):
    monkeypatch.setattr("websync.epub.images.fetch_url", lambda *a, **kw:
                        SimpleNamespace(content=content, raise_for_status=lambda: None, close=lambda: None))
    monkeypatch.setattr("websync.epub.images.is_private_or_local_url", lambda url: False)
    builder = EpubBuilder(str(tmp_path))
    path = builder.build("A", [{"url": "https://example.com/a", "title": "A", "include_images": True,
                                 "content": '<img src="/a.png" alt="Unavailable photo"/>'}], False)
    with ZipFile(path) as archive:
        body = archive.read("EPUB/chap_1.xhtml").decode()
        assert "Unavailable photo" in body and "<img" not in body
        assert not any(name.startswith("EPUB/images/") for name in archive.namelist())


def test_public_article_cannot_fetch_private_image(tmp_path, monkeypatch):
    fetch = MagicMock()
    monkeypatch.setattr("websync.epub.images.fetch_url", fetch)
    monkeypatch.setattr("websync.epub.images.is_private_or_local_url", lambda url: "127.0.0.1" in url)
    builder = EpubBuilder(str(tmp_path))
    builder.build("A", [{"url": "https://example.com/a", "title": "A", "include_images": True,
                          "content": '<img src="http://127.0.0.1/private"/>'}], False)
    fetch.assert_not_called()
