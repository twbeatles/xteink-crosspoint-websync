"""config.json 설정 검증 로직 테스트"""
from websync.config.validator import validate_config, validate_site, log_validation_warnings


def _base_config():
    return {
        "font_size": 16,
        "line_height": 1.7,
        "epub_merge_mode": "per_site",
        "epub_theme": "default",
        "opds_server": {"port": 8765},
        "web_dashboard": {"port": 8766},
        "sites": [],
    }


def test_validate_config_valid():
    errors = validate_config(_base_config())
    assert errors == []


def test_validate_config_port_out_of_range():
    cfg = _base_config()
    cfg["opds_server"]["port"] = 80  # below 1024
    errors = validate_config(cfg)
    assert any("포트 범위" in e for e in errors)

    cfg["web_dashboard"]["port"] = 70000  # above 65535
    errors = validate_config(cfg)
    assert any("포트 범위" in e for e in errors)


def test_validate_config_port_not_integer():
    cfg = _base_config()
    cfg["opds_server"]["port"] = "abc"
    errors = validate_config(cfg)
    assert any("유효한 정수" in e for e in errors)


def test_validate_config_font_size_out_of_range():
    cfg = _base_config()
    cfg["font_size"] = 5  # below 8
    errors = validate_config(cfg)
    assert any("font_size" in e for e in errors)

    cfg["font_size"] = 100  # above 48
    errors = validate_config(cfg)
    assert any("font_size" in e for e in errors)


def test_validate_config_line_height_out_of_range():
    cfg = _base_config()
    cfg["line_height"] = 0.5  # below 1.0
    errors = validate_config(cfg)
    assert any("line_height" in e for e in errors)


def test_validate_config_invalid_merge_mode():
    cfg = _base_config()
    cfg["epub_merge_mode"] = "invalid_mode"
    errors = validate_config(cfg)
    assert any("epub_merge_mode" in e for e in errors)


def test_validate_config_invalid_theme():
    cfg = _base_config()
    cfg["epub_theme"] = "nonexistent_theme"
    errors = validate_config(cfg)
    assert any("epub_theme" in e for e in errors)


def test_validate_site_valid():
    site = {
        "name": "테스트",
        "type": "rss",
        "url": "https://example.com/feed",
        "limit": 5,
    }
    errors = validate_site(site)
    assert errors == []


def test_validate_site_empty_name():
    site = {"name": "", "type": "css", "url": "https://example.com", "limit": 5}
    errors = validate_site(site)
    assert any("이름" in e for e in errors)


def test_validate_site_empty_url():
    site = {"name": "테스트", "type": "css", "url": "", "limit": 5}
    errors = validate_site(site)
    assert any("URL" in e for e in errors)


def test_validate_site_invalid_url_scheme():
    site = {"name": "테스트", "type": "css", "url": "ftp://example.com", "limit": 5}
    errors = validate_site(site)
    assert any("http://" in e for e in errors)


def test_validate_site_invalid_type():
    site = {"name": "테스트", "type": "unknown_type", "url": "https://example.com", "limit": 5}
    errors = validate_site(site)
    assert any("타입" in e for e in errors)


def test_validate_site_limit_out_of_range():
    site = {"name": "테스트", "type": "css", "url": "https://example.com", "limit": 0}
    errors = validate_site(site)
    assert any("limit" in e for e in errors)

    site["limit"] = 200
    errors = validate_site(site)
    assert any("limit" in e for e in errors)


def test_log_validation_warnings_does_not_raise():
    """log_validation_warnings가 검증 실패 시 예외를 발생시키지 않고 로그만 출력해야 함."""
    cfg = _base_config()
    cfg["font_size"] = 999
    # 예외 발생 없이 정상 실행되어야 함
    log_validation_warnings(cfg)


def test_validate_site_css_requires_item_selector():
    site = {
        "name": "CSS 사이트",
        "type": "css",
        "url": "https://example.com/blog",
        "item_selector": "",
        "title_selector": "h2",
        "content_selector": ".body",
        "limit": 5,
    }
    errors = validate_site(site)
    assert any("item_selector" in e for e in errors)


def test_validate_site_css_invalid_selector_syntax():
    site = {
        "name": "CSS 사이트",
        "type": "css",
        "url": "https://example.com/blog",
        "item_selector": "[[[",
        "title_selector": "h2",
        "content_selector": ".body",
        "limit": 5,
    }
    errors = validate_site(site)
    assert any("문법" in e for e in errors)


def test_validate_site_css_valid_selectors():
    site = {
        "name": "CSS 사이트",
        "type": "css",
        "url": "https://example.com/blog",
        "item_selector": "article.post",
        "title_selector": "h2 a",
        "link_selector": "h2 a",
        "content_selector": ".entry-content",
        "limit": 5,
    }
    errors = validate_site(site)
    assert errors == []


def test_validate_config_ui_language():
    cfg = _base_config()
    cfg["ui_language"] = "fr"
    errors = validate_config(cfg)
    assert any("ui_language" in e for e in errors)

    cfg["ui_language"] = "ko"
    assert validate_config(cfg) == []
    cfg["ui_language"] = "auto"
    assert validate_config(cfg) == []
    cfg["ui_language"] = "en"
    assert validate_config(cfg) == []
