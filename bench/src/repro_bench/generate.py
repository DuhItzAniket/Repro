"""Agent patches for S2's tasks: a two-call localize-and-repair scaffold (J05).

The protocol wants S2's patches from at least two scaffolds and two model families (§3). The
scaffold here is the smallest that makes a real patch within Groq's free tier, where a request
may not exceed 8,000 tokens a minute with its answer (J03). It is Agentless's shape reduced to
two calls [Xia et al., "Agentless: Demystifying LLM-based Software Engineering Agents",
arXiv 2407.01489]:

1. **Localize** (``repair_localize/1``): the issue and the repository's Python files, ranked by
   the words they share with the issue. The model names up to three files, or functions in them.
2. **Repair** (``repair_edit/1``): the issue and that code. The code is a whole file when it is
   small, else its outline and the definitions named. The model answers with a short summary and
   search/replace blocks (``repro_bench.edits``). The diff is made from them, never written by
   the model.

Answers are plain text: Qwen's schema-constrained JSON on Groq came back malformed (J05). The
summary is the agent's claim (J01). Every request, answer and their tokens are kept as the
patch's trajectory.

The second scaffold is mini-SWE-agent v2.4.6 (MIT), a bash-only agent loop. Its conversation
outgrows one 8,000-token request within a few steps, so it is specified, not run, under the
free tier (J05 record).

    uv run python -m repro_bench.generate --instances <jsonl> --mirrors <dir> --out <dir>
        --model openai/gpt-oss-120b [--mode record|replay --cassettes <dir>]
"""

import argparse
import ast
import asyncio
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final

from repro.agents import CassetteBackend, LLMBackend
from repro.agents.backend import AgentRequest, Budget
from repro.agents.openai_compat import Endpoint, OpenAICompatibleBackend
from repro.agents.prompts import load_prompt
from repro.agents.untrusted import block
from repro.gitops import Git
from repro.gitops.snapshot import regular_files
from repro_bench import edits, swe

PROMPTS: Final = Path(__file__).parent / "prompts"
SCAFFOLD: Final = "repair2"
BUDGET: Final = Budget(max_turns=2, max_budget_usd=0.1, timeout_s=900.0)
#: What fits one request beside its 3,000-token answer on the free tier (J03), in characters.
ISSUE_MAX: Final = 4_000
LIST_MAX: Final = 250
CODE_MAX: Final = 10_000
FILE_WHOLE_MAX: Final = 6_000
_WORD: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")


@dataclass
class Trajectory:
    steps: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self, request: AgentRequest, answer: str, tokens: tuple[int, int], outcome: str
    ) -> None:
        self.steps.append(
            {
                "prompt_version": request.prompt_version,
                "prompt": request.prompt,
                "answer": answer,
                "tokens": list(tokens),
                "outcome": outcome,
            }
        )


def ranked_files(files: Sequence[str], issue: str) -> list[str]:
    """The repository's Python files that are not tests, most words shared with the issue first."""
    words = {word.lower() for word in _WORD.findall(issue)}

    def shared(path: str) -> int:
        return sum(1 for part in re.split(r"[/_.]", path.lower()) if part in words)

    code = [f for f in files if f.endswith(".py") and "test" not in f.lower()]
    return sorted(code, key=lambda f: (-shared(f), f))


def located(answer: str, files: Sequence[str]) -> list[tuple[str, str | None]]:
    """The files (and names) the model chose, only those that exist, three at most."""
    known = set(files)
    found: list[tuple[str, str | None]] = []
    for line in answer.splitlines():
        path, _, name = line.strip().strip("`*- ").partition("::")
        path = path.strip().lstrip("./")
        if path in known and all(path != p or name != n for p, n in found):
            found.append((path, name.strip() or None))
    return found[:3]


def context(text: str, names: Sequence[str]) -> str:
    """A file as the model sees it: whole when small, else its outline and the definitions named
    (by ``ast``; the start of the file when none can be found)."""
    if len(text) <= FILE_WHOLE_MAX:
        return text
    lines = text.splitlines(keepends=True)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "".join(lines[:150])
    outline, shown = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            outline.append(f"line {node.lineno}: {lines[node.lineno - 1].strip()}")
            if node.name in names and node.end_lineno is not None:
                shown.append("".join(lines[node.lineno - 1 : node.end_lineno]))
    body = "\n".join(shown) if shown else "".join(lines[:120])
    return "(outline)\n" + "\n".join(outline[:80]) + "\n\n(code)\n" + body


