"""The card for other tools (H04): in-toto, SARIF 2.1.0 and JUnit XML, each against its schema.

Roadmap H04: "outputs validate against their specs and schemas. Card -> attestation -> card
round trip." The in-toto Statement and Repro's predicate are checked against their schemas in
``packages/events/schema/attestation``; SARIF against OASIS's SARIF 2.1.0 schema (Errata 01);
JUnit against the JUnit.xsd of github.com/windyroad/JUnit-Schema (Apache Ant's format). Both are
kept in ``data/schemas`` with their notices (README there).

The card comes from the cockpit's demo log, which holds claims of every verdict, gap items,
invariants and missing items; one export also runs through ``repro export`` on a real run.
"""

import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pytest
import xmlschema
from jsonschema import Draft4Validator
from typer.testing import CliRunner

from cli_support import clean_env
from gitrepo import Repo
from repro.card import canonical, digest, regenerate
from repro.card.exports import (
    PREDICATE_TYPE,
    AttestationError,
    attestation,
    card_from_attestation,
    cited,
    junit,
    sarif,
)
from repro.cli import app
from repro.config import load_settings
from repro.store import StoreReader
from repro_events.schemas import load_schema_set

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "apps" / "web" / "fixtures" / "demo-run.jsonl"
SCHEMAS = Path(__file__).parent / "data" / "schemas"
STATEMENT = "attestation/in-toto-statement-v1.schema.json"
PREDICATE = "attestation/reproduction-card-v0.schema.json"
runner = CliRunner()


def evidence_of(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        e["payload"]["evidence"]["id"]: e["payload"]["evidence"]
        for e in events
        if e["kind"] == "evidence.created"
    }


@pytest.fixture(scope="module")
def demo() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """The demo's card, assembled from its log (its card.published predates F05's card), with
    one supported verdict made unverifiable so that every verdict appears."""
    events = [json.loads(line) for line in DEMO.read_text(encoding="utf-8").splitlines() if line]
    card = regenerate(events).card
    supported = next(v for v in card["verdicts"] if v["verdict"] == "supported")
    supported["verdict"] = "unverifiable"
    return card, evidence_of(events)


def valid_statement(statement: dict[str, Any]) -> None:
    schemas = load_schema_set()
    schemas.validator(STATEMENT).validate(statement)
    schemas.validator(PREDICATE).validate(statement["predicate"])


def valid_sarif(log: dict[str, Any]) -> None:
    schema = json.loads((SCHEMAS / "sarif-schema-2.1.0.json").read_text(encoding="utf-8"))
    Draft4Validator(schema).validate(log)


def valid_junit(report: bytes) -> ET.Element:
    xmlschema.XMLSchema(str(SCHEMAS / "JUnit.xsd")).validate(report.decode("utf-8"))
    return ET.fromstring(report)  # noqa: S314 - Repro's own output, just validated


def test_the_demo_card_has_something_of_everything(
    demo: tuple[dict[str, Any], dict[str, dict[str, Any]]],
) -> None:
    card, _ = demo
    verdicts = Counter(v["verdict"] for v in card["verdicts"])
    assert set(verdicts) == {"supported", "contradicted", "unverifiable"}, verdicts
    assert card["gap"]
    assert card["missing"]


def test_the_attestation_is_a_statement_with_repros_predicate(
    demo: tuple[dict[str, Any], dict[str, dict[str, Any]]],
) -> None:
    card, evidence = demo
    statement = attestation(card, evidence)
    valid_statement(statement)
    assert statement["predicateType"] == PREDICATE_TYPE
    assert statement["subject"] == [
        {"name": card["repo"]["name"], "digest": {"gitCommit": card["conditions"]["head"]["sha"]}}
    ]
    predicate = statement["predicate"]
    assert predicate["cardDigest"] == {"sha256": digest(canonical(card))}
    assert predicate["eventLog"]["digest"]["sha256"] == card["replay"]["event_log_sha256"]
    named = {d["name"]: d["digest"]["sha256"] for d in predicate["evidence"]}
    assert set(named) == set(cited(card))
    assert all(named[i] == digest(canonical(evidence[i])) for i in named)


def test_card_to_attestation_to_card_is_exact(
    demo: tuple[dict[str, Any], dict[str, dict[str, Any]]],
) -> None:
    card, evidence = demo
    statement = json.loads(json.dumps(attestation(card, evidence)))  # as a file would hold it
    back = card_from_attestation(statement)
    assert canonical(back) == canonical(card)


def test_a_statement_signed_through_github_names_the_card_itself(
    demo: tuple[dict[str, Any], dict[str, dict[str, Any]]],
) -> None:
    """I03: GitHub's attestations take sha256 subjects, so the signed subject is the card."""
    card, evidence = demo
    statement = copy.deepcopy(attestation(card, evidence))
    statement["subject"] = [{"name": "card.json", "digest": {"sha256": digest(canonical(card))}}]
    assert canonical(card_from_attestation(statement)) == canonical(card)
    statement["subject"][0]["digest"]["sha256"] = "0" * 64
    with pytest.raises(AttestationError, match="or the card itself"):
        card_from_attestation(statement)


