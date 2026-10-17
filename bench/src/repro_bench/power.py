"""How many labelled patches the study needs: McNemar's test, approximate and exact (J04).

The primary comparison (``docs/paper/EVALUATION_PROTOCOL.md`` §7) is McNemar's test on the
patches one system flags and the other does not. On the INCORRECT patches this compares catch
rates; on the CORRECT ones, false-flag rates. With ``p_d`` the share of patches the two systems
disagree on, and ``delta`` the difference in their rates, two numbers are computed.

- **The normal approximation** research/06 §4 used [Connor, "Sample Size for Testing
  Differences in Proportions for the Paired-Sample Design", Biometrics 43(1):207-211, 1987,
  doi:10.2307/2531961]:
  ``n = (z_{1-a/2} sqrt(p_d) + z_{1-b} sqrt(p_d - delta^2))^2 / delta^2``.
- **The exact power** of the test the protocol registers. It is the exact binomial test on the
  discordant pairs, two-sided by doubling the smaller tail [McNemar 1947,
  doi:10.1007/BF02295996]. The number of discordant pairs is itself binomial(n, p_d). Among
  them, the first system is the one that flags with probability ``(p_d + delta) / (2 p_d)``.
  The power is summed over both.

The exact test is discrete and conservative, so it needs more patches than the approximation
says. At p_d = 0.2 and delta = 0.1 the approximation gives 155, as research/06 did. The exact
power reaches 0.8 and stays there from 168 on.

    uv run python -m repro_bench.power [--discordance 0.2] [--delta 0.1] [--power 0.8]
"""

import argparse
import math
import sys
from collections.abc import Sequence
from functools import cache
from statistics import NormalDist
from typing import Final

ALPHA: Final = 0.05
POWER: Final = 0.8


def connor(discordance: float, delta: float, *, alpha: float = ALPHA, power: float = POWER) -> int:
    """Patches needed by the normal approximation (rounded up)."""
    _check(discordance, delta)
    z_alpha = NormalDist().inv_cdf(1 - alpha / 2)
    z_beta = NormalDist().inv_cdf(power)
    n = (z_alpha * math.sqrt(discordance) + z_beta * math.sqrt(discordance - delta**2)) ** 2
    return math.ceil(n / delta**2)


def _check(discordance: float, delta: float) -> None:
    if not 0 < discordance <= 1 or not 0 < delta <= discordance:
        raise ValueError("need 0 < delta <= discordance <= 1")


def _pmf(k: int, n: int, p: float) -> float:
    return math.comb(n, k) * p**k * (1 - p) ** (n - k)


@cache
def rejected(discordant: int, alpha: float = ALPHA) -> tuple[int, ...]:
    """The counts ``b`` (of ``discordant`` pairs) the two-sided exact binomial test rejects at
    ``alpha``: twice the smaller tail of binomial(discordant, 1/2) at most ``alpha``."""
    tails = []
    below = 0.0
    for b in range(discordant + 1):
        mass = _pmf(b, discordant, 0.5)
        tails.append((below + mass, 1 - below))  # P(X <= b), P(X >= b)
        below += mass
    return tuple(b for b, (low, high) in enumerate(tails) if min(1.0, 2 * min(low, high)) <= alpha)


def exact_power(n: int, discordance: float, delta: float, *, alpha: float = ALPHA) -> float:
    """The exact test's power with ``n`` patches."""
    _check(discordance, delta)
    first = (discordance + delta) / (2 * discordance)
    total = 0.0
    for discordant in range(n + 1):
        weight = _pmf(discordant, n, discordance)
        if weight < 1e-15:  # noqa: PLR2004 - too small to change the sum
            continue
        total += weight * sum(_pmf(b, discordant, first) for b in rejected(discordant, alpha))
    return total


def exact_n(discordance: float, delta: float, *, alpha: float = ALPHA, power: float = POWER,
            start: int | None = None, limit: int = 5000) -> int:  # fmt: skip
    """The fewest patches whose exact power reaches ``power`` and stays there for the next 10
    (power is not monotone in n for a discrete test)."""
    n = start or connor(discordance, delta, alpha=alpha, power=power)
    while n <= limit:
        if all(exact_power(m, discordance, delta, alpha=alpha) >= power for m in range(n, n + 10)):
            return n
        n += 1
    raise ValueError(f"no n up to {limit} reaches power {power}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--discordance", type=float, nargs="*", default=[0.1, 0.15, 0.2, 0.3])
    parser.add_argument("--delta", type=float, nargs="*", default=[0.05, 0.1, 0.15])
    parser.add_argument("--power", type=float, default=POWER)
    parser.add_argument("--alpha", type=float, default=ALPHA)
    args = parser.parse_args(argv)
    sys.stdout.write("p_d    delta  approx  exact\n")
    for discordance in args.discordance:
        for delta in args.delta:
            if delta > discordance:
                continue
            approx = connor(discordance, delta, alpha=args.alpha, power=args.power)
            exact = exact_n(discordance, delta, alpha=args.alpha, power=args.power)
            sys.stdout.write(f"{discordance:<6} {delta:<6} {approx:>6}  {exact:>5}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
