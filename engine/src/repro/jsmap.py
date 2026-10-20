"""JavaScript and TypeScript: which functions each test runs, and which tests a change selects
(K06; ADR-0017, phase 2).

**The map.** Repro copies a setup file into the snapshot (``_hook/repro_map_vitest.mjs`` or
``repro_map_jest.cjs``), on the host or into a container's volume (``vitest_files``,
``jest_files``; K11), and adds it after the project's own setup files:
- for Vitest, a wrapper config imports the project's config and appends it;
- for Jest, it goes after the ``setupFilesAfterEnv`` that ``--showConfig`` reports.

The setup file starts V8's precise coverage through the inspector and records, for each test,
the functions it ran (by file and name), and for each test file what importing it ran. V8
reports functions in the code the runner executes (Vite and Babel rewrite modules), so a
function is known by its name in its file, not by its offsets.

**The change.** ``changed`` attributes each changed line, on each side, to the innermost named
function around it (``functions``, a conservative scanner: declarations, methods, functions
assigned to a name). A line inside no named function is a module-level change.

**A test's own code** (K08) runs from where the runner says the test starts (Vitest's
``--includeTaskLocation``, Jest's ``--testLocationInResults``) to the end of that call
(``own_lines``). A test file's changed lines in no named function are its tests' own code, or
else the file's (its hooks, its imports).

**The rule** is D06's (``select``): a changed function selects the tests that ran it, on base or
on head. A module-level change selects every test that ran anything in that file, and every test
in a test file that loaded it; in a test file, every test in it. A test whose own code changed
selects itself, as new if base does not have it. Functions of the same name in one file are not
told apart: that selects more tests, never fewer.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Final, Literal
from urllib.parse import quote

from repro.gitops import Git, read_blobs
from repro.gitops.changes import FileChange, diff

HOOKS: Final = Path(__file__).parent / "sandbox" / "_hook"
MAP_FILE: Final = "repro-map.jsonl"
VITEST_SETUP: Final = "repro_map_vitest.mjs"
JEST_SETUP: Final = "repro_map_jest.cjs"
WRAPPER: Final = "repro.vitest.config.mts"
#: The tracer runtime and Vitest's plugin (K07), copied beside the setup file when tracing.
TRACE_RUNTIME: Final = "repro_trace_js.cjs"
TRACE_PLUGIN: Final = "repro_trace_vite.mjs"
#: The configs Vitest reads, in the order it looks for them.
VITEST_CONFIGS: Final = tuple(
    f"{stem}.config.{ext}"
    for stem in ("vitest", "vite")
    for ext in ("ts", "mts", "cts", "js", "mjs", "cjs")
)
SOURCES: Final = frozenset({".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx"})
#: A module's own code, as Python's symbols name it (``analysis.symbols.MODULE_QUALNAME``).
MODULE: Final = "<module>"
#: What a module name keeps of a path as it is: ``SymbolId`` allows no whitespace or colon.
_SAFE: Final = "/!$&'()*+,;=@~[]"


def module_name(file: str) -> str:
    """A JavaScript or TypeScript file's module name, in symbol IDs and the graph (K08): its
    path, with whitespace, colons and ``%`` percent-encoded."""
    return quote(file, safe=_SAFE)


def symbol_id(file: str, name: str = MODULE) -> str:
    """A function's ``SymbolId``, ``<module>:<name>#0``; its module's own code by default. A
    function is known by its name in its file, and V8's ``get x`` is ``get-x``: an ID has no
    spaces."""
    return f"{module_name(file)}:{name.replace(' ', '-')}#0"


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


def vitest_files(root: Path, *, trace: bool = False) -> dict[str, bytes]:
    """The setup file and a config that adds it to the project's own (found in ``root``), by
    name in the project's root. With ``trace`` (K07), the tracer runtime and Vitest's plugin
    too, and the plugin comes after the project's own."""
    names = [VITEST_SETUP, *((TRACE_RUNTIME, TRACE_PLUGIN) if trace else ())]
    files = {name: (HOOKS / name).read_bytes() for name in names}
    base = next((name for name in VITEST_CONFIGS if (root / name).is_file()), None)
    lines = [f'import base from "./{base}";'] if base else ["const base = {};"]
    if trace:
        lines.append(f'import reproTrace from "./{TRACE_PLUGIN}";')
    lines += [
        'const resolved = typeof base === "function"',
        '  ? await base({ command: "serve", mode: "test" })',
        "  : base;",
        "const own = resolved?.test?.setupFiles ?? [];",
        "export default {",
        "  ...resolved,",
    ]
    if trace:
        lines.append("  plugins: [...(resolved?.plugins ?? []), reproTrace()],")
    lines += [
        "  test: {",
        "    ...resolved?.test,",
        f'    setupFiles: [...(Array.isArray(own) ? own : [own]), "./{VITEST_SETUP}"],',
        "  },",
        "};",
    ]
    files[WRAPPER] = ("\n".join(lines) + "\n").encode("utf-8")
    return files


