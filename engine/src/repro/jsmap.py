"""JavaScript and TypeScript: which functions each test runs, and which tests a change selects
(K06; ADR-0017, phase 2).

**The map.** Repro copies a setup file into the snapshot (``_hook/repro_map_vitest.mjs`` or
``repro_map_jest.cjs``) and adds it after the project's own setup files:
- for Vitest, a wrapper config imports the project's config and appends it;
- for Jest, it goes after the ``setupFilesAfterEnv`` that ``--showConfig`` reports.

The setup file starts V8's precise coverage through the inspector and records, for each test,
the functions it ran (by file and name), and for each test file what importing it ran. V8
reports functions in the code the runner executes (Vite and Babel rewrite modules), so a
function is known by its name in its file, not by its offsets.

**The change.** ``changed`` attributes each changed line, on each side, to the innermost named
function around it (``functions``, a conservative scanner: declarations, methods, functions
assigned to a name). A line inside no named function is a module-level change.

**The rule** is D06's: a changed function selects the tests that ran it, on base or on head. A
module-level change selects every test that ran anything in that file, and every test in a test
file that loaded it. A changed test file selects its own tests. Functions of the same name in
one file are not told apart: that selects more tests, never fewer.
"""

import json
import re
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Final, Literal

from repro.gitops import Git, GitError
from repro.gitops.changes import diff

HOOKS: Final = Path(__file__).parent / "sandbox" / "_hook"
MAP_FILE: Final = "repro-map.jsonl"
VITEST_SETUP: Final = "repro_map_vitest.mjs"
JEST_SETUP: Final = "repro_map_jest.cjs"
WRAPPER: Final = "repro.vitest.config.mts"
#: The configs Vitest reads, in the order it looks for them.
VITEST_CONFIGS: Final = tuple(
    f"{stem}.config.{ext}"
    for stem in ("vitest", "vite")
    for ext in ("ts", "mts", "cts", "js", "mjs", "cjs")
)
SOURCES: Final = frozenset({".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx"})


class MapError(Exception):
    """The map could not be made or read; the message says why."""


# -- the map --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TestMap:
    """What each test ran, and what each test file loaded, on one side."""

    #: Test ID (``<file>::<full name>``, as ``jsts.read_report`` names it) -> (file, function).
    ran: Mapping[str, frozenset[tuple[str, str]]] = field(default_factory=dict)
    #: Test file -> the files importing it ran.
    loaded: Mapping[str, frozenset[str]] = field(default_factory=dict)
    #: Why the map is incomplete (a setup file that could not take coverage), if it is.
    problem: str = ""

    def tests_in(self, file: str) -> set[str]:
        return {test for test in self.ran if test.partition("::")[0] == file}


def read_map(data: bytes) -> TestMap:
    """The setup file's JSON lines as a ``TestMap``."""
    ran: dict[str, set[tuple[str, str]]] = {}
    loaded: dict[str, set[str]] = {}
    problems: list[str] = []
    for number, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            if "error" in record:
                problems.append(str(record["error"]))
            elif "loaded" in record:
                loaded.setdefault(str(record["file"]), set()).update(map(str, record["loaded"]))
            else:
                test = f"{record['file']}::{record['test']}"
                ran.setdefault(test, set()).update((str(f), str(n)) for f, n in record["ran"])
        except (ValueError, KeyError, TypeError) as exc:
            raise MapError(f"line {number} of the map is not one of its records: {exc}") from None
    return TestMap(
        {test: frozenset(found) for test, found in ran.items()},
        {file: frozenset(found) for file, found in loaded.items()},
        "; ".join(dict.fromkeys(problems)),
    )


def vitest_setup(root: Path) -> list[str]:
    """Copies the setup file into ``root`` with a config that adds it to the project's own;
    the runner's extra arguments."""
    shutil.copyfile(HOOKS / VITEST_SETUP, root / VITEST_SETUP)
    base = next((name for name in VITEST_CONFIGS if (root / name).is_file()), None)
    if base is None:
        source = f'export default {{ test: {{ setupFiles: ["./{VITEST_SETUP}"] }} }};\n'
    else:
        source = (
            f'import base from "./{base}";\n'
            'const resolved = typeof base === "function"\n'
            '  ? await base({ command: "serve", mode: "test" })\n'
            "  : base;\n"
            "const own = resolved?.test?.setupFiles ?? [];\n"
            "export default {\n"
            "  ...resolved,\n"
            "  test: {\n"
            "    ...resolved?.test,\n"
            f'    setupFiles: [...(Array.isArray(own) ? own : [own]), "./{VITEST_SETUP}"],\n'
            "  },\n"
            "};\n"
        )
    (root / WRAPPER).write_bytes(source.encode("utf-8"))
    return ["--config", WRAPPER]


