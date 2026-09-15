"""config.json 설정 값 검증 유틸리티"""
import re
from websync.core.logger import get_logger
from websync.i18n import t

logger = get_logger()


def validate_config(config: dict) -> list[str]:
    """
    설정 값의 유효성을 검증합니다.
    Returns:
        오류 메시지 리스트. 비어있으면 유효.
    """
    errors: list[str] = []

    # 포트 범위 검증
    for section_key, port_key in [
        ("opds_server", "port"),
        ("web_dashboard", "port"),
    ]:
        section = config.get(section_key, {})
        port = section.get(port_key)
        if port is not None:
            try:
                port_int = int(port)
                if not (1024 <= port_int <= 65535):
                    errors.append(t(
                        "validator.port_range",
                        section=section_key,
                        port_key=port_key,
                        port=port,
                    ))
            except (ValueError, TypeError):
                errors.append(t(
                    "validator.port_not_int",
                    section=section_key,
                    port_key=port_key,
                    port=port,
                ))

    # font_size 범위
    font_size = config.get("font_size")
    if font_size is not None:
        try:
            fs = int(font_size)
            if not (8 <= fs <= 48):
                errors.append(t("validator.font_size_range", value=font_size))
        except (ValueError, TypeError):
            errors.append(t("validator.font_size_not_int", value=font_size))

    # line_height 범위
    line_height = config.get("line_height")
    if line_height is not None:
        try:
            lh = float(line_height)
            if not (1.0 <= lh <= 3.0):
                errors.append(t("validator.line_height_range", value=line_height))
        except (ValueError, TypeError):
            errors.append(t("validator.line_height_not_float", value=line_height))

    # epub_merge_mode 검증
    merge_mode = config.get("epub_merge_mode", "per_site")
    if merge_mode not in ("per_site", "daily_digest"):
        errors.append(t("validator.merge_mode", value=merge_mode))

    # epub_theme 검증
    theme = config.get("epub_theme", "default")
    valid_themes = ("default", "serif_classic", "sans_modern", "dark_eink", "custom")
    if theme not in valid_themes:
        errors.append(t("validator.theme", themes=valid_themes, value=theme))

    ui_language = config.get("ui_language")
    if ui_language is not None and str(ui_language).strip().lower() not in ("auto", "ko", "en"):
        errors.append(t("validator.ui_language", value=ui_language))

    # 사이트 검증
    for i, site in enumerate(config.get("sites", [])):
        site_errors = validate_site(site)
        for err in site_errors:
            errors.append(f"sites[{i}] ({site.get('name', '?')}): {err}")

    return errors


def validate_site(site: dict) -> list[str]:
    """개별 사이트 설정 검증"""
    errors: list[str] = []

    if not site.get("name", "").strip():
        errors.append(t("validator.site_name_empty"))

    url = site.get("url", "").strip()
    if not url:
        errors.append(t("validator.url_empty"))
    elif not (url.startswith("http://") or url.startswith("https://")):
        errors.append(t("validator.url_scheme", url=url[:50]))

    site_type = site.get("type", "css")
    try:
        from websync.scrapers.types import SCRAPER_TYPES
        valid_types = SCRAPER_TYPES
    except Exception:
        valid_types = (
            "css", "rss", "velog", "naver", "tistory", "brunch", "newneek",
            "youtube", "substack", "naver_cafe", "naver_post", "soonsal", "moneyletter",
        )
    if site_type not in valid_types:
        errors.append(t("validator.invalid_type", type=site_type))

    limit = site.get("limit", 5)
    try:
        limit_int = int(limit)
        if not (1 <= limit_int <= 100):
            errors.append(t("validator.limit_range", value=limit))
    except (ValueError, TypeError):
        errors.append(t("validator.limit_not_int", value=limit))

    # CSS 타입: 필수 선택자·문법
    if site_type == "css":
        item_sel = (site.get("item_selector") or "").strip()
        if not item_sel:
            errors.append(t("validator.css_item_required"))
        for key in ("item_selector", "title_selector", "content_selector", "link_selector"):
            sel = site.get(key)
            if sel is None or not str(sel).strip():
                continue
            err = _css_selector_syntax_error(str(sel).strip())
            if err:
                errors.append(f"{key}: {err}")
        remove = (site.get("remove_selectors") or "").strip()
        if remove:
            for part in remove.split(","):
                part = part.strip()
                if not part:
                    continue
                err = _css_selector_syntax_error(part)
                if err:
                    errors.append(f"remove_selectors ({part}): {err}")
                    break

    return errors


def _css_selector_syntax_error(selector: str) -> str:
    """soupsieve 문법 검사. 정상이면 빈 문자열."""
    if not selector or selector in (".", ":scope"):
        return ""
    try:
        from bs4 import BeautifulSoup

        BeautifulSoup("<html><body></body></html>", "html.parser").select(selector)
    except Exception as e:
        return t("validator.selector_syntax", error=e)
    return ""


def log_validation_warnings(config: dict) -> None:
    """설정 검증 결과를 경고 로그로 출력합니다 (로드는 중단하지 않음)."""
    errors = validate_config(config)
    for err in errors:
        logger.warning(t("validator.warning", error=err))
