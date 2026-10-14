"""``repro run`` end to end with the run stage (D06): sandboxes, environments, both sides' tests,
and the evidence as stored events.

The fixtures' expectation files name the evidence and missing items; here they must arrive as
``evidence.created`` / ``missing.recorded`` events of a schema-valid log, with ``test.selected``,
``diff.outcome`` and ``diff.tests`` events citing them. The process sandbox runs everywhere; the
container case needs Docker with Linux containers (required on CI's Ubuntu job).
"""

import json
import os
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from cli_support import clean_env
from fixtures.repo_builder import build_repo
from fixtures.specs import ALL_SPECS
from repro.cli import app
from repro.config import load_settings
from repro.sandbox import docker_available
from repro.store import StoreReader
from repro_events.log import read_log, validate_log
from repro_events.schemas import load_schema_set

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def run_fixture(name: str, tmp_path: Path, sandbox: str) -> list[dict[str, Any]]:
    expected = tomllib.loads((FIXTURES / f"{name}.toml").read_text(encoding="utf-8"))
    built = build_repo(ALL_SPECS[name], tmp_path / "repo")
    head = built.head_shas[expected["fixture"]["head"]]
    env = clean_env(tmp_path, REPRO_SANDBOX=sandbox, REPRO_RUN_ROOT=str(tmp_path / "scratch"))
    argv = ["run", "--repo", str(built.path), "--base", built.base_sha, "--head", head]
    result = runner.invoke(app, [*argv, "--no-serve"], env=env)
    assert result.exit_code == 0, result.output
    with StoreReader(load_settings(env=env).paths.database) as reader:
        (run,) = reader.runs(10)
        events = [json.loads(event.body) for event in reader.events(run.id, 0, 100_000)]
    log = tmp_path / "run.jsonl"
    log.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    lines, issues = read_log(log)
    assert issues + validate_log(load_schema_set(), lines) == []
    assert not list((tmp_path / "scratch").iterdir())  # the run left nothing behind
    return events


def check_against_expectation(name: str, events: list[dict[str, Any]]) -> None:
    expected = tomllib.loads((FIXTURES / f"{name}.toml").read_text(encoding="utf-8"))
    log = "\n".join(
        e["payload"]["message"] for e in events if e["kind"] == "log.line"
    )  # shown when an assertion fails
    selected = {
        e["target"]["test"]: e["payload"]["reasons"] for e in events if e["kind"] == "test.selected"
    }
    assert selected == expected["selection"].get("selected", {}), log
    evidence = {
        e["payload"]["evidence"]["id"]: e["payload"]["evidence"]
        for e in events
        if e["kind"] == "evidence.created"
    }
    found = []
    for item in evidence.values():
        data, target = item["data"], item["targets"][0]
        if item["type"] == "test_outcome":
            found.append(f"test_outcome:{data['class']}:{target['test']}")
        elif item["type"] == "test_change":
            found.append(f"test_change:{data['change']}:{target.get('test') or target['file']}")
    assert sorted(found) == sorted(expected["expected"]["evidence"]), log
    cited = [
        e["payload"]["evidence_id"] for e in events if e["kind"] in ("diff.outcome", "diff.tests")
    ]
    assert sorted(cited) == sorted(
        i for i, item in evidence.items() if item["type"] in ("test_outcome", "test_change")
    )
    missing = []
    for event in events:
        if event["kind"] == "missing.recorded":
            item = event["payload"]["missing"]
            target = item["targets"][0] if item["targets"] else {}
            missing.append(f"{item['reason']}:{target.get('symbol') or target.get('test') or ''}")
    assert sorted(missing) == sorted(expected["expected"]["missing"]), log