def jest_own_setup(shown: bytes) -> list[str]:
    """The project's ``setupFilesAfterEnv``, from ``jest --showConfig``. A config of several
    projects is refused: one list for all of them would change what some of them run."""
    try:
        configs = json.loads(shown)["configs"]
    except (ValueError, KeyError, TypeError):
        raise MapError("jest --showConfig gave no configuration") from None
    if len(configs) != 1:
        raise MapError(f"a Jest config of {len(configs)} projects is not mapped yet")
    return [str(path) for path in configs[0].get("setupFilesAfterEnv") or []]


def jest_setup(root: Path, own: Sequence[str]) -> list[str]:
    """Copies the setup file into ``root``; the runner's extra arguments, the project's own
    setup files first."""
    shutil.copyfile(HOOKS / JEST_SETUP, root / JEST_SETUP)
    return ["--setupFilesAfterEnv", *own, str(root / JEST_SETUP)]


# -- the change -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class JsFunction:
    name: str
    first: int  # 1-based lines, inclusive
    last: int


_KEYWORDS: Final = frozenset(
    {"if", "for", "while", "switch", "catch", "with", "return", "function", "else", "do", "try"}
)
_IDENT: Final = r"[A-Za-z_$][\w$]*"
#: Declarations, each with its name (``name``) and, for accessors, ``get`` or ``set``: V8 names
#: a getter ``get x``.
_DECLARATIONS: Final = (
    # function name(...), async function name, function* name, export (default) forms
    re.compile(rf"\bfunction\s*\*?\s*(?P<name>{_IDENT})\s*[(<]"),
    # const name = function / async (...) => / x =>
    re.compile(
        rf"\b(?:const|let|var)\s+(?P<name>{_IDENT})\s*(?::[^=]+)?=\s*(?:async\s+)?"
        rf"(?:function\b|\([^)]*\)\s*(?::[^=]+)?=>|{_IDENT}\s*=>)"
    ),
    # name: function / name: (...) => in an object
    re.compile(
        rf"^\s*(?P<name>{_IDENT})\s*:\s*(?:async\s+)?"
        rf"(?:function\b|\([^)]*\)\s*=>|{_IDENT}\s*=>)"
    ),
    # methods: name(...) {  with modifiers, in a class or an object literal
    re.compile(
        r"^\s*(?:(?:public|private|protected|static|async|override|readonly)\s+)*"
        rf"(?:(?P<accessor>get|set)\s+)?\*?\s*(?P<name>{_IDENT})\s*(?:<[^>]*>)?\s*\([^;]*\)"
        r"\s*(?::[^{]+)?\{"
    ),
)
#: V8 names a constructor after its class: a change to one is taken as module-level.
_CONSTRUCTOR: Final = "constructor"


def _blanked(source: str) -> str:
    """``source`` with comments and the insides of strings and template literals blanked, so
    that braces in them are not counted; line breaks are kept."""
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = source.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif c == "/" and nxt == "*":
            j = source.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join(ch if ch == "\n" else " " for ch in source[i:j]))
            i = j
        elif c in "'\"`":
            j = i + 1
            while j < n and source[j] != c:
                j += 2 if source[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(c + "".join(ch if ch == "\n" else " " for ch in source[i + 1 : j - 1]) + c)
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def functions(source: str) -> list[JsFunction]:
    """The named functions of a JavaScript or TypeScript source, with their lines: a scanner,
    not a parser. What it misses is a module-level change to the rule, which selects more."""
    text = _blanked(source)
    lines = text.split("\n")
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line) + 1)
    found: list[JsFunction] = []
    for number, line in enumerate(lines, 1):
        for pattern in _DECLARATIONS:
            match = pattern.search(line)
            if match is None or match.group("name") in _KEYWORDS:
                continue
            accessor = match.groupdict().get("accessor")
            name = f"{accessor} {match.group('name')}" if accessor else match.group("name")
            last = _body_end(text, starts[number - 1] + match.end("name"), starts)
            found.append(JsFunction(name, number, last or number))
            break
    return found


