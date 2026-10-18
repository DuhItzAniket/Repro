"""Symbolic deep checks: CrossHair's ``diffbehavior`` on small pure functions a change edits (K04).

Tests show what a change does on the inputs they try. For a small, pure function, a symbolic
executor can search the inputs itself. CrossHair's ``diffbehavior`` looks for an input on
which two functions behave differently, and prints it: "Given: (x=10), … returns 10 …
returns 9" [CrossHair, ``crosshair diffbehavior --help`` and its output, v0.0.111, checked
2026-10-18]. When the search finds nothing it says "No differences found". That means none
was found in its budget, not that the functions are equal.

**Which functions**: a top-level function the change edits whose base and head both parse.
It must be small (60 lines at most), take only parameters annotated with plain data types
(numbers, text, bytes, and lists, tuples, dicts and sets of them), and call nothing that
reaches the world (files, processes, the network, the clock, randomness). Methods, decorated
functions, generators and coroutines are left out. Each one left out is named, with why.

**How**: head's environment is provisioned as for a run (D03), and CrossHair 0.0.111 (MIT) is
added to it. A shim module imports head's module and loads base's version of the function
into a copy of that module's namespace. So the two differ only in the function's body; the
helpers it calls are head's for both. The shim runs in the process sandbox, with a time limit
per function.

    repro symbolic --repo <path> --base <ref> --head <ref> [--json <file>]

Experimental: it reports, and makes no card. A counterexample becomes evidence once the event
schema has a type for it (the owner's decision: a schema change).
"""

import ast
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Final

from repro.gitops import Git, GitError, snapshot
from repro.provision import HostProvisioner, ProvisionError, inspect_project
from repro.sandbox import Limits, ProcessSandbox

CROSSHAIR: Final = "crosshair-tool==0.0.111"
MAX_LINES: Final = 60
TIMEOUT_S: Final = 60.0
SHIM: Final = "repro_symbolic_shim"
#: Annotations CrossHair reasons about well: plain data.
_PLAIN: Final = frozenset(
    {
        "int",
        "float",
        "bool",
        "str",
        "bytes",
        "list",
        "tuple",
        "dict",
        "set",
        "frozenset",
        "None",
        "Optional",
        "List",
        "Tuple",
        "Dict",
        "Set",
    }
)
#: Calls that reach the world: a function making any is not pure.
_EFFECTS: Final = re.compile(
    r"\b(open|print|input|exec|eval|compile|__import__|breakpoint)\s*\(|"
    r"\b(os|sys|subprocess|socket|shutil|pathlib|time|random|datetime|requests|urllib|"
    r"threading|asyncio)\."
)
_GIVEN: Final = re.compile(r"^Given: \((?P<args>.*)\),\s*$", re.M)
_ANSWER: Final = re.compile(rf"^\s+{SHIM}\.(?P<side>base|head) : (?P<what>.*)$", re.M)


class SymbolicError(Exception):
    """The check could not run; the message says why."""


@dataclass(frozen=True)
class Changed:
    module: str
    name: str
    base_source: str
    head_source: str
    why_not: str = ""  # empty when the function is checked


@dataclass
class Result:
    module: str
    name: str
    outcome: str  # "difference", "none_found", "not_checked" or "error"
    detail: str = ""
    given: str = ""
    base: str = ""
    head: str = ""


def module_name(path: str) -> str | None:
    """The importable name of a Python file of the repository (``src/`` layout or flat)."""
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if not path.endswith(".py") or not parts:
        return None
    if parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts and all(p.isidentifier() for p in parts) else None


def _functions(source: str) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _annotation_plain(node: ast.expr | None) -> bool:
    if node is None:
        return False
    names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    names |= {
        str(n.value) for n in ast.walk(node) if isinstance(n, ast.Constant) and n.value is None
    }
    return bool(names) and names <= _PLAIN


def why_not(  # noqa: PLR0911 - one return per reason a function is left out
    node: ast.FunctionDef | ast.AsyncFunctionDef, source: str
) -> str:
    """Why a function is not checked, or ``""``."""
    if isinstance(node, ast.AsyncFunctionDef):
        return "a coroutine"
    if node.decorator_list:
        return "decorated"
    if any(isinstance(n, ast.Yield | ast.YieldFrom) for n in ast.walk(node)):
        return "a generator"
    if (node.end_lineno or node.lineno) - node.lineno + 1 > MAX_LINES:
        return f"longer than {MAX_LINES} lines"
    arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    if node.args.vararg or node.args.kwarg:
        return "takes *args or **kwargs"
    if not arguments:
        return "takes no parameters"
    bad = [a.arg for a in arguments if not _annotation_plain(a.annotation)]
    if bad:
        return f"parameters without a plain data annotation: {', '.join(bad)}"
    if _EFFECTS.search(ast.get_source_segment(source, node) or ""):
        return "calls something that reaches the world"
    return ""


