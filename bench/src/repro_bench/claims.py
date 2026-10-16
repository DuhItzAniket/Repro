"""Claim extraction, measured: the reader agent on the labelled claim set (G04).

``bench/data/claims.toml`` holds each pull request's text, the files its change touches and
every claim the text makes, labelled by hand with the regexes a claim must match. The reader
runs on each text through any ``LLMBackend`` (live, recording cassettes, or replaying them),
and its claims are paired with the labels one to one, as many pairs as possible: precision is
the share of its claims that are paired, recall the share of labels. A call that fails counts
as no claims (its labels are missed) and is reported.

    uv run python -m repro_bench.claims --mode replay --cassettes engine/tests/cassettes
"""

import argparse
import asyncio
import csv
import re
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from repro import __version__
from repro.agents import CassetteBackend, LLMBackend
from repro.agents.openai_compat import Endpoint, OpenAICompatibleBackend
from repro.agents.prompts import load_prompt
from repro.agents.reader import PrText, read_claims, reader_request
from repro.agents.setup import GROQ_MODEL

ROOT: Final = Path(__file__).resolve().parents[3]
DATA: Final = ROOT / "bench" / "data" / "claims.toml"
RESULTS: Final = ROOT / "bench" / "results" / "agent-evals.csv"
FIELDS: Final = (
    "date",
    "eval",
    "model",
    "prompt_version",
    "repro_version",
    "items",
    "labels",
    "extracted",
    "matched",
    "precision",
    "recall",
    "failed",
    "source",
)


@dataclass(frozen=True, slots=True)
class Label:
    text: str
    kind: str
    patterns: tuple[re.Pattern[str], ...]

    def matches(self, claim: str) -> bool:
        return all(pattern.search(claim) for pattern in self.patterns)


@dataclass(frozen=True, slots=True)
class Item:
    name: str
    title: str
    description: str
    files: tuple[str, ...]
    labels: tuple[Label, ...]

    def pr(self) -> PrText:
        return PrText.of(title=self.title, description=self.description, commits=[])


@dataclass(frozen=True, slots=True)
class Scored:
    """One pull request: what the reader extracted and which labels it matched."""

    name: str
    extracted: tuple[str, ...]
    matched: int
    labels: int
    failure: str | None = None


@dataclass(frozen=True, slots=True)
class Report:
    scored: tuple[Scored, ...]

    @property
    def labels(self) -> int:
        return sum(s.labels for s in self.scored)

    @property
    def extracted(self) -> int:
        return sum(len(s.extracted) for s in self.scored)

    @property
    def matched(self) -> int:
        return sum(s.matched for s in self.scored)

    @property
    def precision(self) -> float:
        return self.matched / self.extracted if self.extracted else 0.0

    @property
    def recall(self) -> float:
        return self.matched / self.labels if self.labels else 0.0

    @property
    def failed(self) -> int:
        return sum(1 for s in self.scored if s.failure is not None)


def load(path: Path = DATA) -> list[Item]:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    items = []
    for pr in document["pr"]:
        labels = tuple(
            Label(
                claim["text"],
                claim["kind"],
                tuple(re.compile(p, re.IGNORECASE) for p in claim["match"]),
            )
            for claim in pr["claims"]
        )
        items.append(Item(pr["name"], pr["title"], pr["description"], tuple(pr["files"]), labels))
    return items


def matching(claims: Sequence[str], labels: Sequence[Label]) -> int:
    """The most claim-label pairs where each claim matches its label, each used once
    (Kuhn's augmenting paths: a maximum bipartite matching)."""
    edges = [[j for j, label in enumerate(labels) if label.matches(c)] for c in claims]
    owner: dict[int, int] = {}

    def assign(i: int, seen: set[int]) -> bool:
        for j in edges[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in owner or assign(owner[j], seen):
                owner[j] = i
                return True
        return False

    return sum(1 for i in range(len(claims)) if assign(i, set()))


async def score(item: Item, backend: LLMBackend, model: str) -> Scored:
    prompt = load_prompt("reader")
    request = reader_request(item.pr(), item.files, prompt, model)
    result = await backend.run(request)
    if result.outcome != "ok":
        failure = f"{result.outcome}: {result.detail}"[:200]
        return Scored(item.name, (), 0, len(item.labels), failure)
    sources = [source for source, _ in item.pr().parts]
    claims = tuple(c["text"] for c in read_claims(result.structured, item.files, sources))
    return Scored(item.name, claims, matching(claims, item.labels), len(item.labels))


async def evaluate(items: Sequence[Item], backend: LLMBackend, model: str) -> Report:
    """Each item in turn (one call at a time: the free API limits are per minute)."""
    return Report(tuple([await score(item, backend, model) for item in items]))


def backend_for(mode: str, cassettes: Path) -> LLMBackend:
    if mode == "replay":
        return CassetteBackend(cassettes, "replay")
    live = OpenAICompatibleBackend(Endpoint.groq())
    return CassetteBackend(cassettes, "record", live) if mode == "record" else live


def row(report: Report, *, model: str, source: str, date: str) -> dict[str, str]:
    return {
        "date": date,
        "eval": "claims",
        "model": model,
        "prompt_version": load_prompt("reader").prompt_version,
        "repro_version": __version__,
        "items": str(len(report.scored)),
        "labels": str(report.labels),
        "extracted": str(report.extracted),
        "matched": str(report.matched),
        "precision": f"{report.precision:.3f}",
        "recall": f"{report.recall:.3f}",
        "failed": str(report.failed),
        "source": source,
    }


def append(result: dict[str, str], path: Path = RESULTS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n")
        if new:
            writer.writeheader()
        writer.writerow(result)


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("live", "record", "replay"), default="replay")
    parser.add_argument("--cassettes", type=Path, default=ROOT / "engine" / "tests" / "cassettes")
    parser.add_argument("--model", default=GROQ_MODEL)
    parser.add_argument("--append", action="store_true", help=f"append the result to {RESULTS}")
    args = parser.parse_args(argv)
    report = asyncio.run(evaluate(load(), backend_for(args.mode, args.cassettes), args.model))
    for scored in report.scored:
        status = (
            scored.failure
            or f"{scored.matched}/{scored.labels} labels, {len(scored.extracted)} claims"
        )
        _say(f"{scored.name:16} {status}")
        for claim in scored.extracted:
            _say(f"{'':16}   - {claim}")
    _say(
        f"precision {report.precision:.3f} ({report.matched}/{report.extracted}), "
        f"recall {report.recall:.3f} ({report.matched}/{report.labels}), failed {report.failed}"
    )
    if args.append:
        source = "cassettes" if args.mode == "replay" else "live"
        date = datetime.now(UTC).date().isoformat()
        append(row(report, model=args.model, source=source, date=date))
    return 0


if __name__ == "__main__":
    sys.exit(main())
