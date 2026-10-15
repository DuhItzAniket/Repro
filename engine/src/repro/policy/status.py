"""The card's status, by deterministic rules (F04; ARCHITECTURE §4.6, PRODUCT.md, ADR-0015).

Inputs are what a run's log holds (``repro.policy.gap`` reads them from the events); the rules
decide ``FLAGGED``, ``UNVERIFIABLE`` or ``VERIFIED`` and say why, citing evidence IDs or
targets for every reason. No LLM is involved: claims and verdicts, when a run has them
(Stage G), are inputs like any other.

**Gap items** are the differences a run found: each check (``diff.*``) that is not a plain
pass, and head's edit to ``repro.yml``. Each resolves to one of:

- ``pre-existing``: present on base too (F2F); shown, never flagging the change;
- ``unassessed``: it could not be compared (unstable, flaky, modified or removed test);
- ``passed``: a check that is ``ok`` on its own (F2P, a new passing test, a perf improvement);
- ``explained``: a supported claim cites it, and no contradicted claim does;
- ``flagged``: a problem on its own that no claim can explain (a P2F, a base test failing on
  head, head's edit to the policy), anything a contradicted claim cites, or any other
  difference no supported claim explains. Without a review stage (a deterministic-only run)
  nothing is explained, so every difference flags (ADR-0015 §3).

**FLAGGED** if any gap item is flagged, any claim is contradicted, or any invariant failed.
**UNVERIFIABLE**, otherwise, if the evidence is incomplete: base's ``repro.yml`` is not valid
(or was not read), a side's environment was not built, the change was not analysed, a job
failed, timed out or was skipped, no selected test ran, too many changed symbols are
unverified (``missing.max_uncovered_changed_symbols``), an invariant was not evaluated, no
claim was found where ``claims.require_explicit`` asks for one, a claim is not supported, or
every verdict was rejected. **VERIFIED** otherwise: every claim supported, no unexplained gap,
every invariant passing. FLAGGED wins over UNVERIFIABLE: a concrete problem outweighs
incompleteness.

**Unverified changed symbols** are the changed symbols (``blast.computed``, test code left out)
that a missing item names as having no covering test, or calls that could not be compared:
masked as noise (``unstable_observation``), not encoded (``encoding_failed``) or not traced
(``trace_unavailable``). Such an item about no symbol in particular (a run's test map or trace
not made) leaves every changed symbol unverified.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

Status = Literal["VERIFIED", "FLAGGED", "UNVERIFIABLE"]
Resolution = Literal["pre-existing", "unassessed", "passed", "explained", "flagged"]

#: Outcome classes that could not be compared (ADR-0015 §3: unassessed).
UNASSESSED_OUTCOMES: Final = frozenset({"flaky", "modified", "removed", "F2F"})
#: Problems on their own that no claim explains (ARCHITECTURE §4.6: a P2F, including the base
#: version of a modified test failing on head).
UNEXPLAINABLE: Final = frozenset(
    {("diff.outcome", "P2F"), ("diff.outcome", "new"), ("diff.tests", "base_test_fails_on_head")}
)
#: Missing items that leave a changed symbol unverified.
UNVERIFIED_REASONS: Final = frozenset(
    {"no_covering_test", "unstable_observation", "encoding_failed", "trace_unavailable"}
)


@dataclass(frozen=True, slots=True)
class GapItem:
    """A difference the run found, with what review said of it."""

    evidence_id: str
    check: str  # "diff.outcome", ..., or "policy_change"
    kind: str  # the class, change, verdict or breakage the check names
    status: str  # the check's own status (ADR-0015 §2): ok, warn or fail
    stability: str = "stable"
    origin: str = "introduced"
    #: Claims whose supported verdict cites it, and claims whose contradicted verdict does.
    explained_by: tuple[str, ...] = ()
    contradicted_by: tuple[str, ...] = ()

    @property
    def resolution(self) -> Resolution:
        if self.origin == "pre-existing":
            return "pre-existing"
        if self.stability == "unstable" or (
            self.check == "diff.outcome" and self.kind in UNASSESSED_OUTCOMES
        ):
            return "unassessed"
        if self.contradicted_by:
            return "flagged"
        if self.check == "policy_change" or (self.check, self.kind) in UNEXPLAINABLE:
            return "flagged" if self.status != "ok" else "passed"
        if self.status == "ok":
            return "passed"
        return "explained" if self.explained_by else "flagged"


@dataclass(frozen=True, slots=True)
class Verdict:
    claim_id: str
    verdict: Literal["supported", "contradicted", "unverifiable"]
    cited: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Inputs:
    """Everything the status depends on, as a run's log records it."""

    gap: tuple[GapItem, ...] = ()
    #: (invariant, result, evidence IDs) per declared invariant.
    invariants: tuple[tuple[str, str, tuple[str, ...]], ...] = ()
    #: The claims found, or None when the run did not read any (no read stage).
    claims: tuple[str, ...] | None = None
    verdicts: tuple[Verdict, ...] = ()
    rejected: int = 0  # verdicts that failed validation
    #: Whether base's policy was valid; its claims and coverage settings.
    policy_valid: bool = True
    require_explicit_claims: bool = False
    max_uncovered: float = 0.25
    #: The sides whose environment was built ("base", "head").
    environments: frozenset[str] = frozenset({"base", "head"})
    selected: int = 0  # tests selected
    ran: int = 0  # selected tests with an outcome
    #: Whether the change was analysed (its blast radius computed).
    analysed: bool = True
    changed: tuple[str, ...] = ()  # changed symbols, test code left out
    unverified: frozenset[str] = frozenset()  # of those, the ones a missing item names
    #: Stages in which a job failed, timed out or was skipped.
    incomplete_stages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Reason:
    """Why the status is what it is: a rule, and what it rests on."""

    rule: str
    detail: str
    evidence_ids: tuple[str, ...] = ()
    targets: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Decision:
    status: Status
    #: The reasons for that status (FLAGGED: what flags; UNVERIFIABLE: what is missing).
    reasons: tuple[Reason, ...]
    #: What would also have made it UNVERIFIABLE, had nothing flagged (shown on the card).
    incomplete: tuple[Reason, ...] = field(default=())


