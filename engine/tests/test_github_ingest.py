"""A GitHub pull request read from its URL (I01).

Roadmap I01: "PR URL → refs, description, commits (gh/API, token from env), fork handling." A
fake GitHub API on a loopback port serves the pull request; its commits come from a local
repository where ``refs/pull/1/head`` is a commit no branch holds, as a fork's head is. No test
reaches GitHub.
"""

import json
import threading
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from cli_support import clean_env
from gitrepo import Repo
from repro.cli import app
from repro.config import load_settings
from repro.integrations.github import (
    API_VERSION,
    GitHubApi,
    GitHubError,
    PrUrl,
    ingest,
)
from repro.integrations.github.api import _SameHostRedirects
from repro.integrations.github.mirror import _Authenticated
from repro.store import StoreReader

runner = CliRunner()
TOKEN = "ghp_" + "t" * 36  # a personal token's shape, so the scrubbing would know it


@dataclass
class FakeGitHub:
    """GitHub's REST API, as far as I01 reads it: the pull requests it is given."""

    pulls: dict[str, dict[str, Any]] = field(default_factory=dict)
    seen: list[dict[str, str]] = field(default_factory=list)
    url: str = ""

    def serve(self) -> Iterator["FakeGitHub"]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                fake.seen.append({k.lower(): v for k, v in self.headers.items()})
                if self.path == "/repos/o/limited/pulls/1":
                    spent = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"}
                    self._answer(403, {"message": "API rate limit exceeded"}, spent)
                elif self.headers.get("Authorization") == "Bearer refused":
                    self._answer(401, {"message": "Bad credentials"})
                elif self.path in fake.pulls:
                    self._answer(200, fake.pulls[self.path])
                else:
                    self._answer(404, {"message": "Not Found"})

            def _answer(
                self, status: int, body: dict[str, Any], headers: dict[str, str] | None = None
            ) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

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


@dataclass(frozen=True)
class Upstream:
    repo: Repo
    branched: str  # where the pull request left main
    head: str  # the pull request's head, on no branch
    main: str  # main since


@pytest.fixture
def upstream(tmp_path: Path) -> Upstream:
    repo = Repo(tmp_path / "upstream")
    base = {"pkg/__init__.py": "", "pkg/a.py": "def f():\n    return 1\n"}
    branched = repo.commit(base, "start")
    at_branch = dict(repo.files)
    head = repo.commit({"pkg/a.py": "def f():\n    return 2\n"}, "Return 2 from f")
    repo.parent, repo.files = branched, at_branch  # main moves on without the change
    repo.commit({"README.md": "Main moved on.\n"}, "main moves on")
    main = repo.git("rev-parse", "refs/heads/main")
    repo.git("update-ref", "refs/pull/1/head", head)
    return Upstream(repo, branched, head, main)


def pull(upstream: Upstream, **changes: Any) -> dict[str, Any]:
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


@pytest.fixture
def github(upstream: Upstream) -> Iterator[FakeGitHub]:
    fake = FakeGitHub({"/repos/o/r/pulls/1": pull(upstream)})
    yield from fake.serve()


# -- the address ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("address", "parsed"),
    [
        ("https://github.com/pallets/flask/pull/5000", ("github.com", "pallets", "flask", 5000)),
        ("https://github.com/o/r.js/pull/7/files?w=1", ("github.com", "o", "r.js", 7)),
        ("https://GitHub.com/o/r/pull/1#discussion", ("github.com", "o", "r", 1)),
        ("https://ghe.example.com/team/svc/pull/12", ("ghe.example.com", "team", "svc", 12)),
    ],
)
def test_a_pull_request_address_is_parsed(address: str, parsed: tuple[str, str, str, int]) -> None:
    url = PrUrl.parse(address)
    assert (url.host, url.owner, url.repo, url.number) == parsed


@pytest.mark.parametrize(
    "address",
    [
        "http://github.com/o/r/pull/1",  # not https
        "https://github.com/o/r/issues/1",
        "https://github.com/o/r/pull/0",
        "https://github.com/o/r/pull/",
        "https://github.com/-o/r/pull/1",
        "https://github.com/o/../pull/1",
        "github.com/o/r/pull/1",
    ],
)
def test_anything_else_is_refused(address: str) -> None:
    with pytest.raises(GitHubError, match=r"not a pull request's address|names no repository"):
        PrUrl.parse(address)


def test_another_host_needs_its_own_api() -> None:
    url = PrUrl.parse("https://ghe.example.com/team/svc/pull/12")
    with pytest.raises(GitHubError, match="set github_api_url"):
        url.check_api("https://api.github.com")
    url.check_api("https://ghe.example.com/api/v3")


# -- the API ----------------------------------------------------------------------------------


def test_requests_name_the_version_and_carry_the_token_only_when_set(
    github: FakeGitHub,
) -> None:
    GitHubApi.from_environment(github.url, {}).get("/repos/o/r/pulls/1")
    GitHubApi.from_environment(github.url, {"GH_TOKEN": TOKEN}).get("/repos/o/r/pulls/1")
    anonymous, with_token = github.seen
    assert anonymous["accept"] == "application/vnd.github+json"
    assert anonymous["x-github-api-version"] == API_VERSION == "2026-03-10"
    assert anonymous["user-agent"].startswith("repro/")
    assert "authorization" not in anonymous
    assert with_token["authorization"] == f"Bearer {TOKEN}"


def test_github_token_comes_before_gh_token() -> None:
    api = GitHubApi.from_environment(env={"GITHUB_TOKEN": "first", "GH_TOKEN": "second"})
    assert (api.token, api.token_source) == ("first", "GITHUB_TOKEN")


