"""The memorisation probe: does the reviewer model already know a task's fix? (J04)

A reviewer that remembers a task's gold patch can recognise a wrong agent patch by comparing it
with that memory, not by reasoning from evidence. Contamination of this kind would favour the
LLM-only baselines more than Repro, but would inflate both (research/06 §7). The probe follows
"The SWE-Bench Illusion" [Liang, Garg, Zilouchian Moghaddam, arXiv 2506.12286]: the model gets
the repository's name and the issue alone, never the code, and is asked
- which files a fix would change: scored on the gold patch's Python files (a changelog
  entry is no evidence of memory; all its files when it has no Python file), by whether it
  names any of them (``file_hit``) and the share it names (``file_recall``);
- what code the fix would add: scored by the share of the 5-grams those files gain that it
  reproduces (``ngram5``), on tokens of identifiers, numbers and single symbols.

The prompt is locked (``memorisation/1``). The study stratifies its results by these scores
and compares S1 (contaminated) with S2 (fresh) (protocol §3, §9). A call that fails keeps its
``outcome`` and scores nothing: it is left out of any summary, never counted as no memory.

    uv run python -m repro_bench.memo --instances <jsonl> --out <jsonl>
        [--mode record|replay --cassettes <dir>]
"""

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from repro.agents import CassetteBackend, LLMBackend
from repro.agents.backend import AgentRequest, Budget
from repro.agents.openai_compat import Endpoint, OpenAICompatibleBackend
from repro.agents.prompts import load_prompt
from repro.agents.setup import GROQ_MODEL
from repro.agents.untrusted import block
from repro_bench.swe import read_jsonl
from repro_bench.truth import changed_files

PROMPTS: Final = Path(__file__).parent / "prompts"
BUDGET: Final = Budget(max_turns=2, max_budget_usd=0.05, timeout_s=300.0)
SCHEMA: Final = {
    "type": "object",
    "properties": {
        "files": {"type": "array", "items": {"type": "string"}},
        "code": {"type": "string"},
    },
    "required": ["files", "code"],
    "additionalProperties": False,
}
_TOKEN: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+|[^\sA-Za-z0-9_]")
N: Final = 5


def request(repo: str, problem_statement: str, model: str) -> AgentRequest:
    prompt = load_prompt("memorisation", PROMPTS)
    body = f"The repository: {repo}\n\nThe issue:\n{block('issue', problem_statement)}"
    return AgentRequest(
        role="read",
        system_prompt=prompt.text,
        prompt=body,
        model=model,
        prompt_version=prompt.prompt_version,
        budget=BUDGET,
        output_schema=SCHEMA,
        effort="low",
    )


def added_code(diff: str, files: Sequence[str] | None = None) -> str:
    """The lines a diff adds, without their ``+``; only in ``files`` when given."""
    kept: list[str] = []
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            current = line.rsplit(" b/", 1)[-1]
        elif (
            line.startswith("+")
            and not line.startswith("+++")
            and (files is None or current in files)
        ):
            kept.append(line[1:])
    return "\n".join(kept)


def grams(code: str, n: int = N) -> set[tuple[str, ...]]:
    tokens = _TOKEN.findall(code)
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


@dataclass(frozen=True)
class Score:
    instance_id: str
    file_hit: bool  # one of the gold patch's code files is among those named
    file_recall: float  # the share of the gold patch's files named
    ngram5: float  # the share of the gold patch's added 5-grams reproduced
    gold_files: tuple[str, ...]
    named: tuple[str, ...]
    tokens: tuple[int, int]
    outcome: str


def score(record: Mapping[str, Any], answer: Any, tokens: tuple[int, int], outcome: str) -> Score:
    changed = changed_files(str(record["patch"]))
    gold = tuple(f for f in changed if f.endswith(".py")) or changed
    named = tuple(str(f).strip().lstrip("./") for f in (answer or {}).get("files", []))[:3]
    hits = [f for f in gold if f in named]
    wanted = grams(added_code(str(record["patch"]), gold))
    found = grams(str((answer or {}).get("code", "")))
    return Score(
        str(record["instance_id"]),
        bool(hits),
        len(hits) / len(gold) if gold else 0.0,
        len(wanted & found) / len(wanted) if wanted else 0.0,
        gold,
        named,
        tokens,
        outcome,
    )


async def probe(record: Mapping[str, Any], backend: LLMBackend, model: str) -> Score:
    result = await backend.run(
        request(str(record["repo"]), str(record["problem_statement"]), model)
    )
    tokens = (result.usage.input_tokens, result.usage.output_tokens)
    answer = result.structured if result.outcome == "ok" else None
    return score(record, answer, tokens, result.outcome)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--instances", type=Path, required=True, help="SWE-format JSONL")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=("record", "replay"), default="replay")
    parser.add_argument("--cassettes", type=Path, default=Path("bench/cassettes"))
    parser.add_argument("--model", default=GROQ_MODEL)
    args = parser.parse_args(argv)
    if args.mode == "replay":
        backend: LLMBackend = CassetteBackend(args.cassettes, "replay")
    else:
        backend = CassetteBackend(
            args.cassettes, "record", OpenAICompatibleBackend(Endpoint.groq())
        )
    with args.out.open("a", encoding="utf-8") as out:
        for record in read_jsonl(args.instances):
            found = asyncio.run(probe(record, backend, args.model))
            out.write(json.dumps(asdict(found), sort_keys=True) + "\n")
            out.flush()
            sys.stdout.write(
                f"{found.instance_id}: files {found.file_recall:.2f}, "
                f"5-grams {found.ngram5:.2f} ({found.outcome})\n"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
