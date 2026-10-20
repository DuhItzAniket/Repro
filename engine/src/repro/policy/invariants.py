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
- ``no_network`` (F03): no network attempt by head's tests past this machine (the sandbox's
  detections; loopback and Unix sockets are local). Where the sandbox enforces the network (L3)
  a pass rests on that; where it only detects (L2), a pass rests on detection, which code that
  bypasses Python's socket functions escapes: ``network_not_enforced`` says so. Where attempts
  are not detected at all, a JavaScript run (K08, K11): at L2 it is not evaluated; at L3 a pass
  rests on the enforcement alone (nothing reached the network), it cannot fail, and its
  message says that attempts were not seen.
- ``perf_budget`` (F03): no timed test slower than base past ``max_regression``, by D07's
  comparison: a test fails when its interval's low end is past the budget and D07 calls it a
  regression (significant, past this machine's noise). An interval past the budget that D07
  does not call a regression cannot be decided: not evaluated.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from functools import cache
from typing import Any, Final, Literal, NamedTuple

from repro import __version__
from repro.ids import new_evidence_id
from repro.policy.loader import FILE, Invariant
from repro.sandbox.detect import leaves_host

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


# -- no_network ----------------------------------------------------------------------------------


class Attempt(NamedTuple):
    """A network attempt the sandbox detected on head: its audit event, its address or name,
    and its ``network_attempt`` evidence."""

    event: str
    detail: str
    evidence: str


def no_network(
    invariant: Invariant,
    attempts: Sequence[Attempt] | None,
    *,
    network: str | None,
    complete: bool = True,
    unseen: str | None = None,
    undetected: str | None = None,
) -> InvariantResult:
    """``attempts``: what head's test runs were seen to attempt, None if they did not run;
    ``network``: head's sandbox's ``enforced`` or ``detected-only``; ``complete``: whether every
    detection was read (a process's log can be cut, or hold lines that are not records);
    ``unseen``: why head's network use could be neither blocked nor seen (K08: a Node process
    in the process sandbox), which leaves the invariant not evaluated; ``undetected``: why
    attempts are not seen where the network is enforced (K11: a Node process in a container),
    which a pass then states."""
    name, options = invariant.name, invariant.options
    blind = unseen if unseen is not None else undetected
    if blind is not None and network != "enforced":  # neither blocked nor seen
        return InvariantResult(
            name, "not_evaluated", blind, details={"network": network}, options=options
        )
    if attempts is None:
        return InvariantResult(name, "not_evaluated", "head's tests did not run", options=options)
    outside = [a for a in attempts if leaves_host(a.event, a.detail)]
    if outside:
        shown = sorted({a.detail for a in outside})
        return InvariantResult(
            name,
            "fail",
            f"head's tests attempted the network: {_listed(shown)}",
            tuple(dict.fromkeys(a.evidence for a in outside)),
            {"attempts": shown, "network": network},
            options,
        )
    if not complete:
        return InvariantResult(
            name,
            "not_evaluated",
            "head's detections were not all read (a log was cut or held lines that are not "
            "records)",
            details={"network": network},
            options=options,
        )
    if network == "enforced" and undetected is not None:
        message = (
            "nothing head's tests did reached the network: the sandbox had none (enforced); "
            f"their attempts are not seen ({undetected})"
        )
        details = {"network": network, "undetected": undetected}
        return InvariantResult(name, "pass", message, (), details, options)
    if network == "enforced":
        message = "no network attempt by head's tests; the sandbox had no network (enforced)"
    else:
        message = (
            "no network attempt detected by head's tests (detected only: the sandbox does not "
            "enforce the network)"
        )
    return InvariantResult(name, "pass", message, (), {"network": network}, options)


def network_not_enforced() -> dict[str, Any]:
    """The ``missing.recorded`` payload for a ``no_network`` pass that rests on detection."""
    return {
        "missing": {
            "reason": "network_not_enforced",
            "targets": [{"file": FILE}],
            "detail": (
                "no_network passed on detection alone: this sandbox does not enforce the "
                "network, and code that bypasses Python's socket functions is not seen"
            ),
            "resolution": "Run with the Docker sandbox, which runs the tests without a network",
        }
    }


# -- perf_budget ---------------------------------------------------------------------------------


class Timed(NamedTuple):
    """A timed test's comparison (D07) and its ``perf_diff`` evidence."""

    test: str
    verdict: str
    ratio: float
    ci_low: float
    ci_high: float
    evidence: str


def perf_budget(
    invariant: Invariant, timed: Sequence[Timed] | None, too_fast: Sequence[str] = ()
) -> InvariantResult:
    """``timed``: each timed test's comparison, None if the tests were not timed;
    ``too_fast``: the tests under D07's timing floor."""
    name, options = invariant.name, invariant.options
    if timed is None:
        return InvariantResult(name, "not_evaluated", "the tests were not timed", options=options)
    budget = float(options["max_regression"])
    limit = 1 + budget
    within = f"+{budget:.0%}"
    over = [t for t in timed if t.ci_low > limit and t.verdict == "regression"]
    if over:
        shown = [f"{t.test} (x{t.ratio:.2f}, 95% CI from x{t.ci_low:.2f})" for t in over]
        return InvariantResult(
            name,
            "fail",
            f"{len(over)} tests slower than base past the budget ({within}): {_listed(shown)}",
            tuple(t.evidence for t in over),
            {"over": [t.test for t in over], "too_fast": len(too_fast)},
            options,
        )
    if not timed:
        why = f"{len(too_fast)} too fast to time" if too_fast else "none passes on both sides"
        return InvariantResult(
            name, "not_evaluated", f"no selected test could be timed ({why})", options=options
        )
    unclear = [t for t in timed if t.ci_low > limit]
    if unclear:
        return InvariantResult(
            name,
            "not_evaluated",
            f"{len(unclear)} tests past the budget ({within}) by their interval, within this "
            f"machine's noise: {_listed([t.test for t in unclear])}",
            tuple(t.evidence for t in unclear),
            {"unclear": [t.test for t in unclear]},
            options,
        )
    fast = f"; {len(too_fast)} too fast to time" if too_fast else ""
    return InvariantResult(
        name,
        "pass",
        f"{len(timed)} timed tests within the budget ({within}){fast}",
        (),
        {"timed": len(timed), "too_fast": len(too_fast)},
        options,
    )
