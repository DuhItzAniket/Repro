"""Repro's GitHub App at work (I04, ADR-0019): deliveries in, runs and their cards out.

The App's service runs against the loopback fake of ``github_support``, which gives
installation tokens, people's roles and check runs carrying the App's ID. A pull request from
the repository runs ``repro run --pr`` for real, in a process of its own (analysed only, so
quick), and its card is reported. Gates, refusals and failures stop before a run, or replace it
with one that fails. No test reaches GitHub.
"""

import contextlib
import copy
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from cli_support import clean_env
from github_support import FakeGitHub, Upstream, make_upstream, pull
from repro.config import load_settings
from repro.integrations.github.appauth import PERMISSIONS, AppIdentity, Credentials
from repro.integrations.github.appserve import (
    GATE_ACTION,
    RERUN_ACTION,
    AppService,
    Deliveries,
    RunError,
    listener,
    run_environment,
    run_repro,
    start_workers,
)
from repro.integrations.github.report import CONCLUSION, MARKER
from repro.integrations.github.webhook import Delivery, sign
from repro.store import StoreReader

APP_ID = 4242
SECRET = b"a webhook secret for tests"
BOT = "repro-test[bot]"
Run = Callable[[str, Mapping[str, str], Sequence[str]], str]


@pytest.fixture(scope="module")
def pem() -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


@pytest.fixture
def upstream(tmp_path: Path) -> Upstream:
    return make_upstream(tmp_path / "upstream")


def own_pull(upstream: Upstream, **changes: Any) -> dict[str, Any]:
    """The pull request, from a branch of the repository itself."""
    head = {"label": "o:feature", "sha": upstream.head, "repo": {"full_name": "o/r"}}
    return pull(upstream, head=head, **changes)


@contextlib.contextmanager
def github(pr: dict[str, Any], **more: Any) -> Iterator[FakeGitHub]:
    fake = FakeGitHub({"/repos/o/r/pulls/1": pr}, app_id=APP_ID, bot=BOT, **more)
    yield from fake.serve()


@contextlib.contextmanager
def app(
    tmp_path: Path, fake: FakeGitHub, pem: bytes, *, run: Run | None = None, start: bool = True
) -> Iterator[AppService]:
    identity = AppIdentity(
        id=APP_ID,
        client_id="Iv23liTEST",
        slug="repro-test",
        name="Repro test",
        html_url="https://github.com/apps/repro-test",
        owner="o",
        webhook_url="https://smee.io/abc",
    )
    env = clean_env(tmp_path, REPRO_GITHUB_API_URL=fake.url)
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    settings = load_settings(env=env)
    deliveries = Deliveries(tmp_path / "app" / "deliveries.db")
    service = AppService(
        Credentials(identity, pem, SECRET),
        fake.url,
        deliveries,
        settings.paths.database,
        run_environment(env, settings),
        sandbox="process",  # the run is analysed only: no target code runs
        run_args=["--analyse-only"],
        run=run or run_repro,
    )
    if start:
        start_workers(service, 1)
    try:
        yield service
    finally:
        service.stop()
        deliveries.close()


def pull_request(action: str = "opened", head: str = "o/r") -> dict[str, Any]:
    return {
        "action": action,
        "number": 1,
        "pull_request": {"number": 1, "head": {"repo": {"full_name": head}}},
        "repository": {"full_name": "o/r", "html_url": "https://github.com/o/r"},
        "installation": {"id": 7},
        "sender": {"login": "author"},
    }


def button(sender: str) -> dict[str, Any]:
    """A click on the check run's button, on a fork's pull request (no ``pull_requests``)."""
    return {
        "action": "requested_action",
        "requested_action": {"identifier": "run"},
        "check_run": {"app": {"id": APP_ID}, "external_id": "pr/1", "pull_requests": []},
        "repository": {"full_name": "o/r", "html_url": "https://github.com/o/r"},
        "installation": {"id": 7},
        "sender": {"login": sender},
    }


def deliver(
    service: AppService, event: str, payload: dict[str, Any], delivery: str = "d1"
) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    return service.receive(Delivery(delivery, event, sign(SECRET, body), body))


