"""Repro's pytest plugin (D04), loaded with ``-p repro_pytest`` inside the sandbox.

The standard library and pytest only, and Python 3.12 to 3.15: it runs in the target's
environment, never in Repro's (ARCHITECTURE §3). It talks to the engine through files in
``REPRO_OUT``:

- ``results.jsonl``: one JSON object per line, written as the run goes (a crash still leaves
  what came before): ``{"kind": "collected", ...}`` per test collected, with where its function
  is; ``{"kind": "test", ...}`` per test run; ``{"kind": "collect_error", ...}`` per module that
  failed to collect; with ``REPRO_MAP=1``, ``{"kind": "map", ...}`` per test, the functions it
  ran; and ``{"kind": "session", ...}`` last.

A function is a *place*: its file relative to ``REPRO_ROOT`` (the snapshot), its code object's
qualified name and first line, which the engine turns into a symbol. Code outside the root (the
standard library, installed packages) has no place and is not recorded.

The map (D05) uses ``sys.monitoring``: PY_START is recorded once per function and test, then
disabled at that place until the next test restarts events, so a function already seen costs
nothing more in that test. Repro takes tool ID 4, 3, 2 or 5, whichever is free first, and leaves
0 (debuggers) and 1 (coverage) to their owners; with none free the map is reported unavailable.

Determinism: before each test, ``random`` is seeded from ``REPRO_SEED`` and the test's node ID,
so a test's random draws do not depend on which tests ran before it. With ``REPRO_NET_GUARD=1``
TCP connections to anything but the loopback interface, and resolving any name but
``localhost``, fail at once, so a test that needs the network fails the same way every time and
on every isolation level, instead of hanging or flaking. It detects; it is not a boundary
(ADR-0004): UDP ``sendto`` and C extensions are not stopped, only recorded by the audit hook
beside this file.
"""
# ruff: noqa: PTH109, PTH118 - os.path on purpose: plain strings, compared once per function

import errno
import hashlib
import inspect
import ipaddress
import json
import os
import platform
import random
import socket
import sys
from pathlib import Path
from typing import Any

import pytest

_OUT = os.environ.get("REPRO_OUT")
_SEED = int(os.environ.get("REPRO_SEED", "0") or 0)
_LONGREPR = 2000
#: sys.monitoring tool IDs tried in turn: 0 (debuggers) and 1 (coverage) are left alone.
_TOOL_IDS = (4, 3, 2, 5)
_STATE: dict[str, Any] = {"file": None, "tests": {}, "places": None, "collector": None}

Place = tuple[str, str, int]


def _write(record: dict[str, Any]) -> None:
    handle = _STATE["file"]
    if handle is not None:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()


def _seed_for(nodeid: str) -> int:
    digest = hashlib.sha256(f"{_SEED}:{nodeid}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _host(value: object) -> str | None:
    if isinstance(value, bytes):
        return value.decode("ascii", "replace")
    return value if isinstance(value, str) else None


def _ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return None


def _guard_network() -> None:
    """Connections to anything but loopback fail at once, and so does resolving any name but
    ``localhost``; each refusal is raised as the audit event it stands for, so the hook records
    it. Detection evidence and a fixed failure, not a boundary (L3 has no network at all)."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo

    def check(sock: socket.socket, address: Any) -> None:
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            return
        host = _host(address[0]) if isinstance(address, tuple) and address else None
        ip = _ip(host) if host is not None else None
        if host == "localhost" or (ip is not None and ip.is_loopback):
            return
        sys.audit("socket.connect", sock, address)
        raise OSError(errno.ENETUNREACH, f"network access is off in Repro's sandbox: {address!r}")

    def connect(self: socket.socket, address: Any) -> None:
        check(self, address)
        return original_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        check(self, address)
        return original_connect_ex(self, address)

    def getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        name = _host(host)
        if name is not None and name != "localhost" and _ip(name) is None:
            sys.audit("socket.getaddrinfo", host, port, 0, 0, 0)
            raise socket.gaierror(
                socket.EAI_NONAME, f"name resolution is off in Repro's sandbox: {name!r}"
            )
        return original_getaddrinfo(host, port, *args, **kwargs)

    socket.socket.connect = connect  # type: ignore[method-assign,assignment]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign,assignment]
    socket.getaddrinfo = getaddrinfo


class _Places:
    """Each code object's place, or None outside the root; computed once per code object (keyed
    by identity and held, since equal code objects in two files compare equal)."""

    def __init__(self, root: str) -> None:
        self.root = os.path.join(os.path.realpath(root), "")
        self.folded = os.path.normcase(self.root)
        self.known: dict[int, tuple[Any, Place | None]] = {}

    def of(self, code: Any) -> Place | None:
        known = self.known.get(id(code))
        if known is not None:
            return known[1]
        place = None
        filename = code.co_filename
        if filename and not filename.startswith("<"):
            real = os.path.realpath(filename)
            if os.path.normcase(real).startswith(self.folded):
                relative = real[len(self.root) :].replace(os.sep, "/")
                place = (relative, code.co_qualname, code.co_firstlineno)
        self.known[id(code)] = (code, place)
        return place


class _Collector:
    """The places each test runs: PY_START once per function and test, then DISABLE."""

    def __init__(self, places: _Places, tool: int) -> None:
        self.places = places
        self.tool = tool
        self.current: set[Place] | None = None

    def started(self, code: Any, _offset: int) -> Any:
        current = self.current
        if current is not None:
            place = self.places.of(code)
            if place is not None:
                current.add(place)
        return sys.monitoring.DISABLE

    def begin(self) -> None:
        self.current = set()
        sys.monitoring.restart_events()

    def end(self) -> list[list[Any]]:
        found, self.current = self.current or set(), None
        return [list(place) for place in sorted(found)]

    def stop(self) -> None:
        monitoring = sys.monitoring
        monitoring.set_events(self.tool, 0)
        monitoring.register_callback(self.tool, monitoring.events.PY_START, None)
        monitoring.free_tool_id(self.tool)


def _start_collector(places: _Places) -> _Collector | None:
    monitoring = sys.monitoring
    for tool in _TOOL_IDS:
        try:
            monitoring.use_tool_id(tool, "repro")
        except ValueError:
            continue
        collector = _Collector(places, tool)
        monitoring.register_callback(tool, monitoring.events.PY_START, collector.started)
        monitoring.set_events(tool, monitoring.events.PY_START)
        return collector
    return None


def pytest_configure() -> None:
    if _OUT:
        Path(_OUT).mkdir(parents=True, exist_ok=True)
        _STATE["file"] = (Path(_OUT) / "results.jsonl").open("w", encoding="utf-8")
    if os.environ.get("REPRO_NET_GUARD") == "1":
        _guard_network()
    places = _Places(os.environ.get("REPRO_ROOT") or os.getcwd())
    _STATE["places"] = places
    if os.environ.get("REPRO_MAP") == "1":
        collector = _start_collector(places)
        _STATE["collector"] = collector
        if collector is None:
            _write({"kind": "map_unavailable", "reason": "no sys.monitoring tool ID is free"})


def pytest_unconfigure() -> None:
    collector = _STATE["collector"]
    if collector is not None:
        collector.stop()
        _STATE["collector"] = None


def _test_place(item: Any) -> Place | None:
    """Where a test's own function is (None for tests that are not Python functions)."""
    function = getattr(item, "function", None)
    try:
        function = inspect.unwrap(function) if function is not None else None
    except ValueError:  # a cycle of __wrapped__
        return None
    code = getattr(function, "__code__", None)
    places: _Places | None = _STATE["places"]
    return places.of(code) if code is not None and places is not None else None


