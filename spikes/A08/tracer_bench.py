"""A08 spike: overhead of a sys.monitoring tracer shaped like Repro's design (ADR-0005).

Stdlib only; runs on Python 3.12+. Two modes:

  python tracer_bench.py run --config C --workload W --repeats R   (one config, one process)
  python tracer_bench.py drive --rounds N --repeats R              (all configs, interleaved)

Each configuration runs in a fresh process, because DISABLE state and tool ids persist for the
life of an interpreter. The driver interleaves configurations across rounds so that CPU
frequency drift does not favour one of them, and reports the median of per-round medians.

Configurations:
  none              no monitoring (baseline)
  disable_all       PY_START registered globally; every code object returns DISABLE
                    (cost when Repro is loaded but nothing is a target)
  target_dispatch   PY_START + local PY_RETURN on the target only, callbacks do nothing
                    (pure dispatch cost of keeping a target instrumented)
  target_capture    as target_dispatch, plus argument capture from the callee frame and a
                    structural, hash-stable encoding of arguments and return values
                    (Repro's intended steady state)
  target_capture_budget
                    target_capture for the first CAPTURE_BUDGET calls, then DISABLE
                    (the budgeted strategy from ADR-0005)
  settrace_dispatch sys.settrace call/return tracing of the target, callbacks do nothing
  settrace_capture  the same capture implemented with sys.settrace (the pre-PEP-669 way)
"""

import argparse
import gc
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

TOOL_ID = 4  # ADR-0005 claim order starts at 4 (0 = debugger, 1 = coverage)
CONFIGS = (
    "none",
    "disable_all",
    "target_dispatch",
    "target_capture",
    "target_capture_budget",
    "settrace_dispatch",
    "settrace_capture",
)
CAPTURE_BUDGET = 200  # fully encoded calls per target before DISABLE (ADR-0005 budgets)


# -- workloads ---------------------------------------------------------------------------------
def fib(n: int) -> int:
    return n if n < 2 else fib(n - 1) + fib(n - 2)


def normalise_record(record: dict[str, Any]) -> dict[str, Any]:
    name = record["name"].strip().lower()
    tags = sorted(set(record["tags"]))
    return {"name": name, "tags": tags, "total": sum(record["values"])}


RECORDS = [
    {"name": f" Item{i} ", "tags": ["b", "a", "b"], "values": list(range(i % 7))}
    for i in range(20_000)
]


def records_workload() -> list[dict[str, Any]]:
    return [normalise_record(r) for r in RECORDS]


FIB_N = 22
WORKLOADS: dict[str, tuple[Callable[[], object], Any, int]] = {
    # name: (callable, target code object, number of target calls per run)
    "fib": (lambda: fib(FIB_N), fib.__code__, 2 * 28657 - 1),  # 2*F(23)-1 calls
    "records": (records_workload, normalise_record.__code__, len(RECORDS)),
}


# -- structural encoder (never calls user __repr__/__eq__) -------------------------------------
def encode(value: Any, depth: int = 0) -> bytes:  # noqa: PLR0911
    if depth > 6:
        return b"T"
    t = type(value)
    if value is None:
        return b"N"
    if t is bool:
        return b"B1" if value else b"B0"
    if t is int:
        return b"I" + str(value).encode()
    if t is float:
        return b"F" + value.hex().encode()
    if t is str:
        return b"S" + str(len(value)).encode() + b":" + value.encode("utf-8", "surrogatepass")
    if t in (list, tuple):
        return b"L[" + b",".join(encode(v, depth + 1) for v in value) + b"]"
    if t is dict:
        return (
            b"D{"
            + b",".join(
                encode(k, depth + 1) + b"=" + encode(v, depth + 1) for k, v in value.items()
            )
            + b"}"
        )
    if t in (set, frozenset):
        return b"E{" + b",".join(sorted(encode(v, depth + 1) for v in value)) + b"}"
    return b"O" + f"{t.__module__}.{t.__qualname__}".encode()


def digest(value: Any) -> bytes:
    return hashlib.blake2b(encode(value), digest_size=16).digest()


