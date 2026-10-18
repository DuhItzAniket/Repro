"""The registered analysis (J06), checked against values worked out by hand."""

import json
import math
from pathlib import Path

import pytest

from repro_bench import analysis
from repro_bench.labels import Decided, write_finals


def test_k_answers_reduce_to_a_majority_or_unverifiable() -> None:
    assert analysis.majority(["FLAGGED", "FLAGGED", "VERIFIED"]) == "FLAGGED"
    assert analysis.majority(["FLAGGED", "VERIFIED", "UNVERIFIABLE"]) == "UNVERIFIABLE"
    assert analysis.majority(["VERIFIED", "VERIFIED", "FLAGGED", "FLAGGED"]) == "UNVERIFIABLE"
    assert analysis.majority([]) == "UNVERIFIABLE"
    assert analysis.flipped(["FLAGGED", "VERIFIED"])
    assert not analysis.flipped(["FLAGGED"] * 5)


def test_the_exact_mcnemar_p_value() -> None:
    # 10 and 2 discordant pairs: 2 x P(X <= 2), X ~ binomial(12, 1/2) = 2 x 79 / 4096.
    assert analysis.mcnemar(10, 2) == pytest.approx(158 / 4096)
    assert analysis.mcnemar(2, 10) == analysis.mcnemar(10, 2)
    assert analysis.mcnemar(0, 0) == 1.0
    assert analysis.mcnemar(3, 3) == 1.0


def test_holm_adjusts_in_order_and_stays_monotone() -> None:
    # Sorted 0.01, 0.03, 0.04: x3 = 0.03, x2 = 0.06, x1 = 0.04 raised to 0.06.
    assert analysis.holm({"a": 0.01, "b": 0.04, "c": 0.03}) == pytest.approx(
        {"a": 0.03, "c": 0.06, "b": 0.06}
    )
    assert analysis.holm({"a": 0.6, "b": 0.7}) == {"a": 1.0, "b": 1.0}


def test_rates_show_coverage_and_both_bounding_conversions() -> None:
    found = analysis.rates(["FLAGGED", "FLAGGED", "VERIFIED", "UNVERIFIABLE"])
    assert (found.items, found.covered, found.flagged) == (4, 3, 2)
    assert found.rate == pytest.approx(2 / 3)
    assert found.coverage == 0.75
    assert (found.as_flagged, found.as_verified) == (0.75, 0.5)
    assert math.isnan(analysis.rates([]).rate)


def test_the_bootstrap_resamples_repositories_reproducibly() -> None:
    items = [f"i{n}" for n in range(6)]
    repo = {f"i{n}": f"r{n // 2}" for n in range(6)}

    def share(chosen: list[str]) -> float:
        return sum(1 for i in chosen if i in {"i0", "i1"}) / len(chosen)

    first = analysis.bootstrap(items, repo, share, resamples=500)
    assert first == analysis.bootstrap(items, repo, share, resamples=500)
    assert 0.0 <= first[0] <= first[1] <= 1.0
    one = analysis.bootstrap(items[:2], {"i0": "r", "i1": "r"}, share, resamples=50)
    assert one == (1.0, 1.0)  # one repository: nothing to resample


def test_the_whole_analysis_on_a_small_study(tmp_path: Path) -> None:
    labels = {
        "a": "INCORRECT",
        "b": "INCORRECT",
        "c": "INCORRECT",
        "d": "CORRECT",
        "e": "CORRECT",
        "f": "UNCERTAIN",
    }
    answers = {
        "repro": {
            "a": ["FLAGGED"] * 3,
            "b": ["FLAGGED", "FLAGGED", "VERIFIED"],
            "c": ["UNVERIFIABLE"] * 3,
            "d": ["VERIFIED"] * 3,
            "e": ["VERIFIED"] * 3,
            "f": ["FLAGGED"] * 3,
        },
        "b0": {
            "a": ["VERIFIED"] * 3,
            "b": ["VERIFIED"] * 3,
            "c": ["FLAGGED"] * 3,
            "d": ["FLAGGED"] * 3,
            "e": ["VERIFIED"] * 3,
            "f": ["VERIFIED"] * 3,
        },
    }
    repo = dict.fromkeys(labels, "r1") | {"c": "r2", "d": "r2"}
    result = analysis.analyse(labels, answers, repo, resamples=200)
    assert result["items"] == {"labelled": 6, "decided": 5, "uncertain": 1}
    repro = next(s for s in result["systems"] if s["system"] == "repro")
    assert repro["incorrect"]["rate"] == 1.0  # a and b caught; c not covered
    assert repro["incorrect"]["coverage"] == pytest.approx(2 / 3)
    assert repro["correct"]["rate"] == 0.0
    assert repro["flip_rate"] == pytest.approx(1 / 5)  # b's answers differ
    test = result["mcnemar"]["INCORRECT"]["b0"]
    assert (test["repro_only"], test["other_only"]) == (2, 1)  # a, b; c (UNVERIFIABLE: no flag)
    assert test["p"] == pytest.approx(1.0)

    # From files: a frozen label file, and one answers file per system.
    write_finals(
        tmp_path / "labels.jsonl",
        [
            Decided(i, label, "other" if label == "INCORRECT" else None, "agreed")
            for i, label in labels.items()
        ],
    )
    answer_dir = tmp_path / "answers"
    answer_dir.mkdir()
    for system, by_item in answers.items():
        rows = [{"item": i, "status": s} for i, given in by_item.items() for s in given]
        (answer_dir / f"{system}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
        )
    items = tmp_path / "truth.jsonl"
    items.write_text(
        "".join(json.dumps({"item": i, "instance_id": f"{repo[i]}-1"}) + "\n" for i in labels),
        encoding="utf-8",
    )
    out = tmp_path / "result.json"
    argv = [
        "--labels",
        str(tmp_path / "labels.jsonl"),
        "--answers",
        str(answer_dir),
        "--items",
        str(items),
        "--out",
        str(out),
        "--resamples",
        "100",
    ]
    assert analysis.main(argv) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["items"]["decided"] == 5
