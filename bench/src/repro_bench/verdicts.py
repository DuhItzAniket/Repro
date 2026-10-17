"""The reviewers, measured on reviewed runs of the labelled pull requests (G09).

From each run's event log (``repro_bench.runs``), against the labels in
``bench/data/claims.toml`` and the fixtures' expected statuses:

- **verdict accuracy**: of the labels with a verdict, the share whose claim, paired with an
  extracted claim as the claim eval pairs them, got that verdict. A claim's verdict is what the
  status rules make of its verdicts: contradicted if any is, else unverifiable if any is, else
  supported. A label with no paired claim, or a claim with no verdict, counts as wrong.
- **unsafe verdicts**: the wrong ones that point the other way: supported where the label says
  contradicted, or contradicted where it says supported.
- **status accuracy**: the share of cards whose status is the fixture's expected one.
- **citation validity** and **rejection rate**, per reviewer answer: an answer is refused when
  it fails G05's checks (each refusal is a ``verdict.rejected``); citation validity is the
  share of answers not refused for their citations (none, unknown or unrelated).
- **flip rate** (``repro_bench.flips``), from runs that judged every verdict in both orders.
- **cost**: estimated US dollars and tokens per pull request.

    uv run python -m repro_bench.verdicts                # replay the cassettes, print
    uv run python -m repro_bench.verdicts --append       # and append to agent-evals.csv
"""

import argparse
import sys
import tempfile
import tomllib
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from repro import __version__
from repro.agents.setup import GROQ_MODEL
from repro_bench.claims import Item, load, pairs
from repro_bench.flips import Flips, combined, flips
from repro_bench.results import ROOT, append_rows
from repro_bench.runs import REVIEWED, expected_status, run

CITATION_REASONS: Final = frozenset({"uncited", "invalid_citation", "unrelated_citation"})
#: Verdicts that point opposite ways: one where the other is right is unsafe.
OPPOSITE: Final = {("supported", "contradicted"), ("contradicted", "supported")}


def effective(verdicts: Iterable[str]) -> str | None:
    """A claim's verdict as the status rules read its verdicts."""
    found = set(verdicts)
    for verdict in ("contradicted", "unverifiable", "supported"):
        if verdict in found:
            return verdict
    return None


@dataclass(slots=True)
class Scored:
    """One reviewed run against its labels."""

    name: str
    status: str
    expected_status: str
    #: (label, the verdict it deserves, the verdict its claim got or None).
    judged: list[tuple[str, str, str | None]] = field(default_factory=list)
    answers: int = 0
    refused: Counter[str] = field(default_factory=Counter)
    usd: float = 0.0
    tokens: int = 0


