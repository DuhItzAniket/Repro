"""Deliveries through a relay, for a machine GitHub cannot reach (I04, ADR-0019).

The relay is a smee.io channel, as in GitHub's own guide to building an App, which also says not
to use it in production [docs.github.com, "Building a GitHub App that responds to webhook
events", read on 2026-10-21]. GitHub posts to the channel's URL, and Repro reads the channel's
event stream (server-sent events).

smee.io parses each payload and sends it on as JSON: ``data`` holds the request's headers, in
lower case, and its ``body`` as an object [probot/smee.io ``lib/server.js``; its client sends
``JSON.stringify(data.body)``, probot/smee-client ``index.ts`` v4.4.3]. GitHub's bytes are not
kept, so the signature is checked against the payload written again compactly, as smee's own
client writes it. A payload that does not come out the same fails its check and is dropped,
never run: ``repro app serve --listen`` behind the operator's own proxy keeps the bytes.

A channel's URL is not a secret that protects anything: whoever has it can read what passes
and post to it, but cannot sign.
"""

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from typing import Any, Final

from repro import __version__
from repro.integrations.github.api import is_loopback
from repro.integrations.github.webhook import Delivery
from repro.logs import get_logger

log = get_logger("github.relay")

SMEE_NEW: Final = "https://smee.io/new"
#: smee.io writes a ping now and then; a stream silent for this long is opened again.
READ_TIMEOUT_S: Final = 120.0
RETRY_S: Final = 5.0


class RelayError(Exception):
    """The relay cannot be used; the message says why."""


def check_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" and not (parts.scheme == "http" and is_loopback(url)):
        raise RelayError(f"a relay must be an https:// URL, not {url!r}")
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_: Any, **__: Any) -> None:
        return None


def new_channel(url: str = SMEE_NEW, timeout_s: float = 30.0) -> str:
    """A new smee.io channel: the address ``/new`` redirects to."""
    request = urllib.request.Request(  # noqa: S310 - https (check_url)
        check_url(url), method="HEAD", headers={"User-Agent": f"repro/{__version__}"}
    )
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout_s) as answer:
            location = answer.headers.get("Location")
    except urllib.error.HTTPError as error:  # the redirect itself, not followed
        location = error.headers.get("Location")
    except (urllib.error.URLError, OSError) as error:
        raise RelayError(f"cannot reach {url}: {getattr(error, 'reason', error)}") from None
    if not location:
        raise RelayError(f"{url} gave no new channel")
    return check_url(urllib.parse.urljoin(url, location))


def events(lines: Iterable[str]) -> Iterator[tuple[str, str]]:
    """Server-sent events, ``(event, data)``, from the stream's lines (WHATWG's format)."""
    event, data = "message", list[str]()
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            if data:
                yield event, "\n".join(data)
            event, data = "message", []
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if name == "event":
            event = value
        elif name == "data":
            data.append(value)


def relayed(data: str) -> Delivery | None:
    """The delivery a relayed event holds, its payload written compactly; None for anything
    else."""
    try:
        found = json.loads(data)
    except ValueError:
        return None
    if not isinstance(found, dict) or "body" not in found:
        return None
    headers = {key: value for key, value in found.items() if isinstance(value, str)}
    body = json.dumps(found["body"], separators=(",", ":"), ensure_ascii=False)
    try:
        return Delivery.from_headers(headers, body.encode("utf-8"))
    except UnicodeEncodeError:  # a lone surrogate: not GitHub's bytes, and cannot be checked
        return None


def listen(
    url: str,
    receive: Callable[[Delivery], object],
    stop: threading.Event,
    *,
    read_timeout_s: float = READ_TIMEOUT_S,
    retry_s: float = RETRY_S,
) -> None:
    """Hands each relayed delivery to ``receive`` until ``stop`` is set, opening the stream
    again whenever it ends. What arrives while it is closed is not seen: a re-run asks again."""
    check_url(url)
    headers = {"Accept": "text/event-stream", "User-Agent": f"repro/{__version__}"}
    while not stop.is_set():
        request = urllib.request.Request(url, headers=headers)  # noqa: S310 - check_url
        try:
            with urllib.request.urlopen(request, timeout=read_timeout_s) as stream:  # noqa: S310
                log.info("relay open", extra={"fields": {"relay": url}})
                lines = (line.decode("utf-8", "replace") for line in stream)
                for event, data in events(lines):
                    if stop.is_set():
                        return
                    if event in {"ready", "ping"}:
                        continue
                    delivery = relayed(data)
                    if delivery is None:
                        log.warning("relay: an event that is not a delivery, dropped")
                        continue
                    receive(delivery)
        except (urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            log.warning("relay closed", extra={"fields": {"relay": url, "why": str(reason)}})
        stop.wait(retry_s)