def never(*_: object) -> str:
    raise AssertionError("nothing should have run")


def failing(*_: object) -> str:
    raise RunError("the sandbox could not start")


def test_a_pull_request_from_the_repository_is_run_and_its_card_reported(
    tmp_path: Path, upstream: Upstream, pem: bytes
) -> None:
    with github(own_pull(upstream)) as fake, app(tmp_path, fake, pem) as service:
        status, said = deliver(service, "pull_request", pull_request())
        assert (status, said) == (202, "queued: pull request #1 opened")
        assert service.drain(180)
        assert deliver(service, "pull_request", pull_request()) == (200, "already seen")
    ((pr, outcome),) = service.handled
    assert pr == "https://github.com/o/r/pull/1"
    assert outcome.startswith("run_"), outcome
    # The check run: in progress at once, then the card, with the button, the App's own.
    first = fake.made("POST", r"^/repos/o/r/check-runs$")[0].body
    assert (first["status"], first["head_sha"]) == ("in_progress", upstream.head)
    (check,) = fake.check_runs
    assert check["status"] == "completed"
    assert check["conclusion"] in CONCLUSION.values()
    assert (check["external_id"], check["actions"], check["app"]) == (
        "pr/1",
        [RERUN_ACTION],
        {"id": APP_ID},
    )
    (comment,) = fake.comments
    assert MARKER in comment["body"]
    assert comment["user"]["login"] == BOT
    # Tokens: one repository, four permissions, a new one to report with; the run used one.
    asked = fake.made("POST", r"^/app/installations/7/access_tokens$")
    assert len(asked) >= 2
    assert all(a.body == {"repositories": ["r"], "permissions": dict(PERMISSIONS)} for a in asked)
    reads = fake.made("GET", r"^/repos/o/r/pulls/1$")
    assert {r.headers["authorization"] for r in reads} <= {f"Bearer {t}" for t in fake.tokens}
    with StoreReader(load_settings(env=clean_env(tmp_path)).paths.database) as reader:
        (run,) = reader.runs(10)
        logged = "".join(e.body for e in reader.iter_events(run.id))
    assert not any(token in logged for token in fake.tokens)


def test_a_forks_pull_request_waits_for_a_click(
    tmp_path: Path, upstream: Upstream, pem: bytes
) -> None:
    with github(pull(upstream)) as fake, app(tmp_path, fake, pem, run=never) as service:
        assert deliver(service, "pull_request", pull_request(head="fork/r"))[0] == 202
        assert service.drain(30)
    assert service.handled == [("https://github.com/o/r/pull/1", "gated: action_required")]
    (check,) = fake.check_runs
    assert (check["conclusion"], check["actions"], check["external_id"]) == (
        "action_required",
        [GATE_ACTION],
        "pr/1",
    )
    assert check["head_sha"] == upstream.head
    assert fake.comments == []


def test_a_rerun_gets_a_check_run_of_its_own(
    tmp_path: Path, upstream: Upstream, pem: bytes
) -> None:
    """Found in the live trial: updating the completed check run kept its conclusion while the
    run went on, and the next card's annotations were added to the old ones."""
    roles = {"maintainer": "write"}
    with github(own_pull(upstream), roles=roles) as fake, app(tmp_path, fake, pem) as service:
        deliver(service, "pull_request", pull_request(), "d1")
        assert service.drain(180)
        first = copy.deepcopy(fake.check_runs[0])
        rerun = button("maintainer")
        rerun["check_run"]["pull_requests"] = [{"number": 1}]
        deliver(service, "check_run", rerun, "d2")
        assert service.drain(180)
    assert [r["status"] for r in fake.check_runs] == ["completed", "completed"]
    assert fake.check_runs[0] == first  # left as it was
    assert fake.check_runs[1]["actions"] == [RERUN_ACTION]
    assert fake.made("POST", r"^/repos/o/r/check-runs$")[1].body["status"] == "in_progress"
    assert len(fake.comments) == 1  # the comment is updated, not added


