"""Repro's tracer (E01; ADR-0005, ARCHITECTURE §4.3): what the change's target functions
receive and return, call by call, in each test.

The pytest plugin owns the ``sys.monitoring`` tool ID and its PY_START callback (D05's map);
for a code object that is a target it asks this module to start a call. Targets are named by
the engine as ``[path, qualname, first line, last line]``: the file relative to the snapshot,
the qualified name, and the span of the symbol, so that a code object matches when its file
and name match and its first line falls in the span.

**A call** is recorded from its start to its end:
- at PY_START, the arguments, read from the callee's frame (``sys._getframe(1)`` inside the
  callback) before its body runs;
- at PY_RETURN, the value returned; at PY_UNWIND, the exception's type and arguments;
- at PY_YIELD, each value a generator or coroutine yields (at most ``MAX_YIELDS`` of them);
- a generator or coroutine that did not run to its end is ``suspended``: whether it was
  closed during its test (``GeneratorExit``, often when it is collected) or was still suspended
  when the test ended depends on the garbage collector's timing, which is no behaviour of
  the code (Python 3.12 on Linux collected later than elsewhere, E01's CI found).

Calls in flight are keyed by their frame's identity; code objects are held, so identities are
not reused. Each call is attributed to the test and the phase (setup, call, teardown) running
when it started.

**Budget.** Each (test, target) records its first ``BUDGET`` calls (200, measured in A08);
then the target is disabled for the rest of the test, and a ``truncated`` record says so: its
PY_START returns ``DISABLE``, and so do its PY_RETURN and PY_YIELD. Recorded calls still in
flight at that moment (the outer frames of a recursion) end as ``unfinished``, their arguments
known and their results not: keeping their returns would keep the target's return events
firing for every later call (the E01 benchmark measured 27x on a recursive function).

The standard library only, Python 3.12 to 3.15.
"""

import sys
from collections.abc import Callable
from typing import Any

from repro_encode import digest, digests, type_name

BUDGET = 200
MAX_YIELDS = 32
Target = tuple[str, str, int, int]
_VARARGS = 0x04  # inspect.CO_VARARGS, without importing inspect


class _Unset:
    """Stands for a parameter with no value in the frame."""


_UNSET = _Unset()
_VARKEYWORDS = 0x08  # inspect.CO_VARKEYWORDS


def _names(code: Any) -> tuple[str, ...]:
    """The parameter names of ``code``, in order."""
    count = code.co_argcount + code.co_kwonlyargcount
    count += bool(code.co_flags & _VARARGS) + bool(code.co_flags & _VARKEYWORDS)
    return tuple(code.co_varnames[:count])


class _Call:
    __slots__ = (
        "args", "args_any_order", "args_complete", "code", "index", "phase", "target", "test",
        "yields",
    )  # fmt: skip

    def __init__(self, target: Target, test: str, phase: str, index: int, code: int) -> None:
        self.code = code
        self.target = target
        self.test = test
        self.phase = phase
        self.index = index
        self.args = ""
        self.args_any_order = ""
        self.args_complete = True
        self.yields: list[str] = []


