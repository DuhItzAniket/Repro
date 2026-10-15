"""Agent dispatch: concurrency from free memory, slots and agent ids (G01; ARCHITECTURE §10.5)."""

import asyncio
import sys

import pytest

from repro.agents import SLOTS, Dispatch, concurrency_for, default_concurrency
from repro.agents.dispatch import free_memory_gib
from repro.orchestrator import JobCancelled


@pytest.mark.parametrize(
    ("free_gib", "expected"),
    [(None, 1), (0.0, 1), (0.4, 1), (1.0, 1), (3.9, 3), (11.99, 11), (12.0, 12), (512.0, 12)],
)
def test_concurrency_is_free_gib_capped_at_twelve_and_at_least_one(
    free_gib: float | None, expected: int
) -> None:
    assert concurrency_for(free_gib) == expected


@pytest.mark.skipif(sys.platform not in ("win32", "linux"), reason="read on Windows and Linux")
def test_free_memory_is_read_on_windows_and_linux() -> None:
    free = free_memory_gib()
    assert free is not None
    assert 0 < free < 1 << 20  # a positive amount, in GiB, not bytes
    assert 1 <= default_concurrency() <= SLOTS


@pytest.mark.parametrize("concurrency", [0, -1, SLOTS + 1])
def test_concurrency_fits_the_slots(concurrency: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 12"):
        Dispatch(concurrency)


def test_agent_ids_count_up_to_the_schemas_limit() -> None:
    dispatch = Dispatch(1)
    ids = [dispatch.agent_id() for _ in range(999)]
    assert ids[:3] == ["a01", "a02", "a03"]
    assert ids[98:100] == ["a99", "a100"]
    assert ids[-1] == "a999"
    with pytest.raises(RuntimeError, match="at most 999"):
        dispatch.agent_id()


def test_an_agent_takes_the_lowest_free_slot() -> None:
    dispatch = Dispatch(4)
    assert [dispatch.try_seat() for _ in range(SLOTS)] == list(range(SLOTS))
    assert dispatch.try_seat() is None  # all twelve are taken
    dispatch.unseat(5)
    dispatch.unseat(2)
    assert dispatch.try_seat() == 2
    assert dispatch.try_seat() == 5
    with pytest.raises(RuntimeError, match="free"):
        Dispatch(1).unseat(0)


def test_at_most_concurrency_agents_run() -> None:
    dispatch = Dispatch(2)
    assert dispatch.try_start()
    assert dispatch.try_start()
    assert not dispatch.try_start()
    dispatch.stop()
    assert dispatch.try_start()
    with pytest.raises(RuntimeError, match="no agent"):
        Dispatch(1).stop()


def test_waiting_gives_up_when_the_job_is_cancelled() -> None:
    dispatch = Dispatch(1)
    for _ in range(SLOTS):
        dispatch.try_seat()
    assert dispatch.try_start()

    def cancelled() -> None:
        raise JobCancelled("review")

    with pytest.raises(JobCancelled):
        asyncio.run(dispatch.seat(cancelled))
    with pytest.raises(JobCancelled):
        asyncio.run(dispatch.start(cancelled))


def test_a_waiting_agent_gets_the_place_another_gives_back() -> None:
    dispatch = Dispatch(1)
    assert dispatch.try_start()

    async def scenario() -> None:
        waiting = asyncio.ensure_future(dispatch.start(lambda: None))
        await asyncio.sleep(0.1)
        assert not waiting.done()
        dispatch.stop()
        await asyncio.wait_for(waiting, 5)

    asyncio.run(scenario())
