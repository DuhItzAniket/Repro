"""What a run's agent calls cost, and the most they may spend together (G02).

Costs are the client-side estimates the CLI reports, never billing data (research/04 §1.8). A
run's ledger adds up every call's estimate; with a limit, it also keeps the calls within it.
Before a call starts it reserves what it may spend, its own ``max_budget_usd`` cut down to
what is left, so calls running at once cannot together pass the limit; when it ends, the
reservation is replaced by its estimate. A call that finds nothing left does not start.

The SDK can overshoot ``max_budget_usd`` (research/04 §1.8), so the limit bounds what calls
are allowed, not what they can cost to the cent.
"""

import threading
from dataclasses import dataclass, replace

from repro.agents.backend import Budget, Usage


@dataclass(frozen=True, slots=True)
class Reservation:
    """What one call was allowed: its budget, with ``max_budget_usd`` within the run's limit."""

    budget: Budget
    held_usd: float


class RunLedger:
    """A run's estimated agent spending, and its limit (None: no limit). Thread-safe."""

    def __init__(self, limit_usd: float | None = None) -> None:
        if limit_usd is not None and limit_usd <= 0:
            raise ValueError("a run's agent budget must be positive")
        self.limit_usd = limit_usd
        self._lock = threading.Lock()
        self._spent = 0.0
        self._held = 0.0
        self._calls = 0

    @property
    def spent_usd(self) -> float:
        with self._lock:
            return self._spent

    @property
    def calls(self) -> int:
        with self._lock:
            return self._calls

    def reserve(self, budget: Budget) -> Reservation | None:
        """Holds what a call may spend, or None when the run's limit leaves nothing."""
        with self._lock:
            if self.limit_usd is None:
                return Reservation(budget, 0.0)
            left = self.limit_usd - self._spent - self._held
            if left <= 0:
                return None
            allowed = min(budget.max_budget_usd, left)
            self._held += allowed
            return Reservation(replace(budget, max_budget_usd=allowed), allowed)

    def settle(self, reservation: Reservation, usage: Usage) -> None:
        """Replaces a call's reservation with its estimated cost."""
        with self._lock:
            self._held = max(0.0, self._held - reservation.held_usd)
            self._spent += usage.cost_usd
            self._calls += 1
