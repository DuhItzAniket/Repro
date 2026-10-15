"""Declared invariants, evaluated from a run's evidence (F02, F03; ARCHITECTURE §4.6).

Each invariant ``repro.yml`` enables on base gets one result: ``pass``, ``fail``, or
``not_evaluated`` when what it needs could not be observed (never a pass by default). The
result is ``invariant`` evidence of its own, citing the evidence it rests on, and an
``invariant.result`` check (ADR-0015 §2: ``ok`` / ``fail`` / ``warn``).

- ``public_api_stable``: no breaking change of the public API (E05) outside ``except``, dotted
  object patterns (``mypkg.experimental.*``). Not evaluated if a package's API could not be read
  and nothing else broke.
- ``no_new_dependencies``: no package added to the lock or the declared requirements (E05)
  outside ``allow``. A package that is only installed (pulled in by another) is not a
  dependency the change declares. Not evaluated if a side's declared dependencies cannot be
  read statically (and are not locked) and nothing else was added.
- ``forbidden_paths``: no file added, removed, modified or renamed (either path) matching the
  patterns: ``*`` within a path segment, ``**`` across segments, ``?`` one character. A
  pattern that matches a directory forbids everything under it (``migrations``,
  ``migrations/``), as ``migrations/**`` does; a pattern ending in ``/`` matches directories
  only.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from functools import cache
from typing import Any, Final, Literal

from repro import __version__
from repro.ids import new_evidence_id
from repro.policy.loader import FILE, Invariant

Result = Literal["pass", "fail", "not_evaluated"]
STATUS: Final = {"pass": "ok", "fail": "fail", "not_evaluated": "warn"}
LISTED: Final = 10


@dataclass(frozen=True, slots=True)
class InvariantResult:
    invariant: str
    result: Result
    message: str
    #: Evidence the result rests on (``api_diff``, ``dep_diff`` and others' IDs).
    cites: tuple[str, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return STATUS[self.result]

    def evidence(self, run_id: str) -> dict[str, Any]:
        """The ``invariant`` evidence record (the writer adds ``seq``)."""
        return {
            "id": new_evidence_id(),
            "run_id": run_id,
            "type": "invariant",
            "targets": [{"file": FILE}],
            "summary": f"{self.invariant}: {self.result}: {self.message}"[:1000],
            "data": {
                "invariant": self.invariant,
                "result": self.result,
                "options": dict(self.options),
                "details": dict(self.details),
                "cites": list(self.cites),
            },
            "artifacts": [],
            "stability": "n/a" if self.result == "not_evaluated" else "stable",
            "origin": "introduced" if self.result == "fail" else "n/a",
            "produced_by": {"component": "repro.policy.invariants", "version": __version__},
        }

    def payload(self, evidence_id: str) -> dict[str, Any]:
        """The ``invariant.result`` payload: its own evidence first, then what it cites."""
        return {
            "invariant": self.invariant,
            "result": self.result,
            "evidence_ids": [evidence_id, *self.cites],
            "message": self.message[:1000],
        }


def _listed(items: Sequence[str]) -> str:
    shown = ", ".join(items[:LISTED])
    return shown + (f" and {len(items) - LISTED} more" if len(items) > LISTED else "")


# -- public_api_stable ---------------------------------------------------------------------------


def dotted(symbol: str) -> str:
    """``module:qualname#n`` as the dotted path ``repro.yml`` patterns use."""
    module, _, rest = symbol.partition(":")
    qualname = rest.rpartition("#")[0]
    return module if qualname in ("", "<module>") else f"{module}.{qualname}"


