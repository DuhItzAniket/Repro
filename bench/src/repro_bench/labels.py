"""Human labels: agreement, adjudication, audits and the freeze (J02).

The ground-truth procedure (``docs/paper/EVALUATION_PROTOCOL.md`` §4) ends with two annotators
who label each patch independently, blinded to every system's output, following
``docs/paper/ANNOTATION_GUIDELINE.md``. This module reads what they wrote and does the
arithmetic:

- **Cohen's κ** between the two annotators, overall and per source: κ = (p_o - p_e) / (1 - p_e),
  with p_o the observed agreement and p_e the agreement expected from each annotator's own
  label frequencies [Cohen 1960, doi:10.1177/001316446002000104; the worked example in
  Wikipedia's "Cohen's kappa", checked 2026-10-18, is a test here]. κ is undefined when p_e is
  1 (both annotators used one label throughout): reported as such, never as 1.
- **Adjudication**: an item both annotators labelled alike keeps that label; a disagreement
  needs a resolution, recorded with who agreed to it, or stays unresolved.
- **Audits**: the protocol's random 15% of ``CORRECT_auto`` and of ``INCORRECT_auto``, drawn
  reproducibly from a seed.
- **The freeze**: the label file's SHA-256 and counts, written beside it before any system runs
  on the split (§4.5).

Annotators are named by pseudonyms (``A1``, ``A2``): this repository is public, and a label
file names nobody.
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

LABELS: Final = ("CORRECT", "INCORRECT", "UNCERTAIN")
#: Defect classes for an INCORRECT patch (the guideline defines each).
DEFECTS: Final = (
    "incomplete_fix",
    "wrong_behaviour",
    "regression",
    "api_break",
    "edge_case",
    "performance",
    "other",
)
AUDIT_FRACTION: Final = 0.15
PSEUDONYM: Final = re.compile(r"^A[1-9][0-9]?$")
_ITEM: Final = re.compile(r"^[A-Za-z0-9_.:@/+-]{1,200}$")


class LabelError(Exception):
    """A label file that breaks the format or the protocol."""


@dataclass(frozen=True)
class Label:
    """One annotator's judgement of one item."""

    item: str  # the manifest's instance and patch: ``<instance_id>@<patch_sha256[:12]>``
    annotator: str  # a pseudonym, never a name
    label: str
    defect: str | None = None  # for INCORRECT only
    rationale: str = ""

    def check(self) -> None:
        if not _ITEM.match(self.item):
            raise LabelError(f"item {self.item[:60]!r}")
        if not PSEUDONYM.match(self.annotator):
            raise LabelError(
                f"{self.item}: annotator {self.annotator!r} is not a pseudonym (A1, A2)"
            )
        if self.label not in LABELS:
            raise LabelError(f"{self.item}: label {self.label!r}")
        if self.label == "INCORRECT" and self.defect not in DEFECTS:
            raise LabelError(
                f"{self.item}: an INCORRECT label needs a defect class from the guideline"
            )
        if self.label != "INCORRECT" and self.defect is not None:
            raise LabelError(f"{self.item}: only an INCORRECT label has a defect class")


def item_key(instance_id: str, patch_sha256: str) -> str:
    return f"{instance_id}@{patch_sha256[:12]}"


