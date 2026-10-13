"""Bounded raster assets for offline EPUB reading (no optional dependency)."""
from __future__ import annotations

import hashlib
import time
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from ebooklib import epub

from websync.scrapers.base import fetch_url, is_allowed_fetch_url
from websync.scrapers.selector_assistant.url_safety import is_private_or_local_url


class ImageAssets:
    MAX_IMAGE_BYTES = 4 * 1024 * 1024
    MAX_BOOK_BYTES = 24 * 1024 * 1024
    MAX_IMAGES = 32

    def __init__(self, book, logger):
        self.book = book
        self.logger = logger
        self.cache = {}
        self.added = set()
        self.total_bytes = 0
        self.deadline = time.monotonic() + 30

    def _download(self, url, source):
        if not is_allowed_fetch_url(url):
            raise ValueError("Image URL must be HTTP(S)")
        # A public article cannot turn its image into an internal-network fetch.
        if is_private_or_local_url(url) and (
            not is_private_or_local_url(source)
            or urlparse(url).hostname != urlparse(source).hostname
        ):
            raise ValueError("Private image host is not the article host")
        response = fetch_url(url, timeout=5)
        try:
            response.raise_for_status()
            data = response.content
        finally:
            response.close()
        if not data or len(data) > self.MAX_IMAGE_BYTES:
            raise ValueError("Image exceeds size limit or is empty")
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            ext, mime = "png", "image/png"
        elif data.startswith(b"\xff\xd8\xff"):
            ext, mime = "jpg", "image/jpeg"
        elif data.startswith((b"GIF87a", b"GIF89a")):
            ext, mime = "gif", "image/gif"
        else:
            raise ValueError("Only PNG, JPEG and GIF images are supported")
        digest = hashlib.sha256(data).hexdigest()
        path = f"images/{digest}.{ext}"
        if path not in self.added:
            if self.total_bytes + len(data) > self.MAX_BOOK_BYTES:
                raise ValueError("Book image size limit exceeded")
            self.book.add_item(epub.EpubItem(uid=f"image-{digest}", file_name=path,
                                             media_type=mime, content=data))
            self.added.add(path)
            self.total_bytes += len(data)
        return path

    def embed(self, html, source):
        soup = BeautifulSoup(html, "html.parser")
        for image in soup.find_all("img"):
            url = urljoin(source or "", image.get("src") or image.get("data-src") or "")
            if url not in self.cache:
                self.cache[url] = None
                if len(self.cache) <= self.MAX_IMAGES and time.monotonic() < self.deadline:
                    try:
                        self.cache[url] = self._download(url, source)
                    except Exception as error:
                        self.logger.warning("EPUB image omitted: %s", error)
            asset = self.cache[url]
            if asset:
                image["src"] = asset
                for attr in ("srcset", "data-src", "data-srcset", "loading"):
                    image.attrs.pop(attr, None)
            else:
                image.replace_with(image.get("alt") or "")
        return str(soup)
