"""JavaScript and TypeScript: function-level traces of a change, compared base against head (K07).

The runs are real: the monorepo's Vitest 5.0.4 on tiny repositories, each side traced, base
twice (the second time shuffled) and head once, compared as Python's traces are.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from gitrepo import Repo
from repro import jsmap, jstrace, jsts
from repro.gitops import Git

ROOT = Path(__file__).resolve().parents[2]
VITEST = ROOT / "apps" / "web" / "node_modules" / "vitest" / "vitest.mjs"
CHECKS = Path(__file__).parent / "data" / "js" / "encoder_checks.cjs"
NODE = shutil.which("node")
NEEDS_NODE = pytest.mark.skipif(NODE is None, reason="needs node")
NEEDS_VITEST = pytest.mark.skipif(
    NODE is None or not VITEST.is_file(),
    reason="needs node and the monorepo's Vitest (pnpm install)",
)
PROJECT = {
    "package.json": json.dumps({"type": "module", "devDependencies": {"vitest": "5.0.4"}}),
    "package-lock.json": "{}",
    "vitest.config.mjs": "export default { test: { globals: true } };\n",
}


def behaviour_of(tmp_path: Path, base: dict[str, str], head: dict[str, str]) -> dict[str, Any]:
    repo = Repo(tmp_path / "repo")
    base_commit = repo.commit(PROJECT | base)
    head_commit = repo.commit(head)
    found = jsts.run_change(
        Git(repo.path),
        base_commit,
        head_commit,
        tmp_path / "work",
        install=False,
        entry=str(VITEST),
    )
    assert found["base"]["problem"] == ""  # type: ignore[index]
    behaviour = found["behaviour"]
    assert isinstance(behaviour, dict)
    return behaviour


def changes(behaviour: dict[str, Any]) -> set[tuple[str, str, str]]:
    return {(d["function"], d["test"], d["change"]) for d in behaviour["differences"]}


# -- the runtime ----------------------------------------------------------------------------------


@NEEDS_NODE
def test_the_runtime_keeps_its_guarantees(tmp_path: Path) -> None:
    """The same value, the same digest; order kept apart; cycles incomplete; no getter or proxy
    trap run; typed arrays by their own bytes; construction passed through; a raise and a
    settled promise recorded, as Python's tracer writes calls."""
    assert NODE is not None
    runtime = jsmap.HOOKS / jsmap.TRACE_RUNTIME
    done = subprocess.run(
        [NODE, str(CHECKS), str(runtime), str(tmp_path)],
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    assert b"all checks passed (3 records)" in done.stdout


def test_the_plan_is_the_changed_functions() -> None:
    found = jstrace.plan(
        [
            jsmap.JsChange("src/m.js", frozenset({"twice", "add"}), module_level=False),
            jsmap.JsChange("src/top.js", frozenset(), module_level=True),
        ]
    )
    assert found == {"src/m.js": ["add", "twice"]}
    assert jstrace.targets(found) == {
        ("src/m.js", "add", 1, 1): "src/m.js:add",
        ("src/m.js", "twice", 1, 1): "src/m.js:twice",
    }
    assert jstrace.shuffled("vitest") == ["--sequence.shuffle", "--sequence.seed=1"]
    assert jstrace.shuffled("jest") == ["--randomize", "--seed=1"]


# -- for real, with Vitest ------------------------------------------------------------------------


@NEEDS_VITEST
def test_a_change_no_test_catches_is_a_stable_difference(tmp_path: Path) -> None:
    """Every test passes on both sides; label() now rounds to whole numbers. The test that only
    calls twice() sees add() change too: the plugin wraps it inside its module."""
    base = {
        "src/m.js": (
            "export function label(n) {\n  return `n=${n.toFixed(1)}`;\n}\n\n"
            "export function add(a, b) {\n  return a + b;\n}\n\n"
            "export function twice(a) {\n  return add(a, a);\n}\n"
        ),
        "test/m.test.js": (
            'import { label, twice } from "../src/m.js";\n'
            'test("label", () => { expect(label(2)).toContain("n="); });\n'
            'test("twice", () => { expect(twice(2) > 0).toBe(true); });\n'
        ),
    }
    head = {
        "src/m.js": base["src/m.js"]
        .replace("n.toFixed(1)", "n.toFixed(0)")
        .replace("return a + b;", "return a + b + 1;")
    }
    found = behaviour_of(tmp_path, base, head)
    assert changes(found) == {
        ("src/m.js:label", "test/m.test.js::label", "result_changed"),
        ("src/m.js:add", "test/m.test.js::twice", "result_changed"),
    }
    label = next(d for d in found["differences"] if d["function"] == "src/m.js:label")
    assert label["stability"] == "stable"
    assert label["summary"].startswith('label(2) gives another result: head "n=2", base "n=2.0"')


@NEEDS_VITEST
def test_noise_is_masked_not_a_difference(tmp_path: Path) -> None:
    """A function whose result differs between two runs of base (a random draw) is noise."""
    base = {
        "src/m.js": "export function draw() {\n  return Math.random();\n}\n",
        "test/m.test.js": (
            'import { draw } from "../src/m.js";\n'
            'test("draws", () => { expect(draw() < 1).toBe(true); });\n'
        ),
    }
    head = {"src/m.js": "export function draw() {\n  return Math.random() * 1;\n}\n"}
    found = behaviour_of(tmp_path, base, head)
    assert found["differences"] == []
    assert found["counts"]["unstable"] == 1


@NEEDS_VITEST
def test_methods_accessors_and_const_functions_are_traced(tmp_path: Path) -> None:
    base = {
        "src/box.js": (
            "export class Box {\n"
            "  constructor(items) {\n    this.items = items;\n  }\n"
            "  get size() {\n    return this.items.length;\n  }\n"
            "  first() {\n    return this.items[0];\n  }\n"
            "}\n\n"
            "export const total = (box) => {\n  return box.items.reduce((a, b) => a + b, 0);\n};\n"
        ),
        "test/box.test.js": (
            'import { Box, total } from "../src/box.js";\n'
            'test("box", () => {\n'
            "  const box = new Box([1, 2, 3]);\n"
            "  expect(box.size > 0).toBe(true);\n"
            "  expect(box.first() > 0).toBe(true);\n"
            "  expect(total(box) > 0).toBe(true);\n"
            "});\n"
        ),
    }
    head = {
        "src/box.js": base["src/box.js"]
        .replace("return this.items.length;", "return this.items.length + 1;")
        .replace("return this.items[0];", "return this.items[1];")
        .replace("reduce((a, b) => a + b, 0)", "reduce((a, b) => a + b, 1)")
    }
    found = behaviour_of(tmp_path, base, head)
    assert {(fn, change) for fn, _, change in changes(found)} == {
        ("src/box.js:get size", "result_changed"),
        ("src/box.js:first", "result_changed"),
        ("src/box.js:total", "result_changed"),
    }
