"""The QA agent: verdicts read together, inconsistent supported ones withheld (G08)."""

from pathlib import Path
from typing import Any

from repro import __version__
from repro.agents import AgentResult, Dispatch, RunLedger
from repro.agents.evidence import EvidenceView
from repro.agents.openai_compat import strict_allowed
from repro.agents.prompts import load_prompt
from repro.agents.qa import check_answer, judged, qa_request, withheld, worth_checking
from repro.agents.setup import AgentSetup
from repro.agents.stages import qa_job
from repro.bus import EventBus
from repro.ids import new_evidence_id
from repro.orchestrator import GitRef, Job, JobContext, OnFailure, Orchestrator, RunSpec
from repro.policy.gap import inputs_from_events
from repro.policy.status import decide
from repro.store import StoreReader
from repro_events.log import LogLine, validate_log
from repro_events.schemas import SchemaSet
from store_support import started_writer

CHANGE = new_evidence_id()
PASS = new_evidence_id()


def evidence() -> list[dict[str, Any]]:
    common = {
        "run_id": "run_" + "0" * 26,
        "data": {},
        "artifacts": [],
        "stability": "stable",
        "origin": "introduced",
        "produced_by": {"component": "tests", "version": __version__},
    }
    return [
        {
            **common,
            "id": CHANGE,
            "type": "behaviour_diff",
            "targets": [{"symbol": "pkg.m:f#0", "file": "pkg/m.py"}],
            "summary": "f(1) gives another result: head 2, base 1",
        },
        {
            **common,
            "id": PASS,
            "type": "test_outcome",
            "targets": [{"test": "tests/test_m.py::test_f"}],
            "summary": "P2P: tests/test_m.py::test_f",
        },
    ]


def claim(ident: str, text: str, kind: str) -> dict[str, Any]:
    return {"id": ident, "text": text, "kind": kind, "targets": [], "source": "description"}


CLAIMS = [
    claim("C1", "f now returns 2", "fix"),
    claim("C2", "f behaves exactly as before", "refactor"),
    claim("C3", "g is faster", "perf"),
]


def verdict(claim_id: str, value: str, cited: str, rationale: str) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "verdict": value,
        "cited_evidence": [cited],
        "quotes": [],
        "rationale": rationale,
        "model": "m",
        "agreement": None,
    }


VERDICTS = [
    verdict("C1", "supported", CHANGE, "f(1) is 2 on head."),
    verdict("C2", "supported", PASS, "Its test passes on both sides."),
    verdict("C3", "unverifiable", PASS, "Nothing was timed."),
]


def as_events() -> list[dict[str, Any]]:
    events = [{"kind": "evidence.created", "payload": {"evidence": r}} for r in evidence()]
    events += [{"kind": "claim.extracted", "payload": {"claim": c}} for c in CLAIMS]
    events += [{"kind": "verdict.issued", "payload": {"verdict": v}} for v in VERDICTS]
    return events


def test_the_qa_agent_sees_every_verdict_and_what_it_cites() -> None:
    events = as_events()
    found = judged(events)
    assert [c["id"] for c, _ in found] == ["C1", "C2", "C3"]
    assert worth_checking(found)
    assert not worth_checking(found[:1])
    assert not worth_checking(
        [(c, [{**v, "verdict": "unverifiable"} for v in vs]) for c, vs in found]
    )
    request = qa_request(found, EvidenceView.from_events(events), load_prompt("qa"), "m")
    assert (request.role, request.prompt_version) == ("qa", "qa/1")
    assert "C2 (refactor): f behaves exactly as before" in request.prompt
    assert f"supported, citing {CHANGE}: f(1) is 2 on head." in request.prompt
    assert "f(1) gives another result: head 2, base 1" in request.prompt  # the cited evidence
    assert request.prompt.count("<untrusted_content") == 2  # verdicts, evidence
    assert request.output_schema is not None
    assert strict_allowed(request.output_schema)
    enum = request.output_schema["properties"]["inconsistencies"]["items"]["properties"]
    assert enum["claims"]["items"]["enum"] == ["C1", "C2", "C3"]


