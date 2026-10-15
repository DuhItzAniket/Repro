"""Attempts Repro's audit hook detected in a sandboxed command (ADR-0004, L1).

The hook (``_hook/sitecustomize.py``) runs inside the target's own Python processes, so what it
writes is the target's to tamper with: a line that is not a well-formed record is counted and
skipped, never trusted. A detection says a Python-level attempt was made; its absence proves
nothing, because code that bypasses Python's audited functions is not seen.
"""

import ipaddress
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

DetectionKind = Literal["network", "subprocess", "file"]
KINDS: Final[frozenset[str]] = frozenset({"network", "subprocess", "file"})
#: The hook's directory: the sandbox puts it first on ``PYTHONPATH``.
HOOK_DIR: Final = Path(__file__).with_name("_hook")
AUDIT_LOG_ENV: Final = "REPRO_AUDIT_LOG"
AUDIT_ROOTS_ENV: Final = "REPRO_AUDIT_ROOTS"
#: More records than this per command are not read (the hook itself stops at 1000 per process).
MAX_DETECTIONS: Final = 10_000


@dataclass(frozen=True, slots=True)
class Detection:
    kind: DetectionKind
    event: str  # the audit event, e.g. "socket.connect"
    detail: str
    pid: int
    test: str | None  # the pytest node ID running at the time, if any


@dataclass(frozen=True, slots=True)
class Detections:
    items: tuple[Detection, ...]
    #: Records left out: past a process's or the command's cap, or not well formed.
    dropped: int
    #: Whether a process reported more attempts than its hook records.
    truncated: bool


_LOCAL_NAMES: Final = frozenset({"", "localhost", "None"})  # "None": getaddrinfo(None, port)


def leaves_host(event: str, detail: str) -> bool:
    """Whether a network detection reaches past this machine: not loopback, an unspecified
    address, ``localhost`` or a Unix socket (asyncio's self-pipe on Windows is a loopback
    connection, for one). A name other than ``localhost`` needs a resolver, so it counts."""
    if event == "socket.gethostbyname":
        host = detail
    else:
        host, colon, port = detail.rpartition(":")
        if not colon or not port.isdigit():
            return False  # a Unix socket's path: no address and port
    host = host.strip("[]").split("%", 1)[0]
    if host in _LOCAL_NAMES:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True  # a name to resolve
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return not (address.is_loopback or address.is_unspecified)


def _test_id(raw: object) -> str | None:
    """``PYTEST_CURRENT_TEST`` is ``<node id> (<phase>)``: the node ID."""
    if not isinstance(raw, str) or not raw:
        return None
    node, _, phase = raw.rpartition(" ")
    return node if node and phase.startswith("(") else raw


def read_detections(log: Path, *, limit: int = MAX_DETECTIONS) -> Detections:
    """The records in an audit log written by the hook (missing log: none)."""
    try:
        lines = log.read_bytes().splitlines()
    except FileNotFoundError:
        return Detections((), 0, truncated=False)
    items: list[Detection] = []
    dropped = 0
    truncated = False
    for line in lines:
        try:
            record = json.loads(line)
            kind = record["kind"]
            if kind == "truncated":
                truncated = True
                continue
            if kind not in KINDS or len(items) >= limit:
                raise ValueError(kind)
            items.append(
                Detection(
                    kind=kind,
                    event=str(record["event"])[:100],
                    detail=str(record["detail"])[:300],
                    pid=int(record["pid"]),
                    test=_test_id(record.get("test")),
                )
            )
        except (ValueError, KeyError, TypeError):
            dropped += 1
    return Detections(tuple(items), dropped, truncated)