def read_labels(path: Path) -> list[Label]:
    """An annotator's exported labels (JSONL); one label per item."""
    found: dict[str, Label] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            made = Label(
                str(record["item"]),
                str(record["annotator"]),
                str(record["label"]),
                record.get("defect") or None,
                str(record.get("rationale") or ""),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise LabelError(f"{path.name}:{number}: {exc}") from None
        made.check()
        if made.item in found:
            raise LabelError(f"{path.name}: {made.item} is labelled twice")
        found[made.item] = made
    annotators = {label.annotator for label in found.values()}
    if len(annotators) > 1:
        raise LabelError(f"{path.name} mixes annotators {sorted(annotators)}")
    return list(found.values())


# -- agreement -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Agreement:
    items: int
    observed: float  # p_o
    expected: float  # p_e
    kappa: float | None  # None: undefined (p_e = 1)
    table: Mapping[str, Mapping[str, int]]  # first annotator's label -> second's -> count


def cohen_kappa(pairs: Sequence[tuple[str, str]], categories: Sequence[str] = LABELS) -> Agreement:
    """Cohen's κ for two annotators' labels of the same items."""
    if not pairs:
        raise LabelError("no item has both annotators' labels")
    n = len(pairs)
    table = {a: dict.fromkeys(categories, 0) for a in categories}
    for first, second in pairs:
        if first not in table or second not in table:
            raise LabelError(f"a label outside {list(categories)}: {first!r}, {second!r}")
        table[first][second] += 1
    observed = sum(table[c][c] for c in categories) / n
    firsts = Counter(first for first, _ in pairs)
    seconds = Counter(second for _, second in pairs)
    expected = sum(firsts[c] * seconds[c] for c in categories) / (n * n)
    kappa = None if expected == 1 else (observed - expected) / (1 - expected)
    return Agreement(n, observed, expected, kappa, table)


def paired(first: Iterable[Label], second: Iterable[Label]) -> list[tuple[Label, Label]]:
    """The items both annotators labelled, in item order; two different annotators."""
    a = {label.item: label for label in first}
    b = {label.item: label for label in second}
    names = {label.annotator for label in a.values()} | {label.annotator for label in b.values()}
    if len(names) != 2:  # noqa: PLR2004 - two annotators, by the protocol
        raise LabelError(f"agreement needs two different annotators, not {sorted(names)}")
    return [(a[item], b[item]) for item in sorted(a.keys() & b.keys())]


def agreement_by_source(
    pairs: Sequence[tuple[Label, Label]], source: Mapping[str, str]
) -> dict[str, Agreement]:
    """κ overall (``all``) and for each source an item comes from (§4.3: per source)."""
    groups: dict[str, list[tuple[str, str]]] = {"all": []}
    for first, second in pairs:
        both = (first.label, second.label)
        groups["all"].append(both)
        groups.setdefault(source.get(first.item, "unknown"), []).append(both)
    return {name: cohen_kappa(found) for name, found in sorted(groups.items())}


# -- adjudication --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Decided:
    item: str
    label: str
    defect: str | None
    how: str  # "agreed" or "adjudicated"
    note: str = ""


def adjudicate(
    pairs: Sequence[tuple[Label, Label]], resolutions: Mapping[str, Mapping[str, Any]]
) -> tuple[list[Decided], list[str]]:
    """Final labels, and the items whose disagreement has no resolution yet.

    A resolution is ``{"label", "defect", "note", "agreed_by": ["A1", "A2"]}``: both annotators
    agree to it after discussion (§4.3)."""
    finals, open_items = [], []
    for first, second in pairs:
        if first.label == second.label and first.defect == second.defect:
            finals.append(Decided(first.item, first.label, first.defect, "agreed"))
            continue
        resolved = resolutions.get(first.item)
        if resolved is None:
            open_items.append(first.item)
            continue
        if sorted(resolved.get("agreed_by", [])) != sorted({first.annotator, second.annotator}):
            raise LabelError(f"{first.item}: a resolution is agreed by both annotators")
        made = Label(first.item, first.annotator, str(resolved["label"]), resolved.get("defect"))
        made.check()
        note = str(resolved.get("note", ""))
        finals.append(Decided(first.item, made.label, made.defect, "adjudicated", note))
    return finals, open_items


# -- audits and the freeze -------------------------------------------------------------------------


def audit_sample(items: Iterable[str], seed: str, fraction: float = AUDIT_FRACTION) -> list[str]:
    """A reproducible random ``fraction`` of ``items`` (at least one of a non-empty set): the
    items whose SHA-256 with ``seed`` is smallest."""
    pool = sorted(set(items))
    if not pool:
        return []
    count = max(1, round(len(pool) * fraction))
    ranked = sorted(pool, key=lambda item: hashlib.sha256(f"{seed}\0{item}".encode()).hexdigest())
    return sorted(ranked[:count])


def write_finals(path: Path, finals: Iterable[Decided]) -> dict[str, Any]:
    """Writes the final labels and, beside them, ``<name>.lock.json``: their SHA-256 and counts.
    The lock is what the analysis checks before it runs (§4.5)."""
    rows = sorted(finals, key=lambda f: f.item)
    body = "".join(json.dumps(asdict(f), sort_keys=True) + "\n" for f in rows).encode("utf-8")
    path.write_bytes(body)
    lock = {
        "file": path.name,
        "sha256": hashlib.sha256(body).hexdigest(),
        "items": len(rows),
        "labels": dict(sorted(Counter(f.label for f in rows).items())),
        "adjudicated": sum(1 for f in rows if f.how == "adjudicated"),
    }
    lock_path = path.with_name(f"{path.stem}.lock.json")
    lock_path.write_bytes((json.dumps(lock, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return lock


def check_frozen(path: Path) -> None:
    """Raises ``LabelError`` unless ``path`` is what its lock says (nothing changed since)."""
    lock_path = path.with_name(f"{path.stem}.lock.json")
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LabelError(f"{path.name} has no readable lock: {exc}") from None
    if hashlib.sha256(path.read_bytes()).hexdigest() != lock.get("sha256"):
        raise LabelError(f"{path.name} changed after it was frozen")


# -- the command ----------------------------------------------------------------------------------


def _format(agreement: Agreement) -> str:
    kappa = "undefined" if agreement.kappa is None else f"{agreement.kappa:.3f}"
    return (
        f"n={agreement.items} p_o={agreement.observed:.3f} p_e={agreement.expected:.3f} κ={kappa}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    kappa = commands.add_parser("kappa", help="agreement between two annotators' label files")
    kappa.add_argument("first", type=Path)
    kappa.add_argument("second", type=Path)
    kappa.add_argument("--sources", type=Path, help="JSON: item -> source, for κ per source")
    final = commands.add_parser("adjudicate", help="final labels and their lock")
    final.add_argument("first", type=Path)
    final.add_argument("second", type=Path)
    final.add_argument("--resolutions", type=Path, help="JSON: item -> resolution")
    final.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    try:
        pairs = paired(read_labels(args.first), read_labels(args.second))
        if args.command == "kappa":
            sources = json.loads(args.sources.read_text(encoding="utf-8")) if args.sources else {}
            for name, found in agreement_by_source(pairs, sources).items():
                sys.stdout.write(f"{name}: {_format(found)}\n")
            return 0
        resolutions = (
            json.loads(args.resolutions.read_text(encoding="utf-8")) if args.resolutions else {}
        )
        finals, open_items = adjudicate(pairs, resolutions)
        if open_items:
            sys.stdout.write(f"{len(open_items)} disagreements need a resolution:\n")
            sys.stdout.writelines(f"  {item}\n" for item in open_items)
            return 1
        lock = write_finals(args.out, finals)
        sys.stdout.write(f"{lock['items']} final labels, sha256 {lock['sha256']}\n")
        return 0
    except LabelError as exc:
        sys.stderr.write(f"repro_bench.labels: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