def test_failures_say_what_to_do(github: FakeGitHub) -> None:
    anonymous = GitHubApi.from_environment(github.url, {})
    with pytest.raises(GitHubError, match="private repository needs a token: set GITHUB_TOKEN"):
        anonymous.get("/repos/o/missing/pulls/1")
    with pytest.raises(GitHubError, match=r"rate limit is spent until 00:00 UTC; a token"):
        anonymous.get("/repos/o/limited/pulls/1")
    refused = GitHubApi.from_environment(github.url, {"GITHUB_TOKEN": "refused"})
    with pytest.raises(GitHubError, match="token in GITHUB_TOKEN was refused"):
        refused.get("/repos/o/r/pulls/1")
    nobody = GitHubApi("http://127.0.0.1:9")
    with pytest.raises(GitHubError, match="cannot reach GitHub's API"):
        nobody.get("/repos/o/r/pulls/1")


def test_a_redirect_to_another_host_drops_the_token() -> None:
    request = urllib.request.Request("https://api.github.com/x", headers={"Authorization": "x"})
    handler = _SameHostRedirects()
    same = handler.redirect_request(request, None, 301, "", {}, "https://api.github.com/y")
    other = handler.redirect_request(request, None, 301, "", {}, "https://example.com/y")
    assert same is not None
    assert same.has_header("Authorization")
    assert other is not None
    assert not other.has_header("Authorization")


def test_git_authenticates_with_a_header_from_the_environment(tmp_path: Path) -> None:
    git = _Authenticated(tmp_path, "https://github.com", TOKEN)
    env = git.environment()
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert env["GIT_CONFIG_VALUE_0"].startswith("AUTHORIZATION: basic ")
    assert TOKEN not in " ".join(git.command("fetch"))  # on no command line
    assert "GIT_CONFIG_COUNT" not in _Authenticated(tmp_path, None, TOKEN).environment()


# -- ingestion --------------------------------------------------------------------------------


def test_a_pull_request_from_a_fork_is_fetched_and_compared_with_its_merge_base(
    tmp_path: Path, github: FakeGitHub, upstream: Upstream
) -> None:
    found = ingest(
        "https://github.com/o/r/pull/1", api_url=github.url, mirrors=tmp_path / "m", env={}
    )
    assert found.pr.fork
    assert found.pr.head_label == "fork:feature"
    assert found.base == upstream.branched  # not main's tip, which moved on
    assert found.git.resolve(upstream.head) == upstream.head
    assert (tmp_path / "m" / "github.com" / "o" / "r.git" / "HEAD").is_file()
    again = ingest(
        "https://github.com/o/r/pull/1", api_url=github.url, mirrors=tmp_path / "m", env={}
    )
    assert again.base == found.base  # the mirror is fetched again, not cloned


def test_a_clone_that_lacks_the_commits_says_how_to_fetch_them(
    tmp_path: Path, github: FakeGitHub
) -> None:
    other = Repo(tmp_path / "other")
    other.commit({"x.txt": "x"})
    with pytest.raises(GitHubError, match=r"git fetch .* main pull/1/head"):
        ingest(
            "https://github.com/o/r/pull/1",
            api_url=github.url,
            mirrors=tmp_path / "m",
            local=other.path,
            env={},
        )


def test_a_clone_url_off_github_is_not_fetched(tmp_path: Path, upstream: Upstream) -> None:
    fake = FakeGitHub({"/repos/o/r/pulls/1": pull(upstream)})
    fake.pulls["/repos/o/r/pulls/1"]["base"]["repo"]["clone_url"] = "ext::sh -c touch% /tmp/x"
    for served in fake.serve():
        with pytest.raises(GitHubError, match="clone URL Repro does not fetch from"):
            ingest("https://github.com/o/r/pull/1", api_url=served.url, mirrors=tmp_path, env={})


def test_repro_run_takes_a_pull_request(
    tmp_path: Path, github: FakeGitHub, upstream: Upstream
) -> None:
    env = clean_env(tmp_path, REPRO_GITHUB_API_URL=github.url, GITHUB_TOKEN=TOKEN)
    env.pop("GH_TOKEN", None)
    argv = ["run", "--pr", "https://github.com/o/r/pull/1", "--no-serve", "--analyse-only"]
    result = runner.invoke(app, argv, env=env)
    assert result.exit_code == 0, result.output
    assert "o/r#1 (open from a fork): head fork:feature" in result.output
    assert github.seen[-1]["authorization"] == f"Bearer {TOKEN}"
    with StoreReader(load_settings(env=env).paths.database) as reader:
        (run,) = reader.runs(10)
        events = [json.loads(e.body) for e in reader.iter_events(run.id)]
    started = events[0]["payload"]
    assert started["repo"] == {"name": "o/r", "url": "https://github.com/o/r"}
    assert started["pr"] == {
        "title": "Return 2 from f",
        "number": 1,
        "url": "https://github.com/o/r/pull/1",
    }
    assert started["base"] == {"ref": "main", "sha": upstream.branched}
    assert started["head"] == {"ref": "fork:feature", "sha": upstream.head}
    assert TOKEN not in json.dumps(events)
    assert TOKEN not in result.output


def test_a_pull_request_with_refs_given_too_is_refused(tmp_path: Path) -> None:
    env = clean_env(tmp_path)
    argv = ["run", "--pr", "https://github.com/o/r/pull/1", "--base", "main", "--no-serve"]
    result = runner.invoke(app, argv, env=env)
    assert result.exit_code == 2
    assert "--pr reads the base, head, title and description from GitHub" in result.output


def test_neither_refs_nor_a_pull_request_is_refused(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "--no-serve"], env=clean_env(tmp_path))
    assert result.exit_code == 2
    assert "give --repo, --base and --head, or --pr" in result.output
