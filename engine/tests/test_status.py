"""The card's status (F04): every rule, table-driven, and the property the roadmap asks for.

Roadmap F04: "never VERIFIED while any unexplained stable gap or failed invariant exists", and
"table-driven tests over all rule combinations". Each fixture's status through ``repro run``
is checked in ``test_run_stage.py``.
"""

from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from repro.policy.status import (
    UNASSESSED_OUTCOMES,
    GapItem,
    Inputs,
    Verdict,
    decide,
)

EV = "ev_01JABCDEFGHJKMNPQRSTVWXYZ1"
SYMBOLS = ("pkg.a:f#0", "pkg.a:g#0", "pkg.b:h#0", "pkg.b:<module>#0")


def item(check: str, kind: str, status: str, **fields: object) -> GapItem:
    return GapItem(EV, check, kind, status, **fields)  # type: ignore[arg-type]


BEHAVIOUR = item("diff.behaviour", "result_changed", "warn")
SUPPORTED = (Verdict("c1", "supported", (EV,)),)
READ = {"claims": ("c1",), "verdicts": SUPPORTED}  # a review that explains EV


def explained(gap: GapItem) -> GapItem:
    return replace(gap, explained_by=("c1",))


CASES: list[tuple[str, Inputs, str, list[str]]] = [
    ("nothing to report", Inputs(), "VERIFIED", []),
    # -- gap items -------------------------------------------------------------------------
    ("an unexplained behaviour diff", Inputs(gap=(BEHAVIOUR,)), "FLAGGED", ["gap_flagged"]),
    (
        "a behaviour diff a supported claim explains",
        Inputs(gap=(explained(BEHAVIOUR),), **READ),  # type: ignore[arg-type]
        "VERIFIED",
        [],
    ),
    (
        "explained, but a contradicted claim cites it too",
        Inputs(
            gap=(replace(explained(BEHAVIOUR), contradicted_by=("c2",)),),
            claims=("c1", "c2"),
            verdicts=(*SUPPORTED, Verdict("c2", "contradicted", (EV,))),
        ),
        "FLAGGED",
        ["claim_contradicted", "gap_flagged"],
    ),
    (
        "an unstable behaviour diff",
        Inputs(gap=(replace(BEHAVIOUR, stability="unstable"),)),
        "VERIFIED",
        [],
    ),
    ("an unexplained probe diff", Inputs(gap=(item("diff.probe", "exception_added", "warn"),)),
     "FLAGGED", ["gap_flagged"]),
    ("an unexplained API break", Inputs(gap=(item("diff.api", "parameter_removed", "warn"),)),
     "FLAGGED", ["gap_flagged"]),
    ("an unexplained new dependency", Inputs(gap=(item("diff.deps", "added", "warn"),)),
     "FLAGGED", ["gap_flagged"]),
    ("an unexplained perf regression", Inputs(gap=(item("diff.perf", "regression", "warn"),)),
     "FLAGGED", ["gap_flagged"]),
    ("a perf improvement", Inputs(gap=(item("diff.perf", "improvement", "ok"),)), "VERIFIED", []),
    ("a fix: F2P", Inputs(gap=(item("diff.outcome", "F2P", "ok"),)), "VERIFIED", []),
    (
        "a P2F, even with a supported claim",
        Inputs(gap=(explained(item("diff.outcome", "P2F", "fail")),), **READ),  # type: ignore[arg-type]
        "FLAGGED",
        ["gap_flagged"],
    ),
    (
        "a base test failing on head, even with a supported claim",
        Inputs(
            gap=(explained(item("diff.tests", "base_test_fails_on_head", "fail")),),
            **READ,  # type: ignore[arg-type]
        ),
        "FLAGGED",
        ["gap_flagged"],
    ),
    ("a new test failing on head", Inputs(gap=(item("diff.outcome", "new", "fail"),)),
     "FLAGGED", ["gap_flagged"]),
    ("a new test passing on head", Inputs(gap=(item("diff.outcome", "new", "ok"),)),
     "VERIFIED", []),
    ("an unexplained skipped test", Inputs(gap=(item("diff.tests", "skip_added", "fail"),)),
     "FLAGGED", ["gap_flagged"]),
    (
        "a removed test a supported claim explains",
        Inputs(gap=(explained(item("diff.tests", "test_removed", "fail")),), **READ),  # type: ignore[arg-type]
        "VERIFIED",
        [],
    ),
    ("an unexplained edited test", Inputs(gap=(item("diff.tests", "test_modified", "warn"),)),
     "FLAGGED", ["gap_flagged"]),
    (
        "a pre-existing failure (F2F)",
        Inputs(gap=(item("diff.outcome", "F2F", "warn", origin="pre-existing"),)),
        "VERIFIED",
        [],
    ),
    (
        "head edits repro.yml, even with a supported claim",
        Inputs(gap=(explained(item("policy_change", "modified", "warn")),), **READ),  # type: ignore[arg-type]
        "FLAGGED",
        ["gap_flagged"],
    ),
    # -- invariants ------------------------------------------------------------------------
    ("an invariant passing", Inputs(invariants=(("no_network", "pass", (EV,)),)), "VERIFIED", []),
    ("an invariant failing", Inputs(invariants=(("no_network", "fail", (EV,)),)), "FLAGGED",
     ["invariant_failed"]),
    (
        "an invariant not evaluated",
        Inputs(invariants=(("perf_budget", "not_evaluated", (EV,)),)),
        "UNVERIFIABLE",
        ["invariant_not_evaluated"],
    ),
    # -- what could not be checked ---------------------------------------------------------
    ("base's repro.yml not valid", Inputs(policy_valid=False), "UNVERIFIABLE", ["policy_invalid"]),
    ("head's environment not built", Inputs(environments=frozenset({"base"})), "UNVERIFIABLE",
     ["environment_failed"]),
    ("the change not analysed", Inputs(analysed=False), "UNVERIFIABLE", ["not_analysed"]),
    ("a job skipped", Inputs(incomplete_stages=("diff",)), "UNVERIFIABLE", ["job_incomplete"]),
    ("no selected test ran", Inputs(selected=3, ran=0), "UNVERIFIABLE", ["tests_not_run"]),
    # H01: a run that stopped part way leaves tests without an outcome; never a pass.
    ("a selected test unreported", Inputs(selected=3, ran=2), "UNVERIFIABLE", ["tests_not_run"]),
    ("every selected test reported", Inputs(selected=3, ran=3), "VERIFIED", []),
    # H06: a run that did not finish (base's map, head's listing), even with nothing selected.
    (
        "a test run unfinished, nothing selected",
        Inputs(unfinished=("base: the A run ended early, with exit status 1",)),
        "UNVERIFIABLE",
        ["tests_not_run"],
    ),
    (
        "a test run unfinished, every selected test reported",
        Inputs(selected=3, ran=3, unfinished=("head: the H run took longer than its limit",)),
        "UNVERIFIABLE",
        ["tests_not_run"],
    ),
    (
        "changed symbols and no test selected",
        Inputs(changed=SYMBOLS[:2]),
        "UNVERIFIABLE",
        ["tests_not_run"],
    ),
    (
        "1 of 4 changed symbols unverified: at the threshold",
        Inputs(changed=SYMBOLS, unverified=frozenset(SYMBOLS[:1]), selected=1, ran=1),
        "VERIFIED",
        [],
    ),
    (
        "2 of 4 changed symbols unverified: above it",
        Inputs(changed=SYMBOLS, unverified=frozenset(SYMBOLS[:2]), selected=1, ran=1),
        "UNVERIFIABLE",
        ["coverage"],
    ),
    (
        "every changed symbol uncovered, so none selected",
        Inputs(changed=SYMBOLS, unverified=frozenset(SYMBOLS)),
        "UNVERIFIABLE",
        ["coverage"],
    ),
    # -- claims ----------------------------------------------------------------------------
    (
        "no claim found, and repro.yml requires one",
        Inputs(claims=(), require_explicit_claims=True),
        "UNVERIFIABLE",
        ["no_claims"],
    ),
    ("no claim found, none required", Inputs(claims=()), "VERIFIED", []),
    (
        "claims not read (no review stage): nothing to require",
        Inputs(claims=None, require_explicit_claims=True),
        "VERIFIED",
        [],
    ),
    (
        "a claim judged unverifiable",
        Inputs(claims=("c1",), verdicts=(Verdict("c1", "unverifiable", (EV,)),)),
        "UNVERIFIABLE",
        ["claim_not_supported"],
    ),
    ("a claim without a verdict", Inputs(claims=("c1",)), "UNVERIFIABLE",
     ["claim_not_supported"]),
    (
        "every verdict rejected",
        Inputs(claims=("c1",), rejected=2),
        "UNVERIFIABLE",
        ["verdicts_rejected", "claim_not_supported"],
    ),
    (
        "a claim contradicted",
        Inputs(claims=("c1",), verdicts=(Verdict("c1", "contradicted", (EV,)),)),
        "FLAGGED",
        ["claim_contradicted"],
    ),
    # -- precedence ------------------------------------------------------------------------
    (
        "a failed invariant and a missing environment: FLAGGED wins",
        Inputs(invariants=(("no_network", "fail", (EV,)),), environments=frozenset()),
        "FLAGGED",
        ["invariant_failed"],
    ),
]  # fmt: skip


