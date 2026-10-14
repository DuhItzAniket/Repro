"""One side's module import graph (ADR-0006): grimp for packages, ``ast`` for the other modules.

Modules carry C06's names (``module_names``), so the graph, the changed symbols and the blast
radius agree. grimp reads the regular packages (a top-level directory with an ``__init__.py``,
and everything below it through ``__init__.py`` directories). It runs in a process of its own
(``_grimp_worker.py``) over a tree holding only those packages' ``.py`` files, written from
their blobs, so it can be timed out, and no target name is ever resolved through ``sys.path``.

Modules grimp cannot load as a package (a test file outside a package, a script, a root
``conftest.py``) still import the packages, and those edges are what makes a test an importer.
Their imports are read with ``ast`` and resolved against the same names: ``import a.b.c`` and
``from a.b import c`` point to the most specific module that exists, relative imports are
resolved from the module's own package. Dynamic imports (``importlib``, ``__import__``) are not
seen by either.

What could not be read is listed in ``problems``, never dropped in silence.
"""

import ast
import importlib.util
import json
import subprocess
import sys
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from repro.gitops import path_problem
from repro.gitops.snapshot import case_insensitive, remove_snapshot

DEFAULT_TIMEOUT: Final = 120.0
_WORKER: Final = Path(__file__).with_name("_grimp_worker.py")
_INIT: Final = "__init__.py"


@dataclass(frozen=True, slots=True)
class GraphProblem:
    """Something the graph could not include: a file or package, and why."""

    subject: str
    reason: str


@dataclass(frozen=True, slots=True)
class ImportGraph:
    modules: Mapping[str, str]  # module name -> file
    imports: frozenset[tuple[str, str]]  # (importer, imported)
    problems: tuple[GraphProblem, ...]


def _top_level_packages(names: Mapping[str, str]) -> dict[str, str]:
    """Each regular top-level package: name -> its directory."""
    packages = {}
    for path, name in names.items():
        if "." not in name and (path == _INIT or path.endswith("/" + _INIT)):
            packages[name] = path[: -len(_INIT)].rstrip("/")
    return packages


def _in_package(name: str, packages: Collection[str]) -> bool:
    return name.partition(".")[0] in packages


def _grimp_path() -> str:
    spec = importlib.util.find_spec("grimp")  # Repro's own dependency, not a target name
    if spec is None or spec.origin is None:
        raise RuntimeError("grimp is not installed")
    return str(Path(spec.origin).parent.parent)


def _run_grimp(
    sources: Mapping[str, bytes],
    names: Mapping[str, str],
    packages: Mapping[str, str],
    workdir: Path,
    *,
    timeout: float,
    problems: list[GraphProblem],
) -> set[tuple[str, str]]:
    """grimp's edges between the packages' modules; what it could not read goes to ``problems``."""
    tree = workdir / "import-graph"
    tree.mkdir(parents=True)
    try:
        insensitive = case_insensitive(tree)
        written: dict[str, str] = {}  # path as the filesystem sees it -> path
        for path, name in sorted(names.items()):
            if not _in_package(name, packages):
                continue
            key = path.lower() if insensitive else path
            problem = path_problem(path)
            if problem is None and key in written:
                problem = f"collides with {written[key]!r} on this case-insensitive filesystem"
            if problem is not None:
                problems.append(GraphProblem(path, f"not analysed: {problem}"))
                continue
            written[key] = path
            target = tree.joinpath(*path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(sources[path])
        request = {
            "grimp_path": _grimp_path(),
            "tree": str(tree),
            "packages": {
                name: str(tree.joinpath(*directory.split("/")))
                for name, directory in packages.items()
            },
        }
        try:
            done = subprocess.run(  # noqa: S603 - this interpreter, Repro's own worker script
                [sys.executable, "-I", "-S", str(_WORKER)],
                input=json.dumps(request).encode(),
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            problems.append(GraphProblem("packages", f"grimp took longer than {timeout:g} s"))
            return set()
        error = done.stderr.decode("utf-8", "replace").strip().splitlines()
        try:
            response: dict[str, Any] = json.loads(done.stdout) if done.returncode == 0 else {}
        except ValueError:
            response = {}
        if "imports" not in response:
            reason = error[-1] if error else f"exit status {done.returncode}"
            problems.append(GraphProblem("packages", f"grimp failed: {reason}"))
            return set()
    finally:
        remove_snapshot(tree)
    problems.extend(GraphProblem(path, reason) for path, reason in response["unparsable"])
    known = set(names.values())
    return {
        (importer, imported)
        for importer, imported in response["imports"]
        if importer in known and imported in known and importer != imported
    }


def _most_specific(name: str, known: Collection[str]) -> str | None:
    """``name`` or its nearest parent that is a known module."""
    while name:
        if name in known:
            return name
        name = name.rpartition(".")[0]
    return None


def _imported_by(
    module: str, is_package: bool, tree: ast.Module, known: Collection[str]
) -> set[str]:
    package = module if is_package else module.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(t for a in node.names if (t := _most_specific(a.name, known)))
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # from . import x: level 1 is the module's own package
                parts = package.split(".") if package else []
                keep = len(parts) - (node.level - 1)
                if keep <= 0:
                    continue  # above the top-level package (or no package): not importable
                base_parts = parts[:keep]
                if node.module:
                    base_parts.append(node.module)
                base = ".".join(base_parts)
            else:
                base = node.module or ""
            for alias in node.names:
                wanted = base if alias.name == "*" else f"{base}.{alias.name}"
                target = wanted if wanted in known else _most_specific(base, known)
                if target:
                    found.add(target)
    found.discard(module)
    return found


def import_graph(
    sources: Mapping[str, bytes],
    names: Mapping[str, str],
    workdir: Path,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> ImportGraph:
    """The import graph of one side: ``sources`` maps each ``.py`` path to its bytes, ``names``
    each path to its module name (from ``module_names``). ``workdir`` holds grimp's tree while it
    runs."""
    names = {path: name for path, name in names.items() if path in sources}
    problems: list[GraphProblem] = []
    packages = {}
    for name, directory in _top_level_packages(names).items():
        problem = path_problem(directory)
        if problem is None:
            packages[name] = directory
        else:
            problems.append(GraphProblem(directory, f"package not analysed: {problem}"))
    imports = (
        _run_grimp(sources, names, packages, workdir, timeout=timeout, problems=problems)
        if packages
        else set()
    )
    known = set(names.values())
    for path, name in sorted(names.items()):
        if _in_package(name, packages):
            continue
        try:
            tree = ast.parse(sources[path])
        except SyntaxError as exc:
            where = f"line {exc.lineno}: " if exc.lineno else ""
            problems.append(GraphProblem(path, f"does not parse ({where}{exc.msg})"))
            continue
        except (MemoryError, RecursionError):
            problems.append(GraphProblem(path, "too complex to parse"))
            continue
        is_package = path == _INIT or path.endswith("/" + _INIT)
        imports.update((name, target) for target in _imported_by(name, is_package, tree, known))
    modules = {name: path for path, name in names.items()}
    return ImportGraph(modules, frozenset(imports), tuple(problems))
