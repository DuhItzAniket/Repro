"""``repro run`` on three real repositories of increasing size, timed (H02).

The reference changes are pinned commits of three Pallets projects (BSD-3-Clause), cloned at
run time into ``--repos`` and never vendored:

| Name | Python at head (files, lines) | Change |
|---|---|---|
| itsdangerous | 15 files, 1,736 lines | ``93ae366..7f4dcf8``, "access sha1 lazily" (Gate C) |
| flask | 83 files, 18,334 lines | ``de8429f..7203fea``, "Fix IPv6 server name parsing" |
| click | 91 files, 29,214 lines | ``6d5bac5..f67c2bb``, "Fix short help abbreviation" |

(Counted with ``git ls-tree`` and ``git grep -c ''`` over ``*.py`` at each head.)

Each runs twice into one fresh data directory: cold (no test map or package cache, and with
the process sandbox no dependencies' environment: Repro keeps them there) and warm (the same
change again). With Docker, the dependencies' environments are volumes that outlive the data
directory, so a cold run may reuse them. Each run's wall-clock time, the card's status and
counts, the selected tests, cache use and the time of the stages that take it (from the run's
own events) are printed, and with ``--append`` added to ``bench/results/scale.csv``. The
figures depend on the machine, so each row says which.

``evidence`` counts every record but timings; ``timed`` counts the tests timed (``perf_diff``),
which varies between runs of the same change: noise decides which tests near the 5 ms floor
clear it (flask: 38 to 40 in four runs).

``--check`` fails unless H02's targets hold (``problems``): every run ends with a card, well
inside the per-run limit; a warm run reuses both environments, each within D03's measured
reuse time, and base's map; and its card's counts and evidence equal the cold run's.

    uv run python -m repro_bench.scale --repos <dir> [--sandbox process|docker] [--append]
        [--check] [--only <name>...] [--keep <dir>]
"""

import argparse
import csv
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from repro import __version__
from repro.store import StoreReader
from repro_bench.results import ROOT

RESULTS: Final = ROOT / "bench" / "results" / "scale.csv"
FIELDS: Final = (
    "date", "reference", "pass", "seconds", "status", "selected", "evidence", "timed",
    "gap_items", "missing", "provisioned", "provision_s", "env_cached", "map_cached", "build_s",
    "run_s", "diff_s", "sandbox", "platform", "cpus", "repro_version",
)  # fmt: skip
RUN_TIMEOUT_S: Final = 3600
#: Provisioning from a reused environment, per side, as D03 measured it: 1.4-4.6 s in the
#: process sandbox (the project's own install included); in a container, about 6 s with the
#: dependencies cached (the tests' run included).
REUSE_LIMIT_S: Final = {"process": 4.6, "docker": 6.0}
#: The per-run limit (H01's ``test_timeout_s`` default); a reference must end well inside it.
RUN_LIMIT_S: Final = 900.0
#: The card's counts a warm run must repeat.
SAME: Final = ("status", "selected", "evidence", "gap_items", "missing")
TIMED: Final = "perf_diff"


@dataclass(frozen=True, slots=True)
class Reference:
    name: str
    url: str
    base: str
    head: str


REFERENCES: Final = (
    Reference(
        "itsdangerous",
        "https://github.com/pallets/itsdangerous.git",
        "93ae366874bbd4f69d90495c45b2cd336387496c",
        "7f4dcf83a07bb3d53f4e0e65ef1b43327b4cca90",
    ),
    Reference(
        "flask",
        "https://github.com/pallets/flask.git",
        "de8429ffda8cfb54db175529e2bae72a24e1fa7e",
        "7203feabf723edae0286ae5dc64fec8ac4c91735",
    ),
    Reference(
        "click",
        "https://github.com/pallets/click.git",
        "6d5bac5c712195cbfa9666ba0ecbf0573cdea356",
        "f67c2bb6c2f055c1c7a57cd46c3697fc26a7742e",
    ),
)


def clone(reference: Reference, repos: Path) -> Path:
    """The reference's repository under ``repos``, cloned once and fetched when a pinned commit
    is missing."""
    target = repos / reference.name
    git = ["git", "-c", "core.longpaths=true"]
    if not target.is_dir():
        subprocess.run([*git, "clone", "--quiet", reference.url, str(target)], check=True)  # noqa: S603
    for sha in (reference.base, reference.head):
        known = subprocess.run(  # noqa: S603 - git, Repro's own arguments
            [*git, "-C", str(target), "cat-file", "-e", f"{sha}^{{commit}}"], check=False
        )
        if known.returncode != 0:
            subprocess.run([*git, "-C", str(target), "fetch", "--quiet", "origin"], check=True)  # noqa: S603
    return target


def _stages(events: Sequence[dict[str, Any]]) -> dict[str, float]:
    started: dict[str, datetime] = {}
    took: dict[str, float] = {}
    for event in events:
        moment = datetime.fromisoformat(event["ts"].replace("Z", "+00:00"))
        if event["kind"] == "stage.started":
            started[event["stage"]] = moment
        elif event["kind"] == "stage.finished" and event["stage"] in started:
            took[event["stage"]] = (moment - started[event["stage"]]).total_seconds()
    return took