@pytest.mark.parametrize(
    ("inputs", "status", "rules"), [c[1:] for c in CASES], ids=[c[0] for c in CASES]
)
def test_each_rule(inputs: Inputs, status: str, rules: list[str]) -> None:
    decision = decide(inputs)
    assert (decision.status, [r.rule for r in decision.reasons]) == (status, rules)


def test_flagged_still_lists_what_was_missing() -> None:
    inputs = Inputs(gap=(BEHAVIOUR,), environments=frozenset({"base"}))
    decision = decide(inputs)
    assert decision.status == "FLAGGED"
    assert [r.rule for r in decision.incomplete] == ["environment_failed"]


def test_every_flag_cites_its_evidence() -> None:
    decision = decide(Inputs(gap=(BEHAVIOUR,), invariants=(("no_network", "fail", (EV,)),)))
    assert all(reason.evidence_ids == (EV,) for reason in decision.reasons)


# -- the property ----------------------------------------------------------------------------

CHECK_KINDS = {
    "diff.outcome": ["F2P", "P2F", "F2F", "new", "removed", "modified", "flaky"],
    "diff.tests": ["test_modified", "test_removed", "skip_added", "base_test_fails_on_head"],
    "diff.behaviour": ["result_changed", "exception_added", "input_mutated"],
    "diff.probe": ["result_changed", "exception_added"],
    "diff.api": ["parameter_removed", "return_changed"],
    "diff.deps": ["added", "upgraded"],
    "diff.perf": ["regression", "improvement"],
    "policy_change": ["modified", "removed"],
}
CLAIMS = ("c1", "c2", "c3")


