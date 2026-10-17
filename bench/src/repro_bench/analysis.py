"""The study's registered analysis, written before any S2 data exists (J06; protocol §6, §7).

Everything the paper reports about S2 is computed here, from the frozen labels and the systems'
answers. It is frozen with the protocol (``docs/paper/PREREGISTRATION.md``).

- **Per item and system**, the k answers are reduced to one by majority. When no status has a
  majority, the item is UNVERIFIABLE for that system. The *flip rate* is the share of items
  whose k answers are not all the same.
- **Catch rate** is P(FLAGGED | INCORRECT) and **false-flag rate** is P(FLAGGED | CORRECT).
  Each is computed on covered items (answer not UNVERIFIABLE), with **coverage**
  P(not UNVERIFIABLE). The bounding conversions are shown beside them: every UNVERIFIABLE as
  FLAGGED, and every UNVERIFIABLE as VERIFIED. UNCERTAIN labels are left out of the primary
  metrics (§4).
- **McNemar's test, exact**, Repro against each baseline, on the items both answered for. It
  is two-sided, doubling the smaller binomial tail [McNemar 1947, doi:10.1007/BF02295996]. It
  is run separately on INCORRECT items (who flags them) and CORRECT items (who flags them
  falsely). An UNVERIFIABLE answer counts as not flagging: a miss on an INCORRECT item, no
  false flag on a CORRECT one. Holm's method adjusts the p-values across the baselines
  [Holm, "A Simple Sequentially Rejective Multiple Test Procedure", Scand. J. Statist.
  6(2):65-70, 1979, jstor.org/stable/4615733].
- **95% confidence intervals** by a cluster bootstrap that resamples repositories, 10,000
  resamples from a fixed seed: tasks of one repository are not independent.

    uv run python -m repro_bench.analysis --labels <labels.jsonl> --answers <dir>
        --items <truth.jsonl> [--out <json>]
"""

import argparse
import json
import math
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from repro_bench.labels import check_frozen

STATUSES: Final = ("VERIFIED", "FLAGGED", "UNVERIFIABLE")
RESAMPLES: Final = 10_000
SEED: Final = 20261018
REFERENCE: Final = "repro"


def majority(answers: Sequence[str]) -> str:
    """The status most of the k answers give; UNVERIFIABLE when none has a majority."""
    if not answers:
        return "UNVERIFIABLE"
    status, count = Counter(answers).most_common(1)[0]
    return status if count * 2 > len(answers) else "UNVERIFIABLE"


def flipped(answers: Sequence[str]) -> bool:
    return len(set(answers)) > 1


@dataclass(frozen=True)
class Rates:
    items: int
    covered: int
    flagged: int  # among covered
    unverifiable: int

    @property
    def coverage(self) -> float:
        return self.covered / self.items if self.items else math.nan

    @property
    def rate(self) -> float:
        """FLAGGED among covered items: the catch rate on INCORRECT, false-flag on CORRECT."""
        return self.flagged / self.covered if self.covered else math.nan

    @property
    def as_flagged(self) -> float:
        return (self.flagged + self.unverifiable) / self.items if self.items else math.nan

    @property
    def as_verified(self) -> float:
        return self.flagged / self.items if self.items else math.nan


def rates(statuses: Iterable[str]) -> Rates:
    found = Counter(statuses)
    items = sum(found.values())
    return Rates(items, items - found["UNVERIFIABLE"], found["FLAGGED"], found["UNVERIFIABLE"])


def _pmf(k: int, n: int) -> float:
    return float(math.comb(n, k)) / float(2**n)


def mcnemar(only_first: int, only_second: int) -> float:
    """The exact two-sided p-value for ``only_first`` and ``only_second`` discordant pairs."""
    n = only_first + only_second
    if n == 0:
        return 1.0
    low = min(only_first, only_second)
    tail = sum(_pmf(k, n) for k in range(low + 1))
    return min(1.0, 2 * tail)


def holm(p_values: Mapping[str, float]) -> dict[str, float]:
    """Holm's step-down adjustment: the adjusted p-values, monotone, capped at 1."""
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    adjusted: dict[str, float] = {}
    running = 0.0
    m = len(ordered)
    for index, (name, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - index) * p))
        adjusted[name] = running
    return adjusted


def discordant(first: Mapping[str, str], second: Mapping[str, str]) -> tuple[int, int]:
    """Items flagged by one system and not the other, over the items both answered for."""
    shared = first.keys() & second.keys()
    only_first = sum(1 for i in shared if first[i] == "FLAGGED" and second[i] != "FLAGGED")
    only_second = sum(1 for i in shared if second[i] == "FLAGGED" and first[i] != "FLAGGED")
    return only_first, only_second


def bootstrap(
    items: Sequence[str],
    cluster_of: Mapping[str, str],
    statistic: Any,
    *,
    resamples: int = RESAMPLES,
    seed: int = SEED,
) -> tuple[float, float]:
    """A 95% interval for ``statistic(items)`` from resampled clusters (percentile method)."""
    by_cluster: dict[str, list[str]] = defaultdict(list)
    for item in items:
        by_cluster[cluster_of[item]].append(item)
    clusters = sorted(by_cluster)
    if not clusters:
        return (math.nan, math.nan)
    rng = random.Random(seed)  # noqa: S311 - a reproducible resample, not a secret
    values = []
    for _ in range(resamples):
        drawn = [i for c in rng.choices(clusters, k=len(clusters)) for i in by_cluster[c]]
        value = statistic(drawn)
        if not math.isnan(value):
            values.append(value)
    if not values:
        return (math.nan, math.nan)
    values.sort()
    return values[int(0.025 * (len(values) - 1))], values[int(0.975 * (len(values) - 1))]


