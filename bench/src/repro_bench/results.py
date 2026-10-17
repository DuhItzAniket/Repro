"""``bench/results/agent-evals.csv``: every agent eval's results, one row per metric (G09).

Each row: the date, the eval (``claims``, ``verdicts``), the metric, its value and what it is a
share of (``count`` of ``total``; for a mean, the sum and how many it is over), the model, the
prompt versions it rests on, Repro's version, and where the agents' answers came from
(``cassettes``, ``live`` or ``record``, with a note when one helps).
"""

import csv
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[3]
RESULTS: Final = ROOT / "bench" / "results" / "agent-evals.csv"
FIELDS: Final = (
    "date",
    "eval",
    "metric",
    "value",
    "count",
    "total",
    "model",
    "prompts",
    "repro_version",
    "source",
)


def append_rows(rows: Iterable[Mapping[str, str]], path: Path = RESULTS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n")
        if new:
            writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path = RESULTS) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as found:
        return list(csv.DictReader(found))