def _body_end(text: str, at: int, starts: Sequence[int]) -> int | None:
    """The line where a declaration starting after its name, at ``at``, ends: its body's closing
    brace, or, for an expression body, the first line end outside brackets. Braces inside the
    parameters (destructuring) are not the body. None if the text ends first."""
    braces = brackets = 0
    for i in range(at, len(text)):
        c = text[i]
        if braces == 0:
            if c in "([":
                brackets += 1
            elif c in ")]":
                brackets -= 1
            elif brackets > 0:
                continue
            elif c == "{":
                braces = 1
            elif c in ";\n":
                return _line_of(i, starts)
        elif c == "{":
            braces += 1
        elif c == "}":
            braces -= 1
            if braces == 0:
                return _line_of(i, starts)
    return None


def _line_of(offset: int, starts: Sequence[int]) -> int:
    low, high = 0, len(starts) - 1
    while low < high:
        middle = (low + high + 1) // 2
        if starts[middle] <= offset:
            low = middle
        else:
            high = middle - 1
    return low + 1


@dataclass(frozen=True)
class JsChange:
    """What a change does to one JavaScript or TypeScript file."""

    file: str
    functions: frozenset[str]
    module_level: bool


def attribute(source: str, lines: Iterable[int]) -> tuple[set[str], bool]:
    """The innermost named function around each line, and whether a line is in none."""
    named = functions(source)
    found: set[str] = set()
    module = False
    for line in lines:
        around = [f for f in named if f.first <= line <= f.last]
        innermost = min(around, key=lambda f: f.last - f.first).name if around else None
        if innermost is None or innermost == _CONSTRUCTOR:
            module = True
        else:
            found.add(innermost)
    return found, module


def changed(git: Git, base: str, head: str) -> list[JsChange]:
    """Each JavaScript or TypeScript file the change touches, its changed functions on either
    side, and whether it changes code outside them."""
    result = []
    for change in diff(git, base, head):
        if PurePosixPath(change.path).suffix not in SOURCES:
            continue
        names: set[str] = set()
        module = change.old_path is None or change.new_path is None  # added or deleted
        sides: tuple[tuple[Literal["old", "new"], str, str | None], ...] = (
            ("old", base, change.old_path),
            ("new", head, change.new_path),
        )
        for side, commit, path in sides:
            lines = [n for span in change.changed_lines(side) for n in span]
            if path is None or not lines:
                continue
            found, outside = attribute(_read(git, commit, path), lines)
            names |= found
            module = module or outside
        result.append(JsChange(change.path, frozenset(names), module))
    return result


def _read(git: Git, commit: str, path: str) -> str:
    try:
        return git.run("show", f"{commit}:{path}").decode("utf-8", "replace")
    except GitError:
        return ""


# -- the selection --------------------------------------------------------------------------------


def select(changes: Sequence[JsChange], maps: Sequence[TestMap]) -> dict[str, list[str]]:
    """Each selected test and why, from the maps of both sides (``changes`` per ``changed``)."""
    reasons: dict[str, list[str]] = {}

    def add(test: str, why: str) -> None:
        if why not in reasons.setdefault(test, []):
            reasons[test].append(why)

    for change in changes:
        for side in maps:
            for test in side.tests_in(change.file):
                add(test, f"its test file changed ({change.file})")
            for test, ran in side.ran.items():
                for file, name in ran:
                    if file != change.file:
                        continue
                    if name in change.functions:
                        add(test, f"ran {name} in {file}")
                    elif change.module_level:
                        add(test, f"ran code of {file}, changed outside a function")
            if change.module_level:
                for test_file, loaded in side.loaded.items():
                    if change.file in loaded:
                        for test in side.tests_in(test_file):
                            add(test, f"its file loaded {change.file}, changed outside a function")
    return {test: reasons[test] for test in sorted(reasons)}
