"""Deterministic input-replay probes (E06; ARCHITECTURE §4.4): a change's functions called with
generated inputs on both sides, for differences the existing tests do not reach.

**Which functions.** Module-level functions the change modified, renamed or moved that exist on
both sides with the same parameters, every parameter annotated with a JSON type (``int``,
``float``, ``str``, ``bool``, ``None``, ``list[T]``, ``dict[str, T]``, ``Optional`` and unions
of these), no ``*args`` or ``**kwargs``, neither a generator nor ``async``. Read from the
sources with ``ast``: nothing of the target runs on the host.

**Which inputs.** Hypothesis, on the host, from the annotations: ``derandomize=True``, no
example database, the generate phase only, so the same function's inputs are the same in every
run of the same Hypothesis version (its version is in the evidence). Integers are kept within
32 bits, floats finite, text and collections short; at most ``EXAMPLES`` distinct inputs a
function. The inputs are data, written to the sandbox as JSON.

**Proposed inputs** (G07). The probe-writer agent, shown each function and its change but not
the PR's claims, may propose inputs of its own: realistic values random generation would not
form (a valid timestamp, say). A proposal is data, never code: it must name exactly the
function's parameters, each value of its annotated JSON type (``fits``), or it is dropped. The
proposals that fit run beside Hypothesis's, through the same runs and filters; each difference
says which generator's inputs found it (``found_by``).

**How they run.** ``repro_probe`` (beside the plugin) calls each function with each input in
the side's sandbox, with its interpreter: base, base again with another hash seed and another
``random`` seed (A2), and head. A probe whose result differs between the two base runs is not
deterministic and is left out (counted); one that differs between base and head is a
difference, classed as behaviour differences are (E04) and grouped per function and class:
``probe_diff`` evidence with ``provenance: generated``, its first input the reproducer.
"""

import ast
import json
import math
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib.metadata import version as installed_version
from typing import Any, Final

from repro import __version__
from repro.analysis.changes import SymbolChange
from repro.ids import new_evidence_id
from repro.runner.pytest import plugin_env
from repro.runner.selection import Resolver, base_id, head_id
from repro.runner.sides import Side
from repro.sandbox.process import read_head
from repro.sandbox.remote import WORK, RemoteSandbox

#: Functions probed in one run, at most, and inputs per function.
MAX_FUNCTIONS: Final = 20
EXAMPLES: Final = 40
#: A proposed input's text and collections, at most this long.
MAX_PROPOSED: Final = 1000
MAX_BYTES: Final = 16 * 1024 * 1024
PREVIEW: Final = 512
SUMMARY: Final = 1000
#: A2's hash seed and random seed, as for the tests (twosided).
OTHER_SEED: Final = 1
PROBED_CHANGES: Final = frozenset({"modified", "renamed", "moved"})
_INT: Final = 2**31
_SLUG: Final = re.compile(r"[^0-9a-z_]+")

Spec = dict[str, Any]  # a JSON type: {"kind": ..., ...}


# -- candidates ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Candidate:
    """A function to probe: where it is on each side, and its parameters' types."""

    symbol: str  # the change's symbol ID
    module: tuple[str, str]  # base's and head's module
    name: str
    file: str  # head's file
    roots: tuple[str, str]  # base's and head's import roots, relative to the snapshot
    parameters: tuple[tuple[str, str, Spec], ...]  # name, "positional" or "keyword", type

    def call(self, given: dict[str, Any]) -> str:
        """The call with ``given``, as Python text (the reproducer)."""
        names = [name for name, _, _ in self.parameters]
        values = [*given["args"], *given["kwargs"].values()]
        text = f"{self.name}({', '.join(f'{n}={v!r}' for n, v in zip(names, values, strict=True))})"
        return text if len(text) <= PREVIEW else text[: PREVIEW - 1] + "…"