@pytest.mark.parametrize("name", ["honest-fix", "test-tamper"])
def test_a_run_reproduces_the_fixture(name: str, tmp_path: Path) -> None:
    events = run_fixture(name, tmp_path, "process")
    check_against_expectation(name, events)
    kinds = Counter(e["kind"] for e in events)
    assert kinds["sandbox.ready"] == 2
    assert kinds["env.provisioned"] == 2
    ready = [e["payload"] for e in events if e["kind"] == "sandbox.ready"]
    assert {r["backend"] for r in ready} == {"process"}
    assert {r["network"] for r in ready} == {"detected-only"}
    stages = [e["stage"] for e in events if e["kind"] == "stage.started"]
    assert stages == ["build", "run", "diff"]  # claims (read) arrive in Stage G
    assert events[-1]["kind"] == "run.finished"
    assert events[-1]["status"] == "ok"


def test_test_events_count_attempts(tmp_path: Path) -> None:
    events = run_fixture("honest-fix", tmp_path, "process")
    finished = [
        (
            e["target"]["test"],
            e["payload"]["side"],
            e["payload"]["attempt"],
            e["payload"]["outcome"],
        )
        for e in events
        if e["kind"] == "test.finished"
    ]
    test = "tests/test_dates.py::test_parse_date_with_timezone"
    # A, A2, then three reruns on base; H, then three reruns on head.
    assert [f[2:] for f in finished if f[0] == test and f[1] == "base"] == [
        (1, "failed"),
        (2, "failed"),
        (3, "failed"),
        (4, "failed"),
        (5, "failed"),
    ]
    assert [f[2:] for f in finished if f[0] == test and f[1] == "head"] == [
        (1, "passed"),
        (2, "passed"),
        (3, "passed"),
        (4, "passed"),
    ]


def test_an_environment_that_cannot_be_built_is_unverifiable(tmp_path: Path) -> None:
    """A dependency that is not on the index: provisioning fails with uv's reason, the tests
    are not attempted, and the run still completes with what it could not check."""
    spec = ALL_SPECS["honest-fix"]
    broken = type(spec)(
        name="broken-env",
        description=spec.description,
        base={
            **spec.base,
            "pyproject.toml": (
                '[project]\nname = "dates-fixture"\nversion = "0.1.0"\n'
                'dependencies = ["repro-fixture-package-that-does-not-exist==1.0"]\n'
            ),
        },
        heads=spec.heads,
    )
    built = build_repo(broken, tmp_path / "repo")
    env = clean_env(tmp_path, REPRO_SANDBOX="process", REPRO_RUN_ROOT=str(tmp_path / "scratch"))
    head = built.head_shas["fix/parse-date-utc"]
    argv = ["run", "--repo", str(built.path), "--base", built.base_sha, "--head", head]
    result = runner.invoke(app, [*argv, "--no-serve"], env=env)
    assert result.exit_code == 0, result.output
    with StoreReader(load_settings(env=env).paths.database) as reader:
        (run,) = reader.runs(10)
        events = [json.loads(event.body) for event in reader.events(run.id, 0, 100_000)]
    missing = [e["payload"]["missing"] for e in events if e["kind"] == "missing.recorded"]
    assert sorted(m["detail"].split(":", 1)[0] for m in missing) == ["base", "head"]
    assert {m["reason"] for m in missing} == {"environment_failed"}
    assert all("repro-fixture-package-that-does-not-exist" in m["detail"] for m in missing)
    assert not [e for e in events if e["kind"] in ("evidence.created", "test.selected")]
    assert events[-1]["kind"] == "run.finished"


docker = pytest.mark.skipif(
    not docker_available() and os.environ.get("REPRO_REQUIRE_DOCKER") != "1",
    reason="Docker with Linux containers is not available",
)


@docker
def test_a_run_in_containers(tmp_path: Path) -> None:
    events = run_fixture("test-tamper", tmp_path, "docker")
    check_against_expectation("test-tamper", events)
    ready = [e["payload"] for e in events if e["kind"] == "sandbox.ready"]
    assert {(r["backend"], r["isolation_level"], r["network"]) for r in ready} == {
        ("docker", "L3", "enforced")
    }
