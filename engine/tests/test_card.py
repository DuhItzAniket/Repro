"""The Reproduction Card (F05): assembled from a log, canonical, exported, and checked on replay.

Every fixture's card through ``repro run`` is checked in ``test_run_stage.py`` (published once,
recorded, assembled again byte for byte, and against its golden file).
"""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from cli_support import clean_env, free_port
from gitrepo import Repo
from repro.card import (
    assemble,
    before_card,
    canonical,
    digest,
    log_digest,
    published,
    regenerate,
    render,
)
from repro.card.markdown import verified_why
from repro.cli import app
from repro.config import load_settings
from repro.store import StoreReader
from repro_events import models

RUN = "run_01JABCDEFGHJKMNPQRSTVWXYZ0"
EV = [f"ev_01JABCDEFGHJKMNPQRSTVWXY{i:02d}" for i in range(10)]
REF = {"ref": "main", "sha": "a" * 40}
HEAD = {"ref": "fix", "sha": "b" * 40}
runner = CliRunner()


class Log:
    """A synthetic run log: envelopes with ``seq``, ``ts`` and the fields the card reads."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def add(self, kind: str, payload: dict[str, Any], **fields: Any) -> "Log":
        seq = len(self.events) + 1
        self.events.append(
            {
                "run_id": RUN,
                "seq": seq,
                "ts": f"2026-10-15T10:00:{seq:02d}.000Z",
                "kind": kind,
                "stage": "diff",
                "status": "ok",
                "target": None,
                "payload": payload,
                "producer": "repro/0.6.0",
                **fields,
            }
        )
        return self

    def evidence(self, evidence_id: str, kind: str, data: dict[str, Any], **fields: Any) -> "Log":
        record = {
            "id": evidence_id,
            "type": kind,
            "summary": f"{kind} {evidence_id[-2:]}",
            "data": data,
            "stability": "stable",
            "origin": "introduced",
            **fields,
        }
        return self.add("evidence.created", {"evidence": record})


def run_log() -> Log:
    """A run of one changed function, its test passing on both sides, and one invariant."""
    test = "tests/test_a.py::test_f"
    document = {
        "invariants": [{"no_network": True}],
        "claims": {"require_explicit": False},
        "missing": {"max_uncovered_changed_symbols": 0.25},
    }
    log = Log().add(
        "run.started",
        {
            "repo": {"name": "demo", "url": None},
            "base": REF,
            "head": HEAD,
            "pr": None,
            "mode": {"deterministic_only": True, "sandbox_backend": "process"},
        },
        stage="read",
    )
    log.evidence(EV[9], "policy", {"found": True, "valid": True, "policy": document})
    for side, level, network in (("base", "L2", "detected-only"), ("head", "L3", "enforced")):
        log.add(
            "sandbox.ready",
            {
                "side": side,
                "backend": "process",
                "isolation_level": level,
                "network": network,
                "platform": f"{side}-os",
            },
        )
        log.add(
            "env.provisioned",
            {"side": side, "python_version": f"3.13.{len(side)}", "lock_sha256": None},
        )
    log.add(
        "blast.computed", {"changed": ["pkg.a:f#0"], "affected": [], "module_level_changes": []}
    )
    log.add("test.selected", {"reasons": ["blast_radius"]}, target={"test": test})
    log.evidence(EV[8], "environment", {"hash_seed": 0, "hash_seed_repeat": 1})
    log.evidence(EV[0], "test_outcome", {"class": "P2P"}, origin="n/a")
    log.add("diff.outcome", {"evidence_id": EV[0]}, target={"test": test})
    log.evidence(EV[1], "invariant", {"invariant": "no_network"})
    log.add(
        "invariant.result",
        {
            "invariant": "no_network",
            "result": "pass",
            "evidence_ids": [EV[1]],
            "message": "no network attempt",
        },
        stage="check",
    )
    return log.add("stage.finished", {"duration_ms": 1}, stage="check")


def test_canonical_json_is_sorted_compact_and_utf8() -> None:
    assert canonical({"b": [1, "é"], "a": None}) == '{"a":null,"b":[1,"é"]}'.encode()
    with pytest.raises(ValueError, match="Out of range float"):
        canonical({"x": float("nan")})


def test_a_card_from_a_log() -> None:
    events = run_log().events
    card = assemble(events)
    models.ReproductionCard.model_validate(card)
    models.CardPublishedPayload.model_validate(published(card))
    assert (card["run_id"], card["status"], card["status_reasons"]) == (RUN, "VERIFIED", [])
    assert card["conditions"] == {
        "base": REF,
        "head": HEAD,
        "python_version": "3.13.4",  # head's
        "platform": "head-os",
        "isolation_level": "L2",  # the lower side's
        "network": "detected-only",  # enforced only if every side's was
        "lock_sha256": {"base": None, "head": None},
        "selected_tests": 1,
        "seeds": {"hash_seed": 0, "hash_seed_repeat": 1},
        "repro_version": "0.6.0",
        "models": [],
    }
    assert card["invariants"] == [
        {
            "name": "no_network",
            "result": "pass",
            "evidence_ids": [EV[1]],
            "message": "no network attempt",
        }
    ]
    assert card["replay"] == {"event_log_sha256": log_digest(events), "event_count": len(events)}
    assert card["generated_at"] == events[-1]["ts"]


def test_a_flagged_card_names_its_reasons_and_gap() -> None:
    log = run_log()
    log.evidence(EV[2], "behaviour_diff", {"change": "result_changed"})
    log.add("diff.behaviour", {"evidence_id": EV[2]}, status="warn")
    card = assemble(log.events)
    assert card["status"] == "FLAGGED"
    (reason,) = card["status_reasons"]
    assert (reason["rule"], reason["evidence_ids"], reason["decides"]) == (
        "gap_flagged",
        [EV[2]],
        True,
    )
    (item,) = card["gap"]
    assert (item["type"], item["check"], item["kind"], item["resolution"]) == (
        "behaviour_diff",
        "diff.behaviour",
        "result_changed",
        "flagged",
    )
    assert item["summary"] == f"behaviour_diff {EV[2][-2:]}"


def test_the_card_rests_on_what_precedes_its_publication() -> None:
    log = run_log()
    card = assemble(log.events)
    log.add("card.published", published(card), stage="card")
    log.add("run.finished", {"outcome": "completed", "card_status": card["status"]}, stage="card")
    assert before_card(log.events) == log.events[:-2]
    found = regenerate(reversed(log.events))  # in seq order whatever the order given
    assert found.identical
    assert found.card == card
    assert found.sha256 == digest(canonical(card))
    after = json.loads(json.dumps(log.events))
    after[-1]["payload"]["duration_ms"] = 99  # after the card: not what it rests on
    assert regenerate(after).identical
    tampered = json.loads(json.dumps(log.events))
    tampered[8]["payload"]["evidence"]["data"]["hash_seed"] = 7  # before it: the card differs
    assert not regenerate(tampered).identical


def test_what_a_run_did_not_reach_is_null() -> None:
    log = Log().add(
        "run.started",
        {
            "repo": {"name": "demo", "url": None},
            "base": REF,
            "head": HEAD,
            "pr": None,
            "mode": {"deterministic_only": True, "sandbox_backend": "process"},
        },
        stage="read",
    )
    card = assemble(log.events)
    models.ReproductionCard.model_validate(card)
    conditions = card["conditions"]
    assert [
        conditions[k] for k in ("python_version", "platform", "isolation_level", "network", "seeds")
    ] == [None] * 5
    assert card["status"] == "UNVERIFIABLE"
    assert {r["rule"] for r in card["status_reasons"]} >= {"policy_invalid", "environment_failed"}
    with pytest.raises(ValueError, match=r"no run\.started"):
        assemble([])


def test_markdown() -> None:
    log = run_log()
    log.evidence(EV[2], "behaviour_diff", {"change": "result_changed"}, summary="a | b\nc")
    log.add("diff.behaviour", {"evidence_id": EV[2]}, status="warn")
    text = render(assemble(log.events))
    assert text.startswith("# Reproduction Card: FLAGGED\n")
    for heading in (
        "## Why",
        "## Claims",
        "## Gap",
        "## Invariants",
        "## Missing",
        "## Conditions",
        "## Replay",
    ):
        assert f"\n{heading}\n" in text
    assert "a \\| b c" in text  # a pipe escaped, a line break folded
    assert f"`repro replay {RUN}`" in text


def test_a_verified_card_says_everything_was_checked_only_when_it_was() -> None:
    """H06: a VERIFIED card can list what it could not check; its Why never denies it."""
    card = assemble(run_log().events)
    clean = {**card, "status": "VERIFIED", "status_reasons": [], "missing": []}
    assert verified_why(clean) == "Nothing flags, and everything was checked."
    item: dict[str, Any] = {"reason": "perf_not_assessable", "targets": [], "detail": "fast"}
    timed = {**clean, "missing": [item]}
    assert "under Missing" in verified_why(timed)
    assert f"- {verified_why(timed)}" in render(timed)


# -- export and replay through the CLI -------------------------------------------------------


@pytest.fixture
def analysed(tmp_path: Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """A real run (analysing only: no target code runs): its environment and its log."""
    repo = Repo(tmp_path / "target")
    base = repo.commit({"pkg/__init__.py": "", "pkg/a.py": "def f():\n    return 1\n"})
    head = repo.commit({"pkg/a.py": "def f():\n    return 2\n"})
    env = clean_env(tmp_path)
    argv = [
        "run",
        "--repo",
        str(repo.path),
        "--base",
        base,
        "--head",
        head,
        "--no-serve",
        "--analyse-only",
    ]
    result = runner.invoke(app, argv, env=env)
    assert result.exit_code == 0, result.output
    with StoreReader(load_settings(env=env).paths.database) as reader:
        (run,) = reader.runs(10)
        events = [json.loads(e.body) for e in reader.iter_events(run.id)]
    return env, events


def test_export_writes_the_card_the_run_published(
    analysed: tuple[dict[str, str], list[dict[str, Any]]], tmp_path: Path
) -> None:
    env, events = analysed
    (published_card,) = [e["payload"]["card"] for e in events if e["kind"] == "card.published"]
    assert published_card["status"] == "UNVERIFIABLE"  # nothing ran: no environment
    run_id = events[0]["run_id"]
    out = tmp_path / "card.json"
    result = runner.invoke(app, ["export", run_id, "--format", "json", "-o", str(out)], env=env)
    assert result.exit_code == 0, result.output
    assert out.read_bytes() == canonical(published_card) + b"\n"
    log = tmp_path / "run.jsonl"
    log.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    markdown = tmp_path / "card.md"
    result = runner.invoke(app, ["export", str(log), "-o", str(markdown)], env=env)
    assert result.exit_code == 0, result.output
    assert markdown.read_text(encoding="utf-8") == render(published_card)


def test_a_card_that_differs_from_its_log_is_refused(
    analysed: tuple[dict[str, str], list[dict[str, Any]]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env, events = analysed
    for event in events:
        if event["kind"] == "card.published":
            event["payload"]["card_sha256"] = "0" * 64
    log = tmp_path / "tampered.jsonl"
    log.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    result = runner.invoke(app, ["export", str(log)], env=env)
    assert result.exit_code == 1
    assert "differs from the one the run published" in result.output
    monkeypatch.setattr("repro.cli._run_server", lambda api, sock, log_level: sock.close())
    result = runner.invoke(app, ["replay", str(log), "--port", str(free_port())], env=env)
    assert result.exit_code == 0, result.output  # replay shows the log as it is, and says so
    assert "differs from the one the run published" in result.output


def test_a_missing_item_shows_five_targets_and_counts_the_rest() -> None:
    card = assemble(run_log().events)
    tests = [{"test": f"tests/test_a.py::t{n}"} for n in range(7)]
    item = {"reason": "perf_not_assessable", "targets": tests, "detail": "fast", "resolution": None}
    text = render({**card, "missing": [item]})
    assert "tests/test_a.py::t4 and 2 more |" in text
    assert "t5" not in text
