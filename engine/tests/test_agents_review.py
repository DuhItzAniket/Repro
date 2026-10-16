"""The reviewer agents: verdicts checked against the evidence, or rejected (G05).

G05's acceptance is that no uncited verdict reaches the card. Two layers show it: every answer
a reviewer can give, generated adversarially (made-up IDs, unrelated IDs, misquotes, empty
citations, verdicts the evidence rules out), either passes ``check`` with real, related,
exactly quoted evidence or is rejected; and the review job, run through the orchestrator on such
answers, emits ``verdict.issued`` only for verdicts that passed.
"""

import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from gitrepo import Repo
from repro import __version__
from repro.agents import AgentResult, Dispatch, RunLedger, Usage
from repro.agents.evidence import EvidenceView
from repro.agents.openai_compat import strict_allowed
from repro.agents.prompts import load_prompt
from repro.agents.reviewer import relevant, reviewer_request, schema
from repro.agents.setup import AgentSetup
from repro.agents.sources import RepoSources
from repro.agents.stages import review_job
from repro.agents.validate import Rejection, check
from repro.bus import EventBus
from repro.gitops import Git
from repro.ids import new_evidence_id
from repro.orchestrator import GitRef, Job, JobContext, OnFailure, Orchestrator, RunSpec
from repro.store import StoreReader
from repro_events.log import LogLine, validate_log
from repro_events.schemas import SchemaSet
from store_support import started_writer

PARSE = "pkg.dates:parse_date#0"
TEST = "tests/test_dates.py::test_parse"


def evidence(
    kind: str, target: dict[str, str], summary: str, stability: str = "stable", **data: Any
) -> dict[str, Any]:
    return {
        "id": new_evidence_id(),
        "run_id": "run_" + "0" * 26,
        "type": kind,
        "targets": [target],
        "summary": summary,
        "data": data,
        "artifacts": [],
        "stability": stability,
        "origin": "introduced",
        "produced_by": {"component": "tests", "version": __version__},
    }


def records() -> list[dict[str, Any]]:
    return [
        evidence(
            "behaviour_diff",
            {"symbol": PARSE, "test": TEST, "file": "pkg/dates.py"},
            "parse_date('x') gives another result: head 2, base 1",
            change="result_changed",
            reproducer={"call": "parse_date('x')", "base": "1", "head": "2"},
        ),
        evidence(
            "test_outcome",
            {"test": TEST},
            f"F2P: {TEST} (base failed, head passed)",
            **{"class": "F2P", "base_outcome": "failed", "head_outcome": "passed"},
        ),
        evidence(
            "behaviour_diff",
            {"symbol": PARSE, "test": TEST, "file": "pkg/dates.py"},
            "parse_date('y') gives another result now and then",
            stability="unstable",
            change="result_changed",
        ),
        evidence(
            "api_diff",
            {"file": "pkg/other.py", "symbol": "pkg.other:f#0"},
            "f removed",
            breakage="removed",
        ),
    ]


def as_events(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"kind": "evidence.created", "payload": {"evidence": r}} for r in found]


FIX = {
    "id": "C1",
    "text": "parse_date returns 2",
    "kind": "fix",
    "targets": [{"file": "pkg/dates.py"}],
    "source": "description",
}
SAME = {
    "id": "C2",
    "text": "No behaviour change",
    "kind": "no-change",
    "targets": [],
    "source": "description",
}


def answer(
    verdict: str,
    cited: list[str],
    quotes: Sequence[tuple[str, str]] = (),
    rationale: str = "Because.",
) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "cited_evidence": cited,
        "quotes": [{"evidence_id": i, "text": t} for i, t in quotes],
        "rationale": rationale,
    }


@pytest.fixture
def view() -> EvidenceView:
    return EvidenceView.from_events(as_events(records()))


def ids_of(view: EvidenceView, claim: Mapping[str, Any]) -> list[str]:
    return [item.id for item in relevant(view, claim)]


# -- the check -------------------------------------------------------------------------------


