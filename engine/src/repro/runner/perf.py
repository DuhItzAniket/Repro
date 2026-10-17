"""The performance pass (D07, research/03 §9): untraced, interleaved timings of the selected
tests that pass on both sides, compared per test.

**Runs.** Base and head alternate in ABBA blocks (``B H H B``), so drift in the machine's speed
(heat, frequency, other load) falls on both sides alike; each block adds two samples per side.
The sample is a test's *call* phase from pytest's report: its body, without its fixtures.

**Per test.** The ratio of head's median to base's, with a 95 % bias-corrected and accelerated
(BCa) bootstrap interval, the two samples resampled independently and the acceleration from the
jackknife of each (the multi-sample form SciPy's ``bootstrap`` implements); and a two-sided
Mann-Whitney U test, its p-values adjusted across tests with Benjamini-Hochberg.

**The floors.** A test is not assessable when both medians are under the timing floor (5 ms:
timer and start-up noise dominate). The noise floor is the larger of a minimum effect (10 %, the
laptop starting point of research/03 §9) and the A/A spread on this machine: the base samples
of each block's first and last position are two runs of the same code, and the 95th percentile
of their ratio's distance from 1, across tests, is what noise alone produces here.

**Verdict.** A regression needs the interval above 1, the ratio at least the noise floor above
1, and an adjusted p-value under 0.05; an improvement the same in the other direction (in ratio
terms, below 1 / (1 + floor)). Anything else is no change.
"""

import hashlib
import math
import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from repro import __version__
from repro.ids import new_evidence_id
from repro.runner.pytest import TestRun
from repro.runner.sides import Side

Verdict = Literal["regression", "improvement", "no_change", "not_assessable"]
#: Samples per side: research/03 §9 asks for at least 10.
REPETITIONS: Final = 10
#: A test whose medians are both under this many seconds is not assessable.
TIMING_FLOOR_S: Final = 0.005
#: The smallest relative change ever reported (research/03 §9: 10 % on laptops).
MIN_EFFECT: Final = 0.10
CONFIDENCE: Final = 0.95
ALPHA: Final = 0.05
RESAMPLES: Final = 9999
#: Tests named in a not-assessable item's detail (all are in its targets).
LISTED: Final = 5
_NORMAL: Final = statistics.NormalDist()


def abba(blocks: int) -> list[str]:
    """The order of runs: ``base head head base`` per block."""
    return ["base", "head", "head", "base"] * blocks


def _quantile(ordered: Sequence[float], q: float) -> float:
    """Linear interpolation between order statistics (NumPy's default ``linear`` method)."""
    position = q * (len(ordered) - 1)
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _ratio(base: Sequence[float], head: Sequence[float]) -> float:
    return statistics.median(head) / statistics.median(base)


def bca_ratio_interval(
    base: Sequence[float],
    head: Sequence[float],
    *,
    rng: random.Random,
    resamples: int = RESAMPLES,
    confidence: float = CONFIDENCE,
) -> tuple[float, float, float]:
    """The ratio of medians (head / base) and its BCa bootstrap interval."""
    observed = _ratio(base, head)
    draws = sorted(
        _ratio(rng.choices(base, k=len(base)), rng.choices(head, k=len(head)))
        for _ in range(resamples)
    )
    below = sum(d < observed for d in draws) + 0.5 * sum(d == observed for d in draws)
    share = min(max(below / resamples, 0.5 / resamples), 1 - 0.5 / resamples)
    z0 = _NORMAL.inv_cdf(share)
    # The acceleration: each sample's jackknife, the other sample whole (Efron's multi-sample a).
    numerator = denominator = 0.0
    for left_out, other, is_base in ((base, head, True), (head, base, False)):
        n = len(left_out)
        values = []
        for i in range(n):
            rest = [*left_out[:i], *left_out[i + 1 :]]
            values.append(_ratio(rest, other) if is_base else _ratio(other, rest))
        mean = statistics.fmean(values)
        spread = [(n - 1) * (mean - v) for v in values]
        numerator += sum(u**3 for u in spread) / n**3
        denominator += sum(u**2 for u in spread) / n**2
    acceleration = numerator / (6 * denominator**1.5) if denominator > 0 else 0.0
    tail = (1 - confidence) / 2

    def corrected(z: float) -> float:
        shifted = z0 + z
        return _NORMAL.cdf(z0 + shifted / (1 - acceleration * shifted))

    low = _quantile(draws, corrected(_NORMAL.inv_cdf(tail)))
    high = _quantile(draws, corrected(_NORMAL.inv_cdf(1 - tail)))
    return observed, low, high


