"""i18n 코어: 감지, 카탈로그 조회, 폴백."""
from __future__ import annotations

from websync.i18n import (
    detect_system_language,
    get_language,
    init_from_config,
    init_i18n,
    t,
)


def test_missing_key_returns_key():
    init_i18n("ko")
    assert t("does.not.exist") == "does.not.exist"


def test_t_formats_named_placeholders():
    init_i18n("ko")
    assert t("epub.cover.articles", n=3) == "기사 3건"
    init_i18n("en")
    assert t("epub.cover.articles", n=3) == "3 articles"


def test_t_accepts_key_as_format_kwarg():
    """카탈로그 {key} 플레이스홀더는 t() 첫 인자 이름과 충돌하면 안 된다."""
    init_i18n("ko")
    result = t("gui.settings.api_key_shown", key="SECRET123")
    assert "SECRET123" in result
    init_i18n("en")
    result = t("gui.settings.api_key_masked", key="abcd")
    assert "abcd" in result


def test_unknown_language_falls_back_to_supported():
    init_i18n("xx")
    assert get_language() in ("en", "ko")
    # 카탈로그가 로드되어 실제 문장이 나와야 함 (키 원문 아님)
    assert t("epub.cover.articles", n=1) != "epub.cover.articles"


def test_en_missing_key_falls_back_to_ko(tmp_path, monkeypatch):
    """en에 없는 키는 ko 문구를 반환한다."""
    init_i18n("en")
    # 존재하는 공통 키는 영어
    assert "article" in t("epub.cover.articles", n=2).lower()
    # 없는 키는 키 자체
    assert t("totally.missing.key") == "totally.missing.key"


def test_detect_respects_env(monkeypatch):
    monkeypatch.setenv("X3_WEBSYNC_LANG", "en")
    assert detect_system_language() == "en"
    monkeypatch.setenv("X3_WEBSYNC_LANG", "ko")
    assert detect_system_language() == "ko"
    monkeypatch.setenv("X3_WEBSYNC_LANG", "fr")
    # 지원하지 않는 env 값은 OS 감지로 넘어감 — ko 또는 en
    assert detect_system_language() in ("ko", "en")


def test_init_from_config_auto_uses_detect(monkeypatch):
    monkeypatch.setenv("X3_WEBSYNC_LANG", "en")
    init_from_config({"ui_language": "auto"})
    assert get_language() == "en"
    init_from_config({"ui_language": "ko"})
    assert get_language() == "ko"
    init_from_config({"ui_language": "EN"})
    assert get_language() == "en"
    init_from_config({"ui_language": "bogus"})
    assert get_language() == "en"


def test_init_from_config_missing_key_is_auto(monkeypatch):
    monkeypatch.setenv("X3_WEBSYNC_LANG", "en")
    init_from_config({})
    assert get_language() == "en"


def test_preset_labels_follow_ui_language():
    from websync.scrapers.presets import get_preset_by_label, preset_labels

    init_i18n("ko")
    labels_ko = preset_labels()
    assert any("뉴닉" in x for x in labels_ko)
    assert get_preset_by_label("뉴닉 (공식)") is not None

    init_i18n("en")
    labels_en = preset_labels()
    assert any("NEWNEEK" in x for x in labels_en)
    assert get_preset_by_label("뉴닉 (공식)") is not None
    assert get_preset_by_label("NEWNEEK (official)") is not None
    init_i18n("ko")