@st.composite
def gap_items(draw: st.DrawFn) -> GapItem:
    check = draw(st.sampled_from(sorted(CHECK_KINDS)))
    return GapItem(
        draw(st.sampled_from([f"ev_01JABCDEFGHJKMNPQRSTVWXYZ{i}" for i in range(4)])),
        check,
        draw(st.sampled_from(CHECK_KINDS[check])),
        draw(st.sampled_from(["ok", "warn", "fail"])),
        draw(st.sampled_from(["stable", "unstable", "n/a"])),
        draw(st.sampled_from(["introduced", "pre-existing", "n/a"])),
        tuple(draw(st.lists(st.sampled_from(CLAIMS), max_size=2, unique=True))),
        tuple(draw(st.lists(st.sampled_from(CLAIMS), max_size=1, unique=True))),
    )


inputs_strategy = st.builds(
    Inputs,
    gap=st.lists(gap_items(), max_size=6).map(tuple),
    invariants=st.lists(
        st.tuples(
            st.sampled_from(["no_network", "perf_budget", "forbidden_paths"]),
            st.sampled_from(["pass", "fail", "not_evaluated"]),
            st.just((EV,)),
        ),
        max_size=3,
    ).map(tuple),
    claims=st.one_of(st.none(), st.lists(st.sampled_from(CLAIMS), unique=True).map(tuple)),
    verdicts=st.lists(
        st.builds(
            Verdict,
            st.sampled_from(CLAIMS),
            st.sampled_from(["supported", "contradicted", "unverifiable"]),
            st.just((EV,)),
        ),
        max_size=3,
    ).map(tuple),
    rejected=st.integers(0, 2),
    policy_valid=st.booleans(),
    require_explicit_claims=st.booleans(),
    environments=st.sets(st.sampled_from(["base", "head"])).map(frozenset),
    selected=st.integers(0, 3),
    ran=st.integers(0, 3),
    analysed=st.booleans(),
    changed=st.lists(st.sampled_from(SYMBOLS), unique=True).map(tuple),
    unverified=st.sets(st.sampled_from(SYMBOLS)).map(frozenset),
    incomplete_stages=st.lists(st.sampled_from(["run", "diff"]), max_size=1).map(tuple),
)


def unexplained_stable(gap: GapItem) -> bool:
    """The roadmap's "unexplained stable gap", said without the rules' own words: a stable
    difference this change introduced, that could be compared, that is not a pass on its own,
    and that no supported claim explains."""
    comparable = not (gap.check == "diff.outcome" and gap.kind in UNASSESSED_OUTCOMES)
    return (
        gap.stability == "stable"
        and gap.origin == "introduced"
        and comparable
        and gap.status != "ok"
        and not gap.explained_by
    )


@settings(max_examples=2000, deadline=None)
@given(inputs_strategy)
def test_never_verified_with_an_unexplained_stable_gap_or_a_failed_invariant(
    inputs: Inputs,
) -> None:
    """Roadmap F04's property."""
    decision = decide(inputs)
    if any(unexplained_stable(g) for g in inputs.gap) or any(
        result == "fail" for _, result, _ in inputs.invariants
    ):
        assert decision.status == "FLAGGED"
    if decision.status == "VERIFIED":
        assert not decision.reasons
        assert not decision.incomplete
        assert all(result == "pass" for _, result, _ in inputs.invariants)
        assert inputs.claims is None or all(
            any(v.claim_id == c and v.verdict == "supported" for v in inputs.verdicts)
            for c in inputs.claims
        )
    assert decide(inputs) == decision  # deterministic