def test_a_cited_and_quoted_verdict_passes(view: EvidenceView) -> None:
    behaviour = next(
        i for i in view.items if i.type == "behaviour_diff" and i.stability == "stable"
    )
    verdict = check(
        answer("supported", [behaviour.id], [(behaviour.id, "head 2, base 1")]),
        FIX,
        view,
        ids_of(view, FIX),
        "openai/gpt-oss-120b",
    )
    assert verdict == {
        "claim_id": "C1",
        "verdict": "supported",
        "cited_evidence": [behaviour.id],
        "quotes": [{"evidence_id": behaviour.id, "text": "head 2, base 1"}],
        "rationale": "Because.",
        "model": "openai/gpt-oss-120b",
        "agreement": None,
    }


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (lambda v, b, o, u: answer("supported", []), "uncited"),
        (lambda v, b, o, u: answer("supported", ["ev_" + "Z" * 26]), "invalid_citation"),
        (lambda v, b, o, u: answer("supported", [o.id]), "unrelated_citation"),
        (lambda v, b, o, u: answer("supported", [b.id], [(b.id, "head 3")]), "quote_mismatch"),
        (lambda v, b, o, u: answer("supported", [b.id], [(o.id, "f removed")]), "quote_mismatch"),
        (lambda v, b, o, u: answer("supported", [u.id]), "inconsistent_with_evidence"),
        (lambda v, b, o, u: answer("maybe", [b.id]), "schema_error"),
        (lambda v, b, o, u: answer("supported", [b.id], rationale="  "), "schema_error"),
        (lambda v, b, o, u: "supported", "schema_error"),
    ],
)
def test_a_verdict_the_evidence_does_not_bear_is_rejected(
    view: EvidenceView, make: Callable[..., Any], reason: str
) -> None:
    behaviour = next(
        i for i in view.items if i.type == "behaviour_diff" and i.stability == "stable"
    )
    unstable = next(i for i in view.items if i.stability == "unstable")
    other = next(i for i in view.items if i.type == "api_diff")
    found = check(make(view, behaviour, other, unstable), FIX, view, ids_of(view, FIX), "m")
    assert isinstance(found, Rejection)
    assert found.reason == reason


def test_a_claim_of_no_change_cannot_be_supported_by_a_change(view: EvidenceView) -> None:
    behaviour = next(
        i for i in view.items if i.type == "behaviour_diff" and i.stability == "stable"
    )
    found = check(answer("supported", [behaviour.id]), SAME, view, ids_of(view, SAME), "m")
    assert isinstance(found, Rejection)
    assert found.reason == "inconsistent_with_evidence"
    contradicted = check(
        answer("contradicted", [behaviour.id]), SAME, view, ids_of(view, SAME), "m"
    )
    assert not isinstance(contradicted, Rejection)


@settings(max_examples=300, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.data())
def test_no_answer_passes_without_real_related_exactly_quoted_evidence(
    view: EvidenceView, data: st.DataObject
) -> None:
    claim: dict[str, Any] = data.draw(st.sampled_from([FIX, SAME]))
    ids = ids_of(view, claim)
    some_id = st.one_of(
        st.sampled_from([i.id for i in view.items]),
        st.just("ev_" + "Q" * 26),
        st.text(max_size=30),
    )
    texts = st.one_of(
        st.text(max_size=40),
        st.sampled_from(
            [item.render()[a:b] for item in view.items for a, b in ((0, 10), (20, 60))]
        ),
    )
    raw = {
        "verdict": data.draw(st.sampled_from(["supported", "contradicted", "unverifiable", "x"])),
        "cited_evidence": data.draw(st.lists(some_id, max_size=4)),
        "quotes": [
            {"evidence_id": data.draw(some_id), "text": data.draw(texts)}
            for _ in range(data.draw(st.integers(0, 3)))
        ],
        "rationale": data.draw(st.text(max_size=20)),
    }
    found = check(raw, claim, view, ids, "m")
    if isinstance(found, Rejection):
        return
    assert found["cited_evidence"]
    assert all(c in view.by_id and c in ids for c in found["cited_evidence"])
    for quote in found["quotes"]:
        assert quote["evidence_id"] in found["cited_evidence"]
        assert quote["text"]
        assert quote["text"] in view.by_id[quote["evidence_id"]].render()
    if found["verdict"] == "supported":
        cited = [view.by_id[c] for c in found["cited_evidence"]]
        assert any(item.stability != "unstable" for item in cited)


# -- the request -----------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Git, str, str]:
    repo = Repo(tmp_path / "repo")
    base = repo.commit({"pkg/dates.py": "def parse_date(t):\n    return 1\n"})
    head = repo.commit({"pkg/dates.py": "def parse_date(t):\n    return 2\n"})
    return Git(repo.path), base, head


