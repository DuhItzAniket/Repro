"""The gap reviewer: each difference no verdict accounts for, mapped to the claims that
explain it, or left unexplained (G06; ARCHITECTURE §10.1, ADR-0015).

After the reviewers, the gap (``repro.policy.gap``) may still hold differences that would flag
only because no supported verdict cites them (a ``warn`` check; not a problem on its own such
as a test that now fails or an edit to the policy, ADR-0015 §2; not one a contradicted verdict
cites). Some are what a supported claim describes and its reviewer did not cite: a third test
showing the same new result, say. The gap reviewer sees them beside the claims that may
explain them: the supported claims that describe a change (a claim that nothing changes, or a
refactor, cannot explain a difference).

Its answer is checked like a verdict (``repro.agents.validate``): each difference must be one
it was given, at most once; each claim one it was given, and about the difference's files
(G03's relevance rule); each quote copied exactly from the difference's evidence. A mapping
that fails is dropped, and its difference stays unexplained. What survives becomes, per
claim, a ``verdict.issued`` that supports it and cites the differences it explains: explanation
is a supported verdict's citation (ADR-0015), so the status rules (F04) need nothing new.
Unexplained differences flag, as before.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from repro.agents.backend import AgentRequest, Budget
from repro.agents.evidence import EvidenceView, Item
from repro.agents.prompts import Prompt
from repro.agents.untrusted import block
from repro.agents.validate import MAX_QUOTE, NO_CHANGE_KINDS
from repro.policy.gap import inputs_from_events
from repro.policy.status import UNEXPLAINABLE

GAP_BUDGET: Final = Budget(max_turns=3, max_budget_usd=0.25, timeout_s=600)
#: Differences sent in one call; the rest stay unexplained (and so flag).
MAX_ITEMS: Final = 12


def candidates(events: Sequence[Mapping[str, Any]], view: EvidenceView) -> list[Item]:
    """The differences that flag only for want of an explanation, in rendering order."""
    found = {
        item.evidence_id
        for item in inputs_from_events(events).gap
        if item.resolution == "flagged"
        and item.status == "warn"
        and not item.contradicted_by
        and item.check != "policy_change"
        and (item.check, item.kind) not in UNEXPLAINABLE
    }
    return [item for item in view.items if item.id in found]


def explainers(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The claims a reviewer supported that describe a change, in claim order."""
    supported = {
        e["payload"]["verdict"]["claim_id"]
        for e in events
        if e["kind"] == "verdict.issued" and e["payload"]["verdict"]["verdict"] == "supported"
    }
    claims = [e["payload"]["claim"] for e in events if e["kind"] == "claim.extracted"]
    return [c for c in claims if c["id"] in supported and c["kind"] not in NO_CHANGE_KINDS]


def schema(items: Sequence[str], claims: Sequence[str]) -> dict[str, Any]:
    entry = {
        "type": "object",
        "properties": {
            "evidence_id": {"type": "string", "enum": list(items)},
            "explained_by": {"type": "array", "items": {"type": "string", "enum": list(claims)}},
            "quote": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["evidence_id", "explained_by", "quote", "reason"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"differences": {"type": "array", "items": entry}},
        "required": ["differences"],
        "additionalProperties": False,
    }


def gap_prompt(claims: Sequence[Mapping[str, Any]], items: Sequence[Item]) -> str:
    said = "\n".join(f"{c['id']} ({c['kind']}): {c['text']}" for c in claims)
    return (
        f"The supported claims that describe a change:\n{block('claims', said)}\n\n"
        f"The differences no verdict accounts for yet ({len(items)}):\n\n"
        + "\n\n".join(item.render() for item in items)
    )


def gap_request(
    claims: Sequence[Mapping[str, Any]], items: Sequence[Item], prompt: Prompt, model: str
) -> AgentRequest:
    return AgentRequest(
        role="gap",
        system_prompt=prompt.text,
        prompt=gap_prompt(claims, items),
        model=model,
        prompt_version=prompt.prompt_version,
        budget=GAP_BUDGET,
        output_schema=schema([i.id for i in items], [c["id"] for c in claims]),
        effort="high",
    )


@dataclass(frozen=True, slots=True)
class Explained:
    """What survived the checks: per claim, the differences it explains, with quotes and
    reasons; and what was dropped, with why."""

    by_claim: dict[str, list[tuple[str, str, str]]]
    dropped: list[str]


def check_mapping(
    answer: Any,
    claims: Sequence[Mapping[str, Any]],
    items: Sequence[Item],
    view: EvidenceView,
) -> Explained:
    by_claim: dict[str, list[tuple[str, str, str]]] = {}
    dropped: list[str] = []
    entries = answer.get("differences") if isinstance(answer, Mapping) else None
    if not isinstance(entries, list):
        return Explained(by_claim, ["the answer has no list of differences"])
    given = {item.id: item for item in items}
    known = {c["id"]: c for c in claims}
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        ident = entry.get("evidence_id")
        if ident not in given or ident in seen:
            dropped.append(f"{ident}: not one of the differences given, or given twice")
            continue
        seen.add(str(ident))
        item = given[str(ident)]
        quote, reason = entry.get("quote"), entry.get("reason")
        named = entry.get("explained_by")
        if not isinstance(named, list) or not named:
            continue  # unexplained, as answered
        if not isinstance(quote, str) or not quote or len(quote) > MAX_QUOTE:
            dropped.append(f"{ident}: no quote")
            continue
        if quote not in item.render():
            dropped.append(f"{ident}: the quote is not in its evidence as written")
            continue
        for claim_id in dict.fromkeys(named):
            claim = known.get(claim_id)
            if claim is None:
                dropped.append(f"{ident}: {claim_id} is not a claim that may explain it")
                continue
            targets = list(claim.get("targets") or [])
            if targets and not any(view.related(item, t) for t in targets):
                dropped.append(f"{ident}: {claim_id} is not about its files")
                continue
            why = reason.strip() if isinstance(reason, str) and reason.strip() else "explains it"
            by_claim.setdefault(claim_id, []).append((str(ident), quote, why))
    return Explained(by_claim, dropped)


def verdicts(explained: Explained, model: str) -> list[dict[str, Any]]:
    """One supporting verdict per claim, citing the differences it explains."""
    found = []
    for claim_id, entries in explained.by_claim.items():
        cited = list(dict.fromkeys(ident for ident, _, _ in entries))
        quotes = [{"evidence_id": ident, "text": quote} for ident, quote, _ in entries]
        rationale = "Explains: " + "; ".join(f"{ident}: {why}" for ident, _, why in entries)
        found.append(
            {
                "claim_id": claim_id,
                "verdict": "supported",
                "cited_evidence": cited,
                "quotes": quotes,
                "rationale": rationale[:4000],
                "model": model,
                "agreement": None,
            }
        )
    return found
