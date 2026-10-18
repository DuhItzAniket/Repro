"""JavaScript and TypeScript targets at the level of test outcomes (K01)."""

import json
import shutil
from pathlib import Path

import pytest

from gitrepo import Repo
from repro import jsts
from repro.gitops import Git
from repro.sandbox import Limits, ProcessSandbox

ROOT = Path(__file__).resolve().parents[2]
#: The monorepo's own Vitest (pnpm install), for the real run: no network needed.
VITEST = ROOT / "apps" / "web" / "node_modules" / "vitest" / "vitest.mjs"


def project(tmp_path: Path, manifest: dict[str, object], lockfile: str | None) -> Path:
    (tmp_path / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    if lockfile:
        (tmp_path / lockfile).write_text("{}", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    ("manifest", "lockfile", "runner", "manager"),
    [
        ({"devDependencies": {"vitest": "5.0.4"}}, "package-lock.json", "vitest", "npm"),
        ({"scripts": {"test": "jest --ci"}}, "pnpm-lock.yaml", "jest", "pnpm"),
        ({"dependencies": {"jest": "30"}}, "yarn.lock", "jest", "yarn"),
    ],
)
def test_the_runner_and_manager_are_read_from_the_project(
    tmp_path: Path, manifest: dict[str, object], lockfile: str, runner: str, manager: str
) -> None:
    found = jsts.JsProject.detect(project(tmp_path, manifest, lockfile))
    assert (found.runner, found.manager) == (runner, manager)


@pytest.mark.parametrize(
    ("manifest", "lockfile", "message"),
    [
        ({"devDependencies": {"mocha": "11"}}, "package-lock.json", "neither Vitest nor Jest"),
        ({"devDependencies": {"vitest": "5"}}, None, "no lockfile"),
    ],
)
def test_a_project_repro_cannot_run_is_named(
    tmp_path: Path, manifest: dict[str, object], lockfile: str | None, message: str
) -> None:
    with pytest.raises(jsts.JsError, match=message):
        jsts.JsProject.detect(project(tmp_path, manifest, lockfile))
    with pytest.raises(jsts.JsError, match=r"no package\.json"):
        jsts.JsProject.detect(tmp_path / "missing")


def test_the_report_gives_each_tests_outcome(tmp_path: Path) -> None:
    report = {
        "testResults": [
            {
                "name": str(tmp_path / "test" / "m.test.js"),
                "assertionResults": [
                    {
                        "fullName": "m adds",
                        "title": "adds",
                        "ancestorTitles": ["m"],
                        "status": "passed",
                    },
                    {
                        "fullName": "m fails",
                        "title": "fails",
                        "ancestorTitles": ["m"],
                        "status": "failed",
                    },
                    {"title": "later", "ancestorTitles": ["m"], "status": "todo"},
                    {
                        "fullName": "m off",
                        "title": "off",
                        "ancestorTitles": ["m"],
                        "status": "pending",
                    },
                ],
            }
        ]
    }
    assert jsts.read_report(json.dumps(report).encode(), tmp_path) == {
        "test/m.test.js::m adds": "passed",
        "test/m.test.js::m fails": "failed",
        "test/m.test.js::m later": "skipped",
        "test/m.test.js::m off": "skipped",
    }
    with pytest.raises(jsts.JsError, match="not JSON"):
        jsts.read_report(b"<html>", tmp_path)


def test_outcomes_are_compared_test_by_test() -> None:
    base = {"a": "passed", "b": "failed", "c": "passed", "gone": "passed"}
    head = {"a": "failed", "b": "passed", "c": "passed", "new_bad": "failed", "new_ok": "passed"}
    found = jsts.compare(base, head)
    assert found.regressions == ("a",)
    assert found.fixed == ("b",)
    assert (found.new_failing, found.new_passing, found.removed) == (
        ("new_bad",),
        ("new_ok",),
        ("gone",),
    )
    assert found.same == 1


@pytest.mark.skipif(
    shutil.which("node") is None or not VITEST.is_file(),
    reason="needs node and the monorepo's Vitest (pnpm install)",
)
def test_a_real_change_is_run_on_both_sides(tmp_path: Path) -> None:
    repo = Repo(tmp_path / "repo")
    common = {
        "package.json": json.dumps({"type": "module", "devDependencies": {"vitest": "5.0.4"}}),
        "package-lock.json": "{}",
        "vitest.config.mjs": "export default { test: { globals: true } };\n",
        "test/m.test.js": (
            'import { add } from "../src/m.js";\n'
            'describe("m", () => {\n'
            '  test("adds", () => { expect(add(1, 2)).toBe(3); });\n'
            '  test("adds zero", () => { expect(add(0, 0)).toBe(0); });\n'
            "});\n"
        ),
    }
    base = repo.commit(common | {"src/m.js": "export function add(a, b) { return a + b; }\n"})
    head = repo.commit({"src/m.js": "export function add(a, b) { return a - b; }\n"})
    found = jsts.run_change(
        Git(repo.path), base, head, tmp_path / "work", install=False, entry=str(VITEST)
    )
    assert found["base"] == {"commit": base, "tests": 2, "problem": ""}
    assert found["head"] == {"commit": head, "tests": 2, "problem": ""}
    comparison = found["comparison"]
    assert isinstance(comparison, dict)
    assert comparison["regressions"] == ["test/m.test.js::m adds"]
    assert comparison["same"] == 1  # 0 - 0 is still 0
    assert "no JavaScript tracer yet" in str(found["missing"])


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_node_runs_webassembly_within_the_sandbox_limits(tmp_path: Path) -> None:
    # With V8's trap handler on, each WebAssembly memory reserves a 10 GB cage: four do not fit
    # the POSIX sandbox's address-space limit. That stopped Vitest on Linux (undici is Wasm).
    node = shutil.which("node")
    assert node is not None
    box = ProcessSandbox(tmp_path / "box", Limits(timeout_s=120, memory_bytes=jsts.MEMORY_BYTES))
    script = "const m = [1, 2, 3, 4].map(() => new WebAssembly.Memory({ initial: 1 }));"
    run = box.run(
        [node, "-e", script + " console.log(m.length);"],
        cwd=tmp_path,
        env={"NODE_OPTIONS": jsts.NODE_OPTIONS},
    )
    assert run.stdout.strip() == b"4", run.stderr.decode("utf-8", "replace")