def vitest_setup(root: Path, *, trace: bool = False) -> list[str]:
    """Writes ``vitest_files`` into ``root``; the runner's extra arguments."""
    for name, data in vitest_files(root, trace=trace).items():
        (root / name).write_bytes(data)
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


def jest_files(*, trace: bool = False) -> dict[str, bytes]:
    """The setup file (and the tracer runtime, with ``trace``), by name in the project's
    root."""
    names = [JEST_SETUP, *((TRACE_RUNTIME,) if trace else ())]
    return {name: (HOOKS / name).read_bytes() for name in names}


def jest_args(own: Sequence[str], setup: str) -> list[str]:
    """The runner's extra arguments: the project's own setup files first, then ``setup``, the
    setup file's path as the runner sees it."""
    return ["--setupFilesAfterEnv", *own, setup]


def jest_setup(root: Path, own: Sequence[str], *, trace: bool = False) -> list[str]:
    """Writes ``jest_files`` into ``root``; the runner's extra arguments."""
    for name, data in jest_files(trace=trace).items():
        (root / name).write_bytes(data)
    return jest_args(own, str(root / JEST_SETUP))


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


def blanked(source: str) -> str:
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
    text = blanked(source)
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


Span = tuple[int, int]


@dataclass(frozen=True)
class JsChange:
    """What a change does to one JavaScript or TypeScript file."""

    file: str
    functions: frozenset[str]
    module_level: bool
    #: The file on each side; None where it is not (added or deleted).
    old_path: str | None = None
    new_path: str | None = None
    #: Each side's changed lines in no named function (K08): in a test file, its tests' own code
    #: is among them.
    old_loose: frozenset[int] = frozenset()
    new_loose: frozenset[int] = frozenset()
    #: Each changed function's lines on each side that has it (K08: ``symbol.changed``).
    old_spans: Mapping[str, Span] = field(default_factory=dict)
    new_spans: Mapping[str, Span] = field(default_factory=dict)
    #: Each side's line count; None where the file is not.
    old_size: int | None = None
    new_size: int | None = None


def _innermost(named: Sequence[JsFunction], line: int) -> JsFunction | None:
    around = [f for f in named if f.first <= line <= f.last]
    found = min(around, key=lambda f: f.last - f.first) if around else None
    return None if found is None or found.name == _CONSTRUCTOR else found


def attribute(source: str, lines: Iterable[int]) -> tuple[set[str], bool]:
    """The innermost named function around each line, and whether a line is in none."""
    named = functions(source)
    found: set[str] = set()
    module = False
    for line in lines:
        innermost = _innermost(named, line)
        if innermost is None:
            module = True
        else:
            found.add(innermost.name)
    return found, module


def _side(named: Sequence[JsFunction], lines: Iterable[int]) -> tuple[set[str], frozenset[int]]:
    """One side of a file's change: the changed functions, and the changed lines in none."""
    names: set[str] = set()
    loose = set()
    for line in lines:
        innermost = _innermost(named, line)
        if innermost is None:
            loose.add(line)
        else:
            names.add(innermost.name)
    return names, frozenset(loose)


def file_change(change: FileChange, old: str | None, new: str | None) -> JsChange:
    """What ``change`` does, from the file's source on each side (None where it is not). Each
    changed function's span is its first of that name on each side that has one."""
    old_named = functions(old) if old is not None else []
    new_named = functions(new) if new is not None else []
    old_names, old_loose = _side(old_named, (n for s in change.changed_lines("old") for n in s))
    new_names, new_loose = _side(new_named, (n for s in change.changed_lines("new") for n in s))
    names = old_names | new_names

    def spans(named: Sequence[JsFunction]) -> dict[str, Span]:
        found: dict[str, Span] = {}
        for function in named:
            if function.name in names:
                found.setdefault(function.name, (function.first, function.last))
        return found

    added_or_deleted = change.old_path is None or change.new_path is None
    return JsChange(
        change.path,
        frozenset(names),
        added_or_deleted or bool(old_loose or new_loose),
        change.old_path,
        change.new_path,
        old_loose,
        new_loose,
        spans(old_named),
        spans(new_named),
        None if old is None else old.count("\n") + 1,
        None if new is None else new.count("\n") + 1,
    )


def changed(git: Git, base: str, head: str) -> list[JsChange]:
    """Each JavaScript or TypeScript file the change touches, its changed functions on either
    side, and whether it changes code outside them. Both sides' sources are read through one
    ``git cat-file --batch``."""
    found = [c for c in diff(git, base, head) if PurePosixPath(c.path).suffix in SOURCES]
    wanted = [b for c in found for b in (c.old_blob, c.new_blob) if b is not None]
    blobs = read_blobs(git, wanted) if wanted else {}

    def text(path: str | None, blob: str | None) -> str | None:
        if path is None:
            return None
        return blobs.get(blob, b"").decode("utf-8", "replace") if blob else ""

    return [
        file_change(c, text(c.old_path, c.old_blob), text(c.new_path, c.new_blob)) for c in found
    ]


