"""HTTP response framing and bounded graceful connection shutdown."""
import socket
import time
from http.server import BaseHTTPRequestHandler


class GracefulHTTPHandler(BaseHTTPRequestHandler):
    def finish(self):
        try:
            super().finish()
        finally:
            if getattr(self, "close_connection", True):
                # Half-close writes first, then drain a bounded amount of input.
                # Closing a socket with unread data can reset an already-sent
                # response. Never drain indefinitely on malformed requests.
                try:
                    self.connection.shutdown(socket.SHUT_WR)
                    self.connection.settimeout(0.1)
                    deadline = time.monotonic() + 0.2
                    remaining = 64 * 1024
                    while remaining > 0 and time.monotonic() < deadline:
                        chunk = self.connection.recv(min(8192, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                except OSError:
                    pass


class ExclusiveBindMixin:
    # Microsoft recommends exclusive binding on Windows; SO_REUSEADDR there
    # permits competing bindings with indeterminate behavior:
    # https://learn.microsoft.com/windows/win32/winsock/using-so-reuseaddr-and-so-exclusiveaddruse
    allow_reuse_address = not hasattr(socket, "SO_EXCLUSIVEADDRUSE")

    def server_bind(self):
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()
