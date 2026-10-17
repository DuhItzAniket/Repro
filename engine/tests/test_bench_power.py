"""The study's sample size (J04): McNemar's test, approximate and exact."""

import pytest

from repro_bench import power


def test_the_approximation_gives_research_06s_number() -> None:
    # research/06 §4: p_d 0.2, a 10-point difference, alpha 0.05, power 0.8: about 155.
    assert power.connor(0.2, 0.1) == 155


def test_the_exact_tests_rejection_region() -> None:
    # binomial(10, 1/2): P(X <= 1) = 11/1024, doubled 0.021; P(X <= 2) = 56/1024, doubled 0.109.
    assert power.rejected(10) == (0, 1, 9, 10)
    assert power.rejected(5) == ()  # five discordant pairs can never reach 0.05


def test_the_exact_test_needs_more_patches_than_the_approximation() -> None:
    assert power.exact_power(155, 0.2, 0.1) < 0.8
    assert power.exact_n(0.2, 0.1) == 168
    assert power.exact_power(168, 0.2, 0.1) >= 0.8
    assert power.exact_power(400, 0.2, 0.1) > 0.95


def test_impossible_settings_are_refused() -> None:
    with pytest.raises(ValueError, match="delta <= discordance"):
        power.connor(0.1, 0.2)