def candidates(
    changes: Sequence[SymbolChange], resolvers: tuple[Resolver, Resolver]
) -> list[Candidate]:
    """The changed functions that can be probed (see the module's docstring), at most
    ``MAX_FUNCTIONS``, in symbol order."""
    found = []
    for change in sorted(changes, key=lambda c: c.symbol_id):
        if change.change not in PROBED_CHANGES or change.kind != "function":
            continue
        before = _function(base_id(change), resolvers[0])
        after = _function(head_id(change), resolvers[1])
        if before is None or after is None:
            continue
        (base_module, base_root, base_args), (head_module, head_root, head_args) = before, after
        if base_args is None or base_args != head_args:
            continue
        found.append(
            Candidate(
                change.symbol_id,
                (base_module, head_module),
                change.symbol_id.partition(":")[2].rpartition("#")[0],
                change.file,
                (base_root, head_root),
                base_args,
            )
        )
    return found[:MAX_FUNCTIONS]


def _function(
    symbol: str | None, resolver: Resolver
) -> tuple[str, str, tuple[tuple[str, str, Spec], ...] | None] | None:
    """A module-level function's module, import root and parameter types (None if not one)."""
    module, _, rest = (symbol or "").partition(":")
    qualname = rest.rpartition("#")[0]
    path = next((p for p, m in resolver.names.items() if m == module), None)
    if path is None or not qualname or "." in qualname or qualname == "<module>":
        return None
    node = _definition(resolver.read([path]).get(path), qualname)
    if node is None:
        return None
    parts = module.split(".")
    depth = len(parts) - (0 if path.endswith("__init__.py") else 1)
    root = "/".join(path.split("/")[: max(0, path.count("/") - depth)]) or "."
    return module, root, _parameters(node)


def _definition(source: bytes | None, name: str) -> ast.FunctionDef | None:
    """The last module-level ``def name`` of ``source``."""
    if source is None:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    found = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    return found[-1] if found else None


def _parameters(node: ast.FunctionDef) -> tuple[tuple[str, str, Spec], ...] | None:
    arguments = node.args
    if (
        arguments.vararg
        or arguments.kwarg
        or any(isinstance(n, ast.Yield | ast.YieldFrom) for n in ast.walk(node))
    ):
        return None
    found: list[tuple[str, str, Spec]] = []
    for kind, listed in (
        ("positional", [*arguments.posonlyargs, *arguments.args]),
        ("keyword", arguments.kwonlyargs),
    ):
        for argument in listed:
            spec = _spec(argument.annotation) if argument.annotation is not None else None
            if spec is None:
                return None
            found.append((argument.arg, kind, spec))
    return tuple(found) if found else None


def _spec(node: ast.expr | None, depth: int = 0) -> Spec | None:  # noqa: PLR0911 - one per form
    if node is None or depth > 3:  # noqa: PLR2004
        return None
    if isinstance(node, ast.Constant) and node.value is None:
        return {"kind": "none"}
    if isinstance(node, ast.Name):
        simple = {"int": "int", "float": "float", "str": "str", "bool": "bool"}.get(node.id)
        return {"kind": simple} if simple else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left, right = _spec(node.left, depth + 1), _spec(node.right, depth + 1)
        return {"kind": "union", "of": [left, right]} if left and right else None
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        outer, inner = node.value.id, node.slice
        if outer in ("list", "List"):
            item = _spec(inner, depth + 1)
            return {"kind": "list", "of": item} if item else None
        if outer in ("dict", "Dict") and isinstance(inner, ast.Tuple) and len(inner.elts) == 2:  # noqa: PLR2004
            key, value = inner.elts
            if isinstance(key, ast.Name) and key.id == "str":
                item = _spec(value, depth + 1)
                return {"kind": "dict", "of": item} if item else None
        if outer == "Optional":
            item = _spec(inner, depth + 1)
            return {"kind": "union", "of": [item, {"kind": "none"}]} if item else None
        if outer == "Union" and isinstance(inner, ast.Tuple):
            members = [_spec(e, depth + 1) for e in inner.elts]
            return {"kind": "union", "of": members} if all(members) else None
    return None


# -- inputs --------------------------------------------------------------------------------------


