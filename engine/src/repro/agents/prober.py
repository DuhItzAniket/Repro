"""The probe-writer agent: inputs for the changed functions, proposed without the claims (G07).

ARCHITECTURE §4.4. Random inputs miss what only realistic ones reach: random text is rarely a
well-formed timestamp, so a change confined to valid ones is invisible to it (E06's own
finding). The probe writer is shown each function E06 can probe (``repro.runner.probes``:
JSON-typed parameters on both sides) as it is on head, with its parameters' types and the
change to its file, and proposes concrete inputs. It is never shown the PR's text or claims,
so its probes cannot be written to confirm them.

Its proposals are data, never code: each names a function and gives its arguments as a JSON
object. ``repro.runner.probes.arranged`` keeps only those that name exactly the function's
parameters with values of their types; the rest are dropped and counted (the first of the
TestGen-LLM-style filters; research/02 §9.1). The kept ones run beside Hypothesis's inputs on
base, base again and head, where the other filters apply: a probe the two base runs disagree
on is left out, and only what differs between base and head is evidence.
"""

import ast
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from repro.agents.backend import AgentRequest, Budget
from repro.agents.prompts import Prompt
from repro.agents.sources import RepoSources, SourceError
from repro.agents.untrusted import block
from repro.runner.probes import Candidate, Spec, arranged

PROBE_BUDGET: Final = Budget(max_turns=3, max_budget_usd=0.25, timeout_s=600)
#: Functions shown in one call (the rest get Hypothesis's inputs only), and inputs kept each.
MAX_FUNCTIONS: Final = 6
MAX_INPUTS: Final = 8
MAX_SOURCE_LINES: Final = 60
MAX_DIFF_LINES: Final = 60


def type_text(spec: Spec) -> str:
    """A parameter's JSON type as Python would write it."""
    kind = spec["kind"]
    if kind == "none":
        return "None"
    if kind in ("int", "float", "str", "bool"):
        return str(kind)
    if kind == "list":
        return f"list[{type_text(spec['of'])}]"
    if kind == "dict":
        return f"dict[str, {type_text(spec['of'])}]"
    return " | ".join(type_text(member) for member in spec["of"])


def _definition(text: str | None, name: str) -> str:
    if not text:
        return "(not found)"
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "(the file does not parse)"
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            start = min([d.lineno for d in node.decorator_list] + [node.lineno])
            lines = text.split("\n")[start - 1 : node.end_lineno]
            if len(lines) > MAX_SOURCE_LINES:
                lines = [*lines[:MAX_SOURCE_LINES], f"... {len(lines) - MAX_SOURCE_LINES} more"]
            return "\n".join(lines)
    return "(not found)"


def _function(candidate: Candidate, sources: RepoSources) -> str:
    try:
        head = sources.read("head", candidate.file)
        diff = sources.diff(candidate.file)
    except SourceError:
        head, diff = None, ""
    lines = diff.rstrip("\n").split("\n") if diff else []
    if len(lines) > MAX_DIFF_LINES:
        lines = [*lines[:MAX_DIFF_LINES], f"... {len(lines) - MAX_DIFF_LINES} more lines"]
    parameters = ", ".join(f"{n}: {type_text(s)}" for n, _, s in candidate.parameters)
    return (
        f"Function {candidate.symbol}: {candidate.name}({parameters})\n"
        f"Its arguments, as the JSON text of an object: {shape(candidate)}\n"
        f"As it is after the change:\n"
        f"{block('source', _definition(head, candidate.name), path=candidate.file)}\n"
        f"What the change did to its file:\n"
        f"{block('diff', chr(10).join(lines) or '(no diff)', path=candidate.file)}"
    )


def shape(candidate: Candidate) -> str:
    """The object a proposal's arguments must be, each value of its type: ``{"text": <str>}``."""
    return "{" + ", ".join(f'"{n}": <{type_text(s)}>' for n, _, s in candidate.parameters) + "}"


def prober_prompt(found: Sequence[Candidate], sources: RepoSources) -> str:
    shown = "\n\n".join(_function(candidate, sources) for candidate in found)
    return f"The functions the change touched ({len(found)}):\n\n{shown}"


def schema(symbols: Sequence[str]) -> dict[str, Any]:
    """Strict-mode ready: each input names its function and gives its arguments as JSON text."""
    entry = {
        "type": "object",
        "properties": {
            "function": {"type": "string", "enum": list(symbols)},
            "arguments": {
                "type": "string",
                "description": "JSON text of an object with one key per parameter",
            },
            "tries": {"type": "string"},
        },
        "required": ["function", "arguments", "tries"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"inputs": {"type": "array", "items": entry}},
        "required": ["inputs"],
        "additionalProperties": False,
    }


def prober_request(
    found: Sequence[Candidate], sources: RepoSources, prompt: Prompt, model: str
) -> AgentRequest:
    shown = list(found[:MAX_FUNCTIONS])
    return AgentRequest(
        role="probe",
        system_prompt=prompt.text,
        prompt=prober_prompt(shown, sources),
        model=model,
        prompt_version=prompt.prompt_version,
        budget=PROBE_BUDGET,
        output_schema=schema([c.symbol for c in shown]),
        effort="medium",
    )


@dataclass(slots=True)
class Proposals:
    """The kept inputs, per function in ``found``'s order, and how many were dropped."""

    inputs: list[list[dict[str, Any]]]
    proposed: int = 0
    dropped: int = 0
    reasons: list[str] = field(default_factory=list)


def read_proposals(answer: Any, found: Sequence[Candidate]) -> Proposals:
    """The answer's inputs that fit their function's signature, at most ``MAX_INPUTS`` each."""
    shown = found[:MAX_FUNCTIONS]
    by_symbol = {candidate.symbol: number for number, candidate in enumerate(shown)}
    kept = Proposals([[] for _ in found])
    entries = answer.get("inputs") if isinstance(answer, dict) else None
    for entry in entries if isinstance(entries, list) else []:
        kept.proposed += 1
        name = entry.get("function") if isinstance(entry, dict) else None
        number = by_symbol.get(name) if isinstance(name, str) else None
        if number is None:
            kept.dropped += 1
            kept.reasons.append("names no function that was shown")
            continue
        try:
            named = json.loads(str(entry.get("arguments", "")))
        except (ValueError, RecursionError):  # not JSON, or nested past the parser's depth
            named = None
        given = arranged(found[number], named)
        if given is None:
            kept.dropped += 1
            kept.reasons.append(f"{found[number].symbol}: arguments do not fit its signature")
            continue
        if len(kept.inputs[number]) < MAX_INPUTS:
            kept.inputs[number].append(given)
    return kept