def mann_whitney_p(base: Sequence[float], head: Sequence[float]) -> float:
    """Two-sided p-value of the Mann-Whitney U test: the normal approximation with the tie and
    continuity corrections (SciPy's ``method="asymptotic"``)."""
    n1, n2 = len(base), len(head)
    pooled = sorted([(v, 0) for v in base] + [(v, 1) for v in head])
    ranks = [0.0] * len(pooled)
    ties = 0.0
    i = 0
    while i < len(pooled):
        j = i
        while j + 1 < len(pooled) and pooled[j + 1][0] == pooled[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j) / 2 + 1
        t = j - i + 1
        ties += t**3 - t
        i = j + 1
    r1 = sum(rank for rank, (_, side) in zip(ranks, pooled, strict=True) if side == 0)
    u1 = r1 - n1 * (n1 + 1) / 2
    n = n1 + n2
    variance = n1 * n2 / 12 * ((n + 1) - ties / (n * (n - 1)))
    if variance <= 0:
        return 1.0
    z = (abs(u1 - n1 * n2 / 2) - 0.5) / math.sqrt(variance)
    return min(1.0, 2 * (1 - _NORMAL.cdf(max(z, 0.0))))


def benjamini_hochberg(pvalues: Sequence[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values, in the input's order."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        index = order[rank - 1]
        running = min(running, pvalues[index] * m / rank)
        adjusted[index] = running
    return adjusted


def _nearest_rank(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


@dataclass(frozen=True, slots=True)
class Samples:
    """One test's call-phase times, in run order, per side."""

    test: str
    base: tuple[float, ...]
    head: tuple[float, ...]


def aa_noise(samples: Sequence[Samples]) -> float:
    """The A/A spread: the 95th percentile, across tests, of how far the ratio of medians of
    base's first-position samples to its last-position ones lies from 1 (0 with no tests)."""
    spreads = []
    for item in samples:
        first, last = item.base[0::2], item.base[1::2]
        if first and last and statistics.median(first) > 0:
            spreads.append(abs(_ratio(first, last) - 1))
    return _nearest_rank(spreads, 0.95) if spreads else 0.0


@dataclass(frozen=True, slots=True)
class PerfDiff:
    test: str
    verdict: Verdict
    ratio: float
    ci_low: float
    ci_high: float
    noise_floor: float
    p_value: float  # Mann-Whitney, Benjamini-Hochberg adjusted
    base_median_s: float
    head_median_s: float
    repetitions: int

    def summary(self) -> str:
        change = (self.ratio - 1) * 100
        word = "slower" if change >= 0 else "faster"
        return (
            f"{self.verdict}: {self.test}: head {abs(change):.0f}% {word} "
            f"(95% CI {(self.ci_low - 1) * 100:+.0f}% to {(self.ci_high - 1) * 100:+.0f}%), "
            f"noise floor {self.noise_floor * 100:.0f}%"
        )[:280]

    def evidence(self, run_id: str) -> dict[str, Any]:
        """The ``perf_diff`` evidence record (the writer adds ``seq``)."""
        return {
            "id": new_evidence_id(),
            "run_id": run_id,
            "type": "perf_diff",
            "targets": [{"test": self.test}],
            "summary": self.summary(),
            "data": {
                "verdict": self.verdict,
                "ratio": self.ratio,
                "ci_low": self.ci_low,
                "ci_high": self.ci_high,
                "noise_floor": self.noise_floor,
                "p_value": self.p_value,
                "base_median_s": self.base_median_s,
                "head_median_s": self.head_median_s,
                "repetitions": self.repetitions,
                "confidence": CONFIDENCE,
            },
            "artifacts": [],
            "stability": "stable",
            "origin": "introduced" if self.verdict in ("regression", "improvement") else "n/a",
            "produced_by": {"component": "repro.runner.perf", "version": __version__},
        }

    def payload(self, evidence_id: str) -> dict[str, Any]:
        """The ``diff.perf`` payload."""
        return {
            "evidence_id": evidence_id,
            "ratio": self.ratio,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "noise_floor": self.noise_floor,
            "verdict": self.verdict,
            "repetitions": self.repetitions,
        }


def _rng(test: str) -> random.Random:
    seed = int.from_bytes(hashlib.sha256(test.encode()).digest()[:8], "big")
    return random.Random(seed)  # noqa: S311 - resampling, reproducible per test; not secrets


def assess(
    samples: Sequence[Samples],
    *,
    timing_floor_s: float = TIMING_FLOOR_S,
    min_effect: float = MIN_EFFECT,
    resamples: int = RESAMPLES,
) -> tuple[list[PerfDiff], list[str]]:
    """Each assessable test's comparison, and the tests under the timing floor."""
    usable = [s for s in samples if s.base and s.head]
    timed = [
        s
        for s in usable
        if max(statistics.median(s.base), statistics.median(s.head)) >= timing_floor_s
        and statistics.median(s.base) > 0
    ]
    too_fast = sorted(s.test for s in usable if s not in timed)
    floor = max(min_effect, aa_noise(timed))
    adjusted = benjamini_hochberg([mann_whitney_p(s.base, s.head) for s in timed])
    found = []
    for item, p_value in zip(timed, adjusted, strict=True):
        ratio, low, high = bca_ratio_interval(
            item.base, item.head, rng=_rng(item.test), resamples=resamples
        )
        significant = p_value < ALPHA
        verdict: Verdict = "no_change"
        if significant and low > 1 and ratio >= 1 + floor:
            verdict = "regression"
        elif significant and high < 1 and ratio <= 1 / (1 + floor):
            verdict = "improvement"
        found.append(
            PerfDiff(
                item.test,
                verdict,
                ratio,
                low,
                high,
                floor,
                p_value,
                statistics.median(item.base),
                statistics.median(item.head),
                min(len(item.base), len(item.head)),
            )
        )
    return found, too_fast


def not_assessable(tests: Sequence[str], timing_floor_s: float = TIMING_FLOOR_S) -> dict[str, Any]:
    """One ``perf_not_assessable`` item for the tests too fast to time."""
    shown = ", ".join(tests[:LISTED]) + (
        f" and {len(tests) - LISTED} more" if len(tests) > LISTED else ""
    )
    return {
        "missing": {
            "reason": "perf_not_assessable",
            "targets": [{"test": test} for test in tests],
            "detail": (
                f"{len(tests)} {'test runs' if len(tests) == 1 else 'tests run'} in under "
                f"{timing_floor_s * 1000:g} ms on both sides, "
                f"too fast to time: {shown}"
            )[:1000],
            "resolution": "A benchmark that runs the changed code long enough to time",
        }
    }


@dataclass(frozen=True, slots=True)
class TimingRun:
    side: str
    repetition: int  # this side's count, from 1
    record: TestRun


def time_tests(
    base: Side,
    head: Side,
    tests: Sequence[str],
    *,
    repetitions: int = REPETITIONS,
    observe: Callable[[TimingRun], None] | None = None,
    stop: Callable[[], bool] | None = None,
) -> tuple[list[Samples], list[TimingRun]]:
    """Runs ``tests`` untraced in ABBA blocks until each side has ``repetitions`` runs; each
    test's call-phase times per side, in run order, and the runs themselves."""
    sides = {"base": base, "head": head}
    counts = {"base": 0, "head": 0}
    times: dict[str, dict[str, list[float]]] = {t: {"base": [], "head": []} for t in tests}
    runs = []
    for name in abba(max(1, math.ceil(repetitions / 2))):
        counts[name] += 1
        done = sides[name].run(list(tests), stop=stop)
        timing = TimingRun(name, counts[name], done)
        runs.append(timing)
        for test in tests:
            found = done.results.tests.get(test)
            if found is not None and found.outcome == "passed" and found.call_s is not None:
                times[test][name].append(found.call_s)
        if observe is not None:
            observe(timing)
    samples = [
        Samples(test, tuple(times[test]["base"]), tuple(times[test]["head"])) for test in tests
    ]
    return samples, runs