def _strategy(spec: Spec) -> Any:
    from hypothesis import strategies as st  # noqa: PLC0415 - loaded when probing

    simple = {
        "int": lambda: st.integers(min_value=-_INT, max_value=_INT - 1),
        "float": lambda: st.floats(allow_nan=False, allow_infinity=False),
        "str": lambda: st.text(max_size=12),
        "bool": st.booleans,
        "none": st.none,
    }
    kind = spec["kind"]
    if kind in simple:
        return simple[kind]()
    if kind == "list":
        return st.lists(_strategy(spec["of"]), max_size=5)
    if kind == "dict":
        return st.dictionaries(st.text(max_size=6), _strategy(spec["of"]), max_size=4)
    return st.one_of(*[_strategy(member) for member in spec["of"]])


def inputs(candidate: Candidate, count: int = EXAMPLES) -> list[dict[str, Any]]:
    """Up to ``count`` distinct inputs for ``candidate``, the same in every run (Hypothesis,
    derandomized)."""
    from hypothesis import HealthCheck, Phase, given, settings  # noqa: PLC0415
    from hypothesis import strategies as st  # noqa: PLC0415

    strategy = st.tuples(*[_strategy(spec) for _, _, spec in candidate.parameters])
    found: dict[str, dict[str, Any]] = {}

    @settings(
        derandomize=True,
        database=None,
        max_examples=count * 3,
        phases=[Phase.generate],
        suppress_health_check=list(HealthCheck),
        deadline=None,
    )
    @given(strategy)
    def collect(values: tuple[Any, ...]) -> None:
        if len(found) >= count:
            return
        given_input: dict[str, Any] = {"args": [], "kwargs": {}}
        for (name, kind, _), value in zip(candidate.parameters, values, strict=True):
            if kind == "positional":
                given_input["args"].append(value)
            else:
                given_input["kwargs"][name] = value
        found.setdefault(json.dumps(given_input, sort_keys=True), given_input)

    collect()
    return list(found.values())


def fits(spec: Spec, value: Any) -> bool:  # noqa: PLR0911 - one answer per kind
    """Whether ``value`` is of the JSON type ``spec`` describes (within Repro's bounds)."""
    kind = spec["kind"]
    if kind == "none":
        return value is None
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool) and -_INT <= value < _INT
    if kind == "float":
        number = isinstance(value, int | float) and not isinstance(value, bool)
        return number and math.isfinite(value)
    if kind == "str":
        return isinstance(value, str) and len(value) <= MAX_PROPOSED
    if kind == "list":
        return (
            isinstance(value, list)
            and len(value) <= MAX_PROPOSED
            and all(fits(spec["of"], item) for item in value)
        )
    if kind == "dict":
        return (
            isinstance(value, dict)
            and len(value) <= MAX_PROPOSED
            and all(isinstance(k, str) and fits(spec["of"], v) for k, v in value.items())
        )
    return any(fits(member, value) for member in spec["of"])


def arranged(candidate: Candidate, named: Any) -> dict[str, Any] | None:
    """A proposed input, by parameter name, as a call's ``args`` and ``kwargs``; None unless it
    names exactly the function's parameters, each value of its type."""
    names = [name for name, _, _ in candidate.parameters]
    if not isinstance(named, Mapping) or set(named) != set(names) or len(named) != len(names):
        return None
    given: dict[str, Any] = {"args": [], "kwargs": {}}
    for name, kind, spec in candidate.parameters:
        value = named[name]
        if not fits(spec, value):
            return None
        if kind == "positional":
            given["args"].append(value)
        else:
            given["kwargs"][name] = value
    return given


# -- runs ----------------------------------------------------------------------------------------


@dataclass
class ProbeRun:
    """One side's results: ``(function, input) -> record``, and what went wrong."""

    side: str
    label: str
    results: dict[tuple[int, int], dict[str, Any]] = field(default_factory=dict)
    errors: dict[int, str] = field(default_factory=dict)
    complete: bool = True  # False: the run ended early; later calls are missing
    #: Why an incomplete run ended (H01): ``timeout``, ``memory`` or its exit status.
    ended: str = ""


