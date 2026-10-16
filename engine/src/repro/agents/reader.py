"""The reader agent: a pull request's own words as atomic, checkable claims (G04).

ARCHITECTURE §10.1. The reader is given the PR's text (its title, its description, or the
commit messages when there is no description), each part in an ``untrusted_content`` block and
capped (research/04 A.5: PR text fed to agents is capped), and the list of files the change
touches. It answers in a schema made for the call: each claim's text, kind, source and the
files it is about, the files an enum of the changed files, so it cannot name another.

The answer is checked again here, whatever the schema promised: a claim with empty text or
an unknown kind is dropped, overlong text is cut, a file outside the change is dropped, a
source the PR did not have becomes its first part's; the same claim twice is kept once; at
most ``MAX_CLAIMS`` are kept, in the reader's order; and each gets its ID, ``C1``, ``C2``...
Claims carry no evidence and decide nothing: G05 judges each one.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from repro.agents.backend import AgentRequest, Budget
from repro.agents.prompts import Prompt
from repro.agents.untrusted import block

KINDS: Final = ("fix", "feature", "refactor", "no-change", "perf", "deps", "test", "docs")
SOURCES: Final = ("title", "description", "commit")
MAX_CLAIMS: Final = 8
MAX_CLAIM_TEXT: Final = 500
#: Characters of PR text, all parts together, the reader is given.
MAX_PR_TEXT: Final = 4000
#: Changed files listed, at most.
MAX_FILES: Final = 60
READER_BUDGET: Final = Budget(max_turns=4, max_budget_usd=0.25, timeout_s=300)

Source = Literal["title", "description", "commit"]


@dataclass(frozen=True, slots=True)
class PrText:
    """What the pull request says: each part with where it comes from."""

    parts: tuple[tuple[Source, str], ...]

    @classmethod
    def of(cls, *, title: str | None, description: str | None, commits: Sequence[str]) -> "PrText":
        """The title and description when given; the commit messages otherwise."""
        parts: list[tuple[Source, str]] = []
        if title and title.strip():
            parts.append(("title", title.strip()))
        if description and description.strip():
            parts.append(("description", description.strip()))
        if not parts:
            parts.extend(("commit", c.strip()) for c in commits if c.strip())
        return cls(tuple(parts))

    def capped(self) -> tuple[tuple[Source, str], ...]:
        """The parts within ``MAX_PR_TEXT`` characters in all, cut where the cap falls."""
        left, kept = MAX_PR_TEXT, []
        for source, text in self.parts:
            if left <= 0:
                break
            piece = (
                text
                if len(text) <= left
                else f"{text[:left]}\n[... cut: {len(text) - left} more characters]"
            )
            kept.append((source, piece))
            left -= len(text)
        return tuple(kept)


def schema(files: Sequence[str]) -> dict[str, Any]:
    """The answer's schema: strict-mode ready (every property required, no others), draft-07,
    ``$ref``-free; files an enum of the changed files when there are any."""
    file_item: dict[str, Any] = {"type": "string"}
    if files:
        file_item["enum"] = list(files)
    claim = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "kind": {"type": "string", "enum": list(KINDS)},
            "source": {"type": "string", "enum": list(SOURCES)},
            "files": {"type": "array", "items": file_item},
        },
        "required": ["text", "kind", "source", "files"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"claims": {"type": "array", "items": claim}},
        "required": ["claims"],
        "additionalProperties": False,
    }


def reader_prompt(pr: PrText, files: Sequence[str]) -> str:
    """The reader's input: the changed files, then the PR's text, each part delimited."""
    listed = list(files[:MAX_FILES])
    more = f"\n- ... and {len(files) - MAX_FILES} more" if len(files) > MAX_FILES else ""
    changed = "\n".join(f"- {f}" for f in listed) + more if listed else "(none listed)"
    parts = pr.capped()
    text = "\n".join(block("pr", body, source=source) for source, body in parts)
    return (
        f"The files this change touches:\n{changed}\n\n"
        f"The pull request's text ({', '.join(s for s, _ in parts) or 'none'}):\n"
        f"{text or '(the pull request has no text)'}"
    )


def reader_request(
    pr: PrText, files: Sequence[str], prompt: Prompt, model: str, budget: Budget = READER_BUDGET
) -> AgentRequest:
    return AgentRequest(
        role="read",
        system_prompt=prompt.text,
        prompt=reader_prompt(pr, files),
        model=model,
        prompt_version=prompt.prompt_version,
        budget=budget,
        output_schema=schema(files),
        effort="low",
    )


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def read_claims(answer: Any, files: Sequence[str], sources: Sequence[str]) -> list[dict[str, Any]]:
    """The answer's claims, checked: ``claim.extracted`` payloads' ``claim``, in order."""
    found = answer.get("claims") if isinstance(answer, Mapping) else None
    if not isinstance(found, list):
        return []
    changed, given = set(files), set(sources)
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in found:
        if not isinstance(item, Mapping):
            continue
        text = _normal(str(item.get("text", "")))[:MAX_CLAIM_TEXT]
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        kind = item.get("kind")
        if kind not in KINDS:  # not a kind the schema allows: no guess at what was meant
            continue
        source = item.get("source")
        if source not in given:  # a source the PR did not have: its first part's
            source = sources[0] if sources else "description"
        targets = [
            {"file": f}
            for f in dict.fromkeys(item.get("files") or [])
            if isinstance(f, str) and f in changed
        ]
        claims.append(
            {
                "id": f"C{len(claims) + 1}",
                "text": text,
                "kind": kind,
                "targets": targets,
                "source": source,
            }
        )
        if len(claims) == MAX_CLAIMS:
            break
    return claims
