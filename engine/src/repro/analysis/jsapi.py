"""The public API of a JavaScript or TypeScript package, base against head (K11; ADR-0017,
phase 4): Python's E05 (``repro.analysis.api``), with the TypeScript compiler API in griffe's
place, and the same ``api_diff`` evidence and ``diff.api`` events.

**What the API is.** What ``package.json`` exports (``entries``): each subpath of ``exports``
(a string, an array, or conditions, nested), else ``types``, ``typings``, ``module`` and
``main`` as one entry, else Node's default ``index.js``. A subpath pattern (``./*``) is not
expanded, and a missing item says so.

**Which file holds an entry.** An entry names built files (``dist/index.js``). The worker maps
one back to the source the project's ``tsconfig.json`` (or ``tsconfig.build.json``) compiles to
it, as ``tsc`` would emit it (``ts.getOutputFileNames``, declarations as if emitted). Else it
takes a declaration file the entry names that is in the tree, else a source it names that is.
An entry none of whose files is found is not read, and a missing item names it: a package built
by a bundler that tsconfig does not describe (tsup, unbuild) is one.

**How it is read.** Each side's JavaScript, TypeScript and JSON files are written from git to a
scratch tree, ``node_modules`` left out. The pinned compiler (``repro.analysis.typescript``)
builds a program from the entries' files and lists each entry's exports: ES exports, and
CommonJS ``exports.x`` and ``module.exports``. A type from a dependency is not resolved (no
``node_modules``): it reads the same on both sides.

**What is compared**, for each export of each entry on base:
- an export gone: ``object_removed``; a different kind of declaration: ``object_changed_kind``;
- a function, a method or a constructor: each parameter by position (``parameter_removed``,
  ``parameter_added_required``, ``parameter_changed_required``, and ``parameter_changed_kind``
  for a rest parameter), and the return type (``return_changed_type``);
- a class (its public members, static or not), an interface, an object type alias or a
  namespace: each member gone, of another kind, or of another type (``attribute_changed_type``);
- an enum: each member gone, or of another value (``attribute_changed_value``); any other type
  alias: its text (``attribute_changed_value``); a constant: its type, a literal widened
  (``attribute_changed_type``).

Types are compared as the checker writes them (``typeToString``): a change of the declared
type, not a proof of incompatibility, as Python's annotations are. A parameter's type is
``parameter_changed_type`` (K11 added the kind; griffe does not compare Python's). Overloads
gone are compared too, but the schema has no breakage kind for them: they are a missing item,
not a ``diff.api``.
"""

import json
import posixpath
import re
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final

from repro import jsmap
from repro.analysis import typescript
from repro.analysis.api import EXPLANATION, ApiBreak, ApiDiff
from repro.gitops import Git, path_problem, read_blobs, regular_files
from repro.gitops.snapshot import case_insensitive

#: What each breakage is called in an explanation.
LABELS: Final[Mapping[str, str]] = {
    "parameter_removed": "Parameter was removed",
    "parameter_added_required": "Parameter was added as required",
    "parameter_changed_required": "Parameter is now required",
    "parameter_changed_kind": "Parameter kind was changed",
    "parameter_changed_type": "Parameter type changed",
    "return_changed_type": "Return type changed",
    "object_removed": "Public object was removed",
    "object_changed_kind": "Public object points to a different kind of object",
    "attribute_changed_type": "Type changed",
    "attribute_changed_value": "Value changed",
}
#: The ``package.json`` fields that name the package's one entry without ``exports``, in the
#: order they are tried: declarations first.
FIELDS: Final = ("types", "typings", "module", "main")
#: A source file's declaration file, as TypeScript looks for one beside it.
_DECLARATION_FOR: Final[Mapping[str, str]] = {".js": ".d.ts", ".mjs": ".d.mts", ".cjs": ".d.cts"}
#: Shown in place of an over-long type.
_VALUE: Final = 200
#: At most this many differences without a breakage kind are listed in their missing item.
_LISTED: Final = 10
_UNSAFE: Final = re.compile(r"[\s#]")


@dataclass(frozen=True, slots=True)
class Entry:
    """An entry point: its subpath (``.``, ``./utils``) and the repository paths that may hold
    it, in the order they are tried."""

    subpath: str
    paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Parameter:
    name: str
    type: str
    optional: bool
    rest: bool

    def text(self) -> str:
        mark = "?" if self.optional and not self.rest else ""
        return _short(f"{'...' if self.rest else ''}{self.name}{mark}: {self.type}")


