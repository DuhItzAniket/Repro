"""A run's card reported to its pull request (I02).

Roadmap I02: "Conclusion mapping (VERIFIED→success, FLAGGED→failure or action_required,
UNVERIFIABLE→neutral), annotations in batches of 50, sticky comment found by a hidden marker,
under 60k characters, job summary." Reported to a fake GitHub with state (``github_support``):
check runs whose updates append annotations, a pull request's comments in pages. No test
reaches GitHub.
"""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from cli_support import clean_env
from github_support import FakeGitHub, Upstream, make_upstream, pull
from gitrepo import Repo
from repro.cli import app
from repro.config import load_settings
from repro.integrations.github import GitHubApi, GitHubError
from repro.integrations.github.report import (
    BODY_MAX,
    CONCLUSION,
    MARKER,
    Target,
    annotations,
    check_run,
    cut,
    target_of,
)
from repro.store import StoreReader

runner = CliRunner()
TOKEN = "ghs_" + "t" * 36  # an app installation token's shape, as Actions' GITHUB_TOKEN
URL = "https://github.com/o/r/pull/1"


@pytest.fixture
def upstream(tmp_path: Path) -> Upstream:
    return make_upstream(tmp_path / "upstream")


@pytest.fixture
def github(upstream: Upstream) -> Iterator[FakeGitHub]:
    yield from FakeGitHub({"/repos/o/r/pulls/1": pull(upstream)}).serve()


@pytest.fixture
def ran(tmp_path: Path, github: FakeGitHub) -> tuple[str, dict[str, str]]:
    """A run of the pull request (analysed only): its ID and the environment to report with."""
    env = clean_env(tmp_path, REPRO_GITHUB_API_URL=github.url, GITHUB_TOKEN=TOKEN)
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_STEP_SUMMARY", None)
    result = runner.invoke(app, ["run", "--pr", URL, "--no-serve", "--analyse-only"], env=env)
    assert result.exit_code == 0, result.output
    found = re.search(r"(run_[0-9A-Z]{26}) completed", result.output)
    assert found is not None
    return found[1], env


def report(env: dict[str, str], *argv: str) -> Any:
    return runner.invoke(app, ["report", *argv], env=env)


# -- through the command ----------------------------------------------------------------------


def test_a_report_makes_the_check_run_the_comment_and_the_summary(
    tmp_path: Path, github: FakeGitHub, upstream: Upstream, ran: tuple[str, dict[str, str]]
) -> None:
    run_id, env = ran
    summary = tmp_path / "summary.md"
    result = report({**env, "GITHUB_STEP_SUMMARY": str(summary)}, run_id)
    assert result.exit_code == 0, result.output
    assert "o/r#1: check run Repro: created, neutral" in result.output
    assert "o/r#1: comment: created" in result.output
    (check,) = github.check_runs
    assert (check["name"], check["head_sha"], check["external_id"]) == (
        "Repro",
        upstream.head,
        run_id,
    )
    assert (check["status"], check["conclusion"]) == ("completed", "neutral")
    assert check["output"]["title"].startswith("UNVERIFIABLE: ")
    assert "# Reproduction Card: UNVERIFIABLE" in check["output"]["text"]
    (comment,) = github.comments
    assert comment["body"].startswith(MARKER)
    assert "# Reproduction Card: UNVERIFIABLE" in comment["body"]
    assert "# Reproduction Card: UNVERIFIABLE" in summary.read_text(encoding="utf-8")
    writes = [r for r in github.requests if r.method in {"POST", "PATCH"}]
    assert all(r.headers["authorization"] == f"Bearer {TOKEN}" for r in writes)
    assert TOKEN not in result.output


def test_a_second_report_updates_rather_than_adds(
    github: FakeGitHub, ran: tuple[str, dict[str, str]]
) -> None:
    run_id, env = ran
    assert report(env, run_id).exit_code == 0
    again = report(env, run_id)
    assert again.exit_code == 0, again.output
    assert "check run Repro: updated" in again.output
    assert "comment: updated" in again.output
    assert len(github.check_runs) == 1
    assert len(github.comments) == 1
    assert len(github.made("POST", r"/check-runs$")) == 1


def test_a_bot_finds_its_comment_among_pages_of_others(
    github: FakeGitHub, ran: tuple[str, dict[str, str]]
) -> None:
    """An app's token (GET /user refused) writes as a bot; its comment is 151st of 151."""
    run_id, env = ran
    github.comments += [
        {"id": n, "body": "+1", "user": {"login": f"u{n}", "type": "User"}} for n in range(150)
    ]
    github.comments.append({"id": 900, "body": f"{MARKER}\nold", "user": {"type": "Bot"}})
    result = report(env, run_id)
    assert "comment: updated" in result.output
    assert github.comments[-1]["body"].startswith(MARKER)
    assert "old" not in github.comments[-1]["body"]
    assert len(github.made("GET", r"/issues/1/comments")) == 2  # two pages of 100


def test_someone_elses_comment_with_the_marker_is_left_alone(
    github: FakeGitHub, ran: tuple[str, dict[str, str]]
) -> None:
    run_id, env = ran
    github.login = "repro-bot"  # a person's token: GET /user names it
    forged = {"id": 7, "body": f"{MARKER}\nFLAGGED, trust me", "user": {"login": "mallory"}}
    github.comments.append(forged)
    result = report(env, run_id)
    assert "comment: created" in result.output
    assert forged["body"] == f"{MARKER}\nFLAGGED, trust me"
    assert github.comments[-1]["user"]["login"] == "repro-bot"


