"""사용자 대면 한글 리터럴이 카탈로그 밖으로 되돌아가지 않는지 가드."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEBSYNC = ROOT / "websync"

# 콘텐츠 매칭·고유명·샘플 데이터. UI 크롬이 아님.
_ALLOW_FILES = {
    "websync/scrapers/presets.py",  # 프리셋 고유명·label 폴백
    "websync/scrapers/moneyletter.py",  # CTA 본문 휴리스틱
    "websync/scrapers/soonsal.py",
    "websync/scrapers/brunch.py",
    "websync/scrapers/naver_post.py",  # 종료 안내 페이지 HTML 매칭
    "websync/backup/local_import.py",  # 파일명 '설정백업'
    "websync/pipeline/summarizer.py",  # LLM 프롬프트 (사용자 UI 아님)
    "websync/config/manager.py",  # 신규 설치 예시 사이트명
}


def _has_hangul(text: str) -> bool:
    return any("가" <= ch <= "힣" for ch in text)


def _iter_py_literals():
    for path in WEBSYNC.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("websync/i18n/"):
            continue
        if rel.startswith("websync/scrapers/selector_assistant/"):
            # 한글 내비 토큰·정규식 (구 selector_assistant.py)
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        docstring_ids: set[int] = set()
        fstring_const_ids: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(getattr(node.body[0], "value", None), ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                ):
                    docstring_ids.add(id(node.body[0].value))
            if isinstance(node, ast.JoinedStr):
                for part in node.values:
                    if isinstance(part, ast.Constant):
                        fstring_const_ids.add(id(part))
                tmpl_parts: list[str] = []
                for part in node.values:
                    if isinstance(part, ast.Constant) and isinstance(part.value, str):
                        tmpl_parts.append(part.value)
                    else:
                        tmpl_parts.append("{}")
                tmpl = "".join(tmpl_parts)
                if _has_hangul(tmpl):
                    yield rel, node.lineno, tmpl
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstring_ids or id(node) in fstring_const_ids:
                continue
            if _has_hangul(node.value):
                yield rel, node.lineno, node.value


def test_no_unexpected_hangul_string_literals():
    offenders = [
        f"{rel}:{lineno}: {text[:80]!r}"
        for rel, lineno, text in _iter_py_literals()
        if rel not in _ALLOW_FILES
    ]
    assert offenders == [], "Move user-facing Korean strings into i18n catalogs:\n" + "\n".join(offenders)


def test_html_templates_have_no_raw_hangul():
    templates = (WEBSYNC / "servers" / "templates").glob("*.html")
    bad: list[str] = []
    for path in templates:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "{{i18n." in line:
                continue
            if _has_hangul(line):
                bad.append(f"{path.name}:{i}: {line.strip()[:80]}")
    assert bad == [], "Replace leftover Korean in HTML with {{i18n.key}}:\n" + "\n".join(bad)
