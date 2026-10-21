"""The GitHub App at work: deliveries in, runs and their cards out (I04, ADR-0019).

``AppService.receive`` takes a delivery from the relay or the App's own port. It answers at
once, as GitHub asks within 10 seconds [docs.github.com, "Best practices for using webhooks",
read on 2026-10-21], and leaves the work to a queue:

1. the signature is checked, and a delivery that fails it is dropped (``401``);
2. its ``X-GitHub-Delivery`` is recorded, and one already seen is dropped. A redelivery keeps
   the ID, and so does a replay of an intercepted one;
3. ``webhook.decide`` says run, gate or ignore. Runs and gates are queued (``202``). Of the
   ones waiting for the same pull request, only the latest is kept.

A worker then takes each from the queue:

- with a token for that repository alone (``appauth.installation_api``), it reads the pull
  request again, and goes no further if it has closed;
- **a gate** marks the head's check run ``action_required``, with the button "Run Repro";
- **a run someone asked for** goes on only if they have ``admin`` or ``write`` on the
  repository;
- **a run** marks the check run ``in_progress`` and runs ``repro run --pr`` in a process of its
  own. The token is in that process's environment alone, and the sandbox is Docker, which
  passes no host variable to a container (D02). The run's card is then reported (I02) with a
  new token: the check run completed with its button "Re-run Repro", and the App's own comment.

A run that does not complete still completes its check run (``neutral``), with the button.
"""

import collections
import json
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final

from repro.integrations.github import report as reporting
from repro.integrations.github.api import GitHubApi, GitHubError
from repro.integrations.github.appauth import AppError, Credentials, installation_api
from repro.integrations.github.webhook import (
    RUN_ACTION,
    Decision,
    Delivery,
    decide,
    external_id,
    payload_of,
    verify,
)
from repro.logs import clean, get_logger

log = get_logger("github.app")

#: The most a delivery may weigh: GitHub sends none heavier than 25 MB.
BODY_MAX: Final = 25 * 1024 * 1024
_COMPLETED: Final = re.compile(r"\b(run_[0-9A-HJKMNP-TV-Z]{26}) completed\b")
#: The roles that may ask for a run: ``maintain`` is reported as ``write``.
MAY_RUN: Final = frozenset({"admin", "write"})
GATE_ACTION: Final = {
    "label": "Run Repro",
    "description": "Run this fork's code in Repro's sandbox",
    "identifier": RUN_ACTION,
}
RERUN_ACTION: Final = {
    "label": "Re-run Repro",
    "description": "Run Repro again on this pull request",
    "identifier": RUN_ACTION,
}


class RunError(Exception):
    """``repro run`` did not give a card; the message is its last words, scrubbed."""