def test_a_reviewer_is_given_its_claim_evidence_and_diff(
    view: EvidenceView, repo: tuple[Git, str, str]
) -> None:
    git, base, head = repo
    items = relevant(view, FIX)
    request = reviewer_request(
        FIX,
        items,
        RepoSources(git, base, head),
        tools=(),
        prompt=load_prompt("reviewer"),
        model="m",
    )
    assert request.prompt_version == "reviewer/1"
    assert (request.role, request.effort) == ("review", "high")
    assert '<untrusted_content kind="claim">\nC1 (fix): parse_date returns 2\n' in request.prompt
    assert all(item.render() in request.prompt for item in items)
    assert "-    return 1\n+    return 2" in request.prompt
    made = request.output_schema
    assert made == schema([i.id for i in items])
    assert strict_allowed(made)
    assert made["properties"]["cited_evidence"]["minItems"] == 1


# -- the job ---------------------------------------------------------------------------------


class Answers:
    """A backend that gives each call the next answer, then the last again."""

    def __init__(self, *structured: Any, outcome: str = "ok") -> None:
        self.structured = list(structured)
        self.outcome = outcome
        self.calls = 0
        self._lock = threading.Lock()

    async def run(self, request: Any, on_progress: Any = None) -> AgentResult:
        with self._lock:
            index = min(self.calls, len(self.structured) - 1)
            self.calls += 1
        return AgentResult(
            self.outcome,  # type: ignore[arg-type]
            structured=self.structured[index] if self.outcome == "ok" else None,
            detail="" if self.outcome == "ok" else "it went wrong",
            turns=1,
            usage=Usage(10, 5, 0, 0.001),
        )


