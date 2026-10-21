"""Registering Repro's GitHub App from a manifest (I04, ADR-0019).

GitHub's manifest flow [docs.github.com, "Registering a GitHub App from a manifest", read on
2026-10-21]:

1. a form posts the manifest to ``https://github.com/settings/apps/new`` (an organization's:
   ``/organizations/<org>/settings/apps/new``), with a ``state``;
2. the person clicks Create there, and GitHub redirects to the manifest's ``redirect_url`` with
   a ``code`` and the ``state``;
3. ``POST /app-manifests/{code}/conversions`` gives the App's ID, its private key and its
   webhook secret. All three steps must be done within an hour.

Repro serves the form and the redirect on a loopback port of its own, as Probot's local setup
does. A redirect whose ``state`` is not Repro's is refused. The key and the secret go straight
from GitHub's answer into Repro's data directory (``appauth.save``). The person never copies
them, and Repro never shows them.

The App the manifest asks for:
- is private to the account that registers it;
- sends ``pull_request`` and ``check_run`` events to the relay or URL given;
- has the four permissions a run needs (``appauth.PERMISSIONS``).
"""

import html
import json
import secrets
import threading
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Final

from repro.card.exports import INFORMATION_URI
from repro.integrations.github.api import GitHubApi, GitHubError
from repro.integrations.github.appauth import PERMISSIONS, AppError, AppFiles, AppIdentity, save

EVENTS: Final = ("pull_request", "check_run")
#: GitHub's limit for the whole flow.
TIMEOUT_S: Final = 3600.0
DESCRIPTION: Final = (
    "Runs Repro on pull requests: base and head reproduced in a sandbox, their behaviour "
    "compared, and the Reproduction Card as a check run and a comment."
)


def web_url(api_url: str) -> str:
    """GitHub's site for its API: github.com's, or a GitHub Enterprise Server's (``/api/v3``)."""
    if api_url.rstrip("/") == "https://api.github.com":
        return "https://github.com"
    return api_url.rstrip("/").removesuffix("/api/v3")


def manifest(name: str, webhook_url: str, redirect_url: str) -> dict[str, Any]:
    return {
        "name": name,
        "url": INFORMATION_URI,
        "description": DESCRIPTION,
        "hook_attributes": {"url": webhook_url, "active": True},
        "redirect_url": redirect_url,
        "public": False,
        "default_permissions": dict(PERMISSIONS),
        "default_events": list(EVENTS),
    }


def default_name() -> str:
    """A name unlikely to be taken (GitHub's App names are global); editable on GitHub's page."""
    return f"Repro {secrets.token_hex(3)}"


@dataclass
class _Flow:
    files: AppFiles
    api_url: str
    target: str
    manifest: dict[str, Any]
    state: str
    webhook_url: str
    identity: AppIdentity | None = None
    error: str | None = None


def _form(flow: _Flow) -> str:
    action = f"{flow.target}?state={urllib.parse.quote(flow.state)}"
    return (
        "<!doctype html><meta charset=utf-8><title>Register Repro's GitHub App</title>"
        "<body style='font-family:system-ui;max-width:40em;margin:3em auto'>"
        "<h1>Register Repro's GitHub App</h1>"
        "<p>GitHub's page opens with the App filled in: its permissions (Checks and Pull "
        "requests: write; Contents and Metadata: read) and its events (pull requests, check "
        "runs). Click <b>Create GitHub App</b> there, then come back here.</p>"
        f"<form method=post action='{html.escape(action, quote=True)}'>"
        f"<input type=hidden name=manifest value='{html.escape(json.dumps(flow.manifest))}'>"
        "<button type=submit>Continue to GitHub</button></form>"
    )


def _exchange(flow: _Flow, code: str) -> AppIdentity:
    api = GitHubApi(base_url=flow.api_url)
    found = api.request("POST", f"/app-manifests/{urllib.parse.quote(code, safe='')}/conversions")
    data = found.data if isinstance(found.data, dict) else {}
    try:
        identity = AppIdentity(
            id=int(data["id"]),
            client_id=str(data["client_id"]),
            slug=str(data["slug"]),
            name=str(data["name"]),
            html_url=str(data["html_url"]),
            owner=str((data.get("owner") or {}).get("login", "")),
            webhook_url=flow.webhook_url,
        )
        pem, secret = str(data["pem"]), str(data["webhook_secret"])
    except (KeyError, TypeError, ValueError):
        raise GitHubError("GitHub's answer to the conversion lacks the App's parts") from None
    save(flow.files, identity, pem, secret)
    return identity


def register(
    files: AppFiles,
    *,
    api_url: str,
    webhook_url: str,
    name: str,
    org: str | None = None,
    open_page: Callable[[str], object],
    timeout_s: float = TIMEOUT_S,
) -> AppIdentity:
    """Runs the manifest flow; the App registered (raises ``AppError``)."""
    site = web_url(api_url)
    target = (
        f"{site}/organizations/{urllib.parse.quote(org, safe='')}/settings/apps/new"
        if org
        else f"{site}/settings/apps/new"
    )
    done = threading.Event()
    flow = _Flow(files, api_url, target, {}, secrets.token_urlsafe(24), webhook_url)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parts = urllib.parse.urlsplit(self.path)
            if parts.path == "/":
                return self._page(200, _form(flow))
            if parts.path != "/callback":
                return self._page(404, "Not here.")
            query = urllib.parse.parse_qs(parts.query)
            code = query.get("code", [""])[0]
            state = query.get("state", [""])[0]
            if not code or not secrets.compare_digest(state, flow.state):
                return self._page(400, "This redirect is not from the registration Repro began.")
            try:
                flow.identity = _exchange(flow, code)
            except (GitHubError, OSError) as exc:
                flow.error = str(exc)
                done.set()
                said = html.escape(str(exc))
                return self._page(502, f"GitHub's answer could not be used: {said}")
            done.set()
            install = html.escape(f"{flow.identity.html_url}/installations/new")
            return self._page(
                200,
                f"<h1>Registered {html.escape(flow.identity.name)}</h1>"
                f"<p>Install it on the repositories it should run on: "
                f"<a href='{install}'>{install}</a>. You can close this page.</p>",
            )

        def _page(self, status: int, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    local = f"http://127.0.0.1:{server.server_address[1]}"
    flow.manifest = manifest(name, webhook_url, f"{local}/callback")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        open_page(f"{local}/")
        if not done.wait(timeout_s):
            raise AppError("the registration was not finished within the hour GitHub allows")
    finally:
        server.shutdown()
        server.server_close()
    if flow.identity is None:
        raise AppError(f"the registration failed: {flow.error}")
    return flow.identity
