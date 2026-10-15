"""A local stand-in for the Anthropic Messages API, to drive the real Claude Code CLI in tests.

The CLI that the Agent SDK bundles reaches the model over HTTP at ``ANTHROPIC_BASE_URL``; this
server answers there, so a test can run the real CLI with no network and no key, see exactly
what the CLI sends (system prompt, tools, messages) and script what the "model" replies. A
reply is a list of content blocks, streamed as server-sent events the way the API streams them
(``message_start``, a start, delta and stop per block, ``message_delta``, ``message_stop``).
"""

import json
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

#: Given a ``/v1/messages`` request body, the content blocks to answer with.
Script = Callable[[Mapping[str, Any]], list[dict[str, Any]]]

USAGE = {"input_tokens": 100, "output_tokens": 1, "cache_read_input_tokens": 0}


def text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


def tool_use(name: str, arguments: Mapping[str, Any], *, call_id: str) -> dict[str, Any]:
    return {"type": "tool_use", "id": call_id, "name": name, "input": dict(arguments)}


def _stop_reason(blocks: list[dict[str, Any]]) -> str:
    return "tool_use" if any(block["type"] == "tool_use" for block in blocks) else "end_turn"


def _message(number: int, model: str, content: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": f"msg_fake{number:04d}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": None,
        "stop_sequence": None,
        "usage": USAGE,
    }


def _events(number: int, model: str, blocks: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    yield {"type": "message_start", "message": _message(number, model, [])}
    for index, block in enumerate(blocks):
        if block["type"] == "text":
            start: dict[str, Any] = {"type": "text", "text": ""}
            delta: dict[str, Any] = {"type": "text_delta", "text": block["text"]}
        else:
            start = {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}
            delta = {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
        yield {"type": "content_block_start", "index": index, "content_block": start}
        yield {"type": "content_block_delta", "index": index, "delta": delta}
        yield {"type": "content_block_stop", "index": index}
    yield {
        "type": "message_delta",
        "delta": {"stop_reason": _stop_reason(blocks), "stop_sequence": None},
        "usage": {"output_tokens": 20},
    }
    yield {"type": "message_stop"}


def _error(kind: str, message: str) -> dict[str, Any]:
    return {"type": "error", "error": {"type": kind, "message": message}}


class FakeMessagesApi:
    """A ``ThreadingHTTPServer`` on 127.0.0.1 that records requests and answers from a script."""

    def __init__(self, script: Script) -> None:
        self.script = script
        #: Every request: (method, path, JSON body or None), in arrival order.
        self.requests: list[tuple[str, str, Any]] = []
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}"

    def messages(self) -> list[Mapping[str, Any]]:
        """The bodies of the ``/v1/messages`` calls (not token counts), in order."""
        with self._lock:
            return [
                body
                for method, path, body in self.requests
                if method == "POST" and path.split("?")[0] == "/v1/messages"
            ]

    def _record(self, method: str, path: str, body: Any) -> int:
        with self._lock:
            self.requests.append((method, path, body))
            return len(self.requests)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def _send_json(self, status: int, value: Any) -> None:
                data = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                api._record("GET", self.path, None)
                self._send_json(404, _error("not_found_error", self.path))

            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(length) or b"null")
                number = api._record("POST", self.path, body)
                path = self.path.split("?")[0]
                if path == "/v1/messages/count_tokens":
                    self._send_json(200, {"input_tokens": 100})
                    return
                if path != "/v1/messages":
                    self._send_json(404, _error("not_found_error", path))
                    return
                blocks = api.script(body)
                model = str(body.get("model", "claude-test"))
                if not body.get("stream"):
                    message = _message(number, model, blocks)
                    self._send_json(200, {**message, "stop_reason": _stop_reason(blocks)})
                    return
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache")
                self.end_headers()
                for event in _events(number, model, blocks):
                    self.wfile.write(
                        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()
                    )
                self.wfile.flush()
                self.close_connection = True

        return Handler

    @contextmanager
    def serving(self) -> Iterator["FakeMessagesApi"]:
        self._thread.start()
        try:
            yield self
        finally:
            self._server.shutdown()
            self._server.server_close()
