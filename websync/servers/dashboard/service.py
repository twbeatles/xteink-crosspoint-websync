"""웹 대시보드 서버 수명 주기 관리."""
from __future__ import annotations

import threading
from typing import Callable, Optional

from websync.core.logger import get_logger
from websync.servers.dashboard.http_server import DashboardHTTPServer

logger = get_logger()


class WebDashboard:
    """웹 대시보드 서버 관리 클래스"""

    def __init__(
        self,
        port: int = 8766,
        bind_host: str = "127.0.0.1",
        api_token: str = "",
        sync_callback: Optional[Callable] = None,
        get_log_callback: Optional[Callable] = None,
        pipeline_busy_callback: Optional[Callable[[], bool]] = None,
        get_status_callback: Optional[Callable[[], dict]] = None,
        allow_lan: bool = False,
        cancel_callback: Optional[Callable[[], bool]] = None,
    ):
        self.port = port
        self.bind_host = bind_host
        self.api_token = api_token or ""
        self.sync_callback = sync_callback
        self.get_log_callback = get_log_callback
        self.pipeline_busy_callback = pipeline_busy_callback
        self.get_status_callback = get_status_callback
        self.allow_lan = allow_lan
        self.cancel_callback = cancel_callback
        self._server: Optional[DashboardHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> bool:
        if self._running:
            return True
        if not self.api_token:
            logger.error("웹 대시보드: API 토큰이 없습니다. config.json을 확인하세요.")
            return False
        try:
            self._server = DashboardHTTPServer(
                (self.bind_host, self.port),
                self.api_token,
                self.sync_callback,
                self.get_log_callback,
                self.pipeline_busy_callback,
                self.get_status_callback,
                self.allow_lan,
                self.cancel_callback,
            )
            self.port = self._server.server_port
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            self._running = True
            return True
        except Exception as e:
            logger.error(f"웹 대시보드 서버 시작 실패: {e}")
            return False

    def stop(self):
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        self._running = False
        if server:
            server.shutdown()
            server.server_close()
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    @property
    def is_running(self) -> bool:
        return self._running

    def get_url(self) -> str:
        host = "localhost" if self.bind_host in ("127.0.0.1", "localhost") else self.bind_host
        return f"http://{host}:{self.port}/"
