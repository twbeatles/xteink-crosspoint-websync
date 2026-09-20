"""수집된 기사 데이터를 EPUB 파일로 빌드."""
from __future__ import annotations

import html
import os
from datetime import date, datetime

from ebooklib import epub

from websync.core.logger import get_logger
from websync.epub.cover import make_cover_image
from websync.epub.css import build_default_css, load_theme_css, resolve_css
from websync.epub.sanitize import sanitize_body_html
from websync.i18n import t


class EpubBuilder:
    """수집된 기사 데이터를 받아 EPUB 파일로 빌드하는 역할을 전담하는 클래스"""

    def __init__(
        self,
        output_dir: str = "./output",
        font_family: str = "serif",
        font_size: int = 16,
        line_height: float = 1.7,
        epub_theme: str = "default",
        epub_custom_css: str = "",
    ):
        self.logger = get_logger()
        self.output_dir = output_dir
        self.font_family = font_family
        self.font_size = font_size
        self.line_height = line_height
        self.epub_theme = epub_theme
        self.epub_custom_css = epub_custom_css

    def _load_theme_css(self) -> str:
        """테마 설정에 따라 CSS를 로딩합니다."""
        return load_theme_css(
            self.epub_theme,
            self.epub_custom_css,
            self.font_family,
            self.font_size,
            self.line_height,
            self.logger,
        )

    def _build_default_css(self) -> str:
        """기본 CSS를 생성합니다 (검증된 값 사용)."""
        return build_default_css(self.font_family, self.font_size, self.line_height)

    @staticmethod
    def _sanitize_body_html(content: str) -> str:
        """본문 HTML에서 script/style 제거 후 반환합니다."""
        return sanitize_body_html(content)

    def _make_cover_image(self, site_name: str, article_count: int, today_str: str) -> bytes | None:
        """Pillow를 사용해 EPUB 표지 이미지를 동적으로 생성. Pillow 미설치 시 None 반환."""
        return make_cover_image(site_name, article_count, today_str)

    def _resolve_css(self) -> str:
        return resolve_css(
            self.epub_theme,
            self.epub_custom_css,
            self.font_family,
            self.font_size,
            self.line_height,
            self.logger,
        )

    def build(self, site_name: str, articles: list, generate_cover: bool = True) -> str:
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        today_str = datetime.now().strftime("%Y-%m-%d")
        safe_site_name = "".join(
            [c for c in site_name if c.isalnum() or c in (" ", "_", "-")]
        ).strip()
        safe_site_name = safe_site_name.replace(" ", "_")
        file_name = f"{safe_site_name}_{today_str}.epub"
        file_path = os.path.join(self.output_dir, file_name)

        if os.path.exists(file_path):
            time_suffix = datetime.now().strftime("%H%M%S_%f")
            file_name = f"{safe_site_name}_{today_str}_{time_suffix}.epub"
            file_path = os.path.join(self.output_dir, file_name)

        book = epub.EpubBook()
        book.set_title(f"{site_name} ({today_str})")
        book.set_language("ko")
        book.set_identifier(f"x3-websync-{safe_site_name}-{today_str}")

        if generate_cover:
            cover_bytes = self._make_cover_image(site_name, len(articles), today_str)
            if cover_bytes:
                cover_item = epub.EpubItem(
                    uid="cover-image",
                    file_name="images/cover.jpg",
                    media_type="image/jpeg",
                    content=cover_bytes,
                )
                book.add_item(cover_item)
                book.set_cover("images/cover.jpg", cover_bytes)

        spine = ["nav"]
        toc = []
        custom_css = self._resolve_css()

        for idx, art in enumerate(articles):
            safe_title = html.escape(art.get("title", ""), quote=True)
            summary_html = art.get("summary_html", "")
            body_html = self._sanitize_body_html(art.get("content", ""))

            chapter = epub.EpubHtml(
                title=art.get("title", f"Chapter {idx + 1}"),
                file_name=f"chap_{idx + 1}.xhtml",
                lang="ko",
            )
            chapter.content = f"""
            <?xml version="1.0" encoding="utf-8"?>
            <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
            <html xmlns="http://www.w3.org/1999/xhtml" xml:lang="ko">
            <head>
                <meta http-equiv="Content-Type" content="application/xhtml+xml; charset=utf-8" />
                <title>{safe_title}</title>
                <style>
                    {custom_css}
                </style>
            </head>
            <body>
                <h1>{safe_title}</h1>
                {summary_html}
                {body_html}
            </body>
            </html>
            """
            book.add_item(chapter)
            toc.append(chapter)
            spine.append(chapter)

        book.toc = tuple(toc)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = spine

        epub.write_epub(file_path, book)
        return file_path

    def build_digest(self, articles_by_site: dict[str, list], generate_cover: bool = True) -> str:
        """
        여러 사이트의 기사를 하나의 일간 합본 EPUB으로 빌드합니다.

        Args:
            articles_by_site: {사이트명: [기사 dict, ...]} 형식
            generate_cover: 표지 생성 여부
        Returns:
            생성된 epub 파일 경로
        """
        os.makedirs(self.output_dir, exist_ok=True)
        today = date.today().isoformat()

        total_articles = sum(len(arts) for arts in articles_by_site.values())
        if total_articles == 0:
            raise ValueError(t("epub.digest.empty"))

        filename = f"Daily_Digest_{today}.epub"
        epub_path = os.path.join(self.output_dir, filename)
        if os.path.exists(epub_path):
            suffix = datetime.now().strftime("%H%M%S_%f")
            filename = f"Daily_Digest_{today}_{suffix}.epub"
            epub_path = os.path.join(self.output_dir, filename)

        book = epub.EpubBook()
        book.set_identifier(f"x3-websync-digest-{today}")
        book.set_title(f"Daily Digest {today}")
        book.set_language("ko")
        book.add_metadata(
            "DC",
            "description",
            t("epub.digest.description", sites=len(articles_by_site), articles=total_articles),
        )

        if generate_cover:
            cover_data = self._make_cover_image("Daily Digest", total_articles, today)
            if cover_data:
                cover_item = epub.EpubItem(
                    uid="cover-image",
                    file_name="images/cover.jpg",
                    media_type="image/jpeg",
                    content=cover_data,
                )
                book.add_item(cover_item)
                book.set_cover("images/cover.jpg", cover_data)

        theme_css = self._resolve_css()

        chapters = []
        toc_sections = []
        chapter_num = 0

        for site_name, articles in articles_by_site.items():
            if not articles:
                continue

            section_chapters = []
            for art in articles:
                chapter_num += 1
                title = art.get("title", t("epub.digest.untitled", n=chapter_num))
                safe_title = html.escape(title, quote=True)
                body_html = self._sanitize_body_html(art.get("content", ""))
                summary_html = art.get("summary_html", "")
                summary_block = (
                    f'<blockquote class="ai-summary">{summary_html}</blockquote>'
                    if summary_html
                    else ""
                )

                ch = epub.EpubHtml(
                    title=f"[{site_name}] {title}",
                    file_name=f"chapter_{chapter_num:03d}.xhtml",
                    lang="ko",
                )
                ch.content = (
                    '<?xml version="1.0" encoding="utf-8"?>'
                    '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">'
                    '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="ko">'
                    '<head><meta http-equiv="Content-Type" content="application/xhtml+xml; charset=utf-8"/>'
                    f"<title>{safe_title}</title>"
                    f"<style>{theme_css}</style>"
                    "</head><body>"
                    f'<p style="font-size:0.8em;color:#888;">&mdash; {site_name}</p>'
                    f"<h1>{safe_title}</h1>"
                    f"{summary_block}"
                    f"{body_html}"
                    "</body></html>"
                ).encode("utf-8")
                book.add_item(ch)
                chapters.append(ch)
                section_chapters.append(ch)

            toc_sections.append((epub.Section(site_name), tuple(section_chapters)))

        book.toc = tuple(toc_sections)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav"] + chapters

        epub.write_epub(epub_path, book)
        return epub_path
