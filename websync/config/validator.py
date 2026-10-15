"""config.json 설정 값 검증 유틸리티"""
import re
import math
from dataclasses import dataclass
from typing import Literal
from websync.core.logger import get_logger
from websync.i18n import t

logger = get_logger()


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    code: Literal["type", "invalid_value", "non_finite"]
    message: str
    severity: Literal["error", "warning"] = "error"


def _shape_issues(value: object, defaults: dict, path: str = "") -> list[ValidationIssue]:
    if not isinstance(value, dict):
        return [ValidationIssue(path or "$", "type", f"{path or '$'}: expected object")]
    issues = []
    for key, default in defaults.items():
        if key not in value:
            continue  # Missing keys are filled by migration, never silently coerce supplied values.
        item = value[key]
        field = f"{path}.{key}" if path else key
        if isinstance(default, dict):
            issues.extend(_shape_issues(item, default, field))
            continue
        if isinstance(default, bool):
            valid = isinstance(item, bool)
        elif key in ("config_version", "_config_revision"):
            valid = type(item) is int and item >= 0
        elif isinstance(default, (int, float)):
            try:
                number = float(item) if isinstance(default, float) else int(item)
                valid = not isinstance(item, bool) and isinstance(item, (int, float, str))
                valid = valid and math.isfinite(float(number))
                if isinstance(default, int) and isinstance(item, float):
                    valid = valid and item.is_integer()
            except (TypeError, ValueError, OverflowError):
                valid = False
        else:
            valid = isinstance(item, type(default))
        if not valid:
            message = f"{field}: expected {type(default).__name__}"
            if key == "port":
                message = t("validator.port_not_int", section=path, port_key=key, port=item)
            elif key == "font_size":
                message = t("validator.font_size_not_int", value=item)
            elif key == "line_height":
                message = t("validator.line_height_not_float", value=item)
            elif key == "limit":
                message = t("validator.limit_not_int", value=item)
            issues.append(ValidationIssue(field, "type", message))
    return issues


def validate_config_structure(config: object) -> list[ValidationIssue]:
    """Fatal shape errors only; legacy semantic warnings remain loadable."""
    from websync.config.manager import ConfigManager
    issues = _shape_issues(config, ConfigManager.DEFAULT_CONFIG)
    if not isinstance(config, dict):
        return issues
    for index, site in enumerate(config.get("sites", []) if isinstance(config.get("sites", []), list) else []):
        issues.extend(_shape_issues(site, {**ConfigManager.DEFAULT_SITE, "_sync_updated_at": ""}, f"sites[{index}]"))
    devices = config.get("x3_devices", [])
    if isinstance(devices, list):
        for index, device in enumerate(devices):
            issues.extend(_shape_issues(device, {"name": "", "ip": "", "id": "", "alias_ids": []}, f"x3_devices[{index}]"))
    for section in ("portable_data", "backup_sync"):
        data = config.get(section)
        if isinstance(data, dict) and "deleted_sites" in data:
            deleted = data["deleted_sites"]
            if not isinstance(deleted, list):
                issues.append(ValidationIssue(f"{section}.deleted_sites", "type", f"{section}.deleted_sites: expected list"))
            else:
                for index, item in enumerate(deleted):
                    issues.extend(_shape_issues(item, {"url": "", "deleted_at": ""}, f"{section}.deleted_sites[{index}]"))
    string_lists = [("x3_primary_device_alias_ids", config.get("x3_primary_device_alias_ids", []))]
    watch = config.get("calibre_watch")
    if isinstance(watch, dict):
        string_lists.append(("calibre_watch.pending_files", watch.get("pending_files", [])))
        jobs = watch.get("pending_jobs", {})
        if isinstance(jobs, dict):
            from websync.watch.retry import valid_pending_job
            for path, state in jobs.items():
                if not isinstance(path, str) or not valid_pending_job(state):
                    field = f"calibre_watch.pending_jobs[{path!r}]"
                    issues.append(ValidationIssue(field, "type", f"{field}: invalid pending job"))
    if isinstance(devices, list):
        for index, device in enumerate(devices):
            if isinstance(device, dict):
                string_lists.append((f"x3_devices[{index}].alias_ids", device.get("alias_ids", [])))
    for field, items in string_lists:
        if isinstance(items, list):
            for index, item in enumerate(items):
                if not isinstance(item, str):
                    path = f"{field}[{index}]"
                    issues.append(ValidationIssue(path, "type", f"{path}: expected str"))
    return issues


def validate_site_issues(site: object) -> list[ValidationIssue]:
    from websync.config.manager import ConfigManager
    issues = _shape_issues(site, {**ConfigManager.DEFAULT_SITE, "_sync_updated_at": ""})
    if issues:
        return issues
    assert isinstance(site, dict)
    from websync.scrapers.types import SCRAPER_TYPES
    from urllib.parse import urlsplit
    issues = []
    def add(field: str, message: str) -> None:
        issues.append(ValidationIssue(field, "invalid_value", message))
    if not site.get("name", "").strip():
        add("name", t("validator.site_name_empty"))
    url = site.get("url", "").strip()
    if not url:
        add("url", t("validator.url_empty"))
    else:
        try:
            parsed = urlsplit(url)
            valid_url = parsed.scheme in ("http", "https") and bool(parsed.hostname)
            parsed.port  # Reject malformed ports instead of deferring to requests.
        except ValueError:
            valid_url = False
        if not valid_url:
            add("url", t("validator.url_scheme", url=url[:50]))
    site_type = site.get("type", "css")
    if site_type not in SCRAPER_TYPES:
        add("type", t("validator.invalid_type", type=site_type))
    if not 1 <= int(site.get("limit", 5)) <= 100:
        add("limit", t("validator.limit_range", value=site.get("limit")))
    if site_type == "css":
        if not site.get("item_selector", "").strip():
            add("item_selector", t("validator.css_item_required"))
        for key in ("item_selector", "title_selector", "content_selector", "link_selector", "remove_selectors"):
            selector = site.get(key, "").strip()
            if selector:
                error = _css_selector_syntax_error(selector)
                if error:
                    add(key, f"{key}: {error}")
    return issues


def validate_config_issues(config: object) -> list[ValidationIssue]:
    issues = validate_config_structure(config)
    if issues:
        return issues
    assert isinstance(config, dict)
    # Keep existing localized value checks, but attach a stable field for callers.
    for key, value in config.items():
        if key == "sites":
            for index, site in enumerate(value):
                for issue in validate_site_issues(site):
                    issues.append(ValidationIssue(f"sites[{index}].{issue.field}", issue.code, issue.message, "warning"))
        else:
            for message in _validate_config_values({key: value, "sites": []}):
                field = f"{key}.port" if key in ("opds_server", "web_dashboard") else key
                issues.append(ValidationIssue(field, "invalid_value", message, "warning"))
    return issues


def validate_config(config: object) -> list[str]:
    return [issue.message for issue in validate_config_issues(config)]


def validate_site(site: object) -> list[str]:
    return [issue.message for issue in validate_site_issues(site)]


def _validate_config_values(config: dict) -> list[str]:
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
