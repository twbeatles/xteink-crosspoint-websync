"""websync.config.secrets 유틸 테스트 (N5 — 시크릿 마스킹).

mask_secret / redact_config_for_log 의 동작을 검증한다.
GUI 토글 로직이 mask_secret 에 의존하므로 유틸 자체를 고정한다.
"""

from websync.config.secrets import (
    SECRET_FIELD_PATHS,
    mask_secret,
    redact_config_for_log,
)


def test_mask_secret_empty():
    assert mask_secret("") == ""
    assert mask_secret(None) == ""


def test_mask_secret_short_value_fully_masked():
    # visible_tail(기본 4) 이하면 전부 *
    assert mask_secret("abc") == "***"
    assert mask_secret("ab", visible_tail=4) == "**"


def test_mask_secret_keeps_tail_by_default():
    assert mask_secret("abcdefghij") == "******ghij"
    # 19자 → 15개 * + 뒤 4자리
    assert mask_secret("sk-1234567890abcdef", visible_tail=4) == "***************cdef"


def test_mask_secret_custom_visible_tail():
    result = mask_secret("abcdefghij", visible_tail=6)
    # 뒤 6자리 노출, 앞은 * 처리
    assert result.endswith("efghij")
    assert result.startswith("*")
    assert len(result) == len("abcdefghij")


def test_redact_config_masks_all_secret_paths():
    config = {
        "ai_summary": {"api_key": "sk-verysecret12345"},
        "web_dashboard": {"api_token": "tok_abcdef123456"},
        "opds_server": {"api_key": "opds_key_xyz"},
        "translation": {"libretranslate_api_key": "lt_key_abc"},
        "x3_ip": "192.168.1.10",  # 비-시크릿 필드는 통과
    }
    redacted = redact_config_for_log(config)

    # 시크릿 필드는 마스킹
    assert redacted["ai_summary"]["api_key"] != "sk-verysecret12345"
    assert "*" in redacted["ai_summary"]["api_key"]
    assert redacted["web_dashboard"]["api_token"] != "tok_abcdef123456"
    assert redacted["opds_server"]["api_key"] != "opds_key_xyz"
    assert redacted["translation"]["libretranslate_api_key"] != "lt_key_abc"
    # 비-시크릿 필드는 보존
    assert redacted["x3_ip"] == "192.168.1.10"


def test_redact_config_does_not_mutate_original():
    config = {"ai_summary": {"api_key": "sk-verysecret12345"}}
    original_value = config["ai_summary"]["api_key"]
    redact_config_for_log(config)
    # 원본은 변경되지 않아야
    assert config["ai_summary"]["api_key"] == original_value


def test_redact_config_handles_missing_fields():
    # 시크릿 필드가 아예 없는 config 도 crash 없이 동작
    redacted = redact_config_for_log({"x3_ip": "1.1.1.1"})
    assert redacted["x3_ip"] == "1.1.1.1"


def test_secret_field_paths_covers_known_secrets():
    """알려진 시크릿 4종이 모두 SECRET_FIELD_PATHS 에 포함되어 있는지."""
    expected = {
        "ai_summary.api_key",
        "web_dashboard.api_token",
        "opds_server.api_key",
        "translation.libretranslate_api_key",
    }
    assert expected.issubset(set(SECRET_FIELD_PATHS))