@dataclass(frozen=True, slots=True)
class Signature:
    params: tuple[Parameter, ...]
    returns: str | None
    text: str


@dataclass(frozen=True)
class Shape:
    """What is compared of a declaration or a member."""

    kind: str
    signatures: tuple[Signature, ...] = ()
    type: str | None = None
    value: str | None = None
    members: Mapping[str, "Shape"] | None = None


@dataclass(frozen=True)
class Export:
    """An export of an entry, and the declaration it names."""

    subpath: str
    name: str
    file: str  # the declaration's repository path (the entry's for one not resolved)
    local: str  # the declaration's own name
    shape: Shape


@dataclass
class JsApiDiff(ApiDiff):
    """``ApiDiff``'s breaks and entries not read (``packages`` are the entries' labels), and
    the differences found that the schema has no breakage kind for, in words."""

    unreported: list[str] = field(default_factory=list)

    def missing(self) -> list[dict[str, Any]]:
        items = super().missing()
        if self.unreported:
            listed = "; ".join(self.unreported[:_LISTED])
            more = len(self.unreported) - _LISTED
            detail = (
                f"{len(self.unreported)} API differences have no breakage kind in the schema "
                f"and are not reported as breaks: {listed}"
                + (f" (and {more} more)" if more > 0 else "")
            )
            items.append(
                {
                    "missing": {
                        "reason": "unsupported_project",
                        "targets": [],
                        "detail": detail[:1000],
                        "resolution": None,
                    }
                }
            )
        return items


# -- entry points ---------------------------------------------------------------------------------


def label(name: object, subpath: str) -> str:
    """An entry's name: the package's name and its subpath (``mylib/utils``)."""
    if isinstance(name, str) and name:
        return name + subpath[1:]
    return "the package" if subpath == "." else subpath


def _path(target: str) -> str | None:
    """A target's repository path, or None for one outside the package or not a module."""
    if not target.startswith("./"):
        return None
    found = posixpath.normpath(target[2:])
    if found.startswith("../") or found in ("..", ".") or PurePosixPath(found).is_absolute():
        return None
    return found if PurePosixPath(found).suffix in jsmap.SOURCES else None


def _targets(value: object) -> list[str]:
    """The targets a subpath's value names, ``types`` conditions first at each level."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [target for item in value for target in _targets(item)]
    if isinstance(value, dict):
        keys = sorted(value, key=lambda key: key not in ("types", "typings"))
        return [target for key in keys for target in _targets(value[key])]
    return []


def _with_declarations(paths: Sequence[str]) -> tuple[str, ...]:
    """The paths, then the declaration file beside each JavaScript one (where TypeScript looks
    for its types), each once."""
    found = list(paths)
    for path in paths:
        stem, suffix = posixpath.splitext(path)
        if suffix in _DECLARATION_FOR and not stem.endswith(".d"):
            found.append(stem + _DECLARATION_FOR[suffix])
    return tuple(dict.fromkeys(found))


def entries(manifest: Mapping[str, Any]) -> tuple[list[Entry], list[tuple[str, str]]]:
    """The package's entry points, and the subpaths not read, each with why."""
    exports = manifest.get("exports")
    if exports is None:
        return [_fields_entry(manifest)], []
    if isinstance(exports, dict) and exports:
        subpaths = [key.startswith(".") for key in exports]
        if all(subpaths):
            listed = list(exports.items())
        elif not any(subpaths):
            listed = [(".", exports)]
        else:
            return [], [(".", "package.json's exports mixes subpaths and conditions")]
    else:
        listed = [(".", exports)]
    found: list[Entry] = []
    skipped: list[tuple[str, str]] = []
    for subpath, value in listed:
        targets = _targets(value)
        if "*" in subpath or any("*" in target for target in targets):
            skipped.append((subpath, f"the subpath pattern {subpath} is not expanded"))
            continue
        paths = [p for p in (_path(target) for target in targets) if p is not None]
        if paths:
            found.append(Entry(subpath, _with_declarations(paths)))
    return found, skipped


