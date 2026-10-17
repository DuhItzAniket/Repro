"""Seeded plausible-but-wrong patches for the development set S0 (J04).

The protocol's S0 (``docs/paper/EVALUATION_PROTOCOL.md`` §3) needs patches that look like fixes
and are not, to shake out the pipeline: research/06 §4 suggests LM-Modify-style seeding, kept
only when the patch passes the tests. S0 is for debugging and tuning and is never reported.

A model gets the issue and the gold patch, and the defect class to introduce (prompt
``seed/1``). It answers with edits to the files as the gold patch leaves them: an exact
snippet and its replacement. Each edit must match its file exactly once. The seeded patch is
then the diff from base to those files, written here with ``difflib``, never by the model.
Then ``filter`` keeps a seed only when tier A finds it plausible: it resolves the task's
hidden tests and keeps the full suite. Those are the seeds a CI-only check cannot catch.

    uv run python -m repro_bench.seed --instances <jsonl> --mirrors <dir> --out <jsonl>
        --per-task 3 [--mode record|replay --cassettes <dir>]
"""

import argparse
import asyncio
import difflib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from repro.agents import CassetteBackend, LLMBackend
from repro.agents.backend import AgentRequest, Budget
from repro.agents.openai_compat import Endpoint, OpenAICompatibleBackend
from repro.agents.prompts import load_prompt
from repro.agents.setup import GROQ_MODEL
from repro.agents.untrusted import block
from repro.gitops import Git, GitError
from repro_bench import swe, truth

PROMPTS: Final = Path(__file__).parent / "prompts"
DEFECTS: Final = ("incomplete_fix", "wrong_behaviour", "regression", "edge_case")
BUDGET: Final = Budget(max_turns=2, max_budget_usd=0.1, timeout_s=600.0)
SCHEMA: Final = {
    "type": "object",
    "properties": {
        "what_is_wrong": {"type": "string"},
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "find": {"type": "string"},
                    "replace": {"type": "string"},
                },
                "required": ["path", "find", "replace"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["what_is_wrong", "edits"],
    "additionalProperties": False,
}


class SeedError(Exception):
    """A seed that cannot be made into a patch; the message says why."""


def request(problem_statement: str, gold: str, defect: str, model: str) -> AgentRequest:
    prompt = load_prompt("seed", PROMPTS)
    body = (
        f"The defect to introduce: {defect}\n\nThe issue:\n{block('issue', problem_statement)}\n\n"
        f"The correct fix:\n{block('diff', gold)}"
    )
    return AgentRequest(
        role="probe",
        system_prompt=prompt.text,
        prompt=body,
        model=model,
        prompt_version=prompt.prompt_version,
        budget=BUDGET,
        output_schema=SCHEMA,
        effort="medium",
    )


def _text(git: Git, commit: str, path: str) -> str | None:
    try:
        return git.run("show", f"{commit}:{path}").decode("utf-8")
    except GitError:
        return None


def seeded_patch(git: Git, base: str, gold_head: str, edits: Sequence[Mapping[str, Any]]) -> str:
    """The diff from ``base`` to the gold patch's files with ``edits`` applied (raises
    ``SeedError`` when an edit does not match its file exactly once)."""
    after: dict[str, str] = {}
    for edit in edits:
        path = str(edit["path"]).strip().lstrip("./")
        text = after.get(path) if path in after else _text(git, gold_head, path)
        if text is None:
            raise SeedError(f"{path} is not a file the fix leaves")
        find, replace = str(edit["find"]), str(edit["replace"])
        if not find or text.count(find) != 1:
            raise SeedError(
                f"an edit's snippet occurs {text.count(find) if find else 0} times in {path}"
            )
        after[path] = text.replace(find, replace, 1)
    gold_files = git.run("diff", "--name-only", base, gold_head).decode().split()
    diff = []
    for path in sorted(set(gold_files) | set(after)):
        old = _text(git, base, path) or ""
        new = after.get(path, _text(git, gold_head, path) or "")
        lines = list(
            difflib.unified_diff(
                old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}"
            )
        )
        if lines:
            if not lines[-1].endswith("\n"):
                lines[-1] += "\n\\ No newline at end of file\n"
            diff += [f"diff --git a/{path} b/{path}\n", *lines]
    if not diff:
        raise SeedError("the edits undo the fix entirely")
    return "".join(diff)


@dataclass(frozen=True)
class Seed:
    instance_id: str
    defect: str
    what_is_wrong: str
    patch: str
    tier_a: str = ""  # PLAUSIBLE when kept


async def make(
    record: Mapping[str, Any], git: Git, defect: str, backend: LLMBackend, model: str
) -> Seed:
    gold = str(record["patch"])
    head = swe.head_commit(
        git, swe.Sealed(str(record["repo"]), str(record["base_commit"]), gold, "")
    )
    result = await backend.run(request(str(record["problem_statement"]), gold, defect, model))
    answer = result.structured if result.outcome == "ok" else None
    if not isinstance(answer, Mapping):
        raise SeedError(f"no seed was written: {result.outcome} {result.detail}".strip())
    patch = seeded_patch(git, str(record["base_commit"]), head, answer.get("edits", []))
    return Seed(str(record["instance_id"]), defect, str(answer.get("what_is_wrong", "")), patch)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--instances", type=Path, required=True)
    parser.add_argument("--mirrors", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="predictions JSONL, kept seeds")
    parser.add_argument("--per-task", type=int, default=len(DEFECTS))
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
    kept = tried = 0
    with args.out.open("a", encoding="utf-8") as out:
        for record in swe.read_jsonl(args.instances):
            owner, _, name = str(record["repo"]).partition("/")
            git = swe.fetch_base(
                args.mirrors / owner / f"{name}.git",
                str(record["repo"]),
                str(record["base_commit"]),
            )
            oracle = truth.Oracle.from_record(record)
            gold_full = None
            for defect in DEFECTS[: args.per_task]:
                tried += 1
                try:
                    seed = asyncio.run(make(record, git, defect, backend, args.model))
                    verdict, gold_full = truth.tier_a(oracle, seed.patch, gold_full=gold_full)
                except (SeedError, swe.ContractError) as exc:
                    sys.stdout.write(f"{record['instance_id']} {defect}: dropped: {exc}\n")
                    continue
                sys.stdout.write(f"{record['instance_id']} {defect}: tier A {verdict.tier}\n")
                if verdict.tier != "PLAUSIBLE":
                    continue
                kept += 1
                out.write(
                    json.dumps(
                        {
                            "instance_id": seed.instance_id,
                            "model_name_or_path": f"seeded:{defect}",
                            "model_patch": seed.patch,
                            "seed": {
                                "defect": defect,
                                "what_is_wrong": seed.what_is_wrong,
                                "prompt": "seed/1",
                            },
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
    sys.stdout.write(f"{kept} of {tried} seeds kept (plausible by tier A)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