def test_only_inconsistencies_that_could_withhold_a_supported_verdict_are_kept() -> None:
    found = judged(as_events())
    answer = {
        "inconsistencies": [
            {"claims": ["C1", "C2"], "reason": f"{CHANGE} shows f changed."},
            {"claims": ["C1"], "reason": "one claim alone"},
            {"claims": ["C1", "C9"], "reason": "an unknown claim"},
            {"claims": ["C3", "C3"], "reason": "the same claim twice"},
            {"claims": ["C2", "C1"], "reason": " "},
            "not an object",
        ]
    }
    checked = check_answer(answer, found)
    assert checked.kept == [(["C1", "C2"], f"{CHANGE} shows f changed.")]
    assert len(checked.dropped) == 4
    unsupported = [(c, [{**v, "verdict": "unverifiable"} for v in vs]) for c, vs in found]
    assert (
        check_answer(
            {"inconsistencies": [{"claims": ["C1", "C2"], "reason": "x"}]}, unsupported
        ).kept
        == []
    )
    assert check_answer(None, found).dropped == ["the answer has no list of inconsistencies"]
    held = withheld(checked, found, "qa-model")
    assert [(v["claim_id"], v["verdict"], v["cited_evidence"]) for v in held] == [
        ("C1", "unverifiable", [CHANGE]),
        ("C2", "unverifiable", [PASS]),
    ]
    assert held[1]["rationale"] == (
        f"QA: its verdict cannot hold together with C1: {CHANGE} shows f changed."
    )


class Answering:
    def __init__(self, structured: Any) -> None:
        self.structured = structured
        self.calls = 0

    async def run(self, request: Any, on_progress: Any = None) -> AgentResult:
        self.calls += 1
        return AgentResult("ok", structured=self.structured, turns=1)


def run_qa(tmp_path: Path, backend: Any, verdicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def produce(ctx: JobContext) -> None:
        for record in evidence():
            ctx.emit(
                "evidence.created",
                status="ok",
                payload={"evidence": {**record, "run_id": ctx.run_id}},
            )
        for c in CLAIMS:
            ctx.emit("claim.extracted", status="ok", payload={"claim": c}, stage="read")
        for v in verdicts:
            ctx.emit("verdict.issued", status="ok", payload={"verdict": v}, stage="review")

    setup = AgentSetup(backend, {"qa": "qa-model"}, Dispatch(1), RunLedger(), "test (live)")
    with started_writer(tmp_path / "repro.db") as writer:

        def log(run_id: str) -> list[dict[str, Any]]:
            with StoreReader(writer.path) as reader:
                return [e.envelope() for e in reader.iter_events(run_id)]

        jobs = [
            Job("evidence", "run", produce, OnFailure("environment_failed", "x")),
            qa_job(log, setup=setup, after=["evidence"]),
        ]
        spec = RunSpec(
            "repo", GitRef("main", "a" * 40), GitRef("pr", "b" * 40), deterministic_only=False
        )
        result = Orchestrator(EventBus(writer), concurrency=2).run(spec, jobs)
        assert dict(result.jobs)["qa"] == "ok"
        return log(result.run_id)


def test_the_job_withholds_what_cannot_hold_together(tmp_path: Path, schema_set: SchemaSet) -> None:
    answer = {"inconsistencies": [{"claims": ["C1", "C2"], "reason": f"{CHANGE} shows f changed."}]}
    events = run_qa(tmp_path, Answering(answer), VERDICTS)
    assert validate_log(schema_set, [LogLine(i + 1, e) for i, e in enumerate(events)]) == []
    spawned = [e["payload"] for e in events if e["kind"] == "agent.spawned"]
    assert [(s["role"], s["prompt_version"]) for s in spawned] == [("qa", "qa/1")]
    withheld_ = [
        e
        for e in events
        if e["kind"] == "verdict.issued" and e["payload"]["verdict"]["model"] == "qa-model"
    ]
    assert [(e["payload"]["verdict"]["claim_id"], e["status"]) for e in withheld_] == [
        ("C1", "warn"),
        ("C2", "warn"),
    ]
    decision = decide(inputs_from_events(events))
    assert decision.status == "UNVERIFIABLE"  # withheld, never FLAGGED
    assert "claim_not_supported" in [r.rule for r in decision.reasons]


def test_the_job_asks_nothing_when_there_is_nothing_to_cross_check(tmp_path: Path) -> None:
    backend = Answering({"inconsistencies": []})
    lonely = [v for v in VERDICTS if v["claim_id"] == "C1"]
    events = run_qa(tmp_path, backend, lonely)
    assert backend.calls == 0
    assert not [e for e in events if e["kind"] == "agent.spawned"]


def test_no_inconsistency_changes_nothing(tmp_path: Path) -> None:
    events = run_qa(tmp_path, Answering({"inconsistencies": []}), VERDICTS)
    issued = [e for e in events if e["kind"] == "verdict.issued"]
    assert len(issued) == len(VERDICTS)