class Deliveries:
    """The deliveries seen, by ID: so that none is handled twice."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, event TEXT NOT NULL, "
            "received REAL NOT NULL, outcome TEXT NOT NULL DEFAULT '')"
        )

    def first(self, delivery: Delivery) -> bool:
        """Records ``delivery``; False when its ID was seen before."""
        with self._lock:
            done = self._db.execute(
                "INSERT OR IGNORE INTO deliveries (id, event, received) VALUES (?, ?, ?)",
                (delivery.id, delivery.event, time.time()),
            )
            return done.rowcount == 1

    def outcome(self, delivery_id: str, outcome: str) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE deliveries SET outcome = ? WHERE id = ?", (outcome[:500], delivery_id)
            )

    def close(self) -> None:
        with self._lock:
            self._db.close()


def run_repro(pr_url: str, env: Mapping[str, str], extra: Sequence[str] = ()) -> str:
    """``repro run`` on the pull request in a process of its own; the completed run's ID."""
    done = subprocess.run(  # noqa: S603 - Repro itself, with a pull request's URL
        [sys.executable, "-m", "repro", "run", "--pr", pr_url, "--no-serve", *extra],
        env=dict(env),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    found = _COMPLETED.search(done.stderr)
    if done.returncode != 0 or found is None:
        last = " / ".join(line for line in done.stderr.strip().splitlines()[-3:])
        raise RunError(clean(last) or f"repro run exited {done.returncode}")
    return found[1]


@dataclass
class AppService:
    credentials: Credentials
    api_url: str
    deliveries: Deliveries
    #: The store the runs are written to, which the reports read.
    database: Path
    #: The environment ``repro run`` starts from; the token and the sandbox are set on it.
    run_env: Mapping[str, str]
    repositories: Sequence[str] = ()
    sandbox: str = "docker"
    run_args: Sequence[str] = ()
    run: Callable[[str, Mapping[str, str], Sequence[str]], str] = run_repro
    _pending: dict[tuple[str, int], Decision] = field(default_factory=dict)
    _order: collections.deque[tuple[str, int]] = field(default_factory=collections.deque)
    _busy: set[tuple[str, int]] = field(default_factory=set)
    _ready: threading.Condition = field(default_factory=threading.Condition)
    _stopping: bool = False
    #: What each handled decision came to, for the tests and the log: ``(pr, outcome)``.
    handled: list[tuple[str, str]] = field(default_factory=list)

    # -- receiving ----------------------------------------------------------------------------

    def receive(self, delivery: Delivery) -> tuple[int, str]:
        """GitHub's answer to ``delivery``: an HTTP status and a short reason."""
        if not verify(self.credentials.webhook_secret, delivery.body, delivery.signature):
            fields = {"delivery": delivery.id, "event": delivery.event}
            log.warning("delivery dropped: its signature does not check", extra={"fields": fields})
            return 401, "signature does not check"
        if not delivery.id:
            return 400, "no X-GitHub-Delivery"
        if not self.deliveries.first(delivery):
            return 200, "already seen"
        payload = payload_of(delivery)
        if payload is None:
            self.deliveries.outcome(delivery.id, "not a JSON object")
            return 400, "not a JSON object"
        decision = decide(
            delivery.event,
            payload,
            app_id=self.credentials.identity.id,
            repositories=self.repositories,
        )
        self.deliveries.outcome(delivery.id, f"{decision.kind}: {decision.reason}")
        fields = {"delivery": delivery.id, "event": delivery.event, "kind": decision.kind,
                  "reason": decision.reason}  # fmt: skip
        log.info("delivery", extra={"fields": fields})
        if decision.kind == "ignore":
            return 200, f"ignored: {decision.reason}"
        self.enqueue(decision)
        return 202, f"queued: {decision.reason}"

    def enqueue(self, decision: Decision) -> None:
        key = (decision.full_name, decision.number)
        with self._ready:
            if key not in self._pending and key not in self._order:
                self._order.append(key)
            self._pending[key] = decision  # the latest wins
            self._ready.notify()

    # -- working ------------------------------------------------------------------------------

    def _next(self) -> tuple[tuple[str, int], Decision] | None:
        with self._ready:
            while True:
                if self._stopping:
                    return None
                for key in self._order:
                    if key not in self._busy and key in self._pending:
                        self._order.remove(key)
                        self._busy.add(key)
                        return key, self._pending.pop(key)
                self._ready.wait()

    def work(self) -> None:
        """Handles queued decisions until ``stop``."""
        while (taken := self._next()) is not None:
            key, decision = taken
            try:
                outcome = self.handle(decision)
            except (GitHubError, AppError, OSError) as exc:
                outcome = f"failed: {clean(str(exc))}"
            log.info("handled", extra={"fields": {"pr": decision.pr_url, "outcome": outcome}})
            self.handled.append((decision.pr_url, outcome))
            with self._ready:
                self._busy.discard(key)
                if key in self._pending and key not in self._order:
                    self._order.append(key)
                self._ready.notify_all()

    def drain(self, timeout_s: float) -> bool:
        """Waits until nothing is queued or running (for tests); whether it got there."""
        deadline = time.monotonic() + timeout_s
        with self._ready:
            while self._pending or self._busy:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._ready.wait(left)
        return True

    def stop(self) -> None:
        with self._ready:
            self._stopping = True
            self._ready.notify_all()

    def _api(self, decision: Decision) -> GitHubApi:
        return installation_api(
            self.credentials, self.api_url, decision.installation, decision.repo
        )

    def handle(self, decision: Decision) -> str:
        api = self._api(decision)
        path = f"/repos/{decision.full_name}"
        pr = api.get(f"{path}/pulls/{decision.number}")
        if not isinstance(pr, dict) or pr.get("state") != "open":
            return "not run: the pull request is not open"
        head = str((pr.get("head") or {}).get("sha") or "")
        if decision.kind == "gate":
            self._check(api, path, head, decision, completed="action_required",
                        title="Not run: a fork's pull request",
                        summary="Repro runs a fork's pull request only when someone with write "
                        "access to this repository asks for it, with the button Run Repro.",
                        actions=[GATE_ACTION])  # fmt: skip
            return "gated: action_required"
        if decision.requested_by is not None:
            login = urllib.parse.quote(decision.requested_by, safe="")
            role = api.get(f"{path}/collaborators/{login}/permission")
            permission = role.get("permission") if isinstance(role, dict) else None
            if permission not in MAY_RUN:
                return f"refused: {decision.requested_by} has {permission or 'no'} access"
        self._check(api, path, head, decision, title="Running",
                    summary="Repro is running base and head of this pull request.")  # fmt: skip
        env = dict(self.run_env)
        env.pop("GH_TOKEN", None)
        env.update({"GITHUB_TOKEN": api.token or "", "REPRO_SANDBOX": self.sandbox})
        try:
            run_id = self.run(decision.pr_url, env, self.run_args)
        except RunError as exc:
            self._check(self._api(decision), path, head, decision, completed="neutral",
                        title="Repro could not complete",
                        summary=f"The run stopped before its card: {exc}",
                        actions=[RERUN_ACTION])  # fmt: skip
            return f"run failed: {exc}"
        return self._report(self._api(decision), decision, run_id)

    def _check(
        self,
        api: GitHubApi,
        path: str,
        head: str,
        decision: Decision,
        *,
        title: str,
        summary: str,
        completed: str | None = None,
        actions: Sequence[Mapping[str, str]] = (),
    ) -> None:
        """Creates the head's check run, or updates the App's own."""
        body: dict[str, Any] = {
            "name": reporting.CHECK_NAME,
            "external_id": external_id(decision.number),
            "output": {"title": title, "summary": summary},
            "actions": [dict(a) for a in actions],
        }
        body.update({"status": "completed", "conclusion": completed} if completed else
                    {"status": "in_progress"})  # fmt: skip
        mine = reporting.app_check_runs(api, path, head, self.credentials.identity.id)
        if mine:
            api.request("PATCH", f"{path}/check-runs/{mine[-1]['id']}", body)
        else:
            api.request("POST", f"{path}/check-runs", {**body, "head_sha": head})

    def _report(self, api: GitHubApi, decision: Decision, run_id: str) -> str:
        from repro.card import regenerate  # noqa: PLC0415 - the card's code, only when reporting
        from repro.store import StoreReader  # noqa: PLC0415

        with StoreReader(self.database) as reader:
            events = [json.loads(stored.body) for stored in reader.iter_events(run_id)]
        card = regenerate(events).card
        target = reporting.Target(
            decision.owner, decision.repo, decision.number, card["conditions"]["head"]["sha"]
        )
        reported = reporting.report(
            api,
            card,
            events,
            target,
            summary=None,
            login=self.credentials.identity.bot_login,
            app_id=self.credentials.identity.id,
            actions=[RERUN_ACTION],
            external=external_id(decision.number),
        )
        outcome = f"{run_id} {card['status']}: " + "; ".join(reported.done)
        return outcome + ("; failed: " + "; ".join(reported.failed) if reported.failed else "")


def start_workers(service: AppService, count: int) -> list[threading.Thread]:
    threads = [
        threading.Thread(target=service.work, name=f"repro-app-{i}", daemon=True)
        for i in range(count)
    ]
    for thread in threads:
        thread.start()
    return threads


def listener(service: AppService, host: str, port: int) -> ThreadingHTTPServer:
    """An HTTP server that hands each POST to ``service`` (``repro app serve --listen``)."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > BODY_MAX:
                self._answer(413 if length > BODY_MAX else 400, "no payload, or too large")
                return
            body = self.rfile.read(length)
            status, reason = service.receive(Delivery.from_headers(dict(self.headers), body))
            self._answer(status, reason)

        def do_GET(self) -> None:
            self._answer(404, "deliveries are POSTed")

        def _answer(self, status: int, reason: str) -> None:
            data = (reason + "\n").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_: object) -> None:
            pass

    return ThreadingHTTPServer((host, port), Handler)


def run_environment(base: Mapping[str, str], settings: Any) -> dict[str, str]:
    """The environment ``repro run`` starts from: this process's, with the settings that decide
    where runs go made explicit, so that a ``--data-dir`` given to the App applies to them."""
    env = dict(base)
    env["REPRO_DATA_DIR"] = str(settings.data_dir)
    env["REPRO_RUN_ROOT"] = str(settings.run_root)
    env["REPRO_GITHUB_API_URL"] = str(settings.github_api_url)
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)  # the App's token per run, never this process's own
    return env


__all__ = [
    "AppService",
    "Deliveries",
    "RunError",
    "listener",
    "run_environment",
    "run_repro",
    "start_workers",
]