def test_a_click_runs_only_for_someone_with_write_access(
    tmp_path: Path, upstream: Upstream, pem: bytes
) -> None:
    roles = {"maintainer": "write", "reader": "read"}
    with (
        github(pull(upstream), roles=roles) as fake,
        app(tmp_path, fake, pem, run=failing) as service,
    ):
        deliver(service, "check_run", button("reader"), "d1")
        assert service.drain(30)
        assert fake.check_runs == []
        deliver(service, "check_run", button("maintainer"), "d2")
        assert service.drain(30)
    assert [outcome for _, outcome in service.handled] == [
        "refused: reader has read access",
        "run failed: the sandbox could not start",
    ]
    # A run that fails still completes its check run, with the button to try again.
    (check,) = fake.check_runs
    assert (check["status"], check["conclusion"], check["actions"]) == (
        "completed",
        "neutral",
        [RERUN_ACTION],
    )
    assert "the sandbox could not start" in check["output"]["summary"]


def test_a_closed_pull_request_is_not_run(tmp_path: Path, upstream: Upstream, pem: bytes) -> None:
    closed = own_pull(upstream, state="closed")
    with github(closed) as fake, app(tmp_path, fake, pem, run=never) as service:
        deliver(service, "pull_request", pull_request("reopened"))
        assert service.drain(30)
    assert service.handled == [
        ("https://github.com/o/r/pull/1", "not run: the pull request is not open")
    ]


def test_unsigned_deliveries_are_dropped_and_others_ignored_with_a_reason(
    tmp_path: Path, upstream: Upstream, pem: bytes
) -> None:
    with github(own_pull(upstream)) as fake, app(tmp_path, fake, pem, run=never) as service:
        body = json.dumps(pull_request()).encode("utf-8")
        forged = Delivery("d1", "pull_request", sign(b"not the secret", body), body)
        assert service.receive(forged) == (401, "signature does not check")
        assert service.receive(Delivery("d2", "pull_request", None, body))[0] == 401
        assert deliver(service, "ping", {"zen": "Keep it logically awesome."}, "d3") == (
            200,
            "ignored: ping event",
        )
        assert service.drain(5)
    assert service.handled == []
    assert fake.tokens == []


def test_of_the_deliveries_waiting_for_one_pull_request_the_latest_is_handled(
    tmp_path: Path, upstream: Upstream, pem: bytes
) -> None:
    calls: list[str] = []

    def run(pr: str, *_: object) -> str:
        calls.append(pr)
        raise RunError("stopped")

    with (
        github(own_pull(upstream)) as fake,
        app(tmp_path, fake, pem, run=run, start=False) as service,
    ):
        for n, action in enumerate(["opened", "synchronize", "synchronize"]):
            assert deliver(service, "pull_request", pull_request(action), f"d{n}")[0] == 202
        start_workers(service, 1)
        assert service.drain(30)
    assert calls == ["https://github.com/o/r/pull/1"]


def _post(url: str, body: bytes, headers: dict[str, str]) -> int:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=10) as answer:  # noqa: S310 - loopback
            return int(answer.status)
    except urllib.error.HTTPError as error:
        return error.code


def test_the_apps_own_port_answers_at_once_and_queues(
    tmp_path: Path, upstream: Upstream, pem: bytes
) -> None:
    with github(pull(upstream)) as fake, app(tmp_path, fake, pem, run=never) as service:
        server = listener(service, "127.0.0.1", 0)
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            body = json.dumps(pull_request(head="fork/r")).encode("utf-8")
            headers = {
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "d1",
                "X-Hub-Signature-256": sign(SECRET, body),
                "Content-Type": "application/json",
            }
            assert _post(url, body, headers) == 202
            forged = {**headers, "X-GitHub-Delivery": "d2", "X-Hub-Signature-256": "sha256=0"}
            assert _post(url, body, forged) == 401
            with pytest.raises(urllib.error.HTTPError) as got:
                urllib.request.urlopen(url, timeout=10)
            assert got.value.code == 404
            assert service.drain(30)
        finally:
            server.shutdown()
            server.server_close()
    assert [outcome for _, outcome in service.handled] == ["gated: action_required"]
