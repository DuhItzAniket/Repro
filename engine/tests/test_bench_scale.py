"""The scale benchmark's target check (H02). The benchmark itself clones and runs real
repositories (``uv run python -m repro_bench.scale``); here only its verdict on the rows."""

from typing import Any

from repro_bench import scale


def row(**changes: Any) -> dict[str, Any]:
    found: dict[str, Any] = {
        "seconds": 80.0,
        "status": "FLAGGED",
        "selected": 493,
        "evidence": 654,
        "timed": 38,
        "gap_items": 16,
        "missing": 2,
        "provisioned": True,
        "provision_s": 1.6,
        "env_cached": True,
        "map_cached": True,
    }
    return found | changes


def test_a_warm_run_like_the_cold_one_meets_the_targets() -> None:
    cold = row(provision_s=6.8, env_cached=False, map_cached=False)
    assert scale.problems("flask", cold, row()) == []


def test_each_missed_target_is_named() -> None:
    cold = row(env_cached=False, map_cached=False)
    assert scale.problems("flask", cold, row(env_cached=False, map_cached=False)) == [
        "flask warm: the dependencies' environments were built again",
        "flask warm: base's map was made again",
    ]
    assert scale.problems("flask", cold, row(provision_s=5.0, evidence=655, timed=39)) == [
        "flask warm: provisioning took 5.0 s (> 4.6)",
        "flask: evidence 654 cold, 655 warm",  # the tests timed may differ; nothing else
    ]
    assert scale.problems("flask", cold, row(provision_s=5.0), sandbox="docker") == []
    unprovisioned = row(provisioned=False, env_cached=False, map_cached=False)
    assert scale.problems("flask", unprovisioned, unprovisioned) == [
        "flask cold: a side has no environment (the run's log says why)",
        "flask warm: a side has no environment (the run's log says why)",
    ]
    slow = row(seconds=500.0, status="no card (exit 1)")
    assert scale.problems("flask", slow, row()) == [
        "flask cold: no card (exit 1)",
        "flask cold: 500.0 s, half the 900 s limit",
        "flask: status no card (exit 1) cold, FLAGGED warm",
    ]
