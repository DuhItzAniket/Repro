"""The reviewer agents: one per claim, judged against the run's evidence (G05).

ARCHITECTURE §10.1, §10.3. A reviewer is given its claim (in an untrusted block: claims are
the PR's words), the evidence about the claim's files in full (``repro.agents.evidence``: the
text quotes are checked against), and the diff of those files, so that it can usually answer
at once; G03's tools are there for anything more. Its answer has a schema made for its claim:
the verdict, the cited evidence (``minItems: 1``, each an enum of the claim's evidence IDs),
quotes and a rationale; ``repro.agents.validate`` then checks it whatever the schema promised.
It also sees the PR's other claims: a claim that "nothing else" changes is about the differences
they do not describe.

Evidence is about a claim when it concerns the claim's files (G03's relevance rule); a claim
that names no file is about the whole change. A claim with no such evidence is not sent to a
reviewer: nothing could support it.

``reverse`` gives the same request with the evidence, the other claims and the evidence-ID enum
in the opposite order: G08's order-swap pass, against position bias (ARCHITECTURE §10.4).
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final

from repro.agents.backend import AgentRequest, Budget, ReproTool
from repro.agents.evidence import EvidenceView, Item
from repro.agents.prompts import Prompt
from repro.agents.sources import RepoSources, SourceError
from repro.agents.untrusted import block
from repro.agents.validate import VERDICTS

REVIEW_BUDGET: Final = Budget(max_turns=4, max_budget_usd=0.25, timeout_s=600)
#: Evidence items given in full; more are listed for the tools.
MAX_INLINE_ITEMS: Final = 10
#: Diff lines given per file, and files given.
MAX_DIFF_LINES: Final = 60
MAX_DIFF_FILES: Final = 3


def relevant(view: EvidenceView, claim: Mapping[str, Any]) -> list[Item]:
    """The evidence about the claim's files, or all of it for a claim that names none."""
    return view.relevant(list(claim.get("targets") or []))


def schema(ids: Sequence[str]) -> dict[str, Any]:
    """The verdict's schema for one claim: strict-mode ready, draft-07, ``$ref``-free."""
    evidence = {"type": "string", "enum": list(ids)}
    quote = {
        "type": "object",
        "properties": {"evidence_id": evidence, "text": {"type": "string"}},
        "required": ["evidence_id", "text"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": list(VERDICTS)},
            "cited_evidence": {"type": "array", "minItems": 1, "items": evidence},
            "quotes": {"type": "array", "items": quote},
            "rationale": {"type": "string"},
        },
        "required": ["verdict", "cited_evidence", "quotes", "rationale"],
        "additionalProperties": False,
    }


def _diffs(claim: Mapping[str, Any], sources: RepoSources) -> str:
    files = [t["file"] for t in claim.get("targets") or [] if "file" in t][:MAX_DIFF_FILES]
    shown = []
    for path in files:
        try:
            text = sources.diff(path)
        except SourceError:
            continue
        lines = text.rstrip("\n").split("\n") if text else []
        if len(lines) > MAX_DIFF_LINES:
            lines = [*lines[:MAX_DIFF_LINES], f"... {len(lines) - MAX_DIFF_LINES} more lines"]
        shown.append(block("diff", "\n".join(lines) or "(no change)", path=path))
    return "\n".join(shown) if shown else "(the claim names no file; get_diff shows any file)"


def _others(claim: Mapping[str, Any], claims: Sequence[Mapping[str, Any]]) -> str:
    said = [f"{c['id']} ({c['kind']}): {c['text']}" for c in claims if c["id"] != claim["id"]]
    return block("claims", "\n".join(said)) if said else "(none)"


def reviewer_prompt(
    claim: Mapping[str, Any],
    items: Sequence[Item],
    sources: RepoSources,
    claims: Sequence[Mapping[str, Any]] = (),
    feedback: str = "",
) -> str:
    """The reviewer's prompt, the evidence and the other claims in the order given."""
    inline = items[:MAX_INLINE_ITEMS]
    more = len(items) - len(inline)
    listed = (
        f"\n\n{more} more items about it: list_evidence and get_evidence show them."
        if more > 0
        else ""
    )
    said = f"{claim['id']} ({claim['kind']}): {claim['text']}"
    again = f"\n\nYour previous answer was refused: {feedback}. Answer again." if feedback else ""
    return (
        f"The claim to judge:\n{block('claim', said)}\n\n"
        f"The pull request's other claims:\n{_others(claim, claims)}\n\n"
        f"The evidence about it ({len(items)} items; cite them by ID):\n\n"
        + "\n\n".join(item.render() for item in inline)
        + listed
        + f"\n\nWhat the change edits in the claim's files:\n{_diffs(claim, sources)}"
        + again
    )


def reviewer_request(
    claim: Mapping[str, Any],
    items: Sequence[Item],
    sources: RepoSources,
    *,
    tools: Sequence[ReproTool],
    prompt: Prompt,
    model: str,
    claims: Sequence[Mapping[str, Any]] = (),
    feedback: str = "",
    reverse: bool = False,
) -> AgentRequest:
    """One reviewer's call; ``reverse``: everything listed in the opposite order (G08)."""
    if reverse:  # the same items given in full, in the opposite order
        items = [*items[:MAX_INLINE_ITEMS][::-1], *items[MAX_INLINE_ITEMS:]]
        claims = claims[::-1]
    return AgentRequest(
        role="review",
        system_prompt=prompt.text,
        prompt=reviewer_prompt(claim, items, sources, claims, feedback),
        model=model,
        prompt_version=prompt.prompt_version,
        budget=REVIEW_BUDGET,
        tools=tuple(tools),
        output_schema=schema([item.id for item in items]),
        effort="high",
    )
