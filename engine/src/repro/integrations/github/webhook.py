"""What a GitHub App delivery is, and what Repro does about it (I04, ADR-0019).

A delivery is trusted only once its ``X-Hub-Signature-256`` checks: ``sha256=`` and the
HMAC-SHA256 hex digest of the payload with the webhook secret, compared in constant time
[docs.github.com, "Validating webhook deliveries", read on 2026-10-21]. Nothing reads the
payload before that.

Then ``decide`` says what it asks for, from the payload alone:

- a pull request ``opened``, ``reopened`` or ``synchronize``d from the repository itself is
  **run**. From a fork it is **gated**: its check run asks for a click, and nothing runs;
- a ``check_run`` of this App's, ``rerequested`` or with the requested action ``run``, is run
  **if the person who asked may**: the worker checks that they have ``admin`` or ``write`` on
  the repository before anything runs. This is how a fork's pull request is run;
- anything else is **ignored**, with the reason.

A ``check_run`` names its pull request in ``pull_requests``, which GitHub leaves empty for a
fork's; Repro's own check runs carry it in ``external_id`` (``pr/<number>``) too.
"""

import fnmatch
import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

SIGNATURE_PREFIX: Final = "sha256="
PULL_ACTIONS: Final = frozenset({"opened", "reopened", "synchronize"})
#: The requested action on Repro's check runs: run (again).
RUN_ACTION: Final = "run"
_EXTERNAL: Final = re.compile(r"pr/(\d+)")

Kind = Literal["run", "gate", "ignore"]


def external_id(number: int) -> str:
    return f"pr/{number}"


def sign(secret: bytes, body: bytes) -> str:
    return SIGNATURE_PREFIX + hmac.new(secret, body, hashlib.sha256).hexdigest()


def verify(secret: bytes, body: bytes, signature: str | None) -> bool:
    """Whether ``signature`` is GitHub's for ``body`` with ``secret``."""
    if not secret or not signature or not signature.startswith(SIGNATURE_PREFIX):
        return False
    return hmac.compare_digest(sign(secret, body), signature.strip())


@dataclass(frozen=True)
class Delivery:
    """One delivery as received: its headers' values and the payload's bytes."""

    id: str
    event: str
    signature: str | None
    body: bytes

    @classmethod
    def from_headers(cls, headers: Mapping[str, str], body: bytes) -> "Delivery":
        lower = {key.lower(): value for key, value in headers.items()}
        return cls(
            id=lower.get("x-github-delivery", ""),
            event=lower.get("x-github-event", ""),
            signature=lower.get("x-hub-signature-256"),
            body=body,
        )


@dataclass(frozen=True)
class Decision:
    kind: Kind
    reason: str
    #: Set for ``run`` and ``gate``.
    owner: str = ""
    repo: str = ""
    number: int = 0
    installation: int = 0
    html_url: str = ""
    #: Who asked, for a run someone requested: they must have write access.
    requested_by: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def pr_url(self) -> str:
        return f"{self.html_url}/pull/{self.number}"


def _ignore(reason: str) -> Decision:
    return Decision("ignore", reason)


def allowed(full_name: str, patterns: Sequence[str]) -> bool:
    """Whether the settings let the App run on ``full_name`` (no patterns: every repository)."""
    return not patterns or any(fnmatch.fnmatchcase(full_name.lower(), p.lower()) for p in patterns)


def _where(payload: Mapping[str, Any]) -> tuple[str, str, int, str] | None:
    repository = payload.get("repository") or {}
    installation = (payload.get("installation") or {}).get("id")
    full_name = repository.get("full_name")
    html_url = repository.get("html_url")
    if not (isinstance(full_name, str) and "/" in full_name and isinstance(installation, int)):
        return None
    if not isinstance(html_url, str):
        return None
    owner, _, repo = full_name.partition("/")
    return owner, repo, installation, html_url.rstrip("/")


def decide(
    event: str, payload: Mapping[str, Any], *, app_id: int, repositories: Sequence[str] = ()
) -> Decision:
    """What a verified delivery asks Repro to do."""
    if event not in {"pull_request", "check_run"}:
        return _ignore(f"{event or 'an unnamed'} event")
    action = payload.get("action")
    where = _where(payload)
    if where is None:
        return _ignore(f"{event} {action}: no repository or installation in the payload")
    owner, repo, installation, html_url = where
    if not allowed(f"{owner}/{repo}", repositories):
        return _ignore(f"{owner}/{repo} is not among app_repositories")
    base = {"owner": owner, "repo": repo, "installation": installation, "html_url": html_url}
    if event == "pull_request":
        return _pull_request(payload, action, base)
    return _check_run(payload, action, base, app_id)


def _pull_request(payload: Mapping[str, Any], action: object, base: dict[str, Any]) -> Decision:
    if action not in PULL_ACTIONS:
        return _ignore(f"pull_request {action}")
    pr = payload.get("pull_request") or {}
    number = pr.get("number")
    if not isinstance(number, int):
        return _ignore("pull_request: no number")
    head = (pr.get("head") or {}).get("repo")
    own = isinstance(head, dict) and head.get("full_name") == f"{base['owner']}/{base['repo']}"
    if own:
        return Decision("run", f"pull request #{number} {action}", number=number, **base)
    return Decision(
        "gate",
        f"pull request #{number} {action}, from a fork: run only on request",
        number=number,
        **base,
    )


def _check_run(
    payload: Mapping[str, Any], action: object, base: dict[str, Any], app_id: int
) -> Decision:
    check = payload.get("check_run") or {}
    if (check.get("app") or {}).get("id") != app_id:
        return _ignore("check_run of another app")
    if action == "rerequested":
        pass
    elif action == "requested_action":
        identifier = (payload.get("requested_action") or {}).get("identifier")
        if identifier != RUN_ACTION:
            return _ignore(f"requested action {identifier!r}")
    else:
        return _ignore(f"check_run {action}")
    number = _number(check)
    if number is None:
        return _ignore(f"check_run {action}: it names no pull request")
    sender = (payload.get("sender") or {}).get("login")
    if not isinstance(sender, str) or not sender:
        return _ignore(f"check_run {action}: no sender")
    return Decision(
        "run",
        f"pull request #{number}: {action} by {sender}",
        number=number,
        requested_by=sender,
        **base,
    )


def _number(check: Mapping[str, Any]) -> int | None:
    for pr in check.get("pull_requests") or []:
        if isinstance(pr, dict) and isinstance(pr.get("number"), int):
            return int(pr["number"])
    found = _EXTERNAL.fullmatch(str(check.get("external_id") or ""))
    return int(found[1]) if found else None


def payload_of(delivery: Delivery) -> dict[str, Any] | None:
    """The verified delivery's payload, or None when it is not a JSON object."""
    try:
        found = json.loads(delivery.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return found if isinstance(found, dict) else None
