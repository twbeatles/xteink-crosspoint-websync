import sys
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from websync.i18n import init_i18n

init_i18n("ko")


@pytest.fixture(autouse=True)
def _pin_ui_language_ko():
    """테스트가 언어를 바꿔도 다음 테스트는 한국어 카탈로그를 본다."""
    init_i18n("ko")
    yield
    init_i18n("ko")
