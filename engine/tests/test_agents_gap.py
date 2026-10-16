"""The gap reviewer: differences mapped to the claims that explain them, or unexplained (G06)."""

from pathlib import Path
from typing import Any

import pytest

from repro import __version__
from repro.agents import AgentResult, Dispatch, RunLedger
from repro.agents.evidence import EvidenceView
from repro.agents.gap import candidates, check_mapping, explainers, gap_request, schema, verdicts
from repro.agents.openai_compat import strict_allowed
from repro.agents.prompts import load_prompt
from repro.agents.setup import AgentSetup
from repro.agents.stages import gap_job
from repro.bus import EventBus
from repro.ids import new_evidence_id
from repro.orchestrator import GitRef, Job, JobContext, OnFailure, Orchestrator, RunSpec
from repro.policy.gap import inputs_from_events
from repro.policy.status import decide
from repro.store import StoreReader
from repro_events.log import LogLine, validate_log
from repro_events.schemas import SchemaSet
from store_support import started_writer

PARSE = "pkg.dates:parse_date#0"


def behaviour(test: str, head: str, file: str = "pkg/dates.py") -> dict[str, Any]:
    return {
        "id": new_evidence_id(),
        "run_id": "run_" + "0" * 26,
        "type": "behaviour_diff",
        "targets": [{"symbol": PARSE, "test": test, "file": file}],
        "summary": f"parse_date gives another result: head {head}, base 1 (in {test})",
        "data": {"change": "result_changed"},
        "artifacts": [],
        "stability": "stable",
        "origin": "introduced",
        "produced_by": {"component": "tests", "version": __version__},
    }


def claim(cid: str, kind: str, text: str, file: str | None = "pkg/dates.py") -> dict[str, Any]:
    targets = [{"file": file}] if file else []
    return {"id": cid, "text": text, "kind": kind, "targets": targets, "source": "description"}


def verdict(cid: str, value: str, cited: list[str]) -> dict[str, Any]:
    return {
        "claim_id": cid,
        "verdict": value,
        "cited_evidence": cited,
        "quotes": [],
        "rationale": "r",
        "model": "m",
        "agreement": None,
    }


