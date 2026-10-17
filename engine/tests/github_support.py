"""A fake GitHub for the integration's tests (I01, I02): a loopback REST API with state.

It serves pull requests, check runs (an update appends its annotations, as GitHub's does) and a
pull request's comments, in pages of ``per_page`` with ``Link`` headers. ``refuse`` makes a path
answer 403, as a token without the permission gets. Every request is kept, headers and body.
"""

import json
import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from gitrepo import Repo


@dataclass
class Request:
    method: str
    path: str
    headers: dict[str, str]
    body: Any


@dataclass
class FakeGitHub:
    pulls: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: The token's user for ``GET /user``; None answers 403, as for an app's token.
    login: str | None = None
    check_runs: list[dict[str, Any]] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)
    refuse: set[str] = field(default_factory=set)  # path prefixes answered 403
    requests: list[Request] = field(default_factory=list)
    url: str = ""

    def made(self, method: str, pattern: str) -> list[Request]:
        return [r for r in self.requests if r.method == method and re.search(pattern, r.path)]

    def serve(self) -> Iterator["FakeGitHub"]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw) if raw else None
                fake.requests.append(
                    Request(
                        method, self.path, {k.lower(): v for k, v in self.headers.items()}, body
                    )
                )
                parts = urlsplit(self.path)
                if any(parts.path.startswith(prefix) for prefix in fake.refuse):
                    return self._answer(403, {"message": "Resource not accessible by integration"})
                answer = fake.answer(method, parts.path, parse_qs(parts.query), body)
                if answer is None:
                    return self._answer(404, {"message": "Not Found"})
                status, data, headers = answer
                return self._answer(status, data, headers)

            def do_GET(self) -> None:
                self._handle("GET")

            def do_POST(self) -> None:
                self._handle("POST")

            def do_PATCH(self) -> None:
                self._handle("PATCH")

            def _answer(
                self, status: int, data: Any, headers: dict[str, str] | None = None
            ) -> None:
                encoded = json.dumps(data).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *_: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{server.server_address[1]}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield self
        finally:
            server.shutdown()
            server.server_close()

    def answer(  # noqa: PLR0911 - one fake API, one dispatch
        self, method: str, path: str, query: dict[str, list[str]], body: Any
    ) -> tuple[int, Any, dict[str, str]] | None:
        if method == "GET" and path in self.pulls:
            return 200, self.pulls[path], {}
        if method == "GET" and path == "/user":
            if self.login is None:
                return 403, {"message": "Resource not accessible by integration"}, {}
            return 200, {"login": self.login, "type": "User"}, {}
        if found := re.fullmatch(r"/repos/[^/]+/[^/]+/commits/([0-9a-f]+)/check-runs", path):
            name = query.get("check_name", [None])[0]
            runs = [r for r in self.check_runs if r["head_sha"] == found[1] and r["name"] == name]
            return 200, {"total_count": len(runs), "check_runs": runs}, {}
        if method == "POST" and re.fullmatch(r"/repos/[^/]+/[^/]+/check-runs", path):
            run = {**body, "id": len(self.check_runs) + 1}
            run["output"] = {**body["output"], "annotations": list(body["output"]["annotations"])}
            self.check_runs.append(run)
            return 201, run, {}
        if method == "PATCH" and (
            found := re.fullmatch(r"/repos/[^/]+/[^/]+/check-runs/(\d+)", path)
        ):
            run_found: dict[str, Any] | None = next(
                (r for r in self.check_runs if r["id"] == int(found[1])), None
            )
            if run_found is None:
                return None
            kept = run_found["output"]["annotations"]
            new = body.get("output", {})
            run_found.update({k: v for k, v in body.items() if k != "output"})
            run_found["output"] = {
                **run_found["output"],
                **new,
                "annotations": kept + new.get("annotations", []),
            }
            return 200, run_found, {}
        if found := re.fullmatch(r"/repos/[^/]+/[^/]+/issues/(\d+)/comments", path):
            if method == "POST":
                made = {"id": 1000 + len(self.comments), "body": body["body"],
                        "user": {"login": self.login or "github-actions[bot]",
                                 "type": "User" if self.login else "Bot"}}  # fmt: skip
                self.comments.append(made)
                return 201, made, {}
            size = int(query.get("per_page", ["30"])[0])
            page = int(query.get("page", ["1"])[0])
            items = self.comments[(page - 1) * size : page * size]
            more = page * size < len(self.comments)
            link = f'<{self.url}{path}?per_page={size}&page={page + 1}>; rel="next"' if more else ""
            return 200, items, ({"Link": link} if link else {})
        if method == "PATCH" and (
            found := re.fullmatch(r"/repos/[^/]+/[^/]+/issues/comments/(\d+)", path)
        ):
            comment_found: dict[str, Any] | None = next(
                (c for c in self.comments if c["id"] == int(found[1])), None
            )
            if comment_found is None:
                return None
            comment_found["body"] = body["body"]
            return 200, comment_found, {}
        return None


@dataclass(frozen=True)
class Upstream:
    """A repository where ``refs/pull/1/head`` is a commit no branch holds, as a fork's is."""

    repo: Repo
    branched: str  # where the pull request left main
    head: str  # the pull request's head, on no branch
    main: str  # main since


def make_upstream(path: Path) -> Upstream:
    repo = Repo(path)
    branched = repo.commit({"pkg/__init__.py": "", "pkg/a.py": "def f():\n    return 1\n"}, "start")
    at_branch = dict(repo.files)
    head = repo.commit({"pkg/a.py": "def f():\n    return 2\n"}, "Return 2 from f")
    repo.parent, repo.files = branched, at_branch  # main moves on without the change
    repo.commit({"README.md": "Main moved on.\n"}, "main moves on")
    main = repo.git("rev-parse", "refs/heads/main")
    repo.git("update-ref", "refs/pull/1/head", head)
    return Upstream(repo, branched, head, main)


def pull(upstream: Upstream, **changes: Any) -> dict[str, Any]:
    """``GET /repos/o/r/pulls/1``'s answer, from a fork, for ``upstream``."""
    data: dict[str, Any] = {
        "number": 1,
        "html_url": "https://github.com/o/r/pull/1",
        "title": "Return 2 from f",
        "body": "f now returns 2.",
        "state": "open",
        "draft": False,
        "base": {
            "ref": "main",
            "sha": upstream.main,
            "repo": {
                "full_name": "o/r",
                "html_url": "https://github.com/o/r",
                "clone_url": upstream.repo.path.as_uri(),
            },
        },
        "head": {"label": "fork:feature", "sha": upstream.head, "repo": {"full_name": "fork/r"}},
    }
    data.update(changes)
    return data
