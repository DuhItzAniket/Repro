"""GitHub's REST API, as much of it as Repro reads (I01): one GET at a time, JSON back.

Every request names the API version, ``X-GitHub-Api-Version: 2026-03-10``, and asks for
``application/vnd.github+json``; it carries a ``User-Agent``, without which GitHub rejects it,
and, when one is set, the token as ``Authorization: Bearer`` [GitHub REST API docs, "API
versions" and "Getting started with the REST API", checked 2026-10-17]. The token comes from
``GITHUB_TOKEN``, else ``GH_TOKEN``; public repositories need none, at 60 requests an hour
["Rate limits for the REST API", checked 2026-10-17].

A failure is a ``GitHubError`` whose message says what to do, and never holds the token. A
redirect to another host drops the token: it is GitHub's to see, nobody else's.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Final

from repro import __version__

API_VERSION: Final = "2026-03-10"
DEFAULT_API_URL: Final = "https://api.github.com"
#: Where the token is looked for, in order: Actions sets the first, the GitHub CLI reads both.
TOKEN_VARIABLES: Final = ("GITHUB_TOKEN", "GH_TOKEN")
TIMEOUT_S: Final = 30.0
LOOPBACK: Final = frozenset({"127.0.0.1", "::1", "localhost"})
#: The most pages of a listing read: 2,000 items, far more than a pull request's comments.
PAGES_MAX: Final = 20


class GitHubError(Exception):
    """GitHub could not be read or written; the message says why, in words a person can act
    on."""


@dataclass(frozen=True)
class Answer:
    """GitHub's answer: its JSON (None when it sent none) and its headers."""

    data: Any
    headers: Mapping[str, str]


def token_from(env: Mapping[str, str]) -> tuple[str, str] | None:
    """The token and the variable it came from, or None when neither is set."""
    for name in TOKEN_VARIABLES:
        if value := env.get(name, "").strip():
            return value, name
    return None


def is_loopback(url: str) -> bool:
    return (urllib.parse.urlsplit(url).hostname or "") in LOOPBACK


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect, without the token when it leads to another host."""

    def redirect_request(  # noqa: PLR0917 - urllib's signature
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if (
            new is not None
            and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc
        ):
            new.remove_header("Authorization")
        return new


@dataclass(frozen=True)
class GitHubApi:
    """The REST API at ``base_url`` (github.com's, or a GitHub Enterprise Server's)."""

    base_url: str = DEFAULT_API_URL
    token: str | None = None
    #: The variable the token came from, to name it in messages (never the token itself).
    token_source: str | None = None
    timeout_s: float = TIMEOUT_S

    @classmethod
    def from_environment(
        cls, base_url: str = DEFAULT_API_URL, env: Mapping[str, str] | None = None
    ) -> "GitHubApi":
        found = token_from(os.environ if env is None else env)
        token, source = found if found is not None else (None, None)
        return cls(base_url=base_url.rstrip("/"), token=token, token_source=source)

    def headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": f"repro/{__version__}",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def get(self, path: str) -> Any:
        """The JSON at ``path`` (``/repos/...``), or a ``GitHubError``."""
        return self.request("GET", path).data

    def request(self, method: str, path: str, body: Any = None) -> "Answer":
        """``method`` on ``path`` with ``body`` as JSON: GitHub's answer, or a ``GitHubError``."""
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = self.headers() | ({"Content-Type": "application/json"} if data else {})
        request = urllib.request.Request(  # noqa: S310 - https, or a loopback test server (settings)
            self.base_url + path, data=data, headers=headers, method=method
        )
        opener = urllib.request.build_opener(_SameHostRedirects)
        try:
            with opener.open(request, timeout=self.timeout_s) as response:
                raw, answered = response.read(), dict(response.headers.items())
        except urllib.error.HTTPError as error:
            raise GitHubError(self._refused(error, path)) from None
        except (urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise GitHubError(f"cannot reach GitHub's API at {self.base_url}: {reason}") from None
        try:
            return Answer(json.loads(raw.decode("utf-8")) if raw else None, answered)
        except (UnicodeDecodeError, ValueError):
            raise GitHubError(f"GitHub's API answered {path} with something not JSON") from None

    def pages(self, path: str, limit: int = PAGES_MAX) -> Iterator[Any]:
        """The items of a listing, 100 a page, following its ``next`` links (at most ``limit``)."""
        here: str | None = f"{path}{'&' if '?' in path else '?'}per_page=100"
        for _ in range(limit):
            if here is None:
                return
            answer = self.request("GET", here)
            if not isinstance(answer.data, list):
                raise GitHubError(f"GitHub's API answered {path} with something not a list")
            yield from answer.data
            here = self._next(answer.headers)

    def _next(self, headers: Mapping[str, str]) -> str | None:
        links = next((v for k, v in headers.items() if k.lower() == "link"), "")
        for part in links.split(","):
            url, _, rel = part.partition(";")
            if 'rel="next"' in rel:
                target = url.strip().strip("<>")
                if not target.startswith(self.base_url + "/"):
                    raise GitHubError("GitHub's next page is on another server")
                return target[len(self.base_url) :]
        return None

    def _refused(self, error: urllib.error.HTTPError, path: str) -> str:
        status, headers = error.code, error.headers
        said = _message(error)
        if status == 404:  # noqa: PLR2004 - HTTP's
            if self.token is None:
                return (
                    f"{path}: not found. A private repository needs a token: set "
                    f"{' or '.join(TOKEN_VARIABLES)}"
                )
            return f"{path}: not found, or the token in {self.token_source} cannot see it"
        if status == 401:  # noqa: PLR2004
            return f"the token in {self.token_source} was refused (401): it may have expired"
        if status in {403, 429} and (headers.get("x-ratelimit-remaining") == "0"):
            reset = headers.get("x-ratelimit-reset")
            when = (
                time.strftime("%H:%M UTC", time.gmtime(int(reset)))
                if reset and reset.isdigit()
                else "later"
            )
            hint = "" if self.token else f"; a token ({TOKEN_VARIABLES[0]}) allows far more"
            return f"GitHub's rate limit is spent until {when}{hint}"
        if status in {403, 429} and (wait := headers.get("retry-after")):
            return f"GitHub asks to wait {wait} s before the next request (a secondary rate limit)"
        return f"GitHub's API answered {path} with {status}" + (f": {said}" if said else "")


def _message(error: urllib.error.HTTPError) -> str:
    """GitHub's own explanation (``message``), short; empty when there is none."""
    try:
        found = json.loads(error.read().decode("utf-8")).get("message", "")
    except (OSError, UnicodeDecodeError, ValueError, AttributeError):
        return ""
    return str(found).splitlines()[0][:200] if found else ""