def pytest_collection_finish(session: Any) -> None:
    for item in session.items:
        place = _test_place(item)
        _write({"kind": "collected", "nodeid": item.nodeid, "test": list(place) if place else None})


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item: Any) -> Any:
    """With the map on: the places a test runs, from its setup to its teardown."""
    collector: _Collector | None = _STATE["collector"]
    if collector is None:
        yield
        return
    collector.begin()
    try:
        yield
    finally:
        functions = collector.end()
        _write({"kind": "map", "nodeid": item.nodeid, "functions": functions})


@pytest.hookimpl(tryfirst=True)  # before the fixtures, so their draws are seeded too
def pytest_runtest_setup(item: Any) -> None:
    random.seed(_seed_for(item.nodeid))


def _outcome(report: Any) -> str:
    """One phase's outcome: passed, failed, skipped, xfailed, xpassed, or error (setup or
    teardown failed)."""
    if hasattr(report, "wasxfail"):
        return "xpassed" if report.passed else "xfailed"
    if report.failed:
        return "failed" if report.when == "call" else "error"
    return "skipped" if report.skipped else "passed"


def _message(report: Any) -> str | None:
    return str(report.longrepr)[-_LONGREPR:] if report.longrepr else None


def pytest_runtest_logreport(report: Any) -> None:
    """A test's outcome from its three phases, written once its teardown has run: a setup that
    does not pass decides it (error, skip, xfail); otherwise the call does; a teardown that
    fails turns a pass into an error."""
    tests: dict[str, dict[str, Any]] = _STATE["tests"]
    entry = tests.setdefault(
        report.nodeid,
        {"kind": "test", "nodeid": report.nodeid, "outcome": None, "duration_s": 0.0,
         "call_s": None, "phase": None, "message": None},
    )  # fmt: skip
    entry["duration_s"] += float(getattr(report, "duration", 0.0))
    outcome = _outcome(report)
    if report.when == "setup" and outcome != "passed":
        entry.update(outcome=outcome, phase="setup", message=_message(report))
    elif report.when == "call":
        entry["outcome"] = outcome
        entry["call_s"] = round(float(getattr(report, "duration", 0.0)), 9)  # D07: timing
        if outcome != "passed":
            entry.update(phase="call", message=_message(report))
    elif report.when == "teardown":
        if entry["outcome"] is None:
            entry["outcome"] = "passed"
        if outcome == "error" and entry["outcome"] == "passed":
            entry.update(outcome="error", phase="teardown", message=_message(report))
        entry["duration_s"] = round(entry["duration_s"], 6)
        _write(tests.pop(report.nodeid))  # a rerun of the same test starts afresh


def pytest_collectreport(report: Any) -> None:
    if report.failed:
        _write(
            {
                "kind": "collect_error",
                "nodeid": report.nodeid,
                "message": str(report.longrepr)[-_LONGREPR:],
            }
        )


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    _write(
        {
            "kind": "session",
            "exitstatus": int(exitstatus),
            "collected": int(getattr(session, "testscollected", 0)),
            "pytest": pytest.__version__,
            "python": platform.python_version(),
            "seed": _SEED,
        }
    )
    handle = _STATE["file"]
    if handle is not None:
        handle.close()
        _STATE["file"] = None
