"""The QA agent: the verdicts read together, for those that cannot all hold (G08).

ARCHITECTURE §10.1. Each reviewer judges one claim, seeing the other claims' text but not their
verdicts. Once the review and the gap reviewer are done, the QA agent reads every claim with
its verdicts, their rationales and a line about each piece of evidence they cite. It names the
verdicts that cannot hold together: two supported claims that say opposite things about the
same behaviour, or a supported claim that its own cited evidence and another verdict's
together refute.

Its answer is checked: an inconsistency names at least two claims it was given that have
verdicts, at least one of them supported, with a reason. What survives withholds VERIFIED
and nothing more. Each supported claim it names gets an ``unverifiable`` verdict that cites
what its own verdict cited and gives QA's reason, so the status rules leave the claim
unsupported. QA never makes a claim contradicted or a change FLAGGED: one model's reading of
other models' verdicts is not evidence (ground rule 1).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from repro.agents.backend import AgentRequest, Budget
from repro.agents.evidence import EvidenceView
from repro.agents.prompts import Prompt
from repro.agents.untrusted import block

QA_BUDGET: Final = Budget(max_turns=3, max_budget_usd=0.25, timeout_s=600)
MAX_REASON: Final = 1000
MAX_RATIONALE: Final = 4000


def judged(
    events: Sequence[Mapping[str, Any]],
) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Each claim with the verdicts issued on it, in claim order; claims without one left out."""
    claims = [e["payload"]["claim"] for e in events if e["kind"] == "claim.extracted"]
    verdicts: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if event["kind"] == "verdict.issued":
            verdict = event["payload"]["verdict"]
            verdicts.setdefault(verdict["claim_id"], []).append(verdict)
    return [(claim, verdicts[claim["id"]]) for claim in claims if claim["id"] in verdicts]


def worth_checking(found: Sequence[tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]]]) -> bool:
    """Whether there is anything to cross-check: two judged claims, one of them supported."""
    supported = any(v["verdict"] == "supported" for _, verdicts in found for v in verdicts)
    return len(found) >= 2 and supported  # noqa: PLR2004 - a pair


def schema(claims: Sequence[str]) -> dict[str, Any]:
    entry = {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "minItems": 2,
                "items": {"type": "string", "enum": list(claims)},
            },
            "reason": {"type": "string"},
        },
        "required": ["claims", "reason"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"inconsistencies": {"type": "array", "items": entry}},
        "required": ["inconsistencies"],
        "additionalProperties": False,
    }


def qa_prompt(
    found: Sequence[tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]]], view: EvidenceView
) -> str:
    said, cited = [], []
    for claim, verdicts in found:
        said.append(f"{claim['id']} ({claim['kind']}): {claim['text']}")
        for verdict in verdicts:
            ids = ", ".join(verdict["cited_evidence"])
            said.append(f"  {verdict['verdict']}, citing {ids}: {verdict['rationale']}")
            cited += [i for i in verdict["cited_evidence"] if i not in cited]
    lines = [view.by_id[i].line() for i in cited if i in view.by_id]
    return (
        f"The claims and their verdicts:\n{block('verdicts', chr(10).join(said))}\n\n"
        f"The evidence they cite:\n{block('evidence', chr(10).join(lines) or '(none)')}"
    )


def qa_request(
    found: Sequence[tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]]],
    view: EvidenceView,
    prompt: Prompt,
    model: str,
) -> AgentRequest:
    return AgentRequest(
        role="qa",
        system_prompt=prompt.text,
        prompt=qa_prompt(found, view),
        model=model,
        prompt_version=prompt.prompt_version,
        budget=QA_BUDGET,
        output_schema=schema([claim["id"] for claim, _ in found]),
        effort="high",
    )


@dataclass(frozen=True, slots=True)
class Checked:
    """The inconsistencies that passed the checks, as (claims, reason), and what was dropped."""

    kept: list[tuple[list[str], str]]
    dropped: list[str]


def check_answer(
    answer: Any, found: Sequence[tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]]]
) -> Checked:
    entries = answer.get("inconsistencies") if isinstance(answer, Mapping) else None
    if not isinstance(entries, list):
        return Checked([], ["the answer has no list of inconsistencies"])
    verdicts = {claim["id"]: [v["verdict"] for v in given] for claim, given in found}
    kept: list[tuple[list[str], str]] = []
    dropped: list[str] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        named = entry.get("claims")
        reason = entry.get("reason")
        ids = list(dict.fromkeys(named)) if isinstance(named, list) else []
        if len(ids) < 2 or any(i not in verdicts for i in ids):  # noqa: PLR2004 - a pair
            dropped.append(f"{named}: not two or more of the judged claims")
            continue
        if not any("supported" in verdicts[i] for i in ids):
            dropped.append(f"{', '.join(ids)}: none of them is supported")
            continue
        if not isinstance(reason, str) or not reason.strip():
            dropped.append(f"{', '.join(ids)}: no reason")
            continue
        kept.append((ids, reason.strip()[:MAX_REASON]))
    return Checked(kept, dropped)


def withheld(
    checked: Checked,
    found: Sequence[tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]]],
    model: str,
) -> list[dict[str, Any]]:
    """For each supported claim an inconsistency names, an ``unverifiable`` verdict citing what
    its supporting verdict cited, with QA's reason."""
    supporting = {
        claim["id"]: next(v for v in given if v["verdict"] == "supported")
        for claim, given in found
        if any(v["verdict"] == "supported" for v in given)
    }
    reasons: dict[str, list[str]] = {}
    for ids, reason in checked.kept:
        for claim_id in ids:
            if claim_id in supporting:
                others = ", ".join(i for i in ids if i != claim_id)
                reasons.setdefault(claim_id, []).append(f"with {others}: {reason}")
    return [
        {
            "claim_id": claim_id,
            "verdict": "unverifiable",
            "cited_evidence": list(supporting[claim_id]["cited_evidence"]),
            "quotes": [],
            "rationale": f"QA: its verdict cannot hold together {'; '.join(why)}"[:MAX_RATIONALE],
            "model": model,
            "agreement": None,
        }
        for claim_id, why in reasons.items()
    ]
