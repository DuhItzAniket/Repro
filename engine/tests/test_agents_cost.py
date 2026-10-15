"""A run's agent spending and its limit (G02)."""

import threading

import pytest

from repro.agents import Budget, RunLedger, Usage

CALL = Budget(max_turns=8, max_budget_usd=1.0, timeout_s=600)


def test_without_a_limit_every_call_keeps_its_budget_and_is_counted() -> None:
    ledger = RunLedger()
    reservation = ledger.reserve(CALL)
    assert reservation is not None
    assert reservation.budget == CALL
    ledger.settle(reservation, Usage(cost_usd=0.25))
    ledger.settle(ledger.reserve(CALL) or reservation, Usage(cost_usd=0.5))
    assert (ledger.spent_usd, ledger.calls) == (0.75, 2)


def test_a_call_may_spend_only_what_the_run_has_left() -> None:
    ledger = RunLedger(limit_usd=1.5)
    first = ledger.reserve(CALL)
    second = ledger.reserve(CALL)
    assert first is not None
    assert second is not None
    assert (first.budget.max_budget_usd, second.budget.max_budget_usd) == (1.0, 0.5)
    assert ledger.reserve(CALL) is None  # all of it is held
    ledger.settle(first, Usage(cost_usd=0.2))
    third = ledger.reserve(CALL)
    assert third is not None
    assert third.budget.max_budget_usd == pytest.approx(0.8)
    assert third.budget.max_turns == CALL.max_turns


def test_a_spent_run_starts_no_more_calls() -> None:
    ledger = RunLedger(limit_usd=0.5)
    reservation = ledger.reserve(CALL)
    assert reservation is not None
    ledger.settle(reservation, Usage(cost_usd=0.6))  # the SDK can overshoot (research/04 §1.8)
    assert ledger.reserve(CALL) is None
    assert ledger.spent_usd == 0.6


def test_calls_reserving_at_once_never_hold_more_than_the_limit() -> None:
    ledger = RunLedger(limit_usd=3.0)
    held: list[float] = []
    lock = threading.Lock()

    def reserve() -> None:
        reservation = ledger.reserve(CALL)
        if reservation is not None:
            with lock:
                held.append(reservation.budget.max_budget_usd)

    threads = [threading.Thread(target=reserve) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(held) == pytest.approx(3.0)
    assert len(held) == 3


@pytest.mark.parametrize("limit", [0.0, -1.0])
def test_a_limit_is_positive(limit: float) -> None:
    with pytest.raises(ValueError, match="positive"):
        RunLedger(limit_usd=limit)
