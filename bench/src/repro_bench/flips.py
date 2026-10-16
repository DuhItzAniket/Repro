"""Verdict flips under order swap, measured from runs' event logs (G08).

A run with ``agent_order_swap = all`` judges every claim twice: once as the evidence is
ordered, once with it and the other claims reversed. Each verdict then records
``agreement {runs: 2, agreeing}``, and the two judgements differed exactly when ``agreeing`` is
less than 2. The flip rate is the share of claims judged in both orders whose two judgements
differ; it is reported per first verdict too, since a flipped contradiction changes the card
and a flipped unverifiable verdict does not.

    uv run python -m repro_bench.flips run1.jsonl run2.jsonl ...
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SWAPPED = 2  # judgements of a verdict judged in both orders


@dataclass(slots=True)
class Flips:
    """Verdicts judged in both orders, and how many of them the reversed order changed."""

    judged: int = 0
    flipped: int = 0
    #: Per first verdict (the one in the evidence's own order): judged, and flipped.
    by_first: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def rate(self) -> float:
        return self.flipped / self.judged if self.judged else 0.0


def first_verdict(verdict: Mapping[str, Any], rejected: Mapping[str, str]) -> str:
    """What the first judgement answered: the issued verdict, unless the swap changed it, when
    the disagreement's detail names it (``"<first> with the evidence in one order, …"``)."""
    detail = rejected.get(verdict["claim_id"])
    if detail is None:
        return str(verdict["verdict"])
    return detail.split(" ", 1)[0]


def flips(events: Iterable[Mapping[str, Any]]) -> Flips:
    """The flips among one run's reviewer verdicts (not the gap reviewer's or QA's)."""
    events = list(events)
    rejected = {
        e["payload"]["claim_id"]: e["payload"]["detail"]
        for e in events
        if e["kind"] == "verdict.rejected" and e["payload"]["reason"] == "order_swap_disagreement"
    }
    found = Flips()
    judged: Counter[str] = Counter()
    flipped: Counter[str] = Counter()
    for event in events:
        if event["kind"] != "verdict.issued":
            continue
        verdict = event["payload"]["verdict"]
        agreement = verdict.get("agreement") or {}
        if agreement.get("runs") != SWAPPED:
            continue
        first = first_verdict(verdict, rejected)
        judged[first] += 1
        if agreement["agreeing"] < SWAPPED:
            flipped[first] += 1
    found.judged, found.flipped = sum(judged.values()), sum(flipped.values())
    found.by_first = {name: (judged[name], flipped[name]) for name in sorted(judged)}
    return found


def combined(runs: Sequence[Flips]) -> Flips:
    total = Flips()
    for run in runs:
        total.judged += run.judged
        total.flipped += run.flipped
        for name, (judged, flipped) in run.by_first.items():
            had = total.by_first.get(name, (0, 0))
            total.by_first[name] = (had[0] + judged, had[1] + flipped)
    total.by_first = dict(sorted(total.by_first.items()))
    return total


def _events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("logs", nargs="+", type=Path, help="event logs (JSON lines)")
    args = parser.parse_args(argv)
    total = combined([flips(_events(path)) for path in args.logs])
    out = sys.stdout
    out.write(f"flip rate {total.rate:.3f} ({total.flipped}/{total.judged})\n")
    for name, (judged, flipped) in total.by_first.items():
        out.write(f"  first {name}: {flipped}/{judged}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
