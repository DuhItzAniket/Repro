"""Bias controls for the reviewers' verdicts (G08; ARCHITECTURE §10.4, research/04 §2.3).

- **Order swap.** LLM judges favour a position: in MT-Bench, GPT-4's verdicts survived swapping
  the order of what it compared in 65 % of cases. A ``contradicted`` verdict flags the change,
  so the reviewer is asked again with the evidence and the other claims in the opposite order
  (``repro.agents.reviewer``'s ``reverse``); unless both orders give it, the verdict degrades
  to ``unverifiable`` (``degraded``). The ``agent_order_swap`` setting can ask for the second
  order on every verdict, which is how the flip rate is measured, or not at all.
- **Panel.** With ``agent_panel``, three reviewers judge each claim (their models in the
  setting's order, the second with the order reversed) and a verdict stands when two of them
  give it (``majority``); otherwise it is ``unverifiable``.
- **Judge ≠ author.** Judges favour their own generations (Panickssery et al.). A change's
  commits and PR text often name the model that wrote it, as Claude Code's
  ``Co-Authored-By: Claude …`` trailer does; when every reviewer is of that model's family,
  the card says so (``judge_is_author``). The families are read from model names only
  (``family``), never from people's names or addresses.

Every verdict records how many judgements it rests on and how many of them gave it
(``agreement``).
"""

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

#: Model-name tokens and the family (the developer of the model) each belongs to.
FAMILIES: Final[tuple[tuple[str, str], ...]] = (
    ("claude", "anthropic"),
    ("gpt", "openai"),
    ("codex", "openai"),
    ("chatgpt", "openai"),
    ("gemini", "google"),
    ("qwen", "alibaba"),
    ("llama", "meta"),
    ("deepseek", "deepseek"),
    ("mistral", "mistral"),
)
#: The lines that name a change's author: a co-author trailer, a "generated with" line.
_AUTHOR_LINE: Final = re.compile(
    r"^\s*(?:co-authored-by:|.*\bgenerated (?:with|by)\b)(?P<who>.*)$", re.IGNORECASE | re.MULTILINE
)
MAX_RATIONALE: Final = 4000


def family(model: str) -> str | None:
    """The family a model name belongs to (``openai/gpt-oss-120b``: openai), if known."""
    words = re.split(r"[^a-z0-9]+", model.lower())
    for token, name in FAMILIES:  # the token, or the token and a version (qwen3, gpt4o)
        if any(re.fullmatch(rf"{token}(?:\d[\da-z]*)?", word) for word in words):
            return name
    return None


def author_families(texts: Iterable[str]) -> set[str]:
    """The model families the texts name as the change's authors (co-author trailers and
    "generated with" lines only)."""
    found = set()
    for text in texts:
        for match in _AUTHOR_LINE.finditer(text):
            named = family(match.group("who"))
            if named is not None:
                found.add(named)
    return found


def judge_is_author(models: Sequence[str], authors: set[str]) -> str | None:
    """The family every judge shares with the change's authors, or None."""
    families = {family(model) for model in models}
    if len(families) == 1:
        (shared,) = families
        if shared is not None and shared in authors:
            return shared
    return None


def agreeing(verdict: Mapping[str, Any], runs: int, agree: int) -> dict[str, Any]:
    """``verdict`` with how many judgements it rests on and how many of them gave it."""
    return {**verdict, "agreement": {"runs": runs, "agreeing": agree}}


def degraded(first: Mapping[str, Any], why: str, runs: int, agree: int) -> dict[str, Any]:
    """``first`` kept as ``unverifiable``: its judges did not agree (``why``). It still cites
    and quotes what the first judgement did."""
    rationale = f"Not kept as {first['verdict']}: {why}. The first judgement: {first['rationale']}"
    return {
        **first,
        "verdict": "unverifiable",
        "rationale": rationale[:MAX_RATIONALE],
        "agreement": {"runs": runs, "agreeing": agree},
    }


def majority(verdicts: Sequence[Mapping[str, Any]], runs: int) -> dict[str, Any] | None:
    """The first verdict whose value at least two of ``verdicts`` give, with its agreement;
    None when no two agree."""
    counts = Counter(v["verdict"] for v in verdicts)
    for verdict in verdicts:
        if counts[verdict["verdict"]] >= 2:  # noqa: PLR2004 - two of three
            return agreeing(verdict, runs, counts[verdict["verdict"]])
    return None


def described(verdicts: Sequence[tuple[str, Mapping[str, Any] | str]]) -> str:
    """What each judge answered, for a rationale: ``m1: supported; m2: rejected (…)``."""
    return "; ".join(
        f"{model}: {answer['verdict'] if isinstance(answer, Mapping) else answer}"
        for model, answer in verdicts
    )