def test_a_target_it_cannot_update_is_reported_and_the_others_made(
    github: FakeGitHub, ran: tuple[str, dict[str, str]]
) -> None:
    run_id, env = ran
    github.refuse = {"/repos/o/r/issues/"}
    result = report(env, run_id)
    assert result.exit_code == 1
    assert "check run Repro: created" in result.output
    assert "could not update the comment" in result.output
    assert "a workflow's token needs pull-requests: write" in result.output
    assert len(github.check_runs) == 1


def test_a_run_of_no_pull_request_needs_one_named(tmp_path: Path) -> None:
    repo = Repo(tmp_path / "repo")
    base = repo.commit({"pkg/__init__.py": "", "pkg/a.py": "def f():\n    return 1\n"})
    head = repo.commit({"pkg/a.py": "def f():\n    return 2\n"})
    env = clean_env(tmp_path)
    argv = ["run", "--repo", str(repo.path), "--base", base, "--head", head]
    made = runner.invoke(app, [*argv, "--no-serve", "--analyse-only"], env=env)
    found = re.search(r"(run_[0-9A-Z]{26}) completed", made.output)
    assert found is not None, made.output
    result = report(env, found[1])
    assert result.exit_code == 2
    assert "not a pull request's: name one with --pr" in result.output


# -- the parts --------------------------------------------------------------------------------


def test_the_status_becomes_the_conclusion() -> None:
    assert CONCLUSION == {"VERIFIED": "success", "FLAGGED": "failure", "UNVERIFIABLE": "neutral"}


def test_the_pull_request_is_the_runs_or_the_one_named() -> None:
    card = {"pr": {"url": URL}, "conditions": {"head": {"sha": "a" * 40}}}
    assert target_of(card, None, "https://api.github.com") == Target("o", "r", 1, "a" * 40)
    other = target_of(card, "https://github.com/p/q/pull/9", "https://api.github.com")
    assert (other.owner, other.repo, other.number) == ("p", "q", 9)
    with pytest.raises(GitHubError, match="not a pull request's"):
        target_of({"pr": None, "conditions": card["conditions"]}, None, "https://api.github.com")


def test_annotations_mark_flagged_and_unreached_changed_code() -> None:
    def changed(symbol: str, file: str, lines: list[int] | None) -> dict[str, Any]:
        payload = {"symbol_id": symbol, "file": file, "head_lines": lines}
        return {"kind": "symbol.changed", "payload": payload}

    events = [
        changed("pkg.a:f#0", "pkg/a.py", [3, 5]),
        changed("pkg.a:g#0", "pkg/a.py", [8, 9]),
        changed("pkg.a:gone#0", "pkg/a.py", None),  # removed: no line on head
        {"kind": "evidence.created", "payload": {"evidence": {
            "id": "ev_1", "targets": [{"symbol": "pkg.a:f#0", "test": "t.py::t"}]}}},
        {"kind": "evidence.created", "payload": {"evidence": {
            "id": "ev_2", "targets": [{"symbol": "pkg.a:gone#0"}]}}},
    ]  # fmt: skip
    gap = [
        {"evidence_id": "ev_1", "resolution": "flagged", "check": "diff.behaviour",
         "kind": "result_changed", "summary": "f(1) gives another result"},
        {"evidence_id": "ev_2", "resolution": "flagged", "check": "diff.api",
         "kind": "object_removed", "summary": "gone was removed"},
        {"evidence_id": "ev_1", "resolution": "explained", "check": "diff.behaviour",
         "kind": "result_changed", "summary": "explained"},
    ]  # fmt: skip
    missing = [
        {"reason": "no_covering_test", "targets": [{"file": "pkg/a.py", "symbol": "pkg.a:g#0"}],
         "detail": "no selected test runs pkg.a:g#0 (modified)"},
    ]  # fmt: skip
    marks = annotations({"gap": gap, "missing": missing}, events)
    assert [(m["path"], m["start_line"], m["end_line"], m["annotation_level"]) for m in marks] == [
        ("pkg/a.py", 3, 5, "failure"),
        ("pkg/a.py", 8, 9, "warning"),
    ]
    assert marks[0]["title"] == "diff.behaviour: result_changed"


def test_annotations_go_fifty_a_request(
    github: FakeGitHub, ran: tuple[str, dict[str, str]]
) -> None:
    api = GitHubApi(github.url, "token")
    run_id, env = ran
    with StoreReader(load_settings(env=env).paths.database) as reader:
        stored = reader.card(run_id)
    assert stored is not None
    card = {**stored, "status": "FLAGGED"}
    marks = [
        {"path": "a.py", "start_line": n, "end_line": n, "annotation_level": "notice",
         "title": "t", "message": "m"}
        for n in range(1, 121)
    ]  # fmt: skip
    said = check_run(api, Target("o", "r", 1, card["conditions"]["head"]["sha"]), card, marks)
    assert said == "check run Repro: created, failure, 120 annotations"
    (run,) = github.check_runs
    assert len(run["output"]["annotations"]) == 120
    sent = [len(r.body["output"]["annotations"]) for r in github.requests if r.body]
    assert sent == [50, 50, 20]


def test_a_long_card_is_cut_at_a_line_with_a_note() -> None:
    long = "\n".join(f"| row {n} | {'x' * 80} |" for n in range(2000))
    text = cut(long, BODY_MAX, "run_1")
    assert len(text) <= BODY_MAX
    assert text.endswith("`repro export run_1 --format md` gives it whole.*\n")
    assert text.split("\n\n*The card is cut here")[0].endswith("|")  # a whole line
    assert cut("short", BODY_MAX, "run_1") == "short"
