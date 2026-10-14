"""Repro's pytest plugin (D04), loaded with ``-p repro_pytest`` inside the sandbox.

The standard library and pytest only, and Python 3.12 to 3.15: it runs in the target's
environment, never in Repro's (ARCHITECTURE §3). It talks to the engine through files in
``REPRO_OUT``:

- ``results.jsonl``: one JSON object per line, written as the run goes (a crash still leaves
  what came before): ``{"kind": "test", ...}`` per test, ``{"kind": "collect_error", ...}``
  per module that failed to collect, and ``{"kind": "session", ...}`` last.

Determinism: before each test, ``random`` is seeded from ``REPRO_SEED`` and the test's node ID,
so a test's random draws do not depend on which tests ran before it. With ``REPRO_NET_GUARD=1``
TCP connections to anything but the loopback interface, and resolving any name but
``localhost``, fail at once, so a test that needs the network fails the same way every time and
on every isolation level, instead of hanging or flaking. It detects; it is not a boundary
(ADR-0004): UDP ``sendto`` and C extensions are not stopped, only recorded by the audit hook
beside this file.
"""

import errno
import hashlib
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
_STATE: dict[str, Any] = {"file": None, "tests": {}}


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


def pytest_configure() -> None:
    if _OUT:
        Path(_OUT).mkdir(parents=True, exist_ok=True)
        _STATE["file"] = (Path(_OUT) / "results.jsonl").open("w", encoding="utf-8")
    if os.environ.get("REPRO_NET_GUARD") == "1":
        _guard_network()


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
         "phase": None, "message": None},
    )  # fmt: skip
    entry["duration_s"] += float(getattr(report, "duration", 0.0))
    outcome = _outcome(report)
    if report.when == "setup" and outcome != "passed":
        entry.update(outcome=outcome, phase="setup", message=_message(report))
    elif report.when == "call":
        entry["outcome"] = outcome
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
