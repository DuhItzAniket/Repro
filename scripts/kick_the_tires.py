"""Kick the tires: the evaluation's pipeline on one fresh task, in about half an hour (J09).

For artifact evaluation: one command, no model and no API key, that runs every deterministic
part of the study on one S2 candidate task, SWE-rebench `pypa__twine-1309` (split 2026_03). It
uses two patches: the task's gold patch, and a seeded wrong one that empties the fallback
phrase, so its hidden test fails. The steps:

1. **The task**, fetched from the datasets server and checked against its SHA-256 in
   `bench/data/s2-candidates.jsonl`: the row is the one the study pinned.
2. **Sealing** (J01): the input contract; the image pinned by digest (pulled, about 4.5 GB, the
   first time).
3. **Ground truth, tier A** (J02): the hidden tests and the full suite, in the task's image.
4. **B0, CI-only** (J03).
5. **Repro**, in the task's own image (J04's `sandbox_image`).

It prints what each step answered and checks what is known in advance:
- tier A finds the gold patch plausible and the seeded one INCORRECT_auto;
- CI-only passes both, since no existing test covers the case;
- Repro makes a card for each.

Exit status 0 when every check holds.

    uv run python scripts/kick_the_tires.py --work <empty dir>

Needs Docker with Linux containers, network access for the first pull, and `uv sync`.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Final

from repro_bench import baselines, groundtruth, swe, tasks

ROOT: Final = Path(__file__).resolve().parents[1]
TASK: Final = "pypa__twine-1309"
SPLIT: Final = "2026_03"
FALLBACK: Final = 'status_phrase = "Unknown Status"'
PATCHES: Final = ("gold", "seeded-wrong")


def wrong(gold: str) -> str:
    """The seeded wrong patch: the gold patch with an empty fallback phrase."""
    if FALLBACK not in gold:
        raise SystemExit(f"{TASK}'s gold patch no longer holds {FALLBACK!r}")
    return gold.replace(FALLBACK, 'status_phrase = ""')


def pinned_digest() -> str:
    for line in (
        (ROOT / "bench" / "data" / "s2-candidates.jsonl").read_text(encoding="utf-8").splitlines()
    ):
        row = json.loads(line)
        if row["instance_id"] == TASK:
            return str(row["record_sha256"])
    raise SystemExit(f"{TASK} is not among the pinned candidates")


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def step(name: str, started: float) -> None:
    sys.stdout.write(f"[{time.monotonic() - started:6.0f} s] {name}\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", type=Path, required=True, help="an empty directory")
    args = parser.parse_args(argv)
    work: Path = args.work
    work.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    step("fetching the task and checking it against its pinned digest", started)
    record = next(r for r in tasks.rows(SPLIT) if r["instance_id"] == TASK)
    if tasks.digest(record) != pinned_digest():
        raise SystemExit(f"{TASK}'s row is not the one the study pinned")
    instances = work / "instances.jsonl"
    instances.write_text(json.dumps(record) + "\n", encoding="utf-8")
    predictions = work / "predictions.jsonl"
    gold = str(record["patch"])
    predictions.write_text(
        "".join(
            json.dumps({"instance_id": TASK, "model_name_or_path": model, "model_patch": patch})
            + "\n"
            for model, patch in (("gold", gold), ("seeded-wrong", wrong(gold)))
        ),
        encoding="utf-8",
    )

    step("sealing, with the image pinned by digest (pulled the first time)", started)
    sealed = work / "sealed"
    if (
        swe.main(
            [
                "seal",
                "--instances",
                str(instances),
                "--predictions",
                str(predictions),
                "--dataset",
                tasks.DATASET,
                "--split",
                SPLIT,
                "--revision",
                "kick-the-tires",
                "--out",
                str(sealed),
                "--pin-images",
                "--pull",
            ]
        )
        != 0
    ):
        return 1
    image = rows(sealed / "manifest.jsonl")[0]["image"]

    step("ground truth, tier A, in the task's image", started)
    truth_dir = work / "truth"
    groundtruth.main(
        [
            "--instances",
            str(instances),
            "--predictions",
            str(predictions),
            "--out",
            str(truth_dir),
            "--seed",
            "kick-the-tires",
        ]
    )
    tier_a = {r["model"]: r["tier_a"]["tier"] for r in rows(truth_dir / "truth.jsonl")}

    step("B0, CI-only", started)
    answers = work / "baselines"
    baselines.main(
        [
            "--system",
            "b0",
            "--sealed",
            str(sealed / "sealed.jsonl"),
            "--mirrors",
            str(work / "mirrors"),
            "--out",
            str(answers),
            "--instances",
            str(instances),
        ]
    )
    ci = {r["model"]: r["status"] for r in rows(answers / "b0.jsonl")}

    step("Repro, in the task's own image", started)
    os.environ["REPRO_SANDBOX_IMAGE"] = image
    swe.main(
        [
            "run",
            "--sealed",
            str(sealed / "sealed.jsonl"),
            "--mirrors",
            str(work / "mirrors"),
            "--out",
            str(work / "repro"),
            "--data",
            str(work / "repro-data"),
            "--sandbox",
            "docker",
        ]
    )
    repro = {r["model"]: r["status"] for r in rows(work / "repro" / "results.jsonl")}

    step("done", started)
    sys.stdout.write("\npatch          tier A          B0         Repro\n")
    for model in PATCHES:
        sys.stdout.write(
            f"{model:<14} {tier_a.get(model, '-'):<15} {ci.get(model, '-'):<10} "
            f"{repro.get(model, '-')}\n"
        )
    checks = {
        "tier A finds the gold patch plausible": tier_a.get("gold") == "PLAUSIBLE",
        "tier A labels the seeded patch INCORRECT_auto": tier_a.get("seeded-wrong")
        == "INCORRECT_auto",
        "CI-only passes both (no existing test covers the case)": set(ci.values()) == {"VERIFIED"},
        "Repro makes a card for each": all(
            s in ("VERIFIED", "FLAGGED", "UNVERIFIABLE") for s in repro.values()
        )
        and len(repro) == len(PATCHES),
    }
    for name, held in checks.items():
        sys.stdout.write(f"{'ok  ' if held else 'FAIL'} {name}\n")
    digest = hashlib.sha256((work / "sealed" / "manifest.jsonl").read_bytes()).hexdigest()
    sys.stdout.write(f"manifest sha256 {digest}\n")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