def run_probes(
    side: Side,
    label: str,
    found: Sequence[Candidate],
    given: Sequence[Sequence[dict[str, Any]]],
    *,
    seed: int = 0,
    hash_seed: int | None = None,
    timeout_s: float | None = None,
    stop: Callable[[], bool] | None = None,
) -> ProbeRun:
    """Every function of ``found`` with its inputs ``given``, in ``side``'s sandbox."""
    at = 1 if side.name == "head" else 0
    spec = {
        "roots": sorted({c.roots[at] for c in found}),
        "probes": [
            {"module": c.module[at], "function": c.name, "inputs": list(i)}
            for c, i in zip(found, given, strict=True)
        ],
    }
    data = json.dumps(spec).encode()
    name = f"probes-{uuid.uuid4().hex[:12]}"
    sandbox = side.sandbox
    if isinstance(sandbox, RemoteSandbox):
        relative = f".repro/{name}"
        out = f"{WORK}/{relative}"
        variables = plugin_env(out, seed=seed)
        if hash_seed is not None:
            variables["PYTHONHASHSEED"] = str(hash_seed)
        sandbox.write_files(relative, {"spec.json": data})
        argv = [side.env.python, "-m", "repro_probe", f"{out}/spec.json", f"{out}/out.jsonl"]
        execution = sandbox.run(argv, env=variables, timeout_s=timeout_s, stop=stop)
        output = sandbox.read_file(f"{relative}/out.jsonl", limit=MAX_BYTES)
    else:
        folder = sandbox.work / name
        folder.mkdir(parents=True)
        (folder / "spec.json").write_bytes(data)
        variables = plugin_env(str(folder), seed=seed)
        if hash_seed is not None:
            variables["PYTHONHASHSEED"] = str(hash_seed)
        argv = [
            side.env.python,
            "-m",
            "repro_probe",
            str(folder / "spec.json"),
            str(folder / "out.jsonl"),
        ]
        execution = sandbox.run(
            argv,
            cwd=side.env.project.root,
            env=variables,
            timeout_s=timeout_s,
            stop=stop,
            writable=(folder,),
        )
        target = folder / "out.jsonl"
        output = read_head(target, MAX_BYTES)[0] if target.is_file() else None
    ended = (
        "timeout"
        if execution.outcome == "timeout"
        else "memory"
        if execution.oom_killed
        else f"exit status {execution.returncode}"
    )
    complete = execution.returncode == 0
    run = ProbeRun(side.name, label, complete=complete, ended="" if complete else ended)
    for line in (output or b"").splitlines():
        try:
            record = json.loads(line)
            number = int(record["probe"])
        except (ValueError, KeyError, TypeError):
            continue
        if "error" in record:
            run.errors[number] = str(record["error"])[:500]
        elif isinstance(record.get("input"), int) and record.get("outcome") in ("return", "raise"):
            run.results[(number, record["input"])] = record
    return run


# -- differences ---------------------------------------------------------------------------------


def _same(a: dict[str, Any], b: dict[str, Any], *, ordered: bool = True) -> bool | None:
    if a["outcome"] != b["outcome"] or a.get("type") != b.get("type"):
        return False
    if not a.get("complete") or not b.get("complete"):
        return None
    if ordered:
        return bool(a["result"] == b["result"])
    return bool(a.get("any_order", a["result"]) == b.get("any_order", b["result"]))


def change_of(base: dict[str, Any], head: dict[str, Any]) -> str | None:
    """The class of a probe's difference (E04's names), or None if the same or unknowable."""
    if base["outcome"] != head["outcome"]:
        return "exception_added" if head["outcome"] == "raise" else "exception_removed"
    same = _same(base, head)
    if same is None or same:
        return None
    if base["outcome"] == "raise":
        return "exception_changed"
    if base.get("type") == head.get("type") and _same(base, head, ordered=False):
        return "order_only"
    return "result_changed"


