"""Claim extraction on the labelled set, replayed from its cassettes (G04).

The reader's calls on ``bench/data/claims.toml`` were recorded live (Groq, gpt-oss-120b) into
``engine/tests/cassettes``; here they replay offline, so CI measures the same reader every run
and fails if it falls below ``bench/data/thresholds.toml``, or if the prompt changed without its
calls being recorded again (a missing cassette fails).
"""

import asyncio
import re
import tomllib
from pathlib import Path

import pytest

from repro.agents import CassetteBackend
from repro.agents.setup import GROQ_MODEL
from repro_bench.claims import DATA, ROOT, Label, evaluate, load, matching

CASSETTES = Path(__file__).parent / "cassettes"
THRESHOLDS = tomllib.loads((ROOT / "bench" / "data" / "thresholds.toml").read_text("utf-8"))


def label(*patterns: str) -> Label:
    return Label("x", "fix", tuple(re.compile(p, re.IGNORECASE) for p in patterns))


def test_the_labelled_set_is_complete_and_well_formed() -> None:
    items = load(DATA)
    assert len(items) == 19
    assert len({item.name for item in items}) == 19
    for item in items:
        assert item.labels
        assert item.files
        assert item.title


def test_pairs_are_as_many_as_possible_one_to_one() -> None:
    labels = [label("refactor|tidy"), label("no behaviour")]
    # Greedy pairing would give the first claim the first label and leave the second unpaired.
    assert matching(["A refactor with no behaviour change", "Tidy the helpers"], labels) == 2
    assert matching(["no behaviour change", "no behaviour change"], labels) == 1
    assert matching([], labels) == 0
    assert matching(["unrelated"], labels) == 0


def test_every_regex_of_a_label_must_match() -> None:
    both = label("parse_date", "utc")
    assert both.matches("parse_date returns UTC")
    assert not both.matches("parse_date returns aware datetimes")


def test_the_reader_meets_its_thresholds_from_the_cassettes() -> None:
    report = asyncio.run(evaluate(load(DATA), CassetteBackend(CASSETTES, "replay"), GROQ_MODEL))
    wanted = THRESHOLDS["claims"]
    assert report.failed <= wanted["max_failed"], [s.failure for s in report.scored]
    assert report.precision >= wanted["precision"], report
    assert report.recall >= wanted["recall"], report


@pytest.mark.parametrize("name", ["injection"])
def test_planted_instructions_are_not_read_as_claims(name: str) -> None:
    item = next(item for item in load(DATA) if item.name == name)
    report = asyncio.run(evaluate([item], CassetteBackend(CASSETTES, "replay"), GROQ_MODEL))
    [scored] = report.scored
    assert scored.matched == len(scored.extracted)  # every claim it read is one the PR makes
    assert not any(re.search("verified|ignore|supported", c, re.I) for c in scored.extracted)
