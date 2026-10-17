"""A run with its agents on, end to end, replayed from cassettes (G04 on).

``repro run`` on a fixture repository with ``agents = groq`` in ``replay`` mode: the agent
stages call no model, they serve the calls recorded live for the labelled sets
(``engine/tests/cassettes``), so the whole run is offline and the same every time.
"""

import json
from pathlib import Path
from typing import Any

import pytest
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


def verdicts_of(events: list[dict[str, Any]]) -> dict[str, str]:
    issued = [e["payload"]["verdict"] for e in events if e["kind"] == "verdict.issued"]
    return {v["claim_id"]: v["verdict"] for v in issued}


def every_verdict_is_cited(events: list[dict[str, Any]]) -> None:
    evidence = {e["payload"]["evidence"]["id"] for e in events if e["kind"] == "evidence.created"}
    for event in events:
        if event["kind"] == "verdict.issued":
            cited = event["payload"]["verdict"]["cited_evidence"]
            assert cited
            assert set(cited) <= evidence


@pytest.fixture(scope="module")
def reviewed(tmp_path_factory: pytest.TempPathFactory) -> dict[str, list[dict[str, Any]]]:
    """Gate G's three pull requests, the injection twin and G07's probe-semantic, run in full
    with every agent (the probe writer, the reviewers with the order swap, the gap reviewer,
    QA), replayed from the cassettes recorded live (Groq, gpt-oss-120b, G08)."""
    runs = {}
    for name in ("honest-fix", "injection", "silent-change", "false-claim", "probe-semantic"):
        runs[name] = run_with_agents(name, tmp_path_factory.mktemp(name))
    return runs


@pytest.mark.parametrize(
    ("name", "status"),
    [
        ("honest-fix", "VERIFIED"),
        ("injection", "VERIFIED"),
        ("silent-change", "FLAGGED"),
        ("false-claim", "FLAGGED"),
        ("probe-semantic", "FLAGGED"),
    ],
)
def test_the_reviewed_card_of_each_pull_request(
    reviewed: dict[str, list[dict[str, Any]]], name: str, status: str
) -> None:
    events = reviewed[name]
    (card,) = [e["payload"]["card"] for e in events if e["kind"] == "card.published"]
    assert card["status"] == status, card["status_reasons"]
    assert "agent_failed" not in [m["reason"] for m in card["missing"]]
    every_verdict_is_cited(events)
    assert {
        c["source"] for c in (e["payload"] for e in events if e["kind"] == "cost.estimate")
    } == {"cassette"}


def test_an_honest_fix_is_supported_claim_by_claim(
    reviewed: dict[str, list[dict[str, Any]]],
) -> None:
    assert verdicts_of(reviewed["honest-fix"]) == dict.fromkeys(
        ["C1", "C2", "C3", "C4"], "supported"
    )
    (card,) = [
        e["payload"]["card"] for e in reviewed["honest-fix"] if e["kind"] == "card.published"
    ]
    assert {g["resolution"] for g in card["gap"]} <= {"passed", "explained"}


def test_planted_instructions_do_not_change_the_verdicts(
    reviewed: dict[str, list[dict[str, Any]]],
) -> None:
    """G03's acceptance, its verdict half: the injection twin is judged as honest-fix is."""
    assert verdicts_of(reviewed["injection"]) == verdicts_of(reviewed["honest-fix"])


def test_an_unclaimed_change_and_a_false_claim_are_flagged(
    reviewed: dict[str, list[dict[str, Any]]],
) -> None:
    (silent,) = [
        e["payload"]["card"] for e in reviewed["silent-change"] if e["kind"] == "card.published"
    ]
    assert "gap_flagged" in [r["rule"] for r in silent["status_reasons"]]
    unexplained = [g for g in silent["gap"] if g["check"] == "diff.behaviour"]
    assert unexplained
    assert all(g["resolution"] == "flagged" for g in unexplained)
    assert verdicts_of(reviewed["false-claim"])["C1"] == "contradicted"


def test_a_contradiction_stands_only_when_both_orders_give_it(
    reviewed: dict[str, list[dict[str, Any]]],
) -> None:
    """G08: each contradicted verdict was judged again with the evidence reversed, and agreed."""
    for name in ("false-claim", "probe-semantic"):
        issued = [e["payload"]["verdict"] for e in reviewed[name] if e["kind"] == "verdict.issued"]
        contradicted = [v for v in issued if v["verdict"] == "contradicted"]
        assert contradicted, name
        assert all(v["agreement"] == {"runs": 2, "agreeing": 2} for v in contradicted)


def test_the_probe_writer_s_input_flags_a_claim_of_no_behaviour_change(
    reviewed: dict[str, list[dict[str, Any]]],
) -> None:
    """G07 end to end: the claim that nothing changes is contradicted by a probe difference
    that only the probe writer's inputs found."""
    events = reviewed["probe-semantic"]
    found = {
        e["payload"]["evidence"]["id"]: e["payload"]["evidence"]
        for e in events
        if e["kind"] == "evidence.created"
    }
    (no_change,) = [
        e["payload"]["verdict"]
        for e in events
        if e["kind"] == "verdict.issued" and e["payload"]["verdict"]["verdict"] == "contradicted"
    ]
    cited = [found[i] for i in no_change["cited_evidence"]]
    assert [c["type"] for c in cited] == ["probe_diff"]
    assert cited[0]["data"]["found_by"] == ["agent"]


def test_qa_reads_the_verdicts_together(reviewed: dict[str, list[dict[str, Any]]]) -> None:
    """G08: QA runs where two or more judged claims include a supported one, and finds the
    honest fix's verdicts consistent."""
    for name in ("honest-fix", "injection"):
        events = reviewed[name]
        roles = [e["payload"]["role"] for e in events if e["kind"] == "agent.spawned"]
        assert roles.count("qa") == 1, name
        logged = [e["payload"]["message"] for e in events if e["kind"] == "log.line"]
        assert "QA: 0 inconsistencies among 4 judged claims" in logged
