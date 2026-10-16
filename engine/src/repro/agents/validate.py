"""A reviewer's verdict, checked against the evidence before it may count (G05).

ARCHITECTURE §10.3; ground rule 1 (every agent verdict must cite evidence IDs the engine
produced; a verdict with no evidence is rejected). The schema the reviewer answers in already
limits what it can say (its cited IDs are an enum of the claim's evidence), but the answer is
checked here again, whatever the backend or the schema enforced:

- **schema_error**: not a verdict at all (no known verdict value, cited IDs or quotes that are
  not lists of strings and objects, no rationale);
- **uncited**: it cites nothing;
- **invalid_citation**: it cites an ID this run has no evidence for;
- **unrelated_citation**: it cites evidence that is not about the claim;
- **quote_mismatch**: a quote is not copied exactly from the evidence it names (the rendered
  text ``get_evidence`` shows, ``repro.agents.evidence``), or names evidence it does not cite;
- **inconsistent_with_evidence**: a verdict the deterministic evidence rules out: ``supported``
  resting only on unstable evidence, or ``supported`` for a claim that nothing changed (kind
  ``no-change`` or ``refactor``) while it cites a stable difference the change introduced (a
  different result, an API break, a test that now fails), unless another claim of the PR
  describes a change. Then "no behaviour change" means none beyond it, and the differences it
  describes may be cited as accounted for; whether every difference is accounted for is the
  gap's to decide (F04, G06).

A verdict that passes is a ``verdict.issued`` payload's ``verdict``; one that does not is
rejected with the first reason that applies, and never reaches the card.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from repro.agents.evidence import EvidenceView, Item

VERDICTS: Final = ("supported", "contradicted", "unverifiable")
MAX_RATIONALE: Final = 4000
MAX_QUOTE: Final = 500
#: Evidence of a change in behaviour or interface, when stable and introduced by the change.
CHANGE_TYPES: Final = frozenset({"behaviour_diff", "probe_diff", "api_diff"})
#: Claim kinds that say behaviour does not change.
NO_CHANGE_KINDS: Final = frozenset({"no-change", "refactor"})
#: Claim kinds that describe a change in behaviour.
CHANGE_KINDS: Final = frozenset({"fix", "feature", "perf", "deps"})

Reason = Literal[
    "uncited",
    "invalid_citation",
    "unrelated_citation",
    "quote_mismatch",
    "inconsistent_with_evidence",
    "schema_error",
]


@dataclass(frozen=True, slots=True)
class Rejection:
    reason: Reason
    detail: str


def _is_change(item: Item) -> bool:
    if item.stability != "stable" or item.origin != "introduced":
        return False
    if item.type in CHANGE_TYPES:
        return True
    return item.type == "test_outcome" and item.data.get("class") == "P2F"


def _shape(answer: Any) -> Rejection | None:
    if not isinstance(answer, Mapping):
        return Rejection("schema_error", "the answer is not an object")
    if answer.get("verdict") not in VERDICTS:
        return Rejection("schema_error", f"verdict is not one of {', '.join(VERDICTS)}")
    cited = answer.get("cited_evidence")
    if not isinstance(cited, list) or not all(isinstance(c, str) for c in cited):
        return Rejection("schema_error", "cited_evidence is not a list of evidence IDs")
    quotes = answer.get("quotes")
    if not isinstance(quotes, list) or not all(
        isinstance(q, Mapping)
        and isinstance(q.get("evidence_id"), str)
        and isinstance(q.get("text"), str)
        for q in quotes
    ):
        return Rejection("schema_error", "quotes is not a list of {evidence_id, text}")
    rationale = answer.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        return Rejection("schema_error", "there is no rationale")
    return None


def _citations(
    cited: Sequence[str], view: EvidenceView, relevant: Sequence[str]
) -> Rejection | None:
    if not cited:
        return Rejection("uncited", "the verdict cites no evidence")
    unknown = [c for c in cited if c not in view.by_id]
    if unknown:
        return Rejection("invalid_citation", f"no such evidence in this run: {', '.join(unknown)}")
    unrelated = [c for c in cited if c not in set(relevant)]
    if unrelated:
        return Rejection("unrelated_citation", f"not about this claim: {', '.join(unrelated)}")
    return None


def _quotes(
    quotes: Sequence[Mapping[str, str]], cited: Sequence[str], view: EvidenceView
) -> list[dict[str, str]] | Rejection:
    kept = []
    for quote in quotes:
        ident, text = quote["evidence_id"], quote["text"]
        if ident not in cited:
            uncited = f"a quote from {ident}, which the verdict does not cite"
            return Rejection("quote_mismatch", uncited)
        if not text or len(text) > MAX_QUOTE or text not in view.by_id[ident].render():
            shown = text[:80].replace("\n", " ")
            return Rejection("quote_mismatch", f"not in {ident} as written: {shown!r}")
        kept.append({"evidence_id": ident, "text": text})
    return kept


def _consistency(
    verdict: str, claim: Mapping[str, Any], items: Sequence[Item], relative: bool
) -> Rejection | None:
    if verdict != "supported":
        return None
    if all(item.stability == "unstable" for item in items):
        return Rejection("inconsistent_with_evidence", "supported only by unstable evidence")
    changes = [item.id for item in items if _is_change(item)]
    if claim.get("kind") in NO_CHANGE_KINDS and changes and not relative:
        return Rejection(
            "inconsistent_with_evidence",
            "a claim that nothing changes, supported by evidence of a change: "
            + ", ".join(changes),
        )
    return None


def check(
    answer: Any,
    claim: Mapping[str, Any],
    view: EvidenceView,
    relevant: Sequence[str],
    model: str,
    *,
    claims: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any] | Rejection:
    """The verdict payload, or why it is rejected (the first reason that applies). ``claims``
    are the PR's claims: one describing a change makes a no-change claim relative to it."""
    problem = _shape(answer)
    if problem is not None:
        return problem
    cited = list(dict.fromkeys(answer["cited_evidence"]))
    problem = _citations(cited, view, relevant)
    if problem is not None:
        return problem
    quotes = _quotes(answer["quotes"], cited, view)
    if isinstance(quotes, Rejection):
        return quotes
    relative = any(c["kind"] in CHANGE_KINDS for c in claims if c["id"] != claim["id"])
    problem = _consistency(answer["verdict"], claim, [view.by_id[c] for c in cited], relative)
    if problem is not None:
        return problem
    return {
        "claim_id": claim["id"],
        "verdict": answer["verdict"],
        "cited_evidence": cited,
        "quotes": quotes,
        "rationale": answer["rationale"].strip()[:MAX_RATIONALE],
        "model": model,
        "agreement": None,
    }
