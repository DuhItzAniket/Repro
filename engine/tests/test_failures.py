"""Chaos tests: each catalogued failure, met for real by ``repro run`` (H01).

``docs/FAILURES.md`` lists what can go wrong in a run, what the run records, what the card
says and what would resolve it. Each test here makes one of them happen end to end:
- a fixture whose head breaks the thing (``fixtures.failures``);
- an API nobody answers;
- Docker or git missing.

It then holds the run to its entry: the reason, a detail a person can act on (no traceback, no
home directory), the status, and never VERIFIED. The encoder's failure is met in
``test_run_stage.py``'s ``perf-regress`` run.

They run ``repro run`` in full, so they are slow; CI runs them in a job of their own
(``pytest -m chaos``) on Ubuntu and Windows.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from cli_support import clean_env
from fixtures.failures import FAILURE_SPECS
from fixtures.repo_builder import build_repo
from fixtures.specs import ALL_SPECS
from repro.cli import app
from repro.config import load_settings
from repro.store import StoreReader
from repro_events.log import read_log, validate_log
from repro_events.schemas import load_schema_set

pytestmark = pytest.mark.chaos
runner = CliRunner()


def run(
    name: str, tmp_path: Path, *extra: str, exit_code: int | None = None, **variables: str
) -> dict[str, Any]:
    """``name``'s fixture through ``repro run --no-serve``: its events, card and exit code."""
    spec = FAILURE_SPECS.get(name) or ALL_SPECS[name]
    built = build_repo(spec, tmp_path / "repo")
    [head] = built.head_shas.values()
    settings = {"REPRO_SANDBOX": "process", "REPRO_RUN_ROOT": str(tmp_path / "scratch")}
    env = clean_env(tmp_path, **(settings | variables))
    argv = ["run", "--repo", str(built.path), "--base", built.base_sha, "--head", head]
    result = runner.invoke(app, [*argv, *extra, "--no-serve"], env=env)
    if exit_code is not None:
        assert result.exit_code == exit_code, result.output
    with StoreReader(load_settings(env=env).paths.database) as reader:
        (stored,) = reader.runs(10)
        events = [json.loads(e.body) for e in reader.events(stored.id, 0, 100_000)]
    log = tmp_path / "run.jsonl"
    log.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    lines, issues = read_log(log)
    assert issues + validate_log(load_schema_set(), lines) == []
    (card,) = [e["payload"]["card"] for e in events if e["kind"] == "card.published"]
    return {"events": events, "card": card, "exit": result.exit_code, "output": result.output}


def items(found: dict[str, Any], reason: str) -> list[dict[str, Any]]:
    return [m for m in found["card"]["missing"] if m["reason"] == reason]


def readable(item: dict[str, Any]) -> None:
    """What a person reads: a sentence, not a traceback, and nothing of this machine."""
    text = f"{item['detail']} {item.get('resolution') or ''}"
    assert "Traceback" not in text
    assert str(Path.home()) not in text
    assert str(Path.home()).replace("\\", "/") not in text
    assert "\n" not in item["detail"]
    assert len(item["detail"]) <= 1000


def rules(found: dict[str, Any]) -> list[str]:
    return [r["rule"] for r in found["card"]["status_reasons"]]


def test_a_test_module_that_no_longer_imports(tmp_path: Path) -> None:
    found = run("broken-import", tmp_path, exit_code=0)
    (item,) = items(found, "collection_error")
    readable(item)
    assert item["detail"].startswith("head: tests/test_core.py could not be collected: ")
    assert "ImportError: cannot import name 'total' from 'calc.core'" in item["detail"]
    assert item["resolution"]
    assert item["targets"] == [{"file": "tests/test_core.py"}]
    assert found["card"]["status"] == "FLAGGED"  # its test is gone from head's run


def test_a_test_run_that_cannot_start_leaves_the_change_unverifiable(tmp_path: Path) -> None:
    """H06: no code changed, so no test is selected, and neither side's suite can start. The
    card stands only if every run Repro made finished, whatever was selected."""
    found = run("suite-cannot-start", tmp_path, exit_code=0)
    unfinished = items(found, "run_incomplete")
    assert {item["detail"].split(":", 1)[0] for item in unfinished} == {"base", "head"}
    for item in unfinished:
        readable(item)
        assert "ended early, with exit status" in item["detail"]
        # What the run said last, by the line that names its error.
        assert "No module named 'repro_fixture_no_such_plugin'" in item["detail"]
        assert item["resolution"]
    assert found["card"]["conditions"]["selected_tests"] == 0
    assert found["card"]["status"] == "UNVERIFIABLE"
    assert rules(found) == ["tests_not_run"]


