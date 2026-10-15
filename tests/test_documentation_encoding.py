"""Catch UTF-8 text replaced by question marks in generated audit updates."""
from pathlib import Path
import re
import pytest

DOCUMENT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["README.ko.md", "CLAUDE.md", "docs/USER_GUIDE.md", "docs/DEVELOPER.md"])
def test_new_korean_guidance_is_readable_utf8(name):
    text = (DOCUMENT_ROOT / name).read_text(encoding="utf-8")
    assert "## 감사 후 안정성 개선 (2026-10-13)" in text
    section = text.split("## 감사 후 안정성 개선 (2026-10-13)", 1)[1]
    assert "동기화" in section
    assert "??" not in section


def test_audit_completion_record_is_filled_and_readable():
    text = (DOCUMENT_ROOT / "docs/AUDIT_IMPLEMENTATION.md").read_text(encoding="utf-8")
    assert "최종 실행 결과는 아래에 기록한다." not in text
    assert "passed" in text and "GitHub Actions" in text
    report = (DOCUMENT_ROOT / "PROJECT_AUDIT.md").read_text(encoding="utf-8")
    # Audit findings and their numbering change between audits. Verify a dated,
    # readable follow-up record and its evidence link, not obsolete completion text.
    assert report.lstrip("\ufeff").startswith("# Project Audit")
    followup = next((line for line in report.splitlines() if line.startswith("> 후속 개선:")), "")
    assert re.search(r"\b20\d{2}-\d{2}-\d{2}\b", followup)
    assert "??" not in followup and "\ufffd" not in followup
    assert "(docs/AUDIT_IMPLEMENTATION.md)" in report