def _fields_entry(manifest: Mapping[str, Any]) -> Entry:
    """The one entry ``types``, ``typings``, ``module`` and ``main`` name, else ``index.js``."""
    named = [str(manifest[name]) for name in FIELDS if isinstance(manifest.get(name), str)]
    paths: list[str] = []
    for value in named or ["index.js"]:
        target = posixpath.normpath(value.removeprefix("./"))
        if target.startswith("..") or PurePosixPath(target).is_absolute():
            continue
        if PurePosixPath(target).suffix in jsmap.SOURCES:
            paths.append(target)
        else:  # Node's main: the name with .js added, or a directory's index.js
            paths += [f"{target}.js", f"{target}/index.js"]
    return Entry(".", _with_declarations(paths))


# -- the trees ------------------------------------------------------------------------------------


def _manifest(data: bytes | None) -> tuple[dict[str, Any] | None, str | None]:
    if data is None:
        return None, "no package.json"
    try:
        found = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return None, f"package.json cannot be read: {exc}"
    if not isinstance(found, dict):
        return None, "package.json is not an object"
    return found, None


def _wanted(path: str) -> bool:
    """A file the compiler may read: JavaScript, TypeScript (declarations too), JSON."""
    parts = PurePosixPath(path)
    return "node_modules" not in parts.parts and (
        parts.suffix in jsmap.SOURCES or parts.suffix == ".json"
    )


