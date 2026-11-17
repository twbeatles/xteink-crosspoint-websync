"""테스트 스위트가 gitignore 로컬 경로에 의존하지 않는지 검사.

재발 방지: dist/, output/, logs/, config.json, *.db 등 CI 에 없는
경로를 테스트가 필수로 가정하면 로컬만 통과하고 GitHub Actions 가 깨집니다.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

# 테스트 코드에서 하드코딩하면 안 되는 로컬 전용 경로 패턴
FORBIDDEN_PATH_SNIPPETS = (
    r'REPO\s*/\s*["\']dist["\']',
    r'Path\([^)]*["\']dist["\']',
    r'["\']/dist/',
    r'["\']\./dist/',
    r'["\']dist/synced_posts',
    r'["\']dist/output',
    r'os\.path\.join\([^)]*["\']dist["\']',
)

# 허용: 이 파일 자체, 주석만 있는 설명, 문서 문자열 안의 금지 안내
SELF_NAME = Path(__file__).name


def _strip_comments_and_docstrings(source: str) -> str:
    """대략적으로 주석·독스트링을 제거해 실행 코드만 남깁니다."""
    # triple-quoted strings
    no_docs = re.sub(r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\')', '""', source)
    lines = []
    for line in no_docs.splitlines():
        # 단순 # 주석 제거 (문자열 안 # 은 드묾)
        if "#" in line:
            in_str = False
            quote = ""
            out = []
            i = 0
            while i < len(line):
                ch = line[i]
                if not in_str and ch == "#":
                    break
                if ch in ("'", '"') and (i == 0 or line[i - 1] != "\\"):
                    if not in_str:
                        in_str = True
                        quote = ch
                    elif quote == ch:
                        in_str = False
                out.append(ch)
                i += 1
            lines.append("".join(out))
        else:
            lines.append(line)
    return "\n".join(lines)


def test_no_hardcoded_gitignore_local_paths():
    patterns = [re.compile(p) for p in FORBIDDEN_PATH_SNIPPETS]
    offenders: list[str] = []

    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name == SELF_NAME:
            continue
        raw = path.read_text(encoding="utf-8")
        code = _strip_comments_and_docstrings(raw)
        for pat in patterns:
            if pat.search(code):
                offenders.append(f"{path.name}: matches /{pat.pattern}/")
                break

    assert not offenders, (
        "테스트가 gitignore 로컬 경로(dist 등)에 하드 의존합니다. "
        "임시 디렉터리·tests/fixtures 샘플을 사용하세요.\n" + "\n".join(offenders)
    )