@pytest.mark.parametrize(
    ("tamper", "error"),
    [
        (lambda s: s["predicate"]["card"].update(status="VERIFIED"), "does not match its digest"),
        (lambda s: s["subject"][0]["digest"].update(gitCommit="0" * 40), "head commit"),
        (lambda s: s["predicate"].update(status="VERIFIED"), "status is not the card's"),
        (lambda s: s.update(predicateType="https://example.invalid/x/v0"), "not a Repro card"),
        (lambda s: s.update(_type="https://in-toto.io/Statement/v0.1"), "not an in-toto"),
        (lambda s: s["predicate"].pop("card"), "holds no card"),
    ],
)
def test_a_tampered_attestation_gives_no_card(
    demo: tuple[dict[str, Any], dict[str, dict[str, Any]]], tamper: Any, error: str
) -> None:
    card, evidence = demo
    statement = copy.deepcopy(attestation(card, evidence))
    tamper(statement)
    with pytest.raises(AttestationError, match=error):
        card_from_attestation(statement)


def test_an_evidence_record_the_log_lacks_is_an_error(
    demo: tuple[dict[str, Any], dict[str, dict[str, Any]]],
) -> None:
    card, evidence = demo
    first = next(iter(cited(card)))
    with pytest.raises(AttestationError, match=first):
        attestation(card, {k: v for k, v in evidence.items() if k != first})


def test_sarif_has_a_result_for_everything_the_card_reports(
    demo: tuple[dict[str, Any], dict[str, dict[str, Any]]],
) -> None:
    card, evidence = demo
    log = sarif(card, evidence)
    valid_sarif(log)
    (run,) = log["runs"]
    results = run["results"]
    failed = [i for i in card["invariants"] if i["result"] != "pass"]
    expected = len(card["gap"]) + len(failed) + len(card["verdicts"]) + len(card["missing"])
    assert len(results) == expected
    # SARIF 2.1.0 §3.27.10: any kind other than "fail" has level "none".
    assert all(r["level"] == "none" for r in results if r["kind"] != "fail")
    assert all(r["level"] in {"error", "warning"} for r in results if r["kind"] == "fail")
    contradicted = sum(v["verdict"] == "contradicted" for v in card["verdicts"])
    assert sum(r["ruleId"] == "claim/contradicted" and r["kind"] == "fail" for r in results) == (
        contradicted
    )
    missing = [r for r in results if r["ruleId"].startswith("missing/")]
    assert len(missing) == len(card["missing"])
    assert all(r["kind"] == "open" for r in missing)  # could not be decided
    rules = {rule["id"] for rule in run["tool"]["driver"]["rules"]}
    assert {r["ruleId"] for r in results} <= rules
    assert run["properties"]["status"] == card["status"]


def test_junit_has_a_test_case_per_claim_and_one_for_the_card(
    demo: tuple[dict[str, Any], dict[str, dict[str, Any]]],
) -> None:
    card, _ = demo
    suite = valid_junit(junit(card))
    cases = suite.findall("testcase")
    assert len(cases) == len(card["claims"]) + 1
    verdicts = Counter(v["verdict"] for v in card["verdicts"])
    flagged = card["status"] == "FLAGGED"
    unjudged = len(card["claims"]) - len(card["verdicts"])
    assert int(suite.get("failures", "")) == verdicts["contradicted"] + flagged
    assert int(suite.get("skipped", "")) == verdicts["unverifiable"] + unjudged
    assert int(suite.get("tests", "")) == len(cases)
    assert suite.get("hostname") == "repro"  # never this machine's name
    (status,) = [c for c in cases if c.get("classname") == "repro.card"]
    assert status.get("name") == f"status: {card['status']}"
    out = suite.findtext("system-out") or ""
    assert all(m["reason"] in out for m in card["missing"])


def test_repro_export_writes_each_format_of_a_real_run(tmp_path: Path) -> None:
    repo = Repo(tmp_path / "target")
    base = repo.commit({"pkg/__init__.py": "", "pkg/a.py": "def f():\n    return 1\n"})
    head = repo.commit({"pkg/a.py": "def f():\n    return 2\n"})
    env = clean_env(tmp_path)
    argv = ["run", "--repo", str(repo.path), "--base", base, "--head", head, "--no-serve"]
    result = runner.invoke(app, [*argv, "--analyse-only"], env=env)
    assert result.exit_code == 0, result.output
    with StoreReader(load_settings(env=env).paths.database) as reader:
        (run,) = reader.runs(10)
        events = [json.loads(e.body) for e in reader.iter_events(run.id)]
    (card,) = [e["payload"]["card"] for e in events if e["kind"] == "card.published"]
    written = {}
    for kind in ("in-toto", "sarif", "junit"):
        out = tmp_path / f"card.{kind}"
        result = runner.invoke(app, ["export", run.id, "--format", kind, "-o", str(out)], env=env)
        assert result.exit_code == 0, result.output
        written[kind] = out.read_bytes()
    statement = json.loads(written["in-toto"])
    valid_statement(statement)
    assert canonical(card_from_attestation(statement)) == canonical(card)
    valid_sarif(json.loads(written["sarif"]))
    suite = valid_junit(written["junit"])
    assert suite.findall("testcase")[-1].get("name") == f"status: {card['status']}"
