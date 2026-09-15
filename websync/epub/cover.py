"""EPUB 표지 이미지 생성 (Pillow 선택 의존)."""
from __future__ import annotations

import io

from websync.i18n import t


def make_cover_image(site_name: str, article_count: int, today_str: str) -> bytes | None:
    """Pillow를 사용해 EPUB 표지 이미지를 동적으로 생성. Pillow 미설치 시 None 반환."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import textwrap

        W, H = 600, 800
        img = Image.new("RGB", (W, H), color="#1e1e2e")
        draw = ImageDraw.Draw(img)

        for y in range(H):
            ratio = y / H
            r = int(0x1e + (0x31 - 0x1e) * ratio)
            g = int(0x1e + (0x32 - 0x1e) * ratio)
            b = int(0x2e + (0x44 - 0x2e) * ratio)
            draw.line([(0, y), (W, y)], fill=(r, g, b))

        try:
            font_title = ImageFont.truetype("malgunbd.ttf", 48)
            font_sub = ImageFont.truetype("malgun.ttf", 28)
            font_small = ImageFont.truetype("malgun.ttf", 22)
        except Exception:
            font_title = ImageFont.load_default()
            font_sub = font_title
            font_small = font_title

        draw.rectangle([40, 80, W - 40, 85], fill="#89b4fa")
        wrapped = textwrap.fill(site_name, width=12)
        draw.multiline_text(
            (W // 2, 160), wrapped, font=font_title, fill="#cdd6f4", anchor="mm", align="center"
        )
        draw.text((W // 2, H // 2 - 20), today_str, font=font_sub, fill="#89b4fa", anchor="mm")
        draw.text(
            (W // 2, H // 2 + 40),
            t("epub.cover.articles", n=article_count),
            font=font_small,
            fill="#a6e3a1",
            anchor="mm",
        )
        draw.rectangle([40, H - 85, W - 40, H - 80], fill="#89b4fa")
        draw.text((W // 2, H - 55), "X3 WebSync", font=font_small, fill="#585b70", anchor="mm")

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except ImportError:
        try:
            from websync.core.logger import get_logger
            get_logger().info(t("epub.cover.pillow_skip"))
        except Exception:
            pass
        return None
    except Exception:
        return None