@dataclass
class ProbeDiff:
    """The inputs of one function that differ the same way between base and head."""

    candidate: Candidate
    change: str
    inputs: list[int] = field(default_factory=list)
    tried: int = 0
    unstable: int = 0
    #: How many of the function's inputs Hypothesis generated; the rest were proposed (G07).
    generated: int = 0
    first_input: dict[str, Any] = field(default_factory=dict)
    base: dict[str, Any] = field(default_factory=dict)
    head: dict[str, Any] = field(default_factory=dict)

    @property
    def probe_id(self) -> str:
        slug = _SLUG.sub("_", self.candidate.name.lower()).strip("_") or "function"
        return f"probe_{slug}_{self.inputs[0]}"

    def previews(self) -> tuple[str | None, str | None]:
        return _shown(self.base), _shown(self.head)

    @property
    def found_by(self) -> list[str]:
        """Which generators' inputs differ this way: ``hypothesis``, ``agent`` or both."""
        found = {"hypothesis" if index < self.generated else "agent" for index in self.inputs}
        return sorted(found)

    def summary(self) -> str:
        base, head = self.previews()
        call = self.candidate.call(self.first_input)
        words = {
            "exception_added": "now raises",
            "exception_removed": "no longer raises",
            "exception_changed": "raises another exception",
            "result_changed": "gives another result",
            "order_only": "gives the same entries in another order",
        }[self.change]
        count = len(self.inputs)
        source = (
            "generated input"
            if not self.inputs or self.inputs[0] < self.generated
            else "the probe writer's input"
        )
        text = (
            f"{call} {words}: head {head}, base {base} ({source}; "
            f"{count} of {self.tried} inputs differ this way)"
        )
        return text if len(text) <= SUMMARY else text[: SUMMARY - 1] + "…"

    def evidence(self, run_id: str, artifacts: Sequence[dict[str, Any]]) -> dict[str, Any]:
        base, head = self.previews()
        return {
            "id": new_evidence_id(),
            "run_id": run_id,
            "type": "probe_diff",
            "targets": [{"symbol": self.candidate.symbol, "file": self.candidate.file}],
            "summary": self.summary(),
            "data": {
                "provenance": "generated",
                "probe_id": self.probe_id,
                "change": self.change,
                "inputs_differing": len(self.inputs),
                "inputs_tried": self.tried,
                "inputs_unstable": self.unstable,
                "inputs_proposed": self.tried - self.generated,
                "found_by": self.found_by,
                "reproducer": {
                    "call": self.candidate.call(self.first_input),
                    "input": self.first_input,
                    "base": base,
                    "head": head,
                },
                "generator": {"hypothesis": _hypothesis_version(), "derandomize": True},
            },
            "artifacts": [dict(ref) for ref in artifacts],
            "stability": "stable",  # A and A2 agree on every probe kept
            "origin": "introduced",
            "produced_by": {"component": "repro.runner.probes", "version": __version__},
        }

    def payload(self, evidence_id: str) -> dict[str, Any]:
        base, head = self.previews()
        return {
            "evidence_id": evidence_id,
            "symbol_id": self.candidate.symbol,
            "probe_id": self.probe_id,
            "change": self.change,
            "base_preview": base,
            "head_preview": head,
        }


def _shown(record: dict[str, Any]) -> str | None:
    if not record:
        return None
    shown = str(record.get("preview", ""))[:PREVIEW]
    return f"raises {shown}" if record["outcome"] == "raise" else shown


def _hypothesis_version() -> str:
    return installed_version("hypothesis")


@dataclass
class Probing:
    """A run's probes: what was probed, the three runs, and the differences."""

    candidates: list[Candidate]
    inputs: list[list[dict[str, Any]]]
    runs: dict[str, ProbeRun]
    differences: list[ProbeDiff]
    unstable: dict[str, int]  # symbol -> inputs left out (A and A2 differ)
    #: Per function, how many of its inputs Hypothesis generated (the rest were proposed).
    generated: list[int] = field(default_factory=list)
    #: Proposed inputs that ran, that A and A2 disagreed on, and that differ on head (G07).
    proposed: dict[str, int] = field(default_factory=dict)

    def missing(self) -> list[dict[str, Any]]:
        items = []
        for run in self.runs.values():
            if not run.complete:
                why, reason = {
                    "timeout": ("took longer than its limit", "timeout"),
                    "memory": ("reached its memory limit", "memory_limit"),
                }.get(
                    run.ended,
                    (f"ended early ({run.ended or 'no exit status'})", "environment_failed"),
                )
                detail = (
                    f"{run.side} ({run.label}): the probe run {why}; its later calls are missing"
                )
                items.append(_missing(reason, detail, None))
            for number, error in sorted(run.errors.items()):
                symbol = self.candidates[number].symbol
                detail = f"{run.side}: {symbol} could not be probed: {error}"
                items.append(_missing("environment_failed", detail, symbol))
        for symbol, count in sorted(self.unstable.items()):
            detail = (
                f"{count} generated inputs of {symbol} gave different results on two runs of "
                "base: not compared"
            )
            items.append(_missing("unstable_observation", detail, symbol))
        return items

    def document(self) -> dict[str, Any]:
        """The probes and their results, for ``obs/probes.cbor``."""
        return {
            "format": "repro.probes/1",
            "functions": [
                {"symbol": c.symbol, "module": list(c.module), "name": c.name, "inputs": i}
                for c, i in zip(self.candidates, self.inputs, strict=True)
            ],
            "runs": {
                label: [[f, i, r] for (f, i), r in sorted(run.results.items())]
                for label, run in self.runs.items()
            },
        }


