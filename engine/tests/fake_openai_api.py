"""A local stand-in for an OpenAI-compatible Chat Completions API (G10).

``OpenAICompatibleBackend`` is tested against it: it records every request (the body, and
whether a key came with it) and answers from a script, so a test sees exactly what the backend
sends and decides what the "model" replies, including errors such as a 429 with
``retry-after``.
"""

import json
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass(frozen=True, slots=True)
class Failure:
    """An error response: its status, message and headers."""

    status: int
    message: str = "failure"
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Raw:
    """A 200 response whose body is these bytes as they are (H01: an unusable answer)."""

    body: bytes


#: Given a request body, the assistant message to answer with, a failure, or raw bytes.
Script = Callable[[Mapping[str, Any]], "dict[str, Any] | Failure | Raw"]


def say(text: str) -> dict[str, Any]:
    return {"role": "assistant", "content": text}


def call_tools(*calls: tuple[str, Mapping[str, Any] | str], text: str = "") -> dict[str, Any]:
    """An assistant message calling tools; arguments as a mapping, or raw text."""
    return {
        "role": "assistant",
        "content": text or None,
        "tool_calls": [
            {
                "id": f"call_{index}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
                },
            }
            for index, (name, arguments) in enumerate(calls, start=1)
        ],
    }


class FakeOpenAIApi:
    """A ``ThreadingHTTPServer`` on 127.0.0.1 serving ``/v1/chat/completions``."""

    def __init__(self, script: Script, *, model: str | None = None) -> None:
        self.script = script
        self.model = model
        #: Every request body, in order, with whether it carried a bearer key.
        self.requests: list[dict[str, Any]] = []
        self.keyed: list[bool] = []
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}/v1"

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def _send(self, status: int, value: Any, headers: Mapping[str, str] = {}) -> None:
                data = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                for name, header in headers.items():
                    self.send_header(name, header)
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                with api._lock:
                    api.requests.append(body)
                    api.keyed.append(self.headers.get("authorization", "").startswith("Bearer "))
                    number = len(api.requests)
                if self.path != "/v1/chat/completions":
                    self._send(404, {"error": {"message": f"no route {self.path}"}})
                    return
                reply = api.script(body)
                if isinstance(reply, Failure):
                    self._send(reply.status, {"error": {"message": reply.message}}, reply.headers)
                    return
                if isinstance(reply, Raw):
                    self.send_response(200)
                    self.send_header("content-length", str(len(reply.body)))
                    self.end_headers()
                    self.wfile.write(reply.body)
                    return
                self._send(
                    200,
                    {
                        "id": f"chatcmpl-{number}",
                        "object": "chat.completion",
                        "model": api.model or body.get("model", "test-model"),
                        "choices": [{"index": 0, "message": reply, "finish_reason": "stop"}],
                        "usage": {
                            "prompt_tokens": 1000,
                            "completion_tokens": 100,
                            "total_tokens": 1100,
                        },
                    },
                )

        return Handler

    @contextmanager
    def serving(self) -> Iterator["FakeOpenAIApi"]:
        self._thread.start()
        try:
            yield self
        finally:
            self._server.shutdown()
            self._server.server_close()
