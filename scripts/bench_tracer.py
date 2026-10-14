"""The tracer's overhead on a benchmark suite (E01), tracked over time.

Usage:  uv run python scripts/bench_tracer.py [--rounds 5] [--python 3.13] [--out FILE]

The suite (engine/tests/data/bench_suite) runs through Repro's own plugin and command, in the
process sandbox: untraced and traced runs alternate (ABBA, so drift falls on both alike), and
each test's *call* phase is compared, median against median. Its targets are every workload
function, so each is traced to its budget (200 calls a test) and then disabled.

A08 measured budgeted capture at 0.92-1.19x baseline in steady state (spikes/A08/RESULTS.md
section 1). Each measured test runs its target tens of thousands of times after a warm-up test
has paid the process's first-use costs, so its 200 captured calls are a small part of it. Each
ratio comes with a BCa 95 % interval (D07's statistics): run-to-run noise on a laptop is about
as large as the effect, so a test fails the check only when its whole interval lies above
``LIMIT`` (1.20x), the rule D07 uses for a regression. Exit status 1 if one does.

With ``--out``, one JSON line per test is appended to that file (method, machine, numbers), the
record kept over time; ``docs/perf/README.md`` lists it.
"""

import argparse
import datetime
import json
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

from repro.analysis.symbols import build_table
from repro.provision import HostProvisioner, inspect_project
from repro.runner import run_tests
from repro.runner.perf import bca_ratio_interval
from repro.runner.pytest import TestRun, TraceTarget
from repro.sandbox import Limits, ProcessSandbox

ROOT: Final = Path(__file__).resolve().parents[1]
SUITE: Final = ROOT / "engine" / "tests" / "data" / "bench_suite"
LIMIT: Final = 1.20
TRACED: Final = ("fib", "normalise_record", "_small.<locals>.small")


def targets() -> list[TraceTarget]:
    table = build_table((SUITE / "work.py").read_bytes(), "work")
    return [("work.py", s.qualname, s.start, s.end) for s in table.symbols if s.qualname in TRACED]


#: The suite's first test takes the process's one-off costs and is not measured.
WARM_UP: Final = "test_work.py::test_a_warm_up"


def call_times(run: TestRun) -> dict[str, float]:
    if not run.results.complete or set(run.results.outcomes().values()) != {"passed"}:
        raise SystemExit(f"the benchmark suite did not pass:\n{run.execution.stdout.decode()}")
    return {
        test: result.call_s
        for test, result in run.results.tests.items()
        if result.call_s is not None and test != WARM_UP
    }


def commit() -> str:
    """The commit measured, ``-dirty`` when the working tree has changes (they were measured)."""
    done = subprocess.run(
        ["git", "-c", "core.longpaths=true", "describe", "--always", "--dirty", "--abbrev=7"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() or "unknown"


def measure(rounds: int, python: str, work: Path) -> list[dict[str, Any]]:
    snapshot = work / "snapshot"
    shutil.copytree(SUITE, snapshot)
    box = ProcessSandbox(work / "box", Limits(timeout_s=600))
    env = HostProvisioner(work / "envs", python=python).provision(
        "base", inspect_project(snapshot), box
    )
    traced = targets()
    samples: dict[str, dict[str, list[float]]] = {}
    for _ in range(rounds):
        for mode in ("plain", "traced", "traced", "plain"):
            run = run_tests(box, env, trace=traced if mode == "traced" else ())
            for test, seconds in call_times(run).items():
                samples.setdefault(test, {"plain": [], "traced": []})[mode].append(seconds)
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [row(test, times, stamp, env.python_version) for test, times in sorted(samples.items())]


def row(test: str, times: dict[str, list[float]], stamp: str, python: str) -> dict[str, Any]:
    """One test's line: medians, their ratio and its BCa 95 % interval (D07's statistics)."""
    resampling = random.Random(0)  # noqa: S311 - reproducible resampling, not secrets
    ratio, low, high = bca_ratio_interval(times["plain"], times["traced"], rng=resampling)
    return {
        "date": stamp,
        "commit": commit(),
        "os": platform.system(),
        "machine": platform.machine(),
        "python": python,
        "test": test,
        "runs": len(times["plain"]),
        "plain_ms": round(statistics.median(times["plain"]) * 1000, 3),
        "traced_ms": round(statistics.median(times["traced"]) * 1000, 3),
        "ratio": round(ratio, 3),
        "ci_low": round(low, 3),
        "ci_high": round(high, 3),
        "budget": 200,
        "method": "ABBA plain/traced pytest runs, call-phase medians, BCa 95% CI",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--python", default="3.13")
    parser.add_argument("--out", type=Path, default=None)
    options = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="repro-bench-") as scratch:
        rows = measure(options.rounds, options.python, Path(scratch))
    for row in rows:
        sys.stdout.write(json.dumps(row) + "\n")
    if options.out is not None:
        with options.out.open("a", encoding="utf-8", newline="\n") as handle:
            handle.writelines(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    over = [row for row in rows if row["ci_low"] > LIMIT]
    for row in over:
        interval = f"{row['ci_low']}-{row['ci_high']}"
        sys.stderr.write(f"{row['test']}: {row['ratio']}x ({interval}) is over {LIMIT}x\n")
    return 1 if over else 0


if __name__ == "__main__":
    raise SystemExit(main())