def _missing(reason: str, detail: str, symbol: str | None) -> dict[str, Any]:
    return {
        "missing": {
            "reason": reason,
            "targets": [{"symbol": symbol}] if symbol else [],
            "detail": detail[:1000],
            "resolution": None,
        }
    }


def compare(
    found: Sequence[Candidate],
    given: Sequence[Sequence[dict[str, Any]]],
    runs: dict[str, ProbeRun],
    generated: Sequence[int] | None = None,
) -> Probing:
    """Base against head for every input both ran, those A and A2 disagree on left out;
    ``generated``: per function, how many of its inputs came first from Hypothesis."""
    base, again, head = runs["A"], runs["A2"], runs["H"]
    counts = list(generated) if generated is not None else [len(i) for i in given]
    groups: dict[tuple[int, str], ProbeDiff] = {}
    unstable: dict[str, int] = {}
    proposed = {"ran": 0, "unstable": 0, "differing": 0}
    for number, candidate in enumerate(found):
        for index in range(len(given[number])):
            mine = index >= counts[number]
            key = (number, index)
            first, second, last = (
                base.results.get(key),
                again.results.get(key),
                head.results.get(key),
            )
            if first is None or last is None:
                continue
            proposed["ran"] += mine
            if second is None or _same(first, second) is not True:
                unstable[candidate.symbol] = unstable.get(candidate.symbol, 0) + 1
                proposed["unstable"] += mine
                continue
            change = change_of(first, last)
            if change is None:
                continue
            proposed["differing"] += mine
            group = groups.get((number, change))
            if group is None:
                group = ProbeDiff(
                    candidate, change, first_input=given[number][index], base=first, head=last
                )
                groups[(number, change)] = group
            group.inputs.append(index)
    for (number, _), group in groups.items():
        group.tried = len(given[number])
        group.unstable = unstable.get(found[number].symbol, 0)
        group.generated = counts[number]
    differences = sorted(groups.values(), key=lambda g: (g.candidate.symbol, g.change))
    return Probing(
        list(found), [list(i) for i in given], runs, differences, unstable, counts, proposed
    )


def probe(
    sides: tuple[Side, Side],
    found: Sequence[Candidate],
    *,
    proposed: Sequence[Sequence[dict[str, Any]]] | None = None,
    timeout_s: float | None = None,
    stop: Callable[[], bool] | None = None,
) -> Probing:
    """Generates the inputs, adds ``proposed`` (per function, after Hypothesis's, without
    repeats), runs them on base, base again (A2) and head, and compares."""
    generated = [inputs(candidate) for candidate in found]
    given = []
    for number, own in enumerate(generated):
        seen = {json.dumps(i, sort_keys=True) for i in own}
        extra = []
        for item in proposed[number] if proposed is not None else []:
            text = json.dumps(item, sort_keys=True)
            if text not in seen:
                seen.add(text)
                extra.append(item)
        given.append([*own, *extra])
    runs = {
        "A": run_probes(sides[0], "A", found, given, timeout_s=timeout_s, stop=stop),
        "A2": run_probes(
            sides[0],
            "A2",
            found,
            given,
            seed=OTHER_SEED,
            hash_seed=OTHER_SEED,
            timeout_s=timeout_s,
            stop=stop,
        ),
        "H": run_probes(sides[1], "H", found, given, timeout_s=timeout_s, stop=stop),
    }
    return compare(found, given, runs, [len(own) for own in generated])