# -- configurations ---------------------------------------------------------------------------
def install(config: str, target: Any) -> Callable[[], None]:
    """Install instrumentation; return an uninstall function."""
    if config == "none":
        return lambda: None
    if config.startswith("settrace_"):
        return _install_settrace(target, capture=config == "settrace_capture")
    mon = sys.monitoring
    events = mon.events
    mon.use_tool_id(TOOL_ID, "repro-spike")
    records: list[bytes] = []
    argnames = target.co_varnames[: target.co_argcount + target.co_kwonlyargcount]
    capture = config in {"target_capture", "target_capture_budget"}
    budget = CAPTURE_BUDGET if config == "target_capture_budget" else None
    calls = [0]

    def on_start(code: Any, offset: int) -> Any:
        if code is not target or config == "disable_all":
            return mon.DISABLE
        calls[0] += 1
        if budget is not None and calls[0] > budget:
            return mon.DISABLE  # budget spent: this location never fires again
        if capture:
            f_locals = sys._getframe(1).f_locals
            records.append(digest({name: f_locals[name] for name in argnames}))
        return None

    def on_return(code: Any, offset: int, retval: Any) -> Any:
        if budget is not None and calls[0] > budget:
            return mon.DISABLE
        if capture:
            records.append(digest(retval))
        return None

    mon.register_callback(TOOL_ID, events.PY_START, on_start)
    mon.register_callback(TOOL_ID, events.PY_RETURN, on_return)
    mon.set_events(TOOL_ID, events.PY_START)
    if config != "disable_all":
        mon.set_local_events(TOOL_ID, target, events.PY_RETURN)

    def uninstall() -> None:
        mon.set_events(TOOL_ID, 0)
        mon.set_local_events(TOOL_ID, target, 0)
        mon.register_callback(TOOL_ID, events.PY_START, None)
        mon.register_callback(TOOL_ID, events.PY_RETURN, None)
        mon.free_tool_id(TOOL_ID)
        records.clear()

    return uninstall


def _install_settrace(target: Any, *, capture: bool) -> Callable[[], None]:
    records: list[bytes] = []
    argnames = target.co_varnames[: target.co_argcount + target.co_kwonlyargcount]

    def local(frame: Any, event: str, arg: Any) -> Any:
        if capture and event == "return":
            records.append(digest(arg))
        return local

    def global_trace(frame: Any, event: str, arg: Any) -> Any:
        if event != "call" or frame.f_code is not target:
            return None
        if capture:
            records.append(digest({name: frame.f_locals[name] for name in argnames}))
        return local

    sys.settrace(global_trace)

    def uninstall() -> None:
        sys.settrace(None)
        records.clear()

    return uninstall


def run(config: str, workload: str, repeats: int) -> dict[str, Any]:
    fn, target, _calls = WORKLOADS[workload]
    fn()  # warm-up without instrumentation (imports, caches)
    uninstall = install(config, target)
    try:
        fn()  # warm-up with instrumentation (DISABLE takes effect, local events set)
        samples = []
        for _ in range(repeats):
            gc.collect()
            start = time.perf_counter_ns()
            fn()
            samples.append(time.perf_counter_ns() - start)
    finally:
        uninstall()
    return {"config": config, "workload": workload, "samples_ns": samples}


# -- driver -----------------------------------------------------------------------------------
def drive(rounds: int, repeats: int) -> dict[str, Any]:
    medians: dict[str, dict[str, list[float]]] = {w: {c: [] for c in CONFIGS} for w in WORKLOADS}
    for _ in range(rounds):
        for workload in WORKLOADS:
            for config in CONFIGS:
                out = subprocess.run(
                    [
                        sys.executable,
                        __file__,
                        "run",
                        "--config",
                        config,
                        "--workload",
                        workload,
                        "--repeats",
                        str(repeats),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
                result = json.loads(out)
                medians[workload][config].append(statistics.median(result["samples_ns"]))
    summary: dict[str, Any] = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "system": platform.system(),
        "machine": platform.machine(),
        "rounds": rounds,
        "repeats": repeats,
        "workloads": {},
    }
    for workload, (_fn, _target, calls) in WORKLOADS.items():
        base = statistics.median(medians[workload]["none"])
        rows = {}
        for config in CONFIGS:
            values = medians[workload][config]
            median = statistics.median(values)
            rows[config] = {
                "median_ms": round(median / 1e6, 3),
                "round_medians_ms": [round(v / 1e6, 3) for v in values],
                "ratio_vs_none": round(median / base, 3),
                "overhead_ns_per_target_call": round((median - base) / calls, 1),
            }
        summary["workloads"][workload] = {"target_calls": calls, "configs": rows}
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    r = sub.add_parser("run")
    r.add_argument("--config", choices=CONFIGS, required=True)
    r.add_argument("--workload", choices=list(WORKLOADS), required=True)
    r.add_argument("--repeats", type=int, default=15)
    d = sub.add_parser("drive")
    d.add_argument("--rounds", type=int, default=3)
    d.add_argument("--repeats", type=int, default=15)
    args = parser.parse_args()
    if args.mode == "run":
        result = run(args.config, args.workload, args.repeats)
    else:
        result = drive(args.rounds, args.repeats)
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
