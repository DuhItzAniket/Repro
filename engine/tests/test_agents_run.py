"""A run with its agents on, end to end, replayed from cassettes (G04 on).

``repro run`` on a fixture repository with ``agents = groq`` in ``replay`` mode: the agent
stages call no model, they serve the calls recorded live for the labelled sets
(``engine/tests/cassettes``), so the whole run is offline and the same every time.
"""

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from cli_support import clean_env
from fixtures.repo_builder import build_repo
from fixtures.specs import ALL_SPECS
from repro.cli import app
from repro.config import load_settings
from repro.store import StoreReader
from repro_bench.claims import load
from repro_events.log import read_log, validate_log
from repro_events.schemas import load_schema_set

CASSETTES = Path(__file__).parent / "cassettes"
runner = CliRunner()


def run_with_agents(
    name: str, tmp_path: Path, *extra: str, exit_code: int = 0, **env: str
) -> list[dict[str, Any]]:
    item = next(item for item in load() if item.name == name)
    built = build_repo(ALL_SPECS[name], tmp_path / "repo")
    [head] = built.head_shas.values()
    agents = {
        "REPRO_AGENTS": "groq",
        "REPRO_AGENT_MODE": "replay",
        "REPRO_AGENT_CASSETTES": str(CASSETTES),
    }
    variables = clean_env(
        tmp_path,
        REPRO_SANDBOX="process",
        REPRO_RUN_ROOT=str(tmp_path / "scratch"),
        **(agents | env),
    )
    argv = ["run", "--repo", str(built.path), "--base", built.base_sha, "--head", head]
    pr = ["--pr-title", item.title, "--pr-body", item.description]
    result = runner.invoke(app, [*argv, *pr, *extra, "--no-serve"], env=variables)
    assert result.exit_code == exit_code, result.output
    with StoreReader(load_settings(env=variables).paths.database) as reader:
        (run,) = reader.runs(10)
        events = [json.loads(event.body) for event in reader.events(run.id, 0, 100_000)]
    log = tmp_path / "run.jsonl"
    log.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    lines, issues = read_log(log)
    assert issues + validate_log(load_schema_set(), lines) == []
    return events


def test_a_run_reads_the_prs_claims_offline(tmp_path: Path) -> None:
    events = run_with_agents("honest-fix", tmp_path, "--analyse-only")

    started = events[0]["payload"]
    assert started["mode"]["deterministic_only"] is False
    assert started["pr"]["title"] == "Fix parse_date dropping the UTC offset"
    claims = [e["payload"]["claim"] for e in events if e["kind"] == "claim.extracted"]
    assert [c["id"] for c in claims] == ["C1", "C2", "C3", "C4"]
    assert claims[1]["text"] == "parse_date now returns timezone-aware datetimes normalised to UTC."
    spawned = [e for e in events if e["kind"] == "agent.spawned"]
    assert [(e["payload"]["role"], e["payload"]["prompt_version"]) for e in spawned] == [
        ("read", "reader/1")
    ]
    costs = [e["payload"] for e in events if e["kind"] == "cost.estimate"]
    assert [(c["model"], c["source"]) for c in costs] == [("openai/gpt-oss-120b", "cassette")]
    (card,) = [e["payload"]["card"] for e in events if e["kind"] == "card.published"]
    assert [c["id"] for c in card["claims"]] == ["C1", "C2", "C3", "C4"]
    assert card["conditions"]["models"] == ["openai/gpt-oss-120b"]


def test_a_missing_cassette_is_an_agent_failure_on_the_card(tmp_path: Path) -> None:
    events = run_with_agents(
        "honest-fix",
        tmp_path,
        "--analyse-only",
        exit_code=1,  # a job failed: the run did not complete
        REPRO_AGENT_CASSETTES=str(tmp_path / "none"),
    )
    (card,) = [e["payload"]["card"] for e in events if e["kind"] == "card.published"]
    assert "agent_failed" in [m["reason"] for m in card["missing"]]
    assert card["status"] != "VERIFIED"
    assert "claim.extracted" not in {e["kind"] for e in events}


def test_without_agents_a_run_is_deterministic_only(tmp_path: Path) -> None:
    events = run_with_agents("honest-fix", tmp_path, "--analyse-only", REPRO_AGENTS="off")
    assert events[0]["payload"]["mode"]["deterministic_only"] is True
    assert not {"agent.spawned", "claim.extracted"} & {e["kind"] for e in events}