def test_a_test_that_hangs_leaves_the_change_unverifiable(tmp_path: Path) -> None:
    found = run("slow-head", tmp_path, exit_code=0, REPRO_TEST_TIMEOUT_S="20")
    timeouts = items(found, "run_incomplete")
    assert timeouts
    for item in timeouts:
        readable(item)
        assert item["detail"].startswith("head: the ")
        assert "took longer than its limit" in item["detail"]
        assert "test_timeout_s" in item["resolution"]
    assert found["card"]["status"] == "UNVERIFIABLE"
    assert "tests_not_run" in rules(found)
    (why,) = [r for r in found["card"]["status_reasons"] if r["rule"] == "tests_not_run"]
    assert why["detail"] == "1 of the 2 selected tests have no outcome: a run did not report them"


def test_a_change_that_exhausts_memory_says_so(tmp_path: Path) -> None:
    found = run("memory-hog", tmp_path, exit_code=0, REPRO_MEMORY_LIMIT_MB="3072")
    limits = items(found, "memory_limit")
    assert limits
    for item in limits:
        readable(item)
        assert item["detail"].startswith("head: the ")
        assert "reached its memory limit of 3 GiB" in item["detail"]
        assert "failed with MemoryError" in item["detail"]
        assert "memory_limit_mb" in item["resolution"]
    assert found["card"]["status"] == "FLAGGED"  # its test passes on base and fails on head


def test_a_project_that_cannot_be_built_is_unverifiable(tmp_path: Path) -> None:
    found = run("broken-build", tmp_path, exit_code=0)
    (item,) = items(found, "environment_failed")
    readable(item)
    assert item["detail"].startswith("head: ")
    assert "repro-fixture-no-such-backend" in item["detail"]
    assert found["card"]["status"] == "UNVERIFIABLE"
    assert rules(found) == ["environment_failed"]


def test_an_api_nobody_answers_is_an_agent_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("repro.agents.openai_compat.BACKOFF_S", 0.01)
    found = run(
        "honest-fix",
        tmp_path,
        "--pr-title",
        "Fix parse_date dropping the UTC offset",
        "--analyse-only",
        REPRO_AGENTS="openai",
        REPRO_AGENT_BASE_URL="http://127.0.0.1:9/v1",  # nothing listens on port 9
        REPRO_AGENT_MODEL="test-model",
    )
    assert found["exit"] == 1  # a job failed: the run did not complete
    (item,) = items(found, "agent_failed")
    readable(item)
    assert "the pull request's claims could not be read" in item["detail"]
    assert "cannot reach the API" in item["detail"]
    assert found["card"]["status"] != "VERIFIED"


def test_docker_asked_for_and_missing_says_what_to_do(tmp_path: Path) -> None:
    found = run(
        "honest-fix",
        tmp_path,
        REPRO_SANDBOX="docker",
        DOCKER_HOST="tcp://127.0.0.1:9",  # no daemon answers here
    )
    sandbox = [
        m for m in items(found, "environment_failed") if "sandbox could not start" in m["detail"]
    ]
    assert {m["detail"].split(":", 1)[0] for m in sandbox} == {"base", "head"}
    for item in sandbox:
        readable(item)
        assert "REPRO_SANDBOX=process" in item["resolution"]
    assert found["card"]["status"] == "UNVERIFIABLE"


def test_git_missing_is_a_message_not_a_traceback(tmp_path: Path) -> None:
    built = build_repo(ALL_SPECS["honest-fix"], tmp_path / "repo")
    [head] = built.head_shas.values()
    empty = tmp_path / "no-tools"
    empty.mkdir()
    env = clean_env(tmp_path, PATH=str(empty))
    argv = ["run", "--repo", str(built.path), "--base", built.base_sha, "--head", head]
    result = runner.invoke(app, [*argv, "--no-serve"], env=env)
    assert result.exit_code == 2
    assert "git is not installed" in result.output
    assert "Traceback" not in result.output
