"""Random draws: the plugin seeds ``random`` per test, from REPRO_SEED and the node ID."""

import random


def test_draws_a_lot():
    """Consumes the generator's state, which must not change the next test's draws."""
    for _ in range(1000):
        random.random()


def test_reports_its_draw():
    """Fails on purpose: its message carries the draw, for the engine's tests to compare."""
    draw = random.random()
    raise AssertionError(f"draw={draw!r}")