def run_once(repo: Path, reference: Reference, data: Path, sandbox: str) -> dict[str, Any]:
    """One ``repro run`` of the reference change, timed."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("REPRO_")}
    env |= {"REPRO_DATA_DIR": str(data), "REPRO_SANDBOX": sandbox, "REPRO_LOG_FORMAT": "text"}
    argv = [sys.executable, "-m", "repro", "run", "--repo", str(repo)]
    argv += ["--base", reference.base, "--head", reference.head, "--no-serve"]
    started = time.monotonic()
    done = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
        argv, env=env, capture_output=True, timeout=RUN_TIMEOUT_S, check=False
    )
    seconds = time.monotonic() - started
    with StoreReader(data / "repro.db") as reader:
        (stored,) = reader.runs(1)
        events = [json.loads(e.body) for e in reader.iter_events(stored.id)]
    published = next((e["payload"] for e in events if e["kind"] == "card.published"), None)
    stages = _stages(events)
    envs = [e["payload"] for e in events if e["kind"] == "env.provisioned"]
    logged = [e["payload"]["message"] for e in events if e["kind"] == "log.line"]
    base_map = next((m for m in logged if m.startswith("base map: ")), "")
    counts = published["counts"] if published else {}
    provisioned = {p["side"] for p in envs} == {"base", "head"}
    kinds = [e["payload"]["evidence"]["type"] for e in events if e["kind"] == "evidence.created"]
    return {
        "seconds": round(seconds, 1),
        "status": published["status"] if published else f"no card (exit {done.returncode})",
        "selected": sum(1 for e in events if e["kind"] == "test.selected"),
        "evidence": sum(1 for t in kinds if t != TIMED),
        "timed": sum(1 for t in kinds if t == TIMED),
        "gap_items": counts.get("gap_items", ""),
        "missing": counts.get("missing", ""),
        "provisioned": provisioned,
        "provision_s": round(max((p["duration_ms"] for p in envs), default=0) / 1000, 1),
        "env_cached": provisioned and all(p["cache_hit"] for p in envs),
        "map_cached": "from the cache" in base_map,
        "build_s": round(stages.get("build", 0.0), 1),
        "run_s": round(stages.get("run", 0.0), 1),
        "diff_s": round(stages.get("diff", 0.0), 1),
    }


def problems(
    name: str, cold: dict[str, Any], warm: dict[str, Any], sandbox: str = "process"
) -> list[str]:
    """What breaks H02's targets in a reference's cold and warm runs."""
    found = []
    for which, row in (("cold", cold), ("warm", warm)):
        if str(row["status"]).startswith("no card"):
            found.append(f"{name} {which}: {row['status']}")
        if not row["provisioned"]:
            found.append(f"{name} {which}: a side has no environment (the run's log says why)")
        if row["seconds"] >= RUN_LIMIT_S / 2:
            found.append(f"{name} {which}: {row['seconds']} s, half the {RUN_LIMIT_S:g} s limit")
    if not warm["provisioned"]:
        return found  # nothing else to compare: no tests ran
    if not warm["env_cached"]:
        found.append(f"{name} warm: the dependencies' environments were built again")
    elif warm["provision_s"] > REUSE_LIMIT_S[sandbox]:
        limit = REUSE_LIMIT_S[sandbox]
        found.append(f"{name} warm: provisioning took {warm['provision_s']} s (> {limit})")
    if not warm["map_cached"]:
        found.append(f"{name} warm: base's map was made again")
    found += [
        f"{name}: {field} {cold[field]} cold, {warm[field]} warm"
        for field in SAME
        if cold[field] != warm[field]
    ]
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repos", type=Path, required=True, help="where the clones are kept")
    parser.add_argument("--sandbox", choices=("process", "docker"), default="process")
    parser.add_argument("--only", nargs="*", help="reference names to run (default: all)")
    parser.add_argument("--append", action="store_true", help=f"append to {RESULTS.name}")
    parser.add_argument("--check", action="store_true", help="fail unless the targets hold")
    parser.add_argument(
        "--keep", type=Path, help="keep each reference's data directory under this one"
    )
    args = parser.parse_args(argv)
    rows = []
    broken = []
    date = datetime.now(UTC).date().isoformat()
    for reference in REFERENCES:
        if args.only and reference.name not in args.only:
            continue
        repo = clone(reference, args.repos)
        found: dict[str, dict[str, Any]] = {}
        with tempfile.TemporaryDirectory(
            prefix=f"repro-scale-{reference.name}-", ignore_cleanup_errors=True
        ) as work:
            data = args.keep / reference.name if args.keep else Path(work)
            if data.exists() and args.keep:
                parser.error(f"{data} exists: a cold run needs a data directory of its own")
            for which in ("cold", "warm"):
                found[which] = run_once(repo, reference, data, args.sandbox)
                sys.stdout.write(f"{reference.name:13} {which}: {found[which]}\n")
                sys.stdout.flush()
                rows.append(
                    {
                        "date": date,
                        "reference": reference.name,
                        "pass": which,
                        **{k: str(v) for k, v in found[which].items()},
                        "sandbox": args.sandbox,
                        "platform": f"{platform.system()} {platform.machine()}",
                        "cpus": str(os.cpu_count() or 0),
                        "repro_version": __version__,
                    }
                )
        broken += problems(reference.name, found["cold"], found["warm"], args.sandbox)
    if args.append:
        new = not RESULTS.exists()
        with RESULTS.open("a", encoding="utf-8", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n")
            if new:
                writer.writeheader()
            writer.writerows(rows)
    for problem in broken:
        sys.stdout.write(f"target missed: {problem}\n")
    return 1 if args.check and broken else 0


if __name__ == "__main__":
    sys.exit(main())