@dataclass(frozen=True)
class SystemReport:
    system: str
    incorrect: Rates
    correct: Rates
    flip_rate: float
    catch_ci: tuple[float, float]
    false_flag_ci: tuple[float, float]


def analyse(
    labels: Mapping[str, str],
    answers: Mapping[str, Mapping[str, Sequence[str]]],
    repo_of: Mapping[str, str],
    *,
    resamples: int = RESAMPLES,
) -> dict[str, Any]:
    """The registered results: per system, its rates, flip rate and intervals; then McNemar
    of the reference system against each other, Holm-adjusted."""
    decided = {item: label for item, label in labels.items() if label in ("CORRECT", "INCORRECT")}
    final = {
        system: {item: majority(given) for item, given in by_item.items() if item in decided}
        for system, by_item in answers.items()
    }
    reports = []
    for system, by_item in sorted(final.items()):
        bad = [i for i in by_item if decided[i] == "INCORRECT"]
        good = [i for i in by_item if decided[i] == "CORRECT"]
        given = answers[system]

        def rate_of(chosen: Sequence[str], statuses: Mapping[str, str] = by_item) -> float:
            return rates(statuses[i] for i in chosen).rate

        flips = [flipped(given[i]) for i in by_item]
        reports.append(
            SystemReport(
                system,
                rates(by_item[i] for i in bad),
                rates(by_item[i] for i in good),
                sum(flips) / len(flips) if flips else math.nan,
                bootstrap(bad, repo_of, rate_of, resamples=resamples),
                bootstrap(good, repo_of, rate_of, resamples=resamples),
            )
        )
    tests: dict[str, dict[str, Any]] = {}
    if REFERENCE in final:
        for label in ("INCORRECT", "CORRECT"):
            raw = {}
            pairs = {}
            for system in sorted(set(final) - {REFERENCE}):
                mine = {i: s for i, s in final[REFERENCE].items() if decided[i] == label}
                theirs = {i: s for i, s in final[system].items() if decided[i] == label}
                pairs[system] = discordant(mine, theirs)
                raw[system] = mcnemar(*pairs[system])
            adjusted = holm(raw)
            tests[label] = {
                system: {
                    "repro_only": pairs[system][0],
                    "other_only": pairs[system][1],
                    "p": raw[system],
                    "p_holm": adjusted[system],
                }
                for system in raw
            }
    return {
        "items": {
            "labelled": len(labels),
            "decided": len(decided),
            "uncertain": sum(1 for v in labels.values() if v == "UNCERTAIN"),
        },
        "systems": [_report_dict(r) for r in reports],
        "mcnemar": tests,
        "resamples": resamples,
        "seed": SEED,
    }


def _report_dict(report: SystemReport) -> dict[str, Any]:
    def view(found: Rates) -> dict[str, Any]:
        return asdict(found) | {
            "rate": found.rate,
            "coverage": found.coverage,
            "as_flagged": found.as_flagged,
            "as_verified": found.as_verified,
        }

    return {
        "system": report.system,
        "incorrect": view(report.incorrect),
        "correct": view(report.correct),
        "flip_rate": report.flip_rate,
        "catch_ci": report.catch_ci,
        "false_flag_ci": report.false_flag_ci,
    }


def load_answers(directory: Path) -> dict[str, dict[str, list[str]]]:
    """``<system>.jsonl`` files of ``{"item", "status"}`` rows, one row per run (k of them)."""
    found: dict[str, dict[str, list[str]]] = {}
    for path in sorted(directory.glob("*.jsonl")):
        by_item: dict[str, list[str]] = defaultdict(list)
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row["status"] not in STATUSES:
                    raise ValueError(f"{path.name}: status {row['status']!r}")
                by_item[str(row["item"])].append(str(row["status"]))
        found[path.stem] = dict(by_item)
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", type=Path, required=True, help="the frozen final labels")
    parser.add_argument("--answers", type=Path, required=True, help="<system>.jsonl files")
    parser.add_argument("--items", type=Path, required=True, help="truth.jsonl: item -> task")
    parser.add_argument("--repos", type=Path, help="JSONL: instance_id -> repo (else from items)")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--resamples", type=int, default=RESAMPLES)
    args = parser.parse_args(argv)
    check_frozen(args.labels)  # a label file changed after its freeze is refused
    labels = {}
    for line in args.labels.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            labels[str(row["item"])] = str(row["label"])
    rows = [
        json.loads(line) for line in args.items.read_text(encoding="utf-8").splitlines() if line
    ]
    repo_of = {
        str(r["item"]): str(r.get("repo") or r["instance_id"].rsplit("-", 1)[0]) for r in rows
    }
    result = analyse(labels, load_answers(args.answers), repo_of, resamples=args.resamples)
    text = json.dumps(result, indent=2, sort_keys=True, default=str)
    if args.out:
        args.out.write_bytes((text + "\n").encode("utf-8"))
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
