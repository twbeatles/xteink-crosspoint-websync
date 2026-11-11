"""X3 WebSync 경량 웹 대시보드 서버 (하위 호환 Deprecated 래퍼).

권장 Canonical Import 경로: `from websync.servers.dashboard import WebDashboard`
"""
from websync.servers.dashboard import (
    DashboardHandler,
    DashboardHTTPServer,
    WebDashboard,
)
from websync.servers.dashboard.http_server import (
    DashboardHTTPServer as _DashboardHTTPServer,
)
from websync.servers.dashboard.session import (
    SESSION_COOKIE_NAME as _session_cookie_name,
)
from websync.servers.dashboard.session import (
    SESSION_MAX_AGE_SEC as _SESSION_MAX_AGE_SEC,
)
from websync.servers.dashboard.session import (
    session_valid as _session_valid,
)
from websync.servers.dashboard.session import (
    session_value as _session_value,
)
from websync.servers.dashboard.session import (
    token_matches as _token_matches,
)
from websync.servers.dashboard.templates_loader import (
    dashboard_html as _dashboard_html,
)
from websync.servers.dashboard.templates_loader import (
    load_template as _load_template,
)
from websync.servers.dashboard.templates_loader import (
    login_html as _login_html,
)

__all__ = [
    "WebDashboard",
    "DashboardHandler",
    "DashboardHTTPServer",
    "_DashboardHTTPServer",
    "_load_template",
    "_session_value",
    "_session_valid",
    "_token_matches",
    "_login_html",
    "_dashboard_html",
    "_session_cookie_name",
    "_SESSION_MAX_AGE_SEC",
]
