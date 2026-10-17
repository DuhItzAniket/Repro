"""The API's per-session token (THREAT_MODEL T13, H03).

Any process on the machine, of any user, can connect to 127.0.0.1. Without a token, each of
them could read every run: the target's code, its test output, the verdicts. So each server
that ``repro serve``, ``run`` or ``replay`` starts makes a token of its own (32 random bytes,
``secrets.token_urlsafe``), and every request for the engine's data must carry it. The
cockpit's own files hold no data and are served without it.

The token travels in the URL's fragment (``http://127.0.0.1:8780/?run=…#token=…``), which a
browser never sends to a server, so it stays out of request lines, logs and ``Referer``. The
cockpit keeps it in ``sessionStorage``, which is per origin, port included, and sends it as
``Authorization: Bearer <token>``; a WebSocket handshake cannot carry that header, so the event
stream takes it as the ``token`` query parameter instead, and uvicorn's access log, which would
print it, is off. A cookie would be simpler and is not safe here: cookies are not isolated by
port, so a browser would send it to any other server on 127.0.0.1 (RFC 6265 §8.5, "Cookies do
not provide isolation by port", https://www.rfc-editor.org/rfc/rfc6265#section-8.5, checked
2026-10-17). Tokens are compared in constant time.
"""

import hmac
import secrets
from typing import Final

from starlette.requests import HTTPConnection

TOKEN_BYTES: Final = 32
#: The query parameter that carries the token on the event stream.
QUERY: Final = "token"
UNAUTHORISED: Final = "this server needs its session token: open the URL repro printed"


def new_token() -> str:
    """A fresh session token: 32 random bytes, URL-safe base64."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def presented(connection: HTTPConnection, *, query: bool = False) -> str | None:
    """The token ``connection`` carries: ``Authorization: Bearer``, else (with ``query``, for a
    WebSocket handshake) the ``token`` query parameter."""
    scheme, _, value = connection.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return connection.query_params.get(QUERY) if query else None


def matches(given: str | None, token: str) -> bool:
    """Whether ``given`` is ``token``, compared in constant time."""
    return given is not None and hmac.compare_digest(given.encode(), token.encode())
