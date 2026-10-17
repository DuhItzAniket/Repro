"""The ground-truth pipeline over a set of tasks and patches (J02).

For each task, every patch goes through tier A (``truth.tier_a``; the gold patch's full-suite
run is made once per task and reused); a plausible patch goes through tier B with UTBoost's
augmented tests when the task has them and with differential tests written for it when a model
is given (``difftest``). The outputs, in ``--out``:

- ``truth.jsonl``: per patch, each tier's verdict and evidence, the automatic label
  (``INCORRECT_auto``, ``CORRECT_auto``) or none, and whether people must look;
- ``items.jsonl``: the annotators' batch (``repro_bench.annotate``): every patch the tiers
  could not settle (``DIVERGENT``, ``NEEDS_REVIEW``) and the protocol's random 15% of each
  automatic label, drawn from ``--seed`` (§4.3).

Everything a patch is judged by is written down with it: the image by digest, the commands,
the tests that diverged, the model's tokens.

    uv run python -m repro_bench.groundtruth --instances <jsonl> --predictions <jsonl>
        --out <dir> --seed <s> [--utboost <jsonl>] [--generate record|replay --cassettes <dir>]
"""

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from repro.agents import CassetteBackend, LLMBackend
from repro.agents.openai_compat import Endpoint, OpenAICompatibleBackend
from repro.agents.setup import GROQ_MODEL
from repro_bench import difftest, truth
from repro_bench.labels import audit_sample, item_key
from repro_bench.swe import ContractError, Prediction, pinned, read_jsonl
from repro_bench.truth import Divergence, Oracle, OracleError, Verdict

AUTOMATIC = ("INCORRECT_auto", "CORRECT_auto")


def judge(
    oracle: Oracle,
    prediction: Prediction,
    problem_statement: str,
    *,
    gold_full: truth.ContainerRun | None,
    utboost: Mapping[str, Any] | None,
    backend: LLMBackend | None,
    model: str,
    reruns: int,
    run: Any = truth.run_tests,
) -> tuple[dict[str, Any], truth.ContainerRun | None]:
    """One patch through the tiers: its row for ``truth.jsonl``, and the gold full-suite run."""
    first, gold_full = truth.tier_a(oracle, prediction.patch, gold_full=gold_full, run=run)
    row: dict[str, Any] = {
        "item": item_key(prediction.instance_id, prediction.patch_sha256),
        "instance_id": prediction.instance_id,
        "model": prediction.model,
        "patch_sha256": prediction.patch_sha256,
        "image": oracle.image,
        "tier_a": asdict(first),
    }
    final: Verdict = first
    if first.tier == "PLAUSIBLE":
        divergences: list[Divergence] = []
        notes: list[str] = []
        if utboost is not None:
            augmented = truth.utboost_patch(oracle, utboost)
            divergences.append(
                truth.differential(
                    oracle, prediction.patch, augmented, source="utboost", reruns=reruns, run=run
                )
            )
        if backend is not None:
            try:
                tests, result = asyncio.run(
                    difftest.write_tests(
                        oracle, problem_statement, prediction.patch, backend, model
                    )
                )
                row["difftest_tokens"] = [result.usage.input_tokens, result.usage.output_tokens]
                divergences.append(
                    truth.differential(
                        oracle, prediction.patch, tests, source="generated", reruns=reruns, run=run
                    )
                )
            except OracleError as exc:
                notes.append(f"generated tests: {exc}")
        final = truth.tier_b(divergences)
        row["tier_b"] = asdict(final) | {
            "divergences": [asdict(d) for d in divergences],
            "notes": notes,
        }
    row["auto_label"] = final.tier if final.tier in AUTOMATIC else None
    row["needs_people"] = final.tier not in AUTOMATIC
    return row, gold_full


def batch(rows: Sequence[Mapping[str, Any]], tasks: Mapping[str, Mapping[str, Any]],
          patches: Mapping[str, str], seed: str) -> list[dict[str, Any]]:  # fmt: skip
    """The annotators' items: every unsettled patch, and 15% of each automatic label."""
    chosen = {row["item"] for row in rows if row["needs_people"]}
    for label in AUTOMATIC:
        chosen |= set(
            audit_sample([r["item"] for r in rows if r["auto_label"] == label], f"{seed}:{label}")
        )
    items = []
    for row in rows:
        if row["item"] not in chosen:
            continue
        task = tasks[row["instance_id"]]
        tiers = {"tier_a": row["tier_a"], **({"tier_b": row["tier_b"]} if "tier_b" in row else {})}
        items.append(
            {
                "item": row["item"],
                "repo": task["repo"],
                "problem_statement": task["problem_statement"],
                "candidate_patch": patches[row["item"]],
                "gold_patch": task["patch"],
                "test_patch": task["test_patch"],
                "tiers": tiers,
            }
        )
    return items


def _backend(mode: str | None, cassettes: Path | None) -> LLMBackend | None:
    if mode is None:
        return None
    if cassettes is None:
        raise SystemExit("--generate needs --cassettes")
    if mode == "replay":
        return CassetteBackend(cassettes, "replay")
    return CassetteBackend(cassettes, "record", OpenAICompatibleBackend(Endpoint.groq()))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--instances", type=Path, required=True, help="SWE-rebench-format JSONL")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", required=True, help="the audit sample's seed")
    parser.add_argument("--utboost", type=Path, help="UTBoost's augmented instances (JSONL)")
    parser.add_argument("--generate", choices=("record", "replay"), help="write differential tests")
    parser.add_argument("--cassettes", type=Path)
    parser.add_argument("--model", default=GROQ_MODEL)
    parser.add_argument("--reruns", type=int, default=truth.RERUNS)
    args = parser.parse_args(argv)
    try:
        tasks = {str(r["instance_id"]): r for r in read_jsonl(args.instances)}
        augmented = (
            {str(r["instance_id"]): r for r in read_jsonl(args.utboost)} if args.utboost else {}
        )
        by_task: dict[str, list[Prediction]] = defaultdict(list)
        for record in read_jsonl(args.predictions):
            made = Prediction.from_record(record)
            if made.instance_id not in tasks:
                raise ContractError(f"{made.instance_id} is not in {args.instances.name}")
            by_task[made.instance_id].append(made)
        backend = _backend(args.generate, args.cassettes)
        rows, patches = [], {}
        for instance_id, predictions in sorted(by_task.items()):
            task = tasks[instance_id]
            oracle = Oracle.from_record(task)
            oracle = Oracle(**{**asdict(oracle), "image": pinned(oracle.image)})
            gold_full = None
            for prediction in predictions:
                row, gold_full = judge(
                    oracle, prediction, str(task["problem_statement"]), gold_full=gold_full,
                    utboost=augmented.get(instance_id), backend=backend, model=args.model,
                    reruns=args.reruns,
                )  # fmt: skip
                rows.append(row)
                patches[row["item"]] = prediction.patch
                verdict = row["auto_label"] or "to people"
                sys.stdout.write(f"{row['item']} ({prediction.model}): {verdict}\n")
                sys.stdout.flush()
    except (ContractError, OracleError) as exc:
        sys.stderr.write(f"repro_bench.groundtruth: {exc}\n")
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    truth.save(args.out / "truth.jsonl", rows)
    items = batch(rows, tasks, patches, args.seed)
    truth.save(args.out / "items.jsonl", items)
    counts = json.dumps(truth.summary(Verdict(r["auto_label"] or "NEEDS_REVIEW", "") for r in rows))
    sys.stdout.write(f"{len(rows)} patches: {counts}; {len(items)} items for the annotators\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