def log(
    records: list[dict[str, Any]], claims: list[dict[str, Any]], issued: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for record in records:
        events.append({"kind": "evidence.created", "payload": {"evidence": record}, "status": "ok"})
        payload = {"evidence_id": record["id"], "change": "result_changed"}
        events.append(
            {"kind": "diff.behaviour", "payload": payload, "status": "warn", "target": None}
        )
    events += [{"kind": "claim.extracted", "payload": {"claim": c}} for c in claims]
    events += [{"kind": "verdict.issued", "payload": {"verdict": v}} for v in issued]
    return events


A, B, C = (
    behaviour("t::a", "2"),
    behaviour("t::b", "3"),
    behaviour("t::c", "4", file="pkg/other.py"),
)
FIX = claim("C1", "fix", "parse_date returns UTC")
SAME = claim("C2", "no-change", "No other behaviour changes", file=None)
DOCS = claim("C3", "docs", "Document parse_date")


def test_candidates_are_the_differences_only_an_explanation_would_settle() -> None:
    events = log([A, B, C], [FIX, SAME], [verdict("C1", "supported", [A["id"]])])
    view = EvidenceView.from_events(events)
    assert {i.id for i in candidates(events, view)} == {B["id"], C["id"]}  # A is explained
    contradicted = log([A, B], [FIX], [verdict("C1", "contradicted", [B["id"]])])
    assert {i.id for i in candidates(contradicted, EvidenceView.from_events(contradicted))} == {
        A["id"]
    }


def test_only_supported_claims_that_describe_a_change_may_explain() -> None:
    events = log(
        [A],
        [FIX, SAME, DOCS],
        [
            verdict("C1", "supported", []),
            verdict("C2", "supported", []),
            verdict("C3", "unverifiable", []),
        ],
    )
    assert [c["id"] for c in explainers(events)] == ["C1"]


def test_the_request_lists_the_claims_and_differences() -> None:
    events = log([B, C], [FIX], [verdict("C1", "supported", [])])
    view = EvidenceView.from_events(events)
    items = candidates(events, view)
    request = gap_request([FIX], items, load_prompt("gap"), "m")
    assert (request.role, request.prompt_version) == ("gap", "gap/1")
    assert all(item.render() in request.prompt for item in items)
    assert strict_allowed(request.output_schema)
    assert request.output_schema == schema([i.id for i in items], ["C1"])


def mapping(entries: list[tuple[str, list[str], str]]) -> dict[str, Any]:
    return {
        "differences": [
            {"evidence_id": i, "explained_by": c, "quote": q, "reason": "describes it"}
            for i, c, q in entries
        ]
    }


def test_a_mapping_is_checked_like_a_verdict() -> None:
    events = log([B, C], [FIX], [verdict("C1", "supported", [])])
    view = EvidenceView.from_events(events)
    items = candidates(events, view)
    explained = check_mapping(
        mapping(
            [
                (B["id"], ["C1"], "head 3, base 1"),
                (C["id"], ["C1"], "head 4, base 1"),  # pkg/other.py: not the claim's file
                ("ev_" + "Z" * 26, ["C1"], "x"),  # not given
            ]
        ),
        [FIX],
        items,
        view,
    )
    assert explained.by_claim == {"C1": [(B["id"], "head 3, base 1", "describes it")]}
    assert len(explained.dropped) == 2
    [found] = verdicts(explained, "m")
    assert (found["claim_id"], found["verdict"], found["cited_evidence"]) == (
        "C1",
        "supported",
        [B["id"]],
    )


@pytest.mark.parametrize(
    ("entry", "dropped"),
    [
        (lambda b: (b, ["C1"], "head 9"), "not in its evidence"),
        (lambda b: (b, ["C1"], ""), "no quote"),
        (lambda b: (b, ["C7"], "head 3"), "not a claim that may explain it"),
        (lambda b: (b, [], "anything"), None),  # unexplained, as answered: nothing dropped
    ],
)
def test_a_bad_mapping_leaves_its_difference_unexplained(entry: Any, dropped: str | None) -> None:
    events = log([B], [FIX], [verdict("C1", "supported", [])])
    view = EvidenceView.from_events(events)
    explained = check_mapping(mapping([entry(B["id"])]), [FIX], candidates(events, view), view)
    assert explained.by_claim == {}
    assert (dropped in explained.dropped[0]) if dropped else explained.dropped == []


def test_explained_differences_no_longer_flag() -> None:
    events = log([B], [FIX], [verdict("C1", "supported", [])])
    view = EvidenceView.from_events(events)
    explained = check_mapping(
        mapping([(B["id"], ["C1"], "head 3, base 1")]), [FIX], candidates(events, view), view
    )
    after = events + [
        {"kind": "verdict.issued", "payload": {"verdict": v}} for v in verdicts(explained, "m")
    ]
    [item] = inputs_from_events(after).gap
    assert item.resolution == "explained"
    assert decide(inputs_from_events(after)).status != "FLAGGED" or "gap_flagged" not in [
        r.rule for r in decide(inputs_from_events(after)).reasons
    ]


# -- the job ---------------------------------------------------------------------------------


class Mapper:
    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.calls = 0

    async def run(self, request: Any, on_progress: Any = None) -> AgentResult:
        self.calls += 1
        ids = request.output_schema["properties"]["differences"]["items"]["properties"][
            "evidence_id"
        ]["enum"]
        structured = self.answer(ids) if callable(self.answer) else self.answer
        return AgentResult("ok", structured=structured, turns=1)


def run_gap(
    tmp_path: Path, backend: Any, claims: list[dict[str, Any]], issued: list[tuple[str, str, int]]
) -> list[dict[str, Any]]:
    records = [behaviour("t::a", "2"), behaviour("t::b", "3")]

    def produce(ctx: JobContext) -> None:
        for record in records:
            ctx.emit(
                "evidence.created",
                status="ok",
                payload={"evidence": {**record, "run_id": ctx.run_id}},
            )
            ctx.emit(
                "diff.behaviour",
                status="warn",
                stage="diff",
                payload={
                    "evidence_id": record["id"],
                    "change": "result_changed",
                    "symbol_id": PARSE,
                    "test": record["targets"][0]["test"],
                    "stability": "stable",
                    "base_preview": "1",
                    "head_preview": "2",
                },
                target={"symbol": PARSE, "test": record["targets"][0]["test"]},
            )
        for c in claims:
            ctx.emit("claim.extracted", status="ok", payload={"claim": c}, stage="read")
        for cid, value, index in issued:
            ctx.emit(
                "verdict.issued",
                status="ok",
                stage="review",
                payload={"verdict": verdict(cid, value, [records[index]["id"]])},
                agent="a90",
            )

    setup = AgentSetup(backend, {"gap": "m"}, Dispatch(1), RunLedger(), "test (live)")
    with started_writer(tmp_path / "repro.db") as writer:

        def read(run_id: str) -> list[dict[str, Any]]:
            with StoreReader(writer.path) as reader:
                return [e.envelope() for e in reader.iter_events(run_id)]

        jobs = [
            Job("evidence", "run", produce, OnFailure("environment_failed", "x")),
            gap_job(read, setup=setup, after=["evidence"]),
        ]
        spec = RunSpec(
            "repo", GitRef("main", "a" * 40), GitRef("pr", "b" * 40), deterministic_only=False
        )
        result = Orchestrator(EventBus(writer), concurrency=1).run(spec, jobs)
        assert dict(result.jobs)["gap"] == "ok", read(result.run_id)[-3:]
        return read(result.run_id)


def test_the_job_explains_what_a_supported_claim_describes(
    tmp_path: Path, schema_set: SchemaSet
) -> None:
    backend = Mapper(lambda ids: mapping([(ids[0], ["C1"], "head 3, base 1")]))
    events = run_gap(tmp_path, backend, [FIX], [("C1", "supported", 0)])
    assert validate_log(schema_set, [LogLine(i + 1, e) for i, e in enumerate(events)]) == []
    assert backend.calls == 1
    gap = inputs_from_events(events).gap
    assert {item.resolution for item in gap} == {"explained"}


def test_without_a_claim_that_could_explain_nothing_is_asked(tmp_path: Path) -> None:
    """silent-change's case: no supported claim describes a change, so the differences stay
    unexplained and flag, with no call made."""
    backend = Mapper(mapping([]))
    events = run_gap(tmp_path, backend, [SAME], [("C2", "unverifiable", 0)])
    assert backend.calls == 0
    assert {item.resolution for item in inputs_from_events(events).gap} == {"flagged"}


def test_a_difference_left_unexplained_still_flags(tmp_path: Path) -> None:
    backend = Mapper(lambda ids: mapping([(ids[0], [], "head 3")]))
    events = run_gap(tmp_path, backend, [FIX], [("C1", "supported", 0)])
    assert backend.calls == 1
    resolutions = sorted(item.resolution for item in inputs_from_events(events).gap)
    assert resolutions == ["explained", "flagged"]