def _write_tree(root: Path, sources: Mapping[str, bytes]) -> None:
    """Each file at its path under ``root``; a path that cannot be written safely, or that
    collides with another on a case-insensitive filesystem, is left out."""
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    insensitive = case_insensitive(root)
    written: set[str] = set()
    for path in sorted(sources):
        key = path.lower() if insensitive else path
        if path_problem(path) is not None or key in written:
            continue
        written.add(key)
        target = root.joinpath(*path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(sources[path])


# -- the comparison -------------------------------------------------------------------------------


def _short(text: str) -> str:
    return text if len(text) <= _VALUE else text[: _VALUE - 1] + "…"


def _signature(data: Mapping[str, Any]) -> Signature:
    params = tuple(
        Parameter(str(p["name"]), str(p["type"]), bool(p["optional"]), bool(p["rest"]))
        for p in data["params"]
    )
    returns = data.get("returns")
    return Signature(params, None if returns is None else str(returns), str(data["text"]))


def _shape(data: Mapping[str, Any]) -> Shape:
    members = data.get("members")
    value = data.get("value")
    return Shape(
        kind=str(data["kind"]),
        signatures=tuple(_signature(s) for s in data.get("signatures") or ()),
        type=None if data.get("type") is None else str(data["type"]),
        value=None if value is None else str(value),
        members=None if members is None else {str(k): _shape(v) for k, v in members.items()},
    )


def read_exports(response: Mapping[str, Any]) -> list[Export]:
    """One side's exports from the worker's answer."""
    files = {str(e["subpath"]): str(e["file"]) for e in response["entries"]}
    return [
        Export(
            str(item["subpath"]),
            str(item["name"]),
            str(item.get("file") or files[str(item["subpath"])]),
            str(item.get("local") or item["name"]),
            _shape(item),
        )
        for item in response["exports"]
    ]


def _symbol(file: str, qualname: str) -> str:
    return f"{jsmap.module_name(file)}:{_UNSAFE.sub('-', qualname) or '-'}#0"


@dataclass
class _Finder:
    """Breaks between two shapes of one export, with what the schema cannot name."""

    file: str  # head's declaration file
    breaks: list[ApiBreak] = field(default_factory=list)
    unreported: list[str] = field(default_factory=list)

    def add(self, symbol: str, where: str, breakage: str, old: str | None, new: str | None) -> None:
        old, new = (None if v is None else _short(v) for v in (old, new))
        detail = f"{old} → {new}" if old is not None and new is not None else old or new
        text = f"{where}: {LABELS[breakage]}" + (f" ({detail})" if detail else "")
        explanation = text if len(text) <= EXPLANATION else text[: EXPLANATION - 1] + "…"
        self.breaks.append(
            ApiBreak(symbol, self.file, breakage, explanation, old, new, "typescript")
        )

    def shapes(self, symbol: str, where: str, old: Shape, new: Shape) -> None:
        if old.kind != new.kind:
            if "unresolved" not in (old.kind, new.kind):
                self.add(symbol, where, "object_changed_kind", old.kind, new.kind)
            return
        if old.kind in ("function", "method", "constructor"):
            self.signatures(symbol, where, old.signatures, new.signatures)
        elif old.kind == "enum_member":
            if old.value != new.value:
                self.add(symbol, where, "attribute_changed_value", old.value, new.value)
        elif old.members is not None and new.members is not None:
            # A callable interface or object type: its calls and its members; one added breaks
            # no caller.
            self.signatures(symbol, where, old.signatures, new.signatures)
            self.members(symbol, where, old.members, new.members)
        elif old.type != new.type and old.type is not None and new.type is not None:
            kind = "attribute_changed_value" if old.kind == "type" else "attribute_changed_type"
            self.add(symbol, where, kind, old.type, new.type)

    def members(
        self, symbol: str, where: str, old: Mapping[str, Shape], new: Mapping[str, Shape]
    ) -> None:
        module, _, rest = symbol.partition(":")
        owner = rest.rpartition("#")[0]
        for name, before in old.items():
            inner = f"{module}:{_UNSAFE.sub('-', f'{owner}.{name}')}#0"
            after = new.get(name)
            if after is None:
                self.add(inner, f"{where}.{name}", "object_removed", before.kind, None)
            else:
                self.shapes(inner, f"{where}.{name}", before, after)

    def signatures(
        self, symbol: str, where: str, old: Sequence[Signature], new: Sequence[Signature]
    ) -> None:
        for before, after in zip(old, new, strict=False):
            self.parameters(symbol, where, before, after)
        if len(new) < len(old):
            gone = ", ".join(s.text for s in old[len(new) :])
            self.unreported.append(_short(f"{where}: overloads removed: {gone}"))

    def parameters(self, symbol: str, where: str, old: Signature, new: Signature) -> None:
        absorbed = bool(new.params) and new.params[-1].rest
        for index, before in enumerate(old.params):
            if index >= len(new.params):
                if not absorbed:
                    self.add(symbol, where, "parameter_removed", before.text(), None)
                continue
            after = new.params[index]
            if before.rest != after.rest:
                self.add(symbol, where, "parameter_changed_kind", before.text(), after.text())
            elif before.optional and not after.optional and not after.rest:
                self.add(symbol, where, "parameter_changed_required", before.text(), after.text())
            if before.type != after.type:
                self.add(symbol, where, "parameter_changed_type", before.text(), after.text())
        for after in new.params[len(old.params) :]:
            if not after.optional and not after.rest:
                self.add(symbol, where, "parameter_added_required", None, after.text())
        if old.returns is not None and new.returns is not None and old.returns != new.returns:
            self.add(symbol, where, "return_changed_type", old.returns, new.returns)


def compare(
    base: Sequence[Export], head: Sequence[Export], labels: Mapping[str, str]
) -> tuple[list[ApiBreak], list[str]]:
    """The breaks from ``base``'s exports to ``head``'s, each once, and what the schema has no
    breakage kind for, in words. ``labels``: each entry's name, by subpath."""
    heads = {(e.subpath, e.name): e for e in head}
    breaks: list[ApiBreak] = []
    unreported: list[str] = []
    for before in base:
        symbol = _symbol(before.file, before.local)
        where = f"{before.name} in {labels.get(before.subpath, before.subpath)}"
        after = heads.get((before.subpath, before.name))
        finder = _Finder(before.file if after is None else after.file)
        if after is None:
            finder.add(symbol, where, "object_removed", before.shape.kind, None)
        else:
            finder.shapes(symbol, where, before.shape, after.shape)
        breaks += finder.breaks
        unreported += finder.unreported
    unique = {(b.symbol, b.breakage, b.old or "", b.new or ""): b for b in reversed(breaks)}
    ordered = sorted(
        unique.values(), key=lambda b: (b.symbol, b.breakage, b.old or "", b.new or "")
    )
    return ordered, list(dict.fromkeys(unreported))


# -- both sides -----------------------------------------------------------------------------------


@dataclass
class _Side:
    name: str
    manifest: dict[str, Any] | None
    entries: list[Entry]
    problems: list[tuple[str, str]]  # subpath, why


def _sides(git: Git, base: str, head: str) -> tuple[list[_Side], dict[str, dict[str, bytes]]]:
    sides: list[_Side] = []
    sources: dict[str, dict[str, bytes]] = {}
    for name, commit in (("base", base), ("head", head)):
        files = regular_files(git, commit)
        wanted = {path: sha for path, sha in files.items() if _wanted(path)}
        blobs = read_blobs(git, list(wanted.values())) if wanted else {}
        manifest, why = _manifest(blobs.get(wanted.get("package.json", ""), None))
        found, skipped = entries(manifest) if manifest is not None else ([], [(".", str(why))])
        sides.append(_Side(name, manifest, found, list(skipped)))
        sources[name] = {path: blobs[sha] for path, sha in wanted.items()}
    return sides, sources


def _why(entry: Entry, configs: Sequence[str], manifest: Mapping[str, Any]) -> str:
    """Why an entry was not resolved to a file."""
    listed = ", ".join(entry.paths) or "no file"
    mapped = (
        f"{' and '.join(configs)} maps none of them to a source"
        if configs
        else "there is no tsconfig.json to map them to a source"
    )
    why = f"none of {listed} is in the tree, and {mapped}"
    if "exports" in manifest or any(name in manifest for name in FIELDS):
        return why
    return f"package.json names no entry point (exports, main, module or types), and {why}"


def api_diff(git: Git, base: str, head: str, workdir: Path, package: Path) -> JsApiDiff:
    """The breaking changes of the package's entries from ``base`` to ``head``, read with the
    pinned compiler in ``package``. Raises ``typescript.TypeScriptError`` if it cannot run."""
    sides, sources = _sides(git, base, head)
    request: list[dict[str, Any]] = []
    for side in sides:
        root = workdir / side.name
        _write_tree(root, sources[side.name] if side.entries else {})
        listed = [{"subpath": e.subpath, "paths": list(e.paths)} for e in side.entries]
        request.append({"root": str(root.resolve()), "entries": listed})
    try:
        response = typescript.run(package, {"api": request}, workdir)
    finally:
        for side in sides:
            shutil.rmtree(workdir / side.name, ignore_errors=True)
    exports: dict[str, list[Export]] = {}
    for side, answer in zip(sides, response["api"], strict=True):
        by_subpath = {e.subpath: e for e in side.entries}
        for item in answer["unresolved"]:
            subpath = str(item["subpath"])
            why = _why(by_subpath[subpath], answer["configs"], side.manifest or {})
            side.problems.append((subpath, why))
        for item in answer["problems"]:
            side.problems.append((str(item["subpath"]), str(item["why"])))
        exports[side.name] = read_exports(answer)
    base_side, head_side = sides
    labels = {
        e.subpath: label((base_side.manifest or {}).get("name"), e.subpath)
        for e in base_side.entries
    }
    unread = {subpath for subpath, _ in base_side.problems + head_side.problems}
    head_subpaths = {e.subpath for e in head_side.entries}
    breaks: list[ApiBreak] = []
    for entry in base_side.entries:
        if entry.subpath in unread:
            continue
        if entry.subpath not in head_subpaths:
            breaks.append(_removed_entry(entry, exports["base"], labels[entry.subpath]))
    compared = [
        e for e in exports["base"] if e.subpath not in unread and e.subpath in head_subpaths
    ]
    found, unreported = compare(compared, exports["head"], labels)
    breaks = sorted(breaks + found, key=lambda b: (b.symbol, b.breakage, b.old or "", b.new or ""))
    problems = _problems(sides)
    entry_labels = tuple(sorted(labels[e.subpath] for e in base_side.entries))
    return JsApiDiff(breaks, problems, entry_labels, unreported)


def _removed_entry(entry: Entry, exports: Sequence[Export], name: str) -> ApiBreak:
    """An entry head's ``package.json`` no longer has."""
    files = [e.file for e in exports if e.subpath == entry.subpath]
    file = files[0] if files else entry.paths[0]
    text = f"{name}: entry point was removed from package.json"
    return ApiBreak(
        f"{jsmap.module_name(file)}:{jsmap.MODULE}#0",
        file,
        "object_removed",
        text,
        "module",
        None,
        "typescript",
    )


def _problems(sides: Sequence[_Side]) -> list[tuple[str, str, str]]:
    """Each entry not read: on base, head, or both when the reason is the same; its name; why."""
    found: dict[tuple[str, str], list[str]] = {}
    for side in sides:
        for subpath, why in side.problems:
            name = label((side.manifest or {}).get("name"), subpath)
            found.setdefault((name, why), []).append(side.name)
    return [(" and ".join(which), name, why) for (name, why), which in found.items()]
