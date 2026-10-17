"""Repro's GitHub Action (I03): what it decides, what it runs, and its ``action.yml``.

Roadmap I03: "Docker-based Action for Linux runners, caching, ``actions/attest`` with the Repro
predicate." The decisions (``plan``) are checked for every kind of event; ``run`` and ``report``
end to end against the fake GitHub (``github_support``); ``action.yml`` for what a composite
action's steps must agree on. Running the Action on GitHub itself is Gate I's.
"""

import hashlib
import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from cli_support import clean_env
from github_support import FakeGitHub, Upstream, make_upstream, pull
from repro.integrations.github import action
from repro.integrations.github.action import ActionError, plan

ROOT = Path(__file__).resolve().parents[2]
URL = "https://github.com/o/r/pull/1"


def event(*, fork: bool, private: bool = False, head_repo: bool = True) -> dict[str, Any]:
    base = {"full_name": "o/r", "private": private}
    head = {"full_name": "fork/r" if fork else "o/r"} if head_repo else None
    return {"pull_request": {"html_url": URL, "base": {"repo": base}, "head": {"repo": head}}}


# -- plan -------------------------------------------------------------------------------------


def test_a_pull_request_from_this_repository_is_posted_to_and_signed() -> None:
    decided = plan("pull_request", event(fork=False), post_on_forks=False, attest=True)
    assert (decided.pr, decided.fork, decided.post, decided.attest) == (URL, False, True, True)


def test_a_forks_pull_request_is_not_posted_to_by_default() -> None:
    for name in ("pull_request", "pull_request_target"):
        decided = plan(name, event(fork=True), post_on_forks=False, attest=True)
        assert (decided.fork, decided.post, decided.attest) == (True, False, False)
        assert "job's summary and an artifact" in decided.reason


def test_posting_for_forks_needs_both_the_opt_in_and_pull_request_target() -> None:
    target = plan("pull_request_target", event(fork=True), post_on_forks=True, attest=True)
    assert (target.post, target.attest) == (True, True)
    # Under pull_request a fork's token is read-only: the opt-in cannot make it write.
    plain = plan("pull_request", event(fork=True), post_on_forks=True, attest=True)
    assert plain.post is False


def test_a_deleted_fork_is_a_fork() -> None:
    decided = plan(
        "pull_request", event(fork=True, head_repo=False), post_on_forks=False, attest=True
    )
    assert decided.fork


def test_a_private_repository_is_not_signed() -> None:
    decided = plan(
        "pull_request", event(fork=False, private=True), post_on_forks=False, attest=True
    )
    assert (decided.post, decided.attest) == (True, False)
    assert (
        plan("pull_request", event(fork=False), post_on_forks=False, attest=False).attest is False
    )


def test_an_event_that_is_not_a_pull_requests_is_refused() -> None:
    with pytest.raises(ActionError, match="runs on pull_request or pull_request_target, not push"):
        plan("push", {}, post_on_forks=False, attest=True)
    with pytest.raises(ActionError, match="names no pull request"):
        plan("pull_request", {"pull_request": {}}, post_on_forks=False, attest=True)


def test_plan_writes_its_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event(fork=True)), encoding="utf-8")
    outputs = tmp_path / "out"
    for key, value in {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": str(path),
        "GITHUB_OUTPUT": str(outputs),
        "INPUT_POST_ON_FORKS": "false",
        "INPUT_ATTEST": "true",
    }.items():
        monkeypatch.setenv(key, value)
    assert action.main(["plan"]) == 0
    assert outputs.read_text(encoding="utf-8") == (
        f"pr={URL}\nfork=true\npost=false\nattest=false\n"
    )


# -- run and report ---------------------------------------------------------------------------


@pytest.fixture
def upstream(tmp_path: Path) -> Upstream:
    return make_upstream(tmp_path / "upstream")


@pytest.fixture
def github(upstream: Upstream) -> Iterator[FakeGitHub]:
    yield from FakeGitHub({"/repos/o/r/pulls/1": pull(upstream)}).serve()


def test_run_and_report_leave_the_card_where_the_steps_after_them_look(
    tmp_path: Path, github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = clean_env(tmp_path, REPRO_GITHUB_API_URL=github.url, GITHUB_TOKEN="ghs_" + "t" * 36)
    env.pop("GH_TOKEN", None)
    env |= {
        "RUNNER_TEMP": str(tmp_path / "runner"),
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        "REPRO_PR": URL,
        "INPUT_ANALYSE_ONLY": "true",
    }
    for key in list(os.environ):
        monkeypatch.delenv(key)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert action.main(["run"]) == 0
    outputs = dict(
        line.split("=", 1)
        for line in (tmp_path / "output").read_text(encoding="utf-8").splitlines()
    )
    card = Path(outputs["card"])
    assert card.parent == tmp_path / "runner" / "repro-card"
    stored = json.loads(card.read_bytes())
    assert outputs["status"] == stored["status"] == "UNVERIFIABLE"  # analysed only
    assert re.fullmatch(r"run_[0-9A-Z]{26}", outputs["run-id"])
    # The signed subject's digest is the card's own: the file is exactly its canonical bytes.
    predicate = json.loads(Path(outputs["predicate"]).read_text(encoding="utf-8"))
    assert hashlib.sha256(card.read_bytes()).hexdigest() == predicate["cardDigest"]["sha256"]
    assert outputs["predicate-type"].startswith("https://")
    assert Path(outputs["card-md"]).read_text(encoding="utf-8").startswith("# Reproduction Card")

    monkeypatch.setenv("REPRO_RUN_ID", outputs["run-id"])
    monkeypatch.setenv("REPRO_POST", "false")  # a fork's: the summary alone
    assert action.main(["report"]) == 0
    assert "# Reproduction Card" in (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert github.check_runs == []
    assert github.comments == []
    monkeypatch.setenv("REPRO_POST", "true")
    assert action.main(["report"]) == 0
    assert len(github.check_runs) == 1
    assert len(github.comments) == 1


# -- action.yml -------------------------------------------------------------------------------


def test_the_action_pins_every_action_it_uses_and_its_steps_agree() -> None:
    text = (ROOT / "action.yml").read_text(encoding="utf-8")
    spec = yaml.safe_load(text)
    assert spec["runs"]["using"] == "composite"
    steps = spec["runs"]["steps"]
    for line in re.findall(r"uses: (\S+.*)", text):
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+", line), line
    ids = {step.get("id") for step in steps}
    written = {
        "plan": {"pr", "fork", "post", "attest"},
        "run": {"run-id", "status", "card", "card-md", "predicate", "predicate-type"},
        "sign": {"attestation-url", "bundle-path", "attestation-id"},
    }
    for step, name in re.findall(r"steps\.([\w-]+)\.outputs\.([\w-]+)", text):
        assert step in ids, step
        assert name in written[step], (step, name)
    for name in re.findall(r"inputs\.([\w-]+)", text):
        assert name in spec["inputs"], name
    # The pull request's code runs in containers only: never as the job's user, beside its token.
    (reproduce,) = [step for step in steps if step.get("id") == "run"]
    assert reproduce["env"]["REPRO_SANDBOX"] == "docker"
