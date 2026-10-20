"""JavaScript and TypeScript: the static analysis of a change (K08; ADR-0017, phase 4).

The same ``StaticAnalysis`` as Python's (``repro.analysis.static``), read with scanners rather
than a parser (the TypeScript compiler API is K11), so the build stage emits the same events:

- **Modules**: each side's JavaScript and TypeScript sources, declaration files (``.d.ts``)
  left out, each named by its path (``jsmap.module_name``).
- **Imports**: the relative specifiers in ``import … from``, ``export … from``, a bare
  ``import "…"``, ``import("…")`` and ``require("…")``, each a string literal; comments and
  other strings are blanked first. A specifier resolves as Node and bundlers resolve one: the
  file itself, a ``.js`` name standing for its ``.ts`` source (TypeScript's convention), the
  name with an extension added, or a directory's ``index``. A package (``"lodash"``), a path
  alias or a computed specifier is not an edge.
- **Changed symbols** (``jsmap.changed``): each changed named function is ``added``,
  ``removed`` or ``modified`` by whether each side has it, and ``moved`` when its file was
  renamed. A changed line in no named function is a change to the module's own code
  (``<module>``), as in Python.
- **The blast radius** is Python's (``analysis.blast``): the changed modules' importers, at
  their distance.
"""

import posixpath
import re
from collections.abc import Collection, Mapping
from pathlib import PurePosixPath
from typing import Final

from repro import jsmap
from repro.analysis.blast import blast_radius
from repro.analysis.changes import ChangedSymbols, ChangeKind, SymbolChange
from repro.analysis.imports import ImportGraph
from repro.analysis.static import StaticAnalysis
from repro.gitops import Git, diff, read_blobs, regular_files

#: Where an import's specifier starts: the quote after ``from``, ``import``, ``import(`` or
#: ``require(``, in source whose strings are blanked (``jsmap.blanked`` keeps the quotes).
_SPECIFIER: Final = re.compile(r"""(?:\bfrom|\bimport|\b(?:import|require)\s*\()\s*(["'])""")
_EXTENSIONS: Final = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
#: TypeScript's sources for a JavaScript name: ``import "./a.js"`` names ``a.ts``.
_SOURCE_FOR: Final[Mapping[str, tuple[str, ...]]] = {
    ".js": (".ts", ".tsx"),
    ".jsx": (".tsx",),
    ".mjs": (".mts",),
    ".cjs": (".cts",),
}


def is_source(path: str) -> bool:
    """A JavaScript or TypeScript source of the project's own: a declaration file holds no
    code, and a committed ``node_modules`` is its dependencies'."""
    return (
        PurePosixPath(path).suffix in jsmap.SOURCES
        and not re.search(r"\.d\.[mc]?ts$", path)
        and "node_modules" not in PurePosixPath(path).parts
    )


def specifiers(source: str) -> list[str]:
    """The string literals ``source`` imports or requires, in order."""
    blank = jsmap.blanked(source)
    found = []
    for match in _SPECIFIER.finditer(blank):
        quote = match.group(1)
        end = blank.find(quote, match.end())
        if end > match.end():
            found.append(source[match.end() : end])
    return found


def resolve(importer: str, specifier: str, files: Collection[str]) -> str | None:
    """The file a relative ``specifier`` in ``importer`` names, if it is one of ``files``."""
    if not specifier.startswith(("./", "../")):
        return None
    target = posixpath.normpath(posixpath.join(posixpath.dirname(importer), specifier))
    if target == ".." or target.startswith("../"):
        return None
    stem, extension = posixpath.splitext(target)
    candidates = [
        target,
        *(stem + other for other in _SOURCE_FOR.get(extension, ())),
        *(target + other for other in _EXTENSIONS),
        *(f"{target}/index{other}" for other in _EXTENSIONS),
    ]
    return next((c for c in candidates if c in files), None)


def import_graph(sources: Mapping[str, str]) -> ImportGraph:
    """One side's modules and the imports between them."""
    names = {path: jsmap.module_name(path) for path in sources}
    imports = set()
    for path, source in sources.items():
        for specifier in specifiers(source):
            target = resolve(path, specifier, sources)
            if target is not None and target != path:
                imports.add((names[path], names[target]))
    return ImportGraph({names[p]: p for p in sorted(sources)}, frozenset(imports), ())


def symbol_changes(change: jsmap.JsChange) -> list[SymbolChange]:
    """``change``'s symbols: each changed function, and the module's own code if it changed."""
    moved = change.old_path is not None and change.new_path not in (None, change.old_path)
    found = []
    for name in sorted(change.functions):
        old, new = change.old_spans.get(name), change.new_spans.get(name)
        kind: ChangeKind = "removed" if new is None else "added" if old is None else "modified"
        previous = None
        if moved and kind == "modified":
            kind, previous = "moved", jsmap.symbol_id(str(change.old_path), name)
        symbol = jsmap.symbol_id(change.file, name)
        found.append(SymbolChange(symbol, kind, "function", change.file, old, new, previous))
    if change.module_level:
        if change.old_path is None or change.new_path is None:
            kind = "added" if change.old_path is None else "removed"
            previous = None
        else:
            kind = "moved" if moved else "modified"
            previous = jsmap.symbol_id(change.old_path) if moved else None
        old_lines = (1, change.old_size) if change.old_size else None
        new_lines = (1, change.new_size) if change.new_size else None
        symbol = jsmap.symbol_id(change.file)
        found.append(
            SymbolChange(symbol, kind, "module", change.file, old_lines, new_lines, previous)
        )
    return found


def analyse(git: Git, base: str, head: str) -> tuple[StaticAnalysis, list[jsmap.JsChange]]:
    """Changed symbols, both sides' import graphs and the blast radius of ``base..head``, and
    the change per file (``jsmap.changed``'s). Every source of both sides is read through one
    ``git cat-file --batch``."""
    sides = [
        {p: sha for p, sha in regular_files(git, commit).items() if is_source(p)}
        for commit in (base, head)
    ]
    found = [c for c in diff(git, base, head) if PurePosixPath(c.path).suffix in jsmap.SOURCES]
    extra = [b for c in found for b in (c.old_blob, c.new_blob) if b is not None]
    wanted = [*sides[0].values(), *sides[1].values(), *extra]
    blobs = read_blobs(git, wanted) if wanted else {}

    def text(blob: str | None) -> str:
        return blobs.get(blob, b"").decode("utf-8", "replace") if blob else ""

    changes = [
        jsmap.file_change(
            c,
            None if c.old_path is None else text(c.old_blob),
            None if c.new_path is None else text(c.new_blob),
        )
        for c in found
    ]
    symbols = tuple(s for change in changes for s in symbol_changes(change))
    graphs = [import_graph({p: text(sha) for p, sha in files.items()}) for files in sides]
    analysis = StaticAnalysis(
        ChangedSymbols(symbols, ()), graphs[0], graphs[1], blast_radius(symbols, *graphs)
    )
    return analysis, changes