def _ids(items: Iterable[GapItem]) -> tuple[str, ...]:
    return tuple(item.evidence_id for item in items)


def flags(inputs: Inputs) -> list[Reason]:
    """What makes the change FLAGGED, each with the evidence it rests on."""
    found: list[Reason] = []
    contradicted = [v for v in inputs.verdicts if v.verdict == "contradicted"]
    if contradicted:
        claims = sorted({v.claim_id for v in contradicted})
        cited = tuple(dict.fromkeys(i for v in contradicted for i in v.cited))
        found.append(
            Reason("claim_contradicted", f"claims contradicted: {', '.join(claims)}", cited)
        )
    flagged = [item for item in inputs.gap if item.resolution == "flagged"]
    for check in sorted({item.check for item in flagged}):
        items = [item for item in flagged if item.check == check]
        kinds = ", ".join(sorted({item.kind for item in items}))
        found.append(Reason("gap_flagged", f"{len(items)} {check} flagged ({kinds})", _ids(items)))
    failed = [(name, ids) for name, result, ids in inputs.invariants if result == "fail"]
    if failed:
        names = ", ".join(name for name, _ in failed)
        cited = tuple(i for _, ids in failed for i in ids)
        found.append(Reason("invariant_failed", f"invariants failed: {names}", cited))
    return found


def incomplete(inputs: Inputs) -> list[Reason]:
    """What leaves the change unverifiable: what could not be checked."""
    found: list[Reason] = []
    if not inputs.policy_valid:
        found.append(Reason("policy_invalid", "repro.yml on base is not valid, or was not read"))
    missing_sides = sorted({"base", "head"} - inputs.environments)
    if missing_sides:
        found.append(
            Reason("environment_failed", f"no environment for {' and '.join(missing_sides)}")
        )
    if not inputs.analysed:
        found.append(Reason("not_analysed", "the change's blast radius was not computed"))
    if inputs.incomplete_stages:
        stages = ", ".join(inputs.incomplete_stages)
        found.append(Reason("job_incomplete", f"a job did not complete in: {stages}"))
    unverified = sorted(set(inputs.changed) & inputs.unverified)
    if missing_sides:
        pass  # no tests run without both environments: the cause is already a reason
    elif inputs.selected and not inputs.ran:
        found.append(Reason("tests_not_run", f"none of the {inputs.selected} selected tests ran"))
    elif inputs.changed and not inputs.selected and len(unverified) < len(inputs.changed):
        found.append(Reason("tests_not_run", "no test was selected for the changed symbols"))
    if inputs.changed and len(unverified) / len(inputs.changed) > inputs.max_uncovered:
        share = len(unverified) / len(inputs.changed)
        found.append(
            Reason(
                "coverage",
                f"{len(unverified)} of {len(inputs.changed)} changed symbols unverified "
                f"({share:.0%}, above {inputs.max_uncovered:.0%})",
                targets=tuple(unverified),
            )
        )
    unevaluated = [
        (name, ids) for name, result, ids in inputs.invariants if result == "not_evaluated"
    ]
    if unevaluated:
        names = ", ".join(name for name, _ in unevaluated)
        cited = tuple(i for _, ids in unevaluated for i in ids)
        found.append(Reason("invariant_not_evaluated", f"invariants not evaluated: {names}", cited))
    found += _claims(inputs)
    return found


def _claims(inputs: Inputs) -> list[Reason]:
    if inputs.claims is None:
        return []  # no read stage: nothing to require of claims
    found: list[Reason] = []
    if not inputs.claims and inputs.require_explicit_claims:
        found.append(Reason("no_claims", "no claim found, and repro.yml requires one"))
    if inputs.rejected and not inputs.verdicts:
        found.append(Reason("verdicts_rejected", f"all {inputs.rejected} verdicts were rejected"))
    supported = {v.claim_id for v in inputs.verdicts if v.verdict == "supported"}
    judged = {v.claim_id for v in inputs.verdicts if v.verdict != "supported"}
    unsupported = [c for c in inputs.claims if c not in supported or c in judged]
    if unsupported:
        found.append(
            Reason("claim_not_supported", f"claims not supported: {', '.join(unsupported)}")
        )
    return found


def decide(inputs: Inputs) -> Decision:
    """The status and its reasons."""
    flagged, missing = flags(inputs), incomplete(inputs)
    if flagged:
        return Decision("FLAGGED", tuple(flagged), tuple(missing))
    if missing:
        return Decision("UNVERIFIABLE", tuple(missing))
    return Decision("VERIFIED", ())


def unexplained(gap: Sequence[GapItem]) -> list[GapItem]:
    """The gap items no claim explains that would flag: the card's ``unexplained`` count."""
    return [item for item in gap if item.resolution == "flagged"]
