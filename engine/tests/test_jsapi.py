"""A JavaScript or TypeScript package's public API, base against head, with the pinned TypeScript
compiler (K11; ADR-0017, phase 4). The counterpart of ``test_api_diff.py``: real sources in
``gitrepo`` repositories, read by the real compiler."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from gitrepo import Entry as File
from gitrepo import Repo
from repro.analysis import jsapi
from repro.analysis.jsapi import Entry, JsApiDiff
from repro.gitops import Git
from repro_events import models
from ts_support import NEEDS_NODE, pinned

RUN_ID = "run_01JABCDEFGHJKMNPQRSTVWXYZ0"

#: Running any of the target's code is what the API diff must never do.
TRAP = (
    'import { writeFileSync } from "node:fs";\n'
    'writeFileSync(new URL("./RAN", import.meta.url), "ran");\n'
    "export const trap = 1;\n"
)

BASE = {
    "package.json": json.dumps(
        {
            "name": "shapes",
            "type": "module",
            "scripts": {"postinstall": "node src/trap.js"},
            "exports": {
                ".": {"types": "./dist/index.d.ts", "import": "./dist/index.js"},
                "./extra": "./dist/extra.js",
                "./package.json": "./package.json",
            },
        }
    ),
    "tsconfig.json": (
        "{\n  // built to dist, as tsc emits it\n"
        '  "compilerOptions": { "outDir": "dist", "rootDir": "src", "declaration": true, },\n'
        '  "include": ["src"]\n}\n'
    ),
    "src/index.ts": (
        'export { area, scale, describe, gone, label, kind } from "./geometry.js";\n'
        'export { Box } from "./box.js";\n'
        'export type { Shape } from "./shape.js";\n'
        'export { trap } from "./trap.js";\n'
        "export const LIMIT: number = 3;\n"
        'export const VERSION = "1.0";\n'
        'export enum Unit { Cm = "cm", In = "in" }\n'
    ),
    "src/geometry.ts": (
        'import type { Shape } from "./shape.js";\n'
        "export function area(shape: Shape, factor: number): number { return 0; }\n"
        "export function scale(shape: Shape, by?: number): Shape { return shape; }\n"
        'export function describe(shape: Shape): string { return ""; }\n'
        "export function gone(): void {}\n"
        "export function label(name: string): string { return name; }\n"
        'export const kind = "geometry";\n'
    ),
    "src/shape.ts": "export interface Shape { width: number; height: number; name?: string }\n",
    "src/box.ts": (
        "export class Box {\n"
        "  constructor(public size: number) {}\n"
        "  volume(): number { return this.size ** 3; }\n"
        "  lid(): void {}\n"
        "  private secret(): void {}\n"
        "}\n"
    ),
    "src/extra.ts": "export function helper(a: string): string { return a; }\n",
    "src/trap.js": TRAP,
}
HEAD = {
    **BASE,
    "package.json": json.dumps(
        {
            "name": "shapes",
            "type": "module",
            "exports": {".": {"types": "./dist/index.d.ts", "import": "./dist/index.js"}},
        }
    ),
    "src/index.ts": BASE["src/index.ts"]
    .replace(" gone,", "")
    .replace("LIMIT: number = 3", 'LIMIT: string = "3"')
    .replace('"1.0"', '"2.0"')
    .replace('Cm = "cm"', 'Cm = "centimetre"'),
    "src/geometry.ts": (
        'import type { Shape } from "./shape.js";\n'
        "export function area(shape: Shape): number { return 0; }\n"
        "export function scale(shape: Shape, by: number): Shape { return shape; }\n"
        'export function describe(shape: Shape, verbose: boolean): string { return ""; }\n'
        "export function gone(): void {}\n"
        "export function label(name: number): string { return String(name); }\n"
        'export function kind(): string { return "geometry"; }\n'
    ),
    "src/shape.ts": "export interface Shape { width: string; height: number }\n",
    "src/box.ts": (
        "export class Box {\n"
        "  constructor(public size: number) {}\n"
        "  volume(): string { return String(this.size ** 3); }\n"
        "}\n"
    ),
}


@pytest.fixture(scope="module")
def package(pytestconfig: pytest.Config, tmp_path_factory: pytest.TempPathFactory) -> Path:
    return pinned(pytestconfig, tmp_path_factory)


def diff_of(
    package: Path, tmp_path: Path, base: Mapping[str, File], head: Mapping[str, File]
) -> JsApiDiff:
    repo = Repo(tmp_path / "repo")
    old = repo.commit(dict(base), "base")
    new = repo.commit(dict(head), "head", fresh=True)  # exactly head's files
    return jsapi.api_diff(Git(repo.path), old, new, tmp_path / "jsapi", package)


@NEEDS_NODE
def test_breaking_changes_of_a_typescript_package(package: Path, tmp_path: Path) -> None:
    found = diff_of(package, tmp_path, BASE, HEAD)
    assert not list(tmp_path.rglob("RAN"))  # read, never run
    assert found.packages == ("shapes", "shapes/extra")
    assert found.problems == []
    assert [(b.symbol, b.breakage, b.old, b.new) for b in found.breaks] == [
        ("src/box.ts:Box.lid#0", "object_removed", "method", None),
        ("src/box.ts:Box.volume#0", "return_changed_type", "number", "string"),
        ("src/extra.ts:<module>#0", "object_removed", "module", None),
        ("src/geometry.ts:area#0", "parameter_removed", "factor: number", None),
        ("src/geometry.ts:describe#0", "parameter_added_required", None, "verbose: boolean"),
        ("src/geometry.ts:gone#0", "object_removed", "function", None),
        ("src/geometry.ts:kind#0", "object_changed_kind", "variable", "function"),
        ("src/geometry.ts:label#0", "parameter_changed_type", "name: string", "name: number"),
        ("src/geometry.ts:scale#0", "parameter_changed_required", "by?: number", "by: number"),
        ("src/index.ts:LIMIT#0", "attribute_changed_type", "number", "string"),
        ("src/index.ts:Unit.Cm#0", "attribute_changed_value", '"cm"', '"centimetre"'),
        ("src/shape.ts:Shape.name#0", "object_removed", "property", None),
        ("src/shape.ts:Shape.width#0", "attribute_changed_type", "number", "string"),
    ]
    assert {b.source for b in found.breaks} == {"typescript"}
    (removed,) = [b for b in found.breaks if b.breakage == "parameter_removed"]
    assert removed.explanation == "area in shapes: Parameter was removed (factor: number)"
    assert removed.file == "src/geometry.ts"
    assert all(str(tmp_path) not in b.explanation for b in found.breaks)
    assert found.unreported == []
    assert found.missing() == []


@NEEDS_NODE
def test_evidence_and_payload_match_the_schema(package: Path, tmp_path: Path) -> None:
    found = diff_of(package, tmp_path, BASE, HEAD)
    assert found.breaks
    for item in found.breaks:
        record = item.evidence(RUN_ID)
        record["seq"] = 1
        models.Evidence.model_validate(record)
        assert record["produced_by"]["component"] == "repro.analysis.jsapi"
        models.DiffApiPayload.model_validate(item.payload(record["id"]))
    for missing in found.missing():
        models.MissingRecordedPayload.model_validate(missing)


@NEEDS_NODE
def test_no_change_no_break(package: Path, tmp_path: Path) -> None:
    found = diff_of(package, tmp_path, BASE, BASE)
    assert (found.breaks, found.problems, found.unreported) == ([], [], [])


@NEEDS_NODE
def test_a_commonjs_package_and_one_typed_by_a_declaration_file(
    package: Path, tmp_path: Path
) -> None:
    base = {
        "package.json": json.dumps({"name": "plain", "main": "index.js"}),
        "index.js": (
            "function add(a, b) { return a + b; }\n"
            "function sub(a, b) { return a - b; }\n"
            "module.exports = { add, sub };\n"
        ),
    }
    head = {**base, "index.js": "function add(a) { return a; }\nmodule.exports = { add };\n"}
    found = diff_of(package, tmp_path / "cjs", base, head)
    assert [(b.symbol, b.breakage, b.old) for b in found.breaks] == [
        ("index.js:add#0", "parameter_removed", "b: any"),
        ("index.js:sub#0", "object_removed", "function"),
    ]
    typed = {
        "package.json": json.dumps({"name": "typed", "main": "lib/index.js"}),
        "lib/index.js": "exports.f = (a) => a.length;\n",
        "lib/index.d.ts": "export declare function f(a: string): number;\n",
    }
    retyped = {**typed, "lib/index.d.ts": "export declare function f(a: string): string;\n"}
    found = diff_of(package, tmp_path / "dts", typed, retyped)
    assert [(b.symbol, b.breakage, b.file) for b in found.breaks] == [
        ("lib/index.d.ts:f#0", "return_changed_type", "lib/index.d.ts")
    ]


@NEEDS_NODE
def test_a_callable_type_is_compared_by_its_calls_and_members(
    package: Path, tmp_path: Path
) -> None:
    # A member added breaks no caller (p-limit's LimitFunction gained map in 7.0.0); a
    # parameter added to its call does.
    base = {
        "package.json": json.dumps({"name": "limit", "types": "index.d.ts"}),
        "index.d.ts": "export type Limit = { (task: () => void): void; readonly size: number };\n",
    }
    head = {
        **base,
        "index.d.ts": (
            "export type Limit = {\n  (task: () => void, priority: number): void;\n"
            "  readonly size: number;\n  map(items: string[]): void;\n};\n"
        ),
    }
    found = diff_of(package, tmp_path, base, head)
    assert [(b.symbol, b.breakage, b.new) for b in found.breaks] == [
        ("index.d.ts:Limit#0", "parameter_added_required", "priority: number")
    ]


@NEEDS_NODE
def test_an_entry_that_cannot_be_resolved_to_source_is_named(package: Path, tmp_path: Path) -> None:
    # Built by a bundler to dist (not committed), and no tsconfig.json maps dist to src.
    bundled = {
        "package.json": json.dumps(
            {
                "name": "bundled",
                "exports": {".": {"types": "./dist/index.d.mts", "import": "./dist/index.mjs"}},
            }
        ),
        "src/index.ts": "export function f(a: string): string { return a; }\n",
    }
    found = diff_of(package, tmp_path, bundled, bundled)
    assert found.breaks == []
    assert found.problems == [
        (
            "base and head",
            "bundled",
            "none of dist/index.d.mts, dist/index.mjs is in the tree, and there is no "
            "tsconfig.json to map them to a source",
        )
    ]
    (item,) = found.missing()
    models.MissingRecordedPayload.model_validate(item)
    assert item["missing"]["reason"] == "unsupported_project"
    assert item["missing"]["detail"].startswith("API of bundled (base and head) not read: none")


@NEEDS_NODE
def test_a_package_without_an_entry_or_a_manifest_is_named(package: Path, tmp_path: Path) -> None:
    app = {"package.json": json.dumps({"name": "app", "private": True}), "src/a.js": "1;\n"}
    found = diff_of(package, tmp_path / "app", app, app)
    assert found.problems == [
        (
            "base and head",
            "app",
            "package.json names no entry point (exports, main, module or types), and none of "
            "index.js, index.d.ts is in the tree, and there is no tsconfig.json to map them to a "
            "source",
        )
    ]
    found = diff_of(package, tmp_path / "none", {"src/a.js": "1;\n"}, {"src/a.js": "2;\n"})
    assert found.problems == [("base and head", "the package", "no package.json")]


@pytest.mark.parametrize(
    ("manifest", "expected"),
    [
        ({"exports": "./dist/index.js"}, [Entry(".", ("dist/index.js", "dist/index.d.ts"))]),
        (
            {
                "exports": {
                    "import": {"types": "./a.d.mts", "default": "./a.mjs"},
                    "require": "./a.cjs",
                }
            },
            [Entry(".", ("a.d.mts", "a.mjs", "a.cjs", "a.d.cts"))],
        ),
        ({"exports": ["./a.js", "./b.js"]}, [Entry(".", ("a.js", "b.js", "a.d.ts", "b.d.ts"))]),
        (
            {
                "main": "./dist/index.cjs",
                "module": "./dist/index.mjs",
                "types": "./dist/index.d.ts",
            },
            [
                Entry(
                    ".",
                    (
                        "dist/index.d.ts",
                        "dist/index.mjs",
                        "dist/index.cjs",
                        "dist/index.d.mts",
                        "dist/index.d.cts",
                    ),
                )
            ],
        ),
        ({"main": "lib"}, [Entry(".", ("lib.js", "lib/index.js", "lib.d.ts", "lib/index.d.ts"))]),
        ({}, [Entry(".", ("index.js", "index.d.ts"))]),
    ],
)
def test_entries_are_read_as_node_and_typescript_read_them(
    manifest: dict[str, object], expected: list[Entry]
) -> None:
    assert jsapi.entries(manifest) == (expected, [])


def test_subpaths_patterns_and_what_is_not_a_module() -> None:
    manifest = {
        "exports": {
            ".": "./index.js",
            "./utils": {"types": "./utils.d.ts", "default": "./utils.js"},
            "./package.json": "./package.json",
            "./styles.css": "./styles.css",
            "./blocked": None,
            "./*": "./dist/*.js",
        }
    }
    assert jsapi.entries(manifest) == (
        [Entry(".", ("index.js", "index.d.ts")), Entry("./utils", ("utils.d.ts", "utils.js"))],
        [("./*", "the subpath pattern ./* is not expanded")],
    )
    mixed = {"exports": {".": "./a.js", "import": "./b.js"}}
    assert jsapi.entries(mixed) == (
        [],
        [(".", "package.json's exports mixes subpaths and conditions")],
    )
    assert jsapi.label("shapes", "./utils") == "shapes/utils"
    assert jsapi.label(None, ".") == "the package"
