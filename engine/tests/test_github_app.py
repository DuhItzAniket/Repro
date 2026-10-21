"""Repro's GitHub App, its parts (I04, ADR-0019): credentials and tokens, deliveries and what
they ask for, the relay, and the registration.

Roadmap I04: "Webhooks, re-run button, org config." The App's private key is made for each test
module, never stored in the repository. GitHub is the loopback fake of ``github_support``; the
relay is a server-sent event stream on a loopback port. No test reaches GitHub or smee.io.
"""

import contextlib
import json
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from typer.testing import CliRunner

from cli_support import clean_env
from github_support import FakeGitHub
from repro.cli import app
from repro.integrations.github.appauth import (
    PERMISSIONS,
    AppError,
    AppFiles,
    AppIdentity,
    Credentials,
    app_jwt,
    installation_api,
    load,
    save,
)
from repro.integrations.github.appregister import manifest, register, web_url
from repro.integrations.github.relay import (
    RelayError,
    check_url,
    events,
    listen,
    new_channel,
    relayed,
)
from repro.integrations.github.webhook import (
    Delivery,
    decide,
    external_id,
    sign,
    verify,
)

runner = CliRunner()
APP_ID = 4242
SECRET = b"a webhook secret for tests"


@pytest.fixture(scope="module")
def key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def pem_of(key: rsa.RSAPrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


def identity(webhook_url: str = "https://smee.io/abc") -> AppIdentity:
    return AppIdentity(
        id=APP_ID,
        client_id="Iv23liTEST",
        slug="repro-test",
        name="Repro test",
        html_url="https://github.com/apps/repro-test",
        owner="o",
        webhook_url=webhook_url,
    )


@contextlib.contextmanager
def serving(fake: FakeGitHub) -> Iterator[FakeGitHub]:
    yield from fake.serve()


@pytest.fixture
def credentials(key: rsa.RSAPrivateKey) -> Credentials:
    return Credentials(identity(), pem_of(key).encode("ascii"), SECRET)


# -- credentials and tokens -------------------------------------------------------------------


def test_the_apps_jwt_is_rs256_from_its_client_id_for_under_ten_minutes(
    credentials: Credentials, key: rsa.RSAPrivateKey
) -> None:
    token = app_jwt(credentials, now=lambda: 1_000_000.0)
    assert jwt.get_unverified_header(token)["alg"] == "RS256"
    claims = jwt.decode(
        token, key.public_key(), algorithms=["RS256"], options={"verify_exp": False}
    )
    assert claims == {"iat": 1_000_000 - 60, "exp": 1_000_000 + 540, "iss": "Iv23liTEST"}
    assert claims["exp"] - 1_000_000 <= 600  # GitHub's limit


def test_an_installation_token_is_for_one_repository_and_four_permissions(
    credentials: Credentials, key: rsa.RSAPrivateKey
) -> None:
    with serving(FakeGitHub()) as fake:
        api = installation_api(credentials, fake.url, 7, "r")
        (asked,) = fake.made("POST", r"^/app/installations/7/access_tokens$")
        assert asked.body == {"repositories": ["r"], "permissions": dict(PERMISSIONS)}
        sent = asked.headers["authorization"].removeprefix("Bearer ")
        assert jwt.decode(sent, key.public_key(), algorithms=["RS256"])["iss"] == "Iv23liTEST"
        assert api.token == fake.tokens[0]
        assert PERMISSIONS == {
            "checks": "write",
            "pull_requests": "write",
            "contents": "read",
            "metadata": "read",
        }


def test_the_files_keep_the_secrets_private_and_out_of_reprs(
    tmp_path: Path, key: rsa.RSAPrivateKey
) -> None:
    files = AppFiles.under(tmp_path)
    save(files, identity(), pem_of(key), "s3cret")
    loaded = load(files)
    assert loaded.identity == identity()
    assert loaded.webhook_secret == b"s3cret"
    assert "s3cret" not in repr(loaded)
    assert b"PRIVATE KEY" not in repr(loaded).encode()
    assert "s3cret" not in files.identity.read_text(encoding="utf-8")
    if sys.platform != "win32":
        for secret in (files.private_key, files.webhook_secret):
            assert secret.stat().st_mode & 0o777 == 0o600


def test_no_app_registered_says_how_to_register(tmp_path: Path) -> None:
    with pytest.raises(AppError, match="repro app register"):
        load(AppFiles.under(tmp_path))


# -- deliveries -------------------------------------------------------------------------------


def test_a_signature_checks_only_with_the_secret_and_the_exact_bytes() -> None:
    body = b'{"action":"opened"}'
    good = sign(SECRET, body)
    assert good.startswith("sha256=")
    assert verify(SECRET, body, good)
    assert not verify(b"another secret", body, good)
    assert not verify(SECRET, body + b" ", good)
    assert not verify(SECRET, body, good.removeprefix("sha256="))
    assert not verify(SECRET, body, None)
    assert not verify(b"", body, sign(b"", body))


def pull_request(action: str = "opened", *, head: str = "o/r", number: int = 1) -> dict[str, Any]:
    return {
        "action": action,
        "number": number,
        "pull_request": {"number": number, "head": {"repo": {"full_name": head}}},
        "repository": {"full_name": "o/r", "html_url": "https://github.com/o/r"},
        "installation": {"id": 7},
        "sender": {"login": "author"},
    }


def check_run(
    action: str,
    *,
    app: int = APP_ID,
    prs: list[int] | None = None,
    external: str = "pr/5",
    **more: Any,
) -> dict[str, Any]:
    return {
        "action": action,
        "check_run": {
            "app": {"id": app},
            "external_id": external,
            "pull_requests": [{"number": n} for n in (prs or [])],
        },
        "repository": {"full_name": "o/r", "html_url": "https://github.com/o/r"},
        "installation": {"id": 7},
        "sender": {"login": "maintainer"},
        **more,
    }


@pytest.mark.parametrize("action", ["opened", "reopened", "synchronize"])
def test_a_pull_request_from_the_repository_runs(action: str) -> None:
    found = decide("pull_request", pull_request(action), app_id=APP_ID)
    assert (found.kind, found.full_name, found.number, found.installation) == ("run", "o/r", 1, 7)
    assert found.pr_url == "https://github.com/o/r/pull/1"
    assert found.requested_by is None


def test_a_forks_pull_request_is_gated_not_run() -> None:
    assert decide("pull_request", pull_request(head="someone/r"), app_id=APP_ID).kind == "gate"
    deleted = pull_request()
    deleted["pull_request"]["head"]["repo"] = None  # a fork deleted since
    assert decide("pull_request", deleted, app_id=APP_ID).kind == "gate"


@pytest.mark.parametrize(
    ("event", "payload", "why"),
    [
        ("pull_request", pull_request("closed"), "pull_request closed"),
        ("pull_request", pull_request("labeled"), "pull_request labeled"),
        ("push", pull_request(), "push event"),
        ("check_run", check_run("rerequested", app=1), "another app"),
        ("check_run", check_run("created"), "check_run created"),
        (
            "check_run",
            check_run("requested_action", requested_action={"identifier": "fix"}),
            "requested action 'fix'",
        ),
        ("check_run", check_run("rerequested", external="run_x"), "names no pull request"),
        ("pull_request", {**pull_request(), "installation": None}, "no repository or installation"),
    ],
)
def test_everything_else_is_ignored_with_its_reason(
    event: str, payload: dict[str, Any], why: str
) -> None:
    found = decide(event, payload, app_id=APP_ID)
    assert found.kind == "ignore"
    assert why in found.reason


def test_a_rerun_is_asked_for_by_someone_whose_access_the_worker_checks() -> None:
    rerun = decide("check_run", check_run("rerequested", prs=[3]), app_id=APP_ID)
    assert (rerun.kind, rerun.number, rerun.requested_by) == ("run", 3, "maintainer")
    # A fork's check run names no pull request; Repro's own carry it in their external ID.
    button = check_run("requested_action", requested_action={"identifier": "run"})
    found = decide("check_run", button, app_id=APP_ID)
    assert (found.kind, found.number, found.requested_by) == ("run", 5, "maintainer")
    assert external_id(5) == "pr/5"


def test_the_settings_narrow_the_repositories() -> None:
    payload = pull_request()
    assert decide("pull_request", payload, app_id=APP_ID, repositories=["o/*"]).kind == "run"
    assert decide("pull_request", payload, app_id=APP_ID, repositories=["O/R"]).kind == "run"
    narrowed = decide("pull_request", payload, app_id=APP_ID, repositories=["o/other"])
    assert (narrowed.kind, narrowed.reason) == ("ignore", "o/r is not among app_repositories")


def test_a_delivery_reads_githubs_headers_in_any_case() -> None:
    headers = {"X-GitHub-Delivery": "d1", "x-github-event": "ping", "X-Hub-Signature-256": "s"}
    assert Delivery.from_headers(headers, b"{}") == Delivery("d1", "ping", "s", b"{}")


# -- the relay --------------------------------------------------------------------------------


def smee_event(payload: dict[str, Any], *, delivery: str = "d1") -> str:
    """What smee.io sends on: the request's headers in lower case, its body as an object."""
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return json.dumps(
        {
            "host": "smee.io",
            "x-github-event": "pull_request",
            "x-github-delivery": delivery,
            "x-hub-signature-256": sign(SECRET, raw),
            "content-type": "application/json",
            "body": payload,
            "query": {},
            "timestamp": 1761000000000,
        }
    )


def test_a_relayed_payload_written_compactly_checks_its_signature() -> None:
    payload = pull_request()
    payload["pull_request"]["title"] = "Fix naïve parsing ✓ <b>&</b>"  # not ASCII, nor escaped
    delivery = relayed(smee_event(payload))
    assert delivery is not None
    assert (delivery.id, delivery.event) == ("d1", "pull_request")
    assert verify(SECRET, delivery.body, delivery.signature)
    assert json.loads(delivery.body) == payload


def test_what_is_not_a_delivery_is_not_relayed() -> None:
    assert relayed("{}") is None
    assert relayed("not json") is None
    assert relayed('["body"]') is None


def test_server_sent_events_are_read_by_the_format() -> None:
    lines = ["event: ready\n", "data: {}\n", "\n", ": a comment\n", "data: a\n", "data:b\n", "\n"]
    assert list(events(lines)) == [("ready", "{}"), ("message", "a\nb")]


def test_a_relay_must_be_https_or_loopback() -> None:
    assert check_url("https://smee.io/abc") == "https://smee.io/abc"
    assert check_url("http://127.0.0.1:9/x") == "http://127.0.0.1:9/x"
    with pytest.raises(RelayError):
        check_url("http://smee.io/abc")


class _Stream:
    """A smee.io stand-in: ``/new`` redirects to a channel; a channel streams ``frames``."""

    def __init__(self, frames: list[str]) -> None:
        self.frames = frames
        self.opened = 0

    @contextlib.contextmanager
    def serve(self) -> Iterator[str]:
        stream = self

        class Handler(BaseHTTPRequestHandler):
            def do_HEAD(self) -> None:
                self.send_response(307)
                self.send_header("Location", "/channel-1")
                self.end_headers()

            def do_GET(self) -> None:
                stream.opened += 1
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for frame in stream.frames:
                    self.wfile.write(frame.encode("utf-8"))
                    self.wfile.flush()

            def log_message(self, *_: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            server.server_close()


def test_a_new_channel_is_where_new_redirects() -> None:
    with _Stream([]).serve() as url:
        assert new_channel(f"{url}/new") == f"{url}/channel-1"


def test_the_relay_hands_on_deliveries_and_opens_the_stream_again() -> None:
    frame = (
        "event: ready\ndata: {}\n\nevent: ping\ndata: {}\n\n"
        f"data: {smee_event(pull_request())}\n\n"
    )
    stream = _Stream([frame])
    got: list[Delivery] = []
    stop = threading.Event()

    def receive(delivery: Delivery) -> None:
        got.append(delivery)
        if len(got) == 2:  # the same frame, from the stream opened a second time
            stop.set()

    with stream.serve() as url:
        worker = threading.Thread(
            target=listen, args=(f"{url}/channel-1", receive, stop), kwargs={"retry_s": 0.05}
        )
        worker.start()
        worker.join(timeout=20)
        stop.set()
    assert not worker.is_alive()
    assert [d.id for d in got] == ["d1", "d1"]
    assert stream.opened >= 2
    assert all(verify(SECRET, d.body, d.signature) for d in got)


# -- registration -----------------------------------------------------------------------------


def test_the_manifest_asks_for_what_a_run_needs_and_no_more() -> None:
    found = manifest("Repro x", "https://smee.io/abc", "http://127.0.0.1:9/callback")
    assert found["default_permissions"] == dict(PERMISSIONS)
    assert found["default_events"] == ["pull_request", "check_run"]
    assert found["public"] is False
    assert found["hook_attributes"] == {"url": "https://smee.io/abc", "active": True}
    assert web_url("https://api.github.com") == "https://github.com"
    assert web_url("https://ghe.example/api/v3") == "https://ghe.example"


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=10) as answer:  # noqa: S310 - loopback
            return answer.status, answer.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


def test_registration_keeps_what_github_sends_and_refuses_a_stranger_redirect(
    tmp_path: Path, key: rsa.RSAPrivateKey
) -> None:
    pem = pem_of(key)
    converted = {"id": APP_ID, "client_id": "Iv23liTEST", "slug": "repro-test",
                 "name": "Repro test", "html_url": "https://github.com/apps/repro-test",
                 "owner": {"login": "o"}, "pem": pem, "webhook_secret": "whsec",
                 "client_secret": "never kept"}  # fmt: skip
    seen: dict[str, Any] = {}

    def browser(url: str) -> None:
        status, page = _get(url)
        assert status == 200
        seen["page"] = page
        state = page.split("state=", 1)[1].split("'", 1)[0]
        local = url.rstrip("/")
        seen["stranger"] = _get(f"{local}/callback?code=c1&state=not-{state}")[0]
        seen["done"] = _get(f"{local}/callback?code=c1&state={state}")

    with serving(FakeGitHub(conversions={"c1": converted})) as fake:
        made = register(
            AppFiles.under(tmp_path),
            api_url=fake.url,
            webhook_url="https://smee.io/abc",
            name="Repro test",
            open_page=browser,
            timeout_s=30,
        )
        site = fake.url  # the fake is both GitHub's API and its site
    assert made == identity()
    assert f"{site}/settings/apps/new?state=" in seen["page"]
    assert "&quot;checks&quot;: &quot;write&quot;" in seen["page"]
    assert seen["stranger"] == 400
    assert seen["done"][0] == 200
    assert "https://github.com/apps/repro-test/installations/new" in seen["done"][1]
    loaded = load(AppFiles.under(tmp_path))
    assert (loaded.private_key.decode(), loaded.webhook_secret) == (pem, b"whsec")
    assert "never kept" not in "".join(
        p.read_text(encoding="utf-8")
        for p in AppFiles.under(tmp_path).root.iterdir()
        if p.suffix != ".db"
    )


def test_a_registration_github_refuses_fails_with_the_reason(tmp_path: Path) -> None:
    def browser(url: str) -> None:
        state = _get(url)[1].split("state=", 1)[1].split("'", 1)[0]
        _get(f"{url.rstrip('/')}/callback?code=expired&state={state}")

    with serving(FakeGitHub()) as fake, pytest.raises(AppError, match="not found"):
        register(
            AppFiles.under(tmp_path),
            api_url=fake.url,
            webhook_url="https://x.test/h",
            name="Repro test",
            open_page=browser,
            timeout_s=30,
        )
    assert not AppFiles.under(tmp_path).exists()


# -- the commands -----------------------------------------------------------------------------


def test_register_will_not_replace_an_app_unasked(tmp_path: Path, key: rsa.RSAPrivateKey) -> None:
    env = clean_env(tmp_path)
    save(AppFiles.under(tmp_path / "data"), identity(), pem_of(key), "s")
    result = runner.invoke(app, ["app", "register", "--no-browser"], env=env)
    assert result.exit_code == 2
    assert "--replace" in result.output


def test_serve_needs_an_app_one_source_and_docker(
    tmp_path: Path, key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = clean_env(tmp_path)
    nothing = runner.invoke(app, ["app", "serve"], env=env)
    assert nothing.exit_code == 2
    assert "repro app register" in nothing.output
    save(AppFiles.under(tmp_path / "data"), identity(), pem_of(key), "s")
    two = ["app", "serve", "--relay", "https://smee.io/a", "--listen", "127.0.0.1:1"]
    both = runner.invoke(app, two, env=env)
    assert both.exit_code == 2
    assert "not both" in both.output
    bad = runner.invoke(app, ["app", "serve", "--listen", "nowhere"], env=env)
    assert bad.exit_code == 2
    monkeypatch.setattr("repro.sandbox.docker_available", lambda *_: False)
    no_docker = runner.invoke(app, ["app", "serve", "--listen", "127.0.0.1:1"], env=env)
    assert no_docker.exit_code == 2
    assert "Docker is needed" in no_docker.output
