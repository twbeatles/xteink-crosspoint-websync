"""A loopback content origin: real HTTP without public websites or fixed ports."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


@contextmanager
def source_server():
    # Routes may be callables for deterministic response sequences, e.g. 503 -> 200.
    routes = {}
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            requests.append(self.path)
            response = routes.get(self.path, (404, {}, b"not found"))
            status, headers, body = response() if callable(response) else response
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            # Omit length when requested to exercise streamed size limits.
            if "Content-Length" not in headers and headers.get("Connection") != "close":
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", routes, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive(), "content origin did not stop"