def changed_functions(git: Git, base: str, head: str) -> list[Changed]:
    """The top-level functions a change edits, in files present on both sides."""
    try:
        names = git.text("diff", "--name-only", "--no-renames", base, head).splitlines()
    except GitError as exc:
        raise SymbolicError(f"the change cannot be read: {exc}") from None
    found = []
    for path in names:
        module = module_name(path)
        if module is None:
            continue
        try:
            old = git.run("show", f"{base}:{path}").decode("utf-8")
            new = git.run("show", f"{head}:{path}").decode("utf-8")
        except (GitError, UnicodeDecodeError):
            continue  # added, removed or not text: nothing to compare
        before, after = _functions(old), _functions(new)
        for name in sorted(before.keys() & after.keys()):
            old_src = ast.get_source_segment(old, before[name]) or ""
            new_src = ast.get_source_segment(new, after[name]) or ""
            if old_src == new_src:
                continue
            reason = why_not(before[name], old) or why_not(after[name], new)
            found.append(Changed(module, name, old_src, new_src, reason))
    return found


def shim(changed: Changed) -> str:
    """A module whose ``base`` is base's version of the function, in head's module namespace,
    and whose ``head`` is head's."""
    return (
        "import importlib\n"
        f"_module = importlib.import_module({changed.module!r})\n"
        "_namespace = dict(vars(_module))\n"
        f"exec(compile({changed.base_source!r}, '<base>', 'exec'), _namespace)\n"
        f"base = _namespace[{changed.name!r}]\n"
        f"head = getattr(_module, {changed.name!r})\n"
    )


def read_output(text: str) -> tuple[str, str, str, str]:
    """``(outcome, given, base's answer, head's answer)`` from ``diffbehavior``'s output."""
    given = _GIVEN.search(text)
    if given:
        answers = {m["side"]: m["what"].strip() for m in _ANSWER.finditer(text)}
        return "difference", given["args"], answers.get("base", ""), answers.get("head", "")
    if "No differences found" in text:
        return "none_found", "", "", ""
    return "error", "", "", ""


def check(changed: Changed, python: str, box: ProcessSandbox, root: Path, work: Path) -> Result:
    if changed.why_not:
        return Result(changed.module, changed.name, "not_checked", changed.why_not)
    directory = work / f"shim-{changed.module}-{changed.name}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{SHIM}.py").write_bytes(shim(changed).encode("utf-8"))
    argv = [
        python,
        "-m",
        "crosshair",
        "diffbehavior",
        f"{SHIM}.base",
        f"{SHIM}.head",
        "--max_uninteresting_iterations",
        "20",
        "--per_path_timeout",
        "2",
    ]
    run = box.run(
        argv,
        cwd=root,
        env={"PYTHONPATH": str(directory)},
        timeout_s=TIMEOUT_S,
        writable=(directory,),
    )
    said = run.stdout.decode("utf-8", "replace") + run.stderr.decode("utf-8", "replace")
    outcome, given, base, head = read_output(said)
    detail = "" if outcome != "error" else (said.strip().splitlines() or [run.outcome])[-1][:300]
    return Result(changed.module, changed.name, outcome, detail, given, base, head)


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)
    problem: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "functions": [asdict(r) for r in self.results],
            "problem": self.problem,
            "note": "none_found is no difference found within the search's budget, not a proof",
        }


def run_change(git: Git, base: str, head: str, work: Path, cache: Path) -> Report:
    report = Report()
    try:
        found = changed_functions(git, base, head)
        if not any(not c.why_not for c in found):
            report.results = [Result(c.module, c.name, "not_checked", c.why_not) for c in found]
            return report
        tree = work / "head"
        snapshot(git, head, tree)
        box = ProcessSandbox(work / "box", Limits(timeout_s=TIMEOUT_S))
        env = HostProvisioner(cache).provision("head", inspect_project(tree), box)
        added = subprocess.run(  # noqa: S603 - uv, adding a pinned tool to the side's environment
            [
                shutil.which("uv") or "uv",
                "pip",
                "install",
                "--quiet",
                "--python",
                env.python,
                CROSSHAIR,
            ],
            capture_output=True,
            check=False,
            timeout=600,
        )
        if added.returncode != 0:
            raise SymbolicError(f"CrossHair could not be installed: {added.stderr.decode()[-300:]}")
        report.results = [check(c, env.python, box, tree, work) for c in found]
    except (SymbolicError, ProvisionError, GitError) as exc:
        report.problem = str(exc)
    return report


def summary(report: Report) -> str:
    return json.dumps(report.as_dict(), indent=2)