def _roles(events: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    return {e["agent"]: e["payload"]["role"] for e in events if e["kind"] == "agent.spawned"}


def score(item: Item, events: Sequence[Mapping[str, Any]], expected: str) -> Scored:
    roles = _roles(events)
    card = next(e["payload"]["card"] for e in events if e["kind"] == "card.published")
    found = Scored(item.name, card["status"], expected)
    claims = [e["payload"]["claim"] for e in events if e["kind"] == "claim.extracted"]
    given: dict[str, list[str]] = {}
    for event in events:
        if event["kind"] == "verdict.issued":
            verdict = event["payload"]["verdict"]
            given.setdefault(verdict["claim_id"], []).append(verdict["verdict"])
    paired = {
        label: claim for claim, label in pairs([c["text"] for c in claims], item.labels).items()
    }
    for number, label in enumerate(item.labels):
        if label.verdict is None:
            continue
        claim = paired.get(number)
        got = effective(given.get(claims[claim]["id"], [])) if claim is not None else None
        found.judged.append((label.text, label.verdict, got))
    for event in events:
        if event["kind"] == "agent.state" and roles.get(event["agent"]) == "review":
            state, detail = event["payload"]["state"], event["payload"].get("detail") or ""
            if state == "done" or (state == "failed" and detail.startswith("invalid_output")):
                found.answers += 1
        elif event["kind"] == "verdict.rejected":
            reason = event["payload"]["reason"]
            if reason != "order_swap_disagreement" and roles.get(event["agent"]) == "review":
                found.refused[reason] += 1
        elif event["kind"] == "cost.estimate":
            found.usd += event["payload"]["usd"]
            found.tokens += event["payload"]["input_tokens"] + event["payload"]["output_tokens"]
    return found


@dataclass(slots=True)
class Report:
    scored: list[Scored]
    swapped: Flips = field(default_factory=Flips)

    @property
    def labelled(self) -> int:
        return sum(len(s.judged) for s in self.scored)

    @property
    def correct(self) -> int:
        return sum(want == got for s in self.scored for _, want, got in s.judged)

    @property
    def unsafe(self) -> int:
        return sum((want, got) in OPPOSITE for s in self.scored for _, want, got in s.judged)

    @property
    def answers(self) -> int:
        return sum(s.answers for s in self.scored)

    @property
    def refused(self) -> int:
        return sum(sum(s.refused.values()) for s in self.scored)

    @property
    def miscited(self) -> int:
        return sum(n for s in self.scored for r, n in s.refused.items() if r in CITATION_REASONS)

    @property
    def statuses_right(self) -> int:
        return sum(s.status == s.expected_status for s in self.scored)

    def rates(self) -> dict[str, tuple[float, int, int]]:
        """Each metric as (value, count, total)."""

        def share(count: int, total: int) -> tuple[float, int, int]:
            return (count / total if total else 0.0, count, total)

        runs = len(self.scored)
        usd = sum(s.usd for s in self.scored)
        tokens = sum(s.tokens for s in self.scored)
        return {
            "verdict_accuracy": share(self.correct, self.labelled),
            "unsafe_verdicts": (float(self.unsafe), self.unsafe, self.labelled),
            "status_accuracy": share(self.statuses_right, runs),
            "citation_validity": share(self.answers - self.miscited, self.answers),
            "rejection_rate": share(self.refused, self.answers),
            "flip_rate": share(self.swapped.flipped, self.swapped.judged),
            "usd_per_pr": (usd / runs if runs else 0.0, 0, runs),
            "tokens_per_pr": (tokens / runs if runs else 0.0, tokens, runs),
        }


def measure(items: Sequence[Item], work: Path, *, mode: str = "replay") -> tuple[Report, list[str]]:
    """Each reviewed pull request run twice: as configured (the scored run), and with every
    verdict judged in both orders (the flip rate). Returns the report and any run failures."""
    scored, swapped, problems = [], [], []
    for item in items:
        normal = run(item, work / item.name / "normal", mode=mode)
        both = run(
            item,
            work / item.name / "swapped",
            mode=mode,
            settings={"REPRO_AGENT_ORDER_SWAP": "all"},
        )
        problems += [
            f"{item.name}: exit {done.exit_code}: {done.output[-500:]}"
            for done in (normal, both)
            if done.exit_code != 0
        ]
        scored.append(score(item, normal.events, expected_status(item.name)))
        swapped.append(flips(both.events))
    return Report(scored, combined(swapped)), problems


PROMPTS: Final = ("reader/1", "reviewer/1", "gap/1", "probe/1", "qa/1")


def rows(report: Report, *, model: str, source: str, date: str) -> list[dict[str, str]]:
    found = []
    for metric, (value, count, total) in report.rates().items():
        found.append(
            {
                "date": date,
                "eval": "verdicts",
                "metric": metric,
                "value": f"{value:.4f}" if metric == "usd_per_pr" else f"{value:.3f}",
                "count": str(count),
                "total": str(total),
                "model": model,
                "prompts": ";".join(PROMPTS),
                "repro_version": __version__,
                "source": source,
            }
        )
    return found


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")


THRESHOLDS: Final = ROOT / "bench" / "data" / "thresholds.toml"


def regressions(report: Report, wanted: Mapping[str, float]) -> list[str]:
    """Each threshold of ``bench/data/thresholds.toml``'s ``[verdicts]`` the report misses."""
    rates = report.rates()
    floors = ("verdict_accuracy", "status_accuracy", "citation_validity")
    found = [
        f"{name} {rates[name][0]:.3f} is below {wanted[name]}"
        for name in floors
        if rates[name][0] < wanted[name]
    ]
    if report.unsafe > wanted["max_unsafe"]:
        found.append(f"{report.unsafe} unsafe verdicts, more than {wanted['max_unsafe']}")
    if rates["flip_rate"][0] > wanted["max_flip_rate"]:
        found.append(f"flip_rate {rates['flip_rate'][0]:.3f} is above {wanted['max_flip_rate']}")
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("live", "record", "replay"), default="replay")
    parser.add_argument("--append", action="store_true", help="append to agent-evals.csv")
    args = parser.parse_args(argv)
    items = [item for item in load() if item.name in REVIEWED]
    with tempfile.TemporaryDirectory(prefix="repro-evals-") as work:
        report, problems = measure(items, Path(work), mode=args.mode)
    for problem in problems:
        _say(f"run failed: {problem}")
    for scored in report.scored:
        _say(f"{scored.name:16} {scored.status} (expected {scored.expected_status})")
        for label, want, got in scored.judged:
            mark = "ok " if want == got else "XX "
            _say(f"  {mark}{label}: {got} (label {want})")
    for metric, (value, count, total) in report.rates().items():
        _say(f"{metric:18} {value:.3f} ({count}/{total})")
    missed = regressions(report, tomllib.loads(THRESHOLDS.read_text("utf-8"))["verdicts"])
    for problem in missed:
        _say(f"below threshold: {problem}")
    if args.append:
        source = "cassettes" if args.mode == "replay" else args.mode
        date = datetime.now(UTC).date().isoformat()
        append_rows(rows(report, model=GROQ_MODEL, source=source, date=date))
    return 1 if problems or missed else 0


if __name__ == "__main__":
    sys.exit(main())