def public_api_stable(
    invariant: Invariant,
    breaks: Sequence[tuple[str, str, str]] | None,
    unread: Sequence[str] = (),
) -> InvariantResult:
    """``breaks``: (symbol, breakage, evidence ID) per break, None if the API was not compared;
    ``unread``: packages whose API could not be read."""
    name, options = invariant.name, invariant.options
    if breaks is None:
        return InvariantResult(
            name, "not_evaluated", "the public API was not compared", options=options
        )
    allowed = list(options.get("except", ()))
    kept = [b for b in breaks if not any(fnmatchcase(dotted(b[0]), p) for p in allowed)]
    excused = len(breaks) - len(kept)
    if kept:
        shown = [f"{dotted(symbol)} ({breakage})" for symbol, breakage, _ in kept]
        return InvariantResult(
            name,
            "fail",
            f"{len(kept)} breaking changes of the public API: {_listed(shown)}",
            tuple(evidence for _, _, evidence in kept),
            {"breaks": [dotted(s) for s, _, _ in kept], "excused": excused},
            options,
        )
    if unread:
        return InvariantResult(
            name,
            "not_evaluated",
            f"the API of {_listed(list(unread))} could not be read",
            options=options,
        )
    extra = f" ({excused} excepted)" if excused else ""
    return InvariantResult(
        name,
        "pass",
        f"no breaking change of the public API{extra}",
        (),
        {"excused": excused},
        options,
    )


# -- no_new_dependencies -------------------------------------------------------------------------


def no_new_dependencies(
    invariant: Invariant,
    changes: Sequence[tuple[str, str, str, str]] | None,
    unread: Sequence[str] = (),
) -> InvariantResult:
    """``changes``: (package, change, source, evidence ID) per dependency difference, None if
    the dependencies were not compared; ``unread``: the sides whose declared dependencies could
    not be read (what they add would go unseen)."""
    name, options = invariant.name, invariant.options
    if changes is None:
        return InvariantResult(
            name, "not_evaluated", "the dependencies were not compared", options=options
        )
    allowed = [p.lower() for p in options.get("allow", ())]
    added = [
        c for c in changes
        if c[1] == "added" and c[2] in ("lockfile", "declared")
        and not any(fnmatchcase(c[0].lower(), p) for p in allowed)
    ]  # fmt: skip
    if added:
        packages = sorted({package for package, _, _, _ in added})
        return InvariantResult(
            name,
            "fail",
            f"new dependencies: {_listed(packages)}",
            tuple(evidence for _, _, _, evidence in added),
            {"added": packages},
            options,
        )
    if unread:
        return InvariantResult(
            name,
            "not_evaluated",
            f"the dependencies declared on {' and '.join(unread)} could not be read statically",
            options=options,
        )
    return InvariantResult(name, "pass", "no dependency added", options=options)


# -- forbidden_paths -----------------------------------------------------------------------------


@cache
def _glob(pattern: str) -> re.Pattern[str]:
    out, index = [], 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif pattern[index] == "*":
            out.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(out) + r"\Z")


def matches(pattern: str, path: str) -> bool:
    """Whether a repository path (relative, ``/``) matches a ``forbidden_paths`` pattern: the
    path itself, or a directory it is under."""
    pattern = pattern.removeprefix("./")
    directory_only = pattern.endswith("/")
    regex = _glob(pattern.rstrip("/"))
    parts = path.split("/")
    candidates = ["/".join(parts[:end]) for end in range(1, len(parts))]
    if not directory_only:
        candidates.append(path)
    return any(regex.match(candidate) for candidate in candidates)


def forbidden_paths(invariant: Invariant, touched: Sequence[str] | None) -> InvariantResult:
    """``touched``: every path the change adds, removes, modifies or renames (both paths of a
    rename), None if the change's files are not known."""
    name, options = invariant.name, invariant.options
    if touched is None:
        return InvariantResult(
            name, "not_evaluated", "the changed files are not known", options=options
        )
    patterns = list(options.get("paths", ()))
    hits = sorted({path for path in touched if any(matches(p, path) for p in patterns)})
    if hits:
        return InvariantResult(
            name, "fail", f"forbidden paths touched: {_listed(hits)}", (), {"paths": hits}, options
        )
    return InvariantResult(
        name, "pass", f"no forbidden path touched ({len(touched)} files changed)", options=options
    )


def not_yet(invariant: Invariant, phase: str) -> InvariantResult:
    """An invariant whose evaluation a later phase brings."""
    return InvariantResult(
        invariant.name, "not_evaluated", f"evaluated from {phase} on", options=invariant.options
    )