def run_review(
    tmp_path: Path, repo: tuple[Git, str, str], backend: Any, claims: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    git, base, head = repo
    found = records()

    def produce(ctx: JobContext) -> None:
        for record in found:
            ctx.emit(
                "evidence.created",
                status="ok",
                payload={"evidence": {**record, "run_id": ctx.run_id}},
            )
        for claim in claims:
            ctx.emit("claim.extracted", status="ok", payload={"claim": claim}, stage="read")

    setup = AgentSetup(backend, {"review": "m"}, Dispatch(2), RunLedger(), "test (live)")
    with started_writer(tmp_path / "repro.db") as writer:

        def log(run_id: str) -> list[dict[str, Any]]:
            with StoreReader(writer.path) as reader:
                return [e.envelope() for e in reader.iter_events(run_id)]

        jobs = [
            Job("evidence", "run", produce, OnFailure("environment_failed", "x")),
            review_job(log, git, base=base, head=head, setup=setup, others=["evidence"]),
        ]
        spec = RunSpec("repo", GitRef("main", base), GitRef("pr", head), deterministic_only=False)
        result = Orchestrator(EventBus(writer), concurrency=2).run(spec, jobs)
        assert dict(result.jobs)["review"] == "ok"
        return log(result.run_id)


def ids_in(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [e for e in events if e["kind"] == kind]


def test_the_job_issues_checked_verdicts(
    tmp_path: Path, repo: tuple[Git, str, str], schema_set: SchemaSet
) -> None:
    class Contradicting:
        calls = 0

        async def run(self, request: Any, on_progress: Any = None) -> AgentResult:
            Contradicting.calls += 1
            ids = request.output_schema["properties"]["cited_evidence"]["items"]["enum"]
            return AgentResult("ok", structured=answer("contradicted", [ids[0]]), turns=1)

    events = run_review(tmp_path, repo, Contradicting(), [FIX, SAME])
    assert validate_log(schema_set, [LogLine(i + 1, e) for i, e in enumerate(events)]) == []
    issued = ids_in(events, "verdict.issued")
    assert sorted(e["payload"]["verdict"]["claim_id"] for e in issued) == ["C1", "C2"]
    assert {e["status"] for e in issued} == {"fail"}
    assert {e["stage"] for e in issued} == {"review"}
    assert Contradicting.calls == 2


def test_a_rejected_verdict_is_retried_once_then_recorded(
    tmp_path: Path, repo: tuple[Git, str, str]
) -> None:
    backend = Answers(answer("supported", []))  # uncited, twice
    events = run_review(tmp_path, repo, backend, [FIX])
    assert backend.calls == 2
    assert ids_in(events, "verdict.issued") == []
    [rejected] = ids_in(events, "verdict.rejected")
    assert rejected["payload"]["reason"] == "uncited"
    missing = [e["payload"]["missing"] for e in ids_in(events, "missing.recorded")]
    assert [m["reason"] for m in missing] == ["verdict_rejected"]
    assert missing[0]["targets"] == [{"file": "pkg/dates.py"}]


def test_a_second_answer_that_passes_is_issued(tmp_path: Path, repo: tuple[Git, str, str]) -> None:
    class SecondTime:
        calls = 0

        async def run(self, request: Any, on_progress: Any = None) -> AgentResult:
            SecondTime.calls += 1
            ids = request.output_schema["properties"]["cited_evidence"]["items"]["enum"]
            cited = [] if SecondTime.calls == 1 else [ids[0]]
            assert ("previous answer was refused" in request.prompt) == (SecondTime.calls == 2)
            return AgentResult("ok", structured=answer("unverifiable", cited), turns=1)

    events = run_review(tmp_path, repo, SecondTime(), [FIX])
    assert [e["payload"]["verdict"]["verdict"] for e in ids_in(events, "verdict.issued")] == [
        "unverifiable"
    ]
    assert ids_in(events, "verdict.rejected") == []


def test_a_claim_with_no_evidence_is_not_sent_to_a_reviewer(
    tmp_path: Path, repo: tuple[Git, str, str]
) -> None:
    lonely = {**FIX, "id": "C9", "targets": [{"file": "nowhere.py"}]}
    backend = Answers(answer("supported", []))
    events = run_review(tmp_path, repo, backend, [lonely])
    assert backend.calls == 0
    [missing] = [e["payload"]["missing"] for e in ids_in(events, "missing.recorded")]
    assert missing["reason"] == "claim_unverifiable"


def test_a_reviewer_that_fails_is_an_agent_failure(
    tmp_path: Path, repo: tuple[Git, str, str]
) -> None:
    events = run_review(tmp_path, repo, Answers(None, outcome="timeout"), [FIX])
    [missing] = [e["payload"]["missing"] for e in ids_in(events, "missing.recorded")]
    assert missing["reason"] == "agent_failed"
    assert ids_in(events, "verdict.issued") == []


@settings(
    max_examples=12, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(data=st.data())
def test_only_checked_verdicts_reach_the_log(
    tmp_path_factory: pytest.TempPathFactory, data: st.DataObject
) -> None:
    """Adversarial answers through the job: whatever is issued cites real, related evidence."""
    tmp_path = tmp_path_factory.mktemp("adversarial")
    repo_ = Repo(tmp_path / "repo")
    base = repo_.commit({"pkg/dates.py": "x = 1\n"})
    head = repo_.commit({"pkg/dates.py": "x = 2\n"})
    picks = data.draw(st.lists(st.integers(0, 5), min_size=0, max_size=3))
    verdict = data.draw(st.sampled_from(["supported", "contradicted", "unverifiable"]))
    quoted = data.draw(st.booleans())

    class Adversary:
        async def run(self, request: Any, on_progress: Any = None) -> AgentResult:
            ids = request.output_schema["properties"]["cited_evidence"]["items"]["enum"]
            pool = [*ids, "ev_" + "R" * 26, "not-an-id"]
            cited = [pool[p % len(pool)] for p in picks]
            quotes = [(c, "head 2, base 1" if quoted else "made up") for c in cited[:1]]
            return AgentResult("ok", structured=answer(verdict, cited, quotes), turns=1)

    events = run_review(tmp_path, (Git(repo_.path), base, head), Adversary(), [FIX, SAME])
    view = EvidenceView.from_events(events)
    for issued in ids_in(events, "verdict.issued"):
        found = issued["payload"]["verdict"]
        assert found["cited_evidence"]
        assert all(c in view.by_id for c in found["cited_evidence"])
        for quote in found["quotes"]:
            assert quote["text"] in view.by_id[quote["evidence_id"]].render()


def test_nothing_else_changes_is_judged_beside_the_claims_that_say_what_does(
    view: EvidenceView,
) -> None:
    """With a claim describing a change, "no behaviour change" means none beyond it: the
    differences that claim describes may be cited as accounted for."""
    behaviour = next(
        i for i in view.items if i.type == "behaviour_diff" and i.stability == "stable"
    )
    supported = answer("supported", [behaviour.id])
    relative = check(supported, SAME, view, ids_of(view, SAME), "m", claims=[FIX, SAME])
    assert not isinstance(relative, Rejection)
    alone = check(supported, SAME, view, ids_of(view, SAME), "m", claims=[SAME])
    assert isinstance(alone, Rejection)
    assert alone.reason == "inconsistent_with_evidence"


def test_a_reviewer_sees_the_other_claims(view: EvidenceView, repo: tuple[Git, str, str]) -> None:
    git, base, head = repo
    request = reviewer_request(
        SAME,
        relevant(view, SAME),
        RepoSources(git, base, head),
        tools=(),
        prompt=load_prompt("reviewer"),
        model="m",
        claims=[FIX, SAME],
    )
    others = (
        '<untrusted_content kind="claims">\nC1 (fix): parse_date returns 2\n</untrusted_content>'
    )
    assert f"The pull request's other claims:\n{others}" in request.prompt