async def _ask(
    backend: LLMBackend, name: str, body: str, model: str, trajectory: Trajectory
) -> str:
    prompt = load_prompt(name, PROMPTS)
    request = AgentRequest(
        role="build",
        system_prompt=prompt.text,
        prompt=body,
        model=model,
        prompt_version=prompt.prompt_version,
        budget=BUDGET,
        effort="medium",
    )
    result = await backend.run(request)
    tokens = (result.usage.input_tokens, result.usage.output_tokens)
    trajectory.add(request, result.text, tokens, result.outcome)
    if result.outcome != "ok":
        raise edits.EditError(f"{name}: {result.outcome} {result.detail}".strip())
    return result.text


@dataclass(frozen=True)
class Made:
    instance_id: str
    model: str
    patch: str | None
    summary: str
    problem: str
    trajectory: Trajectory


async def repair(record: Mapping[str, Any], git: Git, backend: LLMBackend, model: str) -> Made:
    base = str(record["base_commit"])
    issue = str(record["problem_statement"])[:ISSUE_MAX]
    trajectory = Trajectory()
    files = ranked_files(sorted(regular_files(git, base)), issue)
    try:
        answer = await _ask(
            backend,
            "repair_localize",
            f"The issue:\n{block('issue', issue)}\n\nThe repository's Python files "
            f"({len(files)}, the first {min(len(files), LIST_MAX)} shown):\n"
            + block("files", "\n".join(files[:LIST_MAX])),
            model,
            trajectory,
        )
        chosen = located(answer, files)
        if not chosen:
            raise edits.EditError("the model named no file of the repository")
        shown, used = [], 0
        for path in dict.fromkeys(path for path, _ in chosen):
            text = edits.read(git, base, path) or ""
            names = [name for p, name in chosen if p == path and name]
            part = context(text, names)[: max(0, CODE_MAX - used)]
            used += len(part)
            shown.append(block("code", part, path=path))
        answer = await _ask(
            backend,
            "repair_edit",
            f"The issue:\n{block('issue', issue)}\n\nThe code:\n" + "\n\n".join(shown),
            model,
            trajectory,
        )
        summary = answer.split("FILE:", 1)[0].strip()
        made = edits.parse_blocks(answer)
        if not made:
            raise edits.EditError("the answer has no search/replace block")
        patch = edits.diff(git, base, edits.apply(git, base, made))
        return Made(str(record["instance_id"]), model, patch, summary, "", trajectory)
    except edits.EditError as exc:
        return Made(str(record["instance_id"]), model, None, "", str(exc), trajectory)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--instances", type=Path, required=True)
    parser.add_argument("--mirrors", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--mode", choices=("record", "replay"), default="replay")
    parser.add_argument("--cassettes", type=Path, default=Path("bench/cassettes"))
    args = parser.parse_args(argv)
    if args.mode == "replay":
        backend: LLMBackend = CassetteBackend(args.cassettes, "replay")
    else:
        backend = CassetteBackend(
            args.cassettes, "record", OpenAICompatibleBackend(Endpoint.groq())
        )
    trajectories = args.out / "trajectories"
    trajectories.mkdir(parents=True, exist_ok=True)
    name = f"{SCAFFOLD}:{args.model}"
    with (args.out / "predictions.jsonl").open("a", encoding="utf-8") as out:
        for record in swe.read_jsonl(args.instances):
            owner, _, repo = str(record["repo"]).partition("/")
            git = swe.fetch_base(
                args.mirrors / owner / f"{repo}.git",
                str(record["repo"]),
                str(record["base_commit"]),
            )
            made = asyncio.run(repair(record, git, backend, args.model))
            path = trajectories / f"{made.instance_id}__{args.model.replace('/', '_')}.json"
            path.write_bytes(json.dumps(asdict(made.trajectory), indent=1).encode("utf-8"))
            if made.patch is None:
                sys.stdout.write(f"{made.instance_id} ({name}): no patch: {made.problem}\n")
                continue
            out.write(
                json.dumps(
                    {
                        "instance_id": made.instance_id,
                        "model_name_or_path": name,
                        "model_patch": made.patch,
                        "summary": made.summary,
                        "trajectory": path.name,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
            out.flush()
            sys.stdout.write(
                f"{made.instance_id} ({name}): a patch of {made.patch.count(chr(10))} lines\n"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
