"""Symbolic deep checks with CrossHair (K04)."""

import ast
import importlib
import sys
from pathlib import Path

import pytest

from gitrepo import Repo
from repro import symbolic
from repro.gitops import Git

#: diffbehavior's output, as CrossHair 0.0.111 printed it in K04's trial.
DIFFERENCE = (
    "Given: (x=10),\n"
    "  repro_symbolic_shim.base : returns 10\n"
    "  repro_symbolic_shim.head : returns 9\n"
)
SAME = (
    "No differences found. (attempted 2 iterations)\n"
    "All paths exhausted, functions are likely the same!\n"
)


@pytest.mark.parametrize(
    ("path", "module"),
    [
        ("src/pkg/core.py", "pkg.core"),
        ("pkg/__init__.py", "pkg"),
        ("tool.py", "tool"),
        ("docs/conf-file.py", None),
        ("README.md", None),
    ],
)
def test_a_files_module_name(path: str, module: str | None) -> None:
    assert symbolic.module_name(path) == module


def reason(source: str) -> str:
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    return symbolic.why_not(node, source)


@pytest.mark.parametrize(
    ("source", "why"),
    [
        ("def f(x: int, ys: list[int]) -> int:\n    return x + sum(ys)\n", ""),
        ("def f(x: int | None) -> int:\n    return x or 0\n", ""),
        ("@cache\ndef f(x: int) -> int:\n    return x\n", "decorated"),
        ("def f(x: int):\n    yield x\n", "a generator"),
        ("async def f(x: int) -> int:\n    return x\n", "a coroutine"),
        ("def f(x):\n    return x\n", "parameters without a plain data annotation: x"),
        (
            "def f(p: Path) -> str:\n    return str(p)\n",
            "parameters without a plain data annotation: p",
        ),
        (
            "def f(x: int) -> int:\n    print(x)\n    return x\n",
            "calls something that reaches the world",
        ),
        (
            "def f(x: int) -> float:\n    return time.time() + x\n",
            "calls something that reaches the world",
        ),
        ("def f(*xs: int) -> int:\n    return 0\n", "takes *args or **kwargs"),
        ("def f() -> int:\n    return 1\n", "takes no parameters"),
        (
            "def f(x: int) -> int:\n" + "    x += 1\n" * 61 + "    return x\n",
            "longer than 60 lines",
        ),
    ],
)
def test_only_small_pure_functions_are_checked(source: str, why: str) -> None:
    assert reason(source) == why


BASE = """def threshold(x: int) -> int:
    if x > 10:
        return x - 1
    return x


def loud(x: int) -> int:
    print(x)
    return x


def same(x: int) -> int:
    return x
"""
HEAD = BASE.replace("x > 10", "x >= 10").replace("print(x)", "print(x, x)")


@pytest.fixture
def change(tmp_path: Path) -> tuple[Repo, str, str]:
    repo = Repo(tmp_path / "repo")
    base = repo.commit({"pkg/__init__.py": "", "pkg/m.py": BASE})
    head = repo.commit({"pkg/m.py": HEAD, "pkg/new.py": "def g(x: int) -> int:\n    return x\n"})
    return repo, base, head


def test_the_functions_a_change_edits(change: tuple[Repo, str, str]) -> None:
    repo, base, head = change
    found = {c.name: c for c in symbolic.changed_functions(Git(repo.path), base, head)}
    assert set(found) == {"threshold", "loud"}  # same is unchanged; g is new
    assert found["threshold"].why_not == ""
    assert found["loud"].why_not == "calls something that reaches the world"
    assert found["threshold"].module == "pkg.m"


def test_the_shim_runs_bases_body_beside_heads(
    change: tuple[Repo, str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base, head = change
    (threshold,) = [
        c for c in symbolic.changed_functions(Git(repo.path), base, head) if c.name == "threshold"
    ]
    package = tmp_path / "head" / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "m.py").write_text(HEAD, encoding="utf-8")
    (tmp_path / "head" / f"{symbolic.SHIM}.py").write_text(
        symbolic.shim(threshold), encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path / "head"))
    for name in ("pkg", "pkg.m", symbolic.SHIM):
        sys.modules.pop(name, None)
    loaded = importlib.import_module(symbolic.SHIM)
    assert (loaded.base(10), loaded.head(10)) == (10, 9)
    assert (loaded.base(3), loaded.head(3)) == (3, 3)


def test_diffbehaviors_output_is_read() -> None:
    assert symbolic.read_output(DIFFERENCE) == ("difference", "x=10", "returns 10", "returns 9")
    assert symbolic.read_output(SAME)[0] == "none_found"
    assert symbolic.read_output("Traceback ... ImportError")[0] == "error"


def test_a_real_change_through_crosshair(change: tuple[Repo, str, str], tmp_path: Path) -> None:
    """End to end: head provisioned, CrossHair added, the boundary found."""
    repo, base, head = change
    report = symbolic.run_change(Git(repo.path), base, head, tmp_path / "work", tmp_path / "envs")
    assert report.problem == ""
    results = {r.name: r for r in report.results}
    assert results["threshold"].outcome == "difference"
    assert results["threshold"].given == "x=10"
    assert (results["threshold"].base, results["threshold"].head) == ("returns 10", "returns 9")
    assert results["loud"].outcome == "not_checked"