class Tracer:
    """The tracer's state for one pytest session."""

    def __init__(self, targets: list[Target], write: Callable[[dict[str, Any]], None]) -> None:
        self.by_name: dict[tuple[str, str], list[Target]] = {}
        for target in targets:
            self.by_name.setdefault((target[0], target[1]), []).append(target)
        self.write = write
        self.known: dict[int, tuple[Any, Target | None]] = {}
        self.inflight: dict[int, _Call] = {}
        self.open: dict[int, int] = {}  # id(code) -> recorded calls in flight
        self.counts: dict[tuple[str, Target], int] = {}
        self.test: str | None = None
        self.phase = "setup"

    def target(self, code: Any, place: tuple[str, str, int]) -> Target | None:
        """The target a code object is, or None (decided once per code object)."""
        known = self.known.get(id(code))
        if known is not None:
            return known[1]
        found = None
        for target in self.by_name.get((place[0], place[1]), ()):
            if target[2] <= place[2] <= target[3]:
                found = target
                break
        self.known[id(code)] = (code, found)
        return found

    # -- the monitoring callbacks' work ----------------------------------------------------------

    def start(self, target: Target, code: Any, frame: Any) -> bool:
        """A call of ``target`` starts; False once its budget for this test is spent."""
        test = self.test
        if test is None:  # outside any test (collection, a session fixture's teardown)
            return True
        key = (test, target)
        index = self.counts.get(key, 0)
        if index >= BUDGET:
            if index == BUDGET:
                self.counts[key] = index + 1
                self.write(
                    {
                        "kind": "truncated",
                        "nodeid": test,
                        "target": list(target),
                        "captured": BUDGET,
                    }
                )
                self._unfinished(id(code))
            return False
        self.counts[key] = index + 1
        call = _Call(target, test, self.phase, index, id(code))
        local = frame.f_locals
        # The parameters' values in their order (their names are the function's, the same in
        # every call); one deleted before PY_START (it cannot be) would show as the marker.
        arguments = tuple(local.get(name, _UNSET) for name in _names(code))
        call.args, call.args_any_order, call.args_complete = digests(arguments)
        self.inflight[id(frame)] = call
        self.open[id(code)] = self.open.get(id(code), 0) + 1
        return True

    def _finish(self, frame: Any) -> _Call | None:
        call = self.inflight.pop(id(frame), None)
        if call is not None:
            self.open[call.code] -= 1
        return call

    def idle(self, code: Any) -> bool:
        """Whether none of ``code``'s recorded calls is in flight (its local events can go)."""
        return not self.open.get(id(code))

    def returned(self, frame: Any, value: Any) -> bool:
        """Records a return; False if the call was not being recorded."""
        call = self._finish(frame)
        if call is None:
            return False
        result, any_order, complete = digests(value)
        self._emit(call, "return", result, complete, type_name(type(value)), any_order=any_order)
        return True

    def yielded(self, frame: Any, value: Any) -> bool:
        call = self.inflight.get(id(frame))
        if call is None:
            return False
        if len(call.yields) < MAX_YIELDS:
            call.yields.append(digest(value)[0])
        return True

    def unwound(self, frame: Any, exc: BaseException) -> None:
        call = self._finish(frame)
        if call is None:
            return
        if type(exc) is GeneratorExit:  # closed before it finished: when is the GC's
            self._emit(call, "suspended", "", False, "")
            return
        # The exception itself: its type, its arguments, its cause chain (repro_encode).
        result, complete = digest(exc)
        self._emit(call, "raise", result, complete, type_name(type(exc)))

    # -- tests -----------------------------------------------------------------------------------

    def begin(self, test: str) -> None:
        self.test, self.phase = test, "setup"

    def _unfinished(self, code: int) -> None:
        """Ends the recorded calls of ``code`` still in flight, so its events can go."""
        for key, call in list(self.inflight.items()):
            if call.code == code:
                del self.inflight[key]
                self.open[code] -= 1
                self._emit(call, "unfinished", "", False, "")

    def end(self) -> None:
        """The test is over: calls still suspended are recorded as such."""
        test = self.test
        for key, call in list(self.inflight.items()):
            if call.test == test:
                del self.inflight[key]
                self.open[call.code] -= 1
                self._emit(call, "suspended", "", False, "")
        self.test = None

    def _emit(
        self,
        call: _Call,
        outcome: str,
        result: str,
        complete: bool,
        kind: str,
        *,
        any_order: str = "",
    ) -> None:
        record = {
            "kind": "call",
            "nodeid": call.test,
            "phase": call.phase,
            "target": list(call.target),
            "index": call.index,
            "args": call.args,
            "args_complete": call.args_complete,
            "outcome": outcome,
            "result": result,
            "result_complete": complete,
            "type": kind,
            "yields": call.yields,
            "yields_complete": len(call.yields) < MAX_YIELDS,
        }
        # Digests with every dictionary sorted, only where they differ: a difference in
        # dictionary order alone is told apart from a difference in content (E04).
        if call.args_any_order and call.args_any_order != call.args:
            record["args_any_order"] = call.args_any_order
        if any_order and any_order != result:
            record["result_any_order"] = any_order
        self.write(record)


def parse_targets(raw: str) -> list[Target]:
    """The engine's targets (JSON already decoded by the caller is not trusted either)."""
    import json  # noqa: PLC0415 - only when tracing

    found: list[Target] = []
    for item in json.loads(raw):
        path, qualname, start, end = item
        found.append((str(path), str(qualname), int(start), int(end)))
    return found


def _set_local(tool: int, code: Any, events: int) -> None:
    sys.monitoring.set_local_events(tool, code, events)
