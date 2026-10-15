"""A run's status inputs, read from its event log alone (F04): the gap, its explanations, the
invariants, the claims and verdicts, the policy in force, and what was left unverified.

The log is the contract (CLAUDE.md): a replayed run gives the same inputs, so the same status.
Events are taken as stored, in ``seq`` order.

- **Gap**: every check (``diff.*``) but a plain pass (P2P, a perf comparison with no change),
  with its evidence's stability and origin; and head's edit to ``repro.yml``
  (``policy_change``). A supported verdict that cites an item explains it; a contradicted one
  flags it (ADR-0015 §3).
- **Changed symbols**: ``blast.computed``'s, without test code: symbols in the modules of the
  test files the run's tests come from, and in ``conftest`` modules.
- **Unverified**: the changed symbols a missing item names for ``status.UNVERIFIED_REASONS``.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any, Final

from repro.policy.loader import DEFAULT
from repro.policy.status import UNVERIFIED_REASONS, GapItem, Inputs, Verdict

CHECKS: Final = (
    "diff.outcome",
    "diff.tests",
    "diff.behaviour",
    "diff.probe",
    "diff.api",
    "diff.deps",
    "diff.perf",
)
#: What each evidence type's ``data`` names its kind by.
KIND_FIELD: Final = {
    "test_outcome": "class",
    "test_change": "change",
    "behaviour_diff": "change",
    "probe_diff": "change",
    "api_diff": "breakage",
    "dep_diff": "change",
    "perf_diff": "verdict",
}
#: Checks that are not differences.
_NO_DIFFERENCE: Final = frozenset({("diff.outcome", "P2P"), ("diff.perf", "no_change")})


def _module(symbol: str) -> str:
    return symbol.partition(":")[0]


def _test_modules(events: Iterable[Mapping[str, Any]]) -> set[str]:
    """The dotted module names of the test files the run's tests come from."""
    files = set()
    for event in events:
        if event["kind"] in ("test.selected", "test.started", "test.finished"):
            test = (event.get("target") or {}).get("test")
            if test:
                files.add(test.split("::", 1)[0])
    return {f.removesuffix(".py").replace("/", ".") for f in files if f.endswith(".py")}


def inputs_from_events(events: Iterable[Mapping[str, Any]]) -> Inputs:
    """The status inputs a run's events hold."""
    log = list(events)
    evidence = {
        e["payload"]["evidence"]["id"]: e["payload"]["evidence"]
        for e in log
        if e["kind"] == "evidence.created"
    }
    supported: dict[str, list[str]] = defaultdict(list)
    contradicted: dict[str, list[str]] = defaultdict(list)
    verdicts = []
    for event in log:
        if event["kind"] != "verdict.issued":
            continue
        found = event["payload"]["verdict"]
        cited = tuple(found["cited_evidence"])
        verdicts.append(Verdict(found["claim_id"], found["verdict"], cited))
        if found["verdict"] in ("supported", "contradicted"):
            into = supported if found["verdict"] == "supported" else contradicted
            for evidence_id in cited:
                into[evidence_id].append(found["claim_id"])
    gap = []
    for event in log:
        if event["kind"] not in CHECKS:
            continue
        evidence_id = event["payload"]["evidence_id"]
        record = evidence.get(evidence_id, {})
        kind = str(record.get("data", {}).get(KIND_FIELD.get(record.get("type", ""), ""), ""))
        if (event["kind"], kind) in _NO_DIFFERENCE:
            continue
        gap.append(
            GapItem(
                evidence_id,
                event["kind"],
                kind,
                event["status"],
                record.get("stability", "stable"),
                record.get("origin", "introduced"),
                tuple(dict.fromkeys(supported.get(evidence_id, ()))),
                tuple(dict.fromkeys(contradicted.get(evidence_id, ()))),
            )
        )
    for evidence_id, record in evidence.items():
        if record["type"] == "policy_change":
            gap.append(
                GapItem(
                    evidence_id,
                    "policy_change",
                    record["data"]["change"],
                    "warn",
                    contradicted_by=tuple(contradicted.get(evidence_id, ())),
                )
            )
    return _with_policy(log, evidence, gap, verdicts)


def _with_policy(
    log: list[Mapping[str, Any]],
    evidence: Mapping[str, Mapping[str, Any]],
    gap: list[GapItem],
    verdicts: list[Verdict],
) -> Inputs:
    policy = next((r["data"] for r in evidence.values() if r["type"] == "policy"), None)
    document = (policy or {}).get("policy") or DEFAULT.document()
    tests = _test_modules(log)
    blast = [e for e in log if e["kind"] == "blast.computed"]
    changed = tuple(
        s
        for e in blast[-1:]
        for s in e["payload"]["changed"]
        if _module(s) not in tests and _module(s).rpartition(".")[2] != "conftest"
    )
    unverified: set[str] = set()
    for event in log:
        item = event["payload"]["missing"] if event["kind"] == "missing.recorded" else None
        if item is None or item["reason"] not in UNVERIFIED_REASONS:
            continue
        symbols = [t["symbol"] for t in item["targets"] if "symbol" in t]
        # Not about one symbol (a run's map or trace not made): about every changed one.
        unverified.update(symbols or changed)
    read = any(e["kind"] == "stage.started" and e["stage"] == "read" for e in log)
    claims = [e["payload"]["claim"]["id"] for e in log if e["kind"] == "claim.extracted"]
    selected = {e["target"]["test"] for e in log if e["kind"] == "test.selected"}
    ran = {e["target"]["test"] for e in log if e["kind"] == "diff.outcome"} & selected
    return Inputs(
        gap=tuple(gap),
        invariants=tuple(
            (e["payload"]["invariant"], e["payload"]["result"], tuple(e["payload"]["evidence_ids"]))
            for e in log
            if e["kind"] == "invariant.result"
        ),
        claims=tuple(claims) if read or claims else None,
        verdicts=tuple(verdicts),
        rejected=sum(1 for e in log if e["kind"] == "verdict.rejected"),
        policy_valid=policy is not None and bool(policy["valid"]),  # not read: not known
        require_explicit_claims=bool(document["claims"]["require_explicit"]),
        max_uncovered=float(document["missing"]["max_uncovered_changed_symbols"]),
        environments=frozenset(e["payload"]["side"] for e in log if e["kind"] == "env.provisioned"),
        selected=len(selected),
        ran=len(ran),
        analysed=bool(blast),
        changed=changed,
        unverified=frozenset(unverified),
        incomplete_stages=tuple(
            e["stage"] for e in log if e["kind"] == "stage.finished" and e["status"] != "ok"
        ),
    )
