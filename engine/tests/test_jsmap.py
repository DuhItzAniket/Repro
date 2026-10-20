"""JavaScript and TypeScript: the test -> function map and the selection it makes (K06)."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from gitrepo import Repo
from repro import jsmap, jsts
from repro.gitops import Git

ROOT = Path(__file__).resolve().parents[2]
VITEST = ROOT / "apps" / "web" / "node_modules" / "vitest" / "vitest.mjs"
NEEDS_VITEST = pytest.mark.skipif(
    shutil.which("node") is None or not VITEST.is_file(),
    reason="needs node and the monorepo's Vitest (pnpm install)",
)

SOURCE = """import x from "y";
const TOP = 1;

export function add(a, b) {
  return a + b;
}

function twice({ a, b }) {
  // a brace in a comment {
  const s = "} not a brace";
  return add(a, a);
}

class Box {
  constructor(v) {
    this.v = v;
  }
  get size() {
    return 1;
  }
  async load(path: string): Promise<void> {
    await fetch(path);
  }
}

const arrow = (x) => x * 3;
const block = async (x) => {
  return x;
};
items.map((x) => {
  return x;
});
"""


# -- the scanner ----------------------------------------------------------------------------------


def test_functions_are_found_with_their_lines() -> None:
    found = {(f.name, f.first, f.last) for f in jsmap.functions(SOURCE)}
    assert found == {
        ("add", 4, 6),
        ("twice", 8, 12),  # braces in its parameters, a comment and a string are not its body
        ("constructor", 15, 17),
        ("get size", 18, 20),  # as V8 names a getter
        ("load", 21, 23),  # TypeScript's annotations
        ("arrow", 26, 26),  # an expression body ends with its line
        ("block", 27, 29),
    }


@pytest.mark.parametrize(
    ("lines", "names", "module"),
    [
        ([5], {"add"}, False),
        ([11], {"twice"}, False),
        ([19], {"get size"}, False),
        ([2], set(), True),  # module-level code
        ([16], set(), True),  # V8 names a constructor after its class: taken as module-level
        ([32], set(), True),  # an anonymous callback at module level
        ([5, 23], {"add", "load"}, False),
    ],
)
def test_a_changed_line_belongs_to_the_innermost_named_function(
    lines: list[int], names: set[str], module: bool
) -> None:
    assert jsmap.attribute(SOURCE, lines) == (names, module)


# -- the map --------------------------------------------------------------------------------------


def records(*rows: dict[str, Any]) -> bytes:
    return "".join(json.dumps(row) + "\n" for row in rows).encode()


def test_the_map_is_read_from_the_setup_files_lines() -> None:
    read = jsmap.read_map(
        records(
            {"file": "test/m.test.js", "loaded": ["src/m.js", "test/m.test.js"]},
            {"file": "test/m.test.js", "test": "m adds", "ran": [["src/m.js", "add"]]},
            {"file": "test/m.test.js", "test": "m adds", "ran": [["src/m.js", ""]]},
            {"error": "coverage was not taken: boom"},
        )
    )
    assert read.ran == {
        "test/m.test.js::m adds": frozenset({("src/m.js", "add"), ("src/m.js", "")})
    }
    assert read.loaded == {"test/m.test.js": frozenset({"src/m.js", "test/m.test.js"})}
    assert read.problem == "coverage was not taken: boom"
    with pytest.raises(jsmap.MapError, match="line 1"):
        jsmap.read_map(b'{"file": "t.js", "test": "x"}\n')


def test_jest_keeps_the_projects_own_setup_files(tmp_path: Path) -> None:
    shown = json.dumps({"configs": [{"setupFilesAfterEnv": ["/p/own.js"]}], "globalConfig": {}})
    own = jsmap.jest_own_setup(shown.encode())
    assert jsmap.jest_setup(tmp_path, own) == [
        "--setupFilesAfterEnv",
        "/p/own.js",
        str(tmp_path / jsmap.JEST_SETUP),
    ]
    assert (tmp_path / jsmap.JEST_SETUP).is_file()
    two = json.dumps({"configs": [{}, {}]}).encode()
    with pytest.raises(jsmap.MapError, match="2 projects"):
        jsmap.jest_own_setup(two)
    with pytest.raises(jsmap.MapError, match="no configuration"):
        jsmap.jest_own_setup(b"Error: no config")


def test_vitest_gets_a_config_that_adds_to_the_projects_own(tmp_path: Path) -> None:
    assert jsmap.vitest_setup(tmp_path) == ["--config", jsmap.WRAPPER]
    assert "setupFiles" in (tmp_path / jsmap.WRAPPER).read_text(encoding="utf-8")
    (tmp_path / "vite.config.ts").write_text("export default {};\n", encoding="utf-8")
    (tmp_path / "vitest.config.mjs").write_text("export default {};\n", encoding="utf-8")
    jsmap.vitest_setup(tmp_path)
    wrapper = (tmp_path / jsmap.WRAPPER).read_text(encoding="utf-8")
    assert 'import base from "./vitest.config.mjs";' in wrapper  # Vitest's own config first
    assert (tmp_path / jsmap.VITEST_SETUP).is_file()


# -- the selection --------------------------------------------------------------------------------


def test_a_change_selects_the_tests_that_ran_it() -> None:
    side = jsmap.TestMap(
        ran={
            "test/m.test.js::m adds": frozenset({("src/m.js", "add")}),
            "test/m.test.js::m twice": frozenset({("src/m.js", "twice"), ("src/m.js", "add")}),
            "test/o.test.js::o": frozenset({("src/o.js", "other")}),
        },
        loaded={
            "test/m.test.js": frozenset({"src/m.js"}),
            "test/o.test.js": frozenset({"src/o.js"}),
        },
    )
    twice = jsmap.JsChange("src/m.js", frozenset({"twice"}), module_level=False)
    assert jsmap.select([twice], [side]) == {"test/m.test.js::m twice": ["ran twice in src/m.js"]}
    top = jsmap.JsChange("src/o.js", frozenset(), module_level=True)
    assert set(jsmap.select([top], [side])) == {"test/o.test.js::o"}
    test_file = jsmap.JsChange("test/o.test.js", frozenset(), module_level=True)
    assert jsmap.select([test_file], [side])["test/o.test.js::o"][0].startswith("its test file")
    assert jsmap.select([twice], []) == {}


# -- for real, with Vitest ------------------------------------------------------------------------


BASE = {
    "package.json": json.dumps({"type": "module", "devDependencies": {"vitest": "5.0.4"}}),
    "package-lock.json": "{}",
    "vitest.config.mjs": "export default { test: { globals: true } };\n",
    "src/m.js": (
        "export const LABEL = 'm';\n\n"
        "export function add(a, b) {\n  return a + b;\n}\n\n"
        "export function twice(a) {\n  return add(a, a);\n}\n"
    ),
    "test/m.test.js": (
        'import { add, twice } from "../src/m.js";\n'
        'describe("m", () => {\n'
        '  test("adds", () => { expect(add(1, 2)).toBe(3); });\n'
        '  test("twice", () => { expect(twice(2)).toBe(4); });\n'
        "});\n"
    ),
}


@NEEDS_VITEST
@pytest.mark.parametrize(
    ("head", "selected"),
    [
        # twice changes: only the test that ran it is selected
        (
            {"src/m.js": BASE["src/m.js"].replace("return add(a, a);", "return add(a, a) + 0;")},
            {"test/m.test.js::m twice": ["ran twice in src/m.js"]},
        ),
        # module-level code changes: every test whose file loaded it
        (
            {"src/m.js": BASE["src/m.js"].replace("'m'", "'n'")},
            {"test/m.test.js::m adds", "test/m.test.js::m twice"},
        ),
    ],
)
def test_a_real_change_selects_the_tests_that_reach_it(
    tmp_path: Path, head: dict[str, str], selected: Any
) -> None:
    repo = Repo(tmp_path / "repo")
    base_commit = repo.commit(BASE)
    head_commit = repo.commit(head)
    found = jsts.run_change(
        Git(repo.path),
        base_commit,
        head_commit,
        tmp_path / "work",
        install=False,
        entry=str(VITEST),
    )
    assert found["base"] == {"commit": base_commit, "tests": 2, "problem": ""}
    got = found["selected"]
    assert isinstance(got, dict)
    assert (set(got) if isinstance(selected, set) else got) == selected
    missing = found["missing"]
    assert isinstance(missing, list)
    assert not [m for m in missing if "the test map" in m]
