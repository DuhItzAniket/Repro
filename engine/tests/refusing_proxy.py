"""An HTTP proxy that refuses every request and remembers where each one was going.

Tests that start the Claude Code CLI point ``HTTPS_PROXY`` and ``HTTP_PROXY`` here (the CLI
respects both: code.claude.com/docs/en/network-config, read 2026-10-15), with loopback left
out through ``NO_PROXY`` for the local stand-in for the API. Any connection the CLI tries to
make past this machine (an update check, telemetry, the real API) arrives here, is refused,
and is recorded, so a test can show it ran offline rather than assume it.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class RefusingProxy:
    def __init__(self) -> None:
        #: Each refused request's target (``host:port`` for CONNECT, else the URL), in order.
        self.attempts: list[str] = []
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}"

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def _refuse(self) -> None:
                with proxy._lock:
                    proxy.attempts.append(self.path)
                self.send_response(403, "offline")
                self.send_header("content-length", "0")
                self.end_headers()
                self.close_connection = True

            do_CONNECT = do_GET = do_POST = do_PUT = do_HEAD = _refuse  # noqa: N815

        return Handler

    @contextmanager
    def serving(self) -> Iterator["RefusingProxy"]:
        self._thread.start()
        try:
            yield self
        finally:
            self._server.shutdown()
            self._server.server_close()