# -- a test's own code ----------------------------------------------------------------------------


def _call_end(text: str, at: int) -> int | None:
    """The offset of the ``)`` that closes the first call from ``at``, or of the last call
    chained straight after it (``test.each(rows)(name, fn)``); None if the text ends first."""
    i = text.find("(", at)
    if i < 0:
        return None
    depth, end = 0, None
    while i < len(text):
        c = text[i]
        i += 1
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                end = i - 1
                while i < len(text) and text[i].isspace():
                    i += 1
                if i == len(text) or text[i] != "(":
                    return end
    return end


def own_lines(source: str, starts: Mapping[str, tuple[int, int]]) -> dict[str, Span]:
    """Each test's own lines in ``source``, from where the runner says it starts (line, column,
    1-based) to the end of the call it is, and never into the next test's start."""
    text = blanked(source)
    offsets = [0]
    for row in text.split("\n"):
        offsets.append(offsets[-1] + len(row) + 1)
    count = len(offsets) - 1
    firsts = sorted({line for line, _ in starts.values()})
    found: dict[str, Span] = {}
    for test, (line, column) in starts.items():
        if not 1 <= line <= count:
            continue
        end = _call_end(text, offsets[line - 1] + max(column - 1, 0))
        last = _line_of(end, offsets) if end is not None else line
        later = [first for first in firsts if first > line]
        if later:
            last = min(last, later[0] - 1)
        found[test] = (line, max(last, line))
    return found


# -- the selection --------------------------------------------------------------------------------


Reason = Literal["blast_radius", "module_import", "new_test", "modified_test"]


@dataclass
class Selected:
    """Why a test is selected: the schema's reasons, the changed symbols that select it, and the
    same in words."""

    reasons: list[Reason] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    why: list[str] = field(default_factory=list)

    def add(self, reason: Reason, symbol: str | None, why: str) -> None:
        if reason not in self.reasons:
            self.reasons.append(reason)
        if symbol is not None and symbol not in self.symbols:
            self.symbols.append(symbol)
        if why not in self.why:
            self.why.append(why)


def own_changes(
    change: JsChange, base: Mapping[str, Span], head: Mapping[str, Span]
) -> tuple[set[str], JsChange]:
    """The tests whose own code ``change`` edits, by their lines on each side (``own_lines``),
    and the change without those lines: module-level only for a line in no test, or a file
    added or deleted."""

    def inside(line: int, blocks: Mapping[str, Span]) -> bool:
        return any(first <= line <= last for first, last in blocks.values())

    edited = {t for t, (a, b) in base.items() if any(a <= n <= b for n in change.old_loose)}
    edited |= {t for t, (a, b) in head.items() if any(a <= n <= b for n in change.new_loose)}
    old = frozenset(n for n in change.old_loose if not inside(n, base))
    new = frozenset(n for n in change.new_loose if not inside(n, head))
    whole = change.old_path is None or change.new_path is None
    return edited, replace(change, module_level=whole or bool(old or new), old_loose=old,
                           new_loose=new)  # fmt: skip


def select(
    changes: Sequence[JsChange],
    maps: Sequence[TestMap],
    own: Mapping[str, Reason] | None = None,
) -> dict[str, Selected]:
    """Each selected test and why, from the maps of both sides (``changes`` per ``changed``, a
    test file's after ``own_changes``); ``own``: the tests whose own code changed, each
    ``modified_test`` or ``new_test``."""
    found: dict[str, Selected] = {}
    for test, reason in (own or {}).items():
        why = "its own code changed" + (", new" if reason == "new_test" else "")
        found.setdefault(test, Selected()).add(reason, None, why)
    for change in changes:
        for side in maps:
            for test, reason, symbol, why in _reached(change, side):
                found.setdefault(test, Selected()).add(reason, symbol, why)
    return {test: found[test] for test in sorted(found)}


def _reached(change: JsChange, side: TestMap) -> Iterable[tuple[str, Reason, str, str]]:
    """The tests one side's map says ``change`` reaches: (test, reason, symbol, why)."""
    module = symbol_id(change.file)
    if change.module_level:
        for test in side.tests_in(change.file):
            yield test, "module_import", module, f"its test file changed ({change.file})"
    for test, ran in side.ran.items():
        for file, name in ran:
            if file != change.file:
                continue
            if name in change.functions:
                yield test, "blast_radius", symbol_id(file, name), f"ran {name} in {file}"
            elif change.module_level:
                yield (
                    test,
                    "module_import",
                    module,
                    f"ran code of {file}, changed outside a function",
                )
    if change.module_level:
        why = f"its file loaded {change.file}, changed outside a function"
        for test_file, loaded in side.loaded.items():
            if change.file in loaded:
                for test in side.tests_in(test_file):
                    yield test, "module_import", module, why
