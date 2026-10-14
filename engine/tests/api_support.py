"""Helpers for API tests: a real uvicorn server on an ephemeral port."""

import threading
import time
from typing import Any

import uvicorn


class Server:
    """A real uvicorn server on an ephemeral port, in a background thread."""

    def __init__(self, app: Any) -> None:
        config = uvicorn.Config(
            app, host="127.0.0.1", port=0, log_level="warning", ws="websockets-sansio"
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> "Server":
        self.thread.start()
        deadline = time.monotonic() + 20
        while not self.server.started:
            if time.monotonic() > deadline:
                raise TimeoutError("server did not start")
            time.sleep(0.02)
        return self

    @property
    def port(self) -> int:
        (server,) = self.server.servers
        return int(server.sockets[0].getsockname()[1])

    def __exit__(self, *_: object) -> None:
        self.server.should_exit = True
        self.thread.join(20)
