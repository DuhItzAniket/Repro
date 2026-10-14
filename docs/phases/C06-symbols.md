# C06 — Symbol table & changed-symbol mapping

| | |
|---|---|
| **Stage** | C — Engine core & live stream |
| **Status** | in progress |
| **Depends on** | C05 |
| **Branch / PR** | `phase/C06-symbols` · PR pending |
| **Started / finished** | 2026-10-14 / — |

## Objective
For a change, Repro knows which symbols it touched, on both sides: functions, methods, classes
and module-level code, each with a stable identity, including symbols that were renamed or
moved to another module, and emits one `symbol.changed` event per touched symbol.

## Scope
- **Module names** (`repro.analysis.modules`): each file's dotted module name from the file list
  alone. A directory holding an `__init__.py` is a regular package, so a name walks up through
  such directories, and the first one that is not a package is the import root
  (`engine/src/repro/api/stream.py` → `repro.api.stream`; a `tests/test_api.py` outside a package
  → `test_api`). Names two files would share fall back to the whole path, on both sides.
- **Symbol table** (`repro.analysis.symbols`, ADR-0006): from `ast` (the source is parsed,
  never imported or run), every function, method and class with its qualified name (Python's own
  `__qualname__` form, `<locals>` included for nested definitions), its span from its first
  decorator to `end_lineno`, and an ordinal for repeated names (a property's getter and setter,
  overloads); `<module>` for the module's own code. Line ownership (the innermost symbol owning
  each line) and code lines (not blank, not comment-only) are kept for attributing lines later.
- **Changed symbols** (`repro.analysis.changes`): the diff (C05) says which files changed; in
  each, base and head symbols are paired by qualified name, and each symbol becomes one change:
  - `modified`: paired, and its own code differs;
  - `renamed`: unpaired on both sides in the same module, with near-identical code;
  - `moved`: the same in another module, including every symbol of a renamed file and of a
    file whose module name changed (an `__init__.py` added or removed above it);
  - `added` and `removed` otherwise.
  Files that cannot be read are reported, never silently skipped.
- **Events**: each change as a `symbol.changed` payload (`symbol_id`, `change`, `file`,
  `base_lines`, `head_lines`, `previous_symbol_id`).

## Out of scope
- The import graph, blast radius and `graph.*` events (C07); test identity (Stage D).
- Static call edges (ADR-0006: symbol-level dependencies come from the dynamic map, Stage E).

## Design notes
- **Own code decides "modified".** A symbol's own code is its AST without positions, each
  nested definition reduced to a marker naming it, or left out if only one side has it. So a
  comment, blank lines or a reformat change nothing; a changed method changes the method and not
  its class; an added method is an addition, not also a change to its class; and a nested
  function moved after its use still changes its parent (the marker moved). A docstring is code.
  The spec first said "changed lines map to their owning symbol"; the fixture with a trailing
  comment on `LIMIT = 3` showed that a changed line is not a changed symbol, so lines no longer
  decide (see Deviations).
- **Repeated names are aligned by own code** (`difflib.SequenceMatcher` over each symbol's own
  code), so a new overload is one addition and does not shift the implementation's ordinal into
  a false change; an edited implementation after a new overload is `modified` with its previous
  ID. Within a replaced run of different lengths, the most alike own code pairs first.
- **Rename and move matching** compares each unpaired definition's whole AST (nested definitions
  included, its own name normalised) by `SequenceMatcher` over its tokens; a ratio of at least
  0.8 is required and the best match wins. A parameter renamed together with the function still
  matches; a rewritten body does not, and becomes a removal and an addition. A class never
  matches a function.
- **Never guess.** A side that does not parse, is too complex to parse, or has no unique
  importable module name is reported as `Unanalysed`, and the file's other side is not reported
  as added or removed wholesale. Binary-flagged `.py` files are parsed too (a NUL byte is a
  reported parse error, not a silent skip). Symlinks and submodules are not modules.
- **Hostile input.** The AST serialiser is iterative: a file can nest expressions thousands deep.
  `ast.parse` itself raises `RecursionError` on a 20,000-term sum; that is reported.
- **Paths are exact.** File lists come from `git ls-tree -r -z` (`gitops.regular_files`), so
  names git would quote arrive verbatim.
- Sources are parsed by the host's Python (3.13). Syntax newer than that cannot be parsed and is
  reported as unparsable, not guessed.

## Acceptance criteria
- [x] AC1 (roadmap): fixture repositories with edits, renames, moves, decorators and class-body
      changes map correctly (table-driven tests).
- [x] AC2: symbol IDs match the schema's `SymbolId` and are stable across sides.
- [x] AC3: changes become schema-valid `symbol.changed` payloads.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_analysis_changes.py`: 30 cases, one fixture repository each |
| AC2 | `test_analysis_symbols.py`; module names table |
| AC3 | `test_analysis_changes.py`: every payload validated with the generated event model |

---
*Filled in at the end of the phase:*

## What shipped
- `engine/src/repro/analysis/`: `modules.py` (module names), `symbols.py` (symbol tables, own
  code, fingerprints), `changes.py` (changed symbols, `changed_symbols_between`).
- `repro.gitops`: `read_blobs` (one `git cat-file --batch` for many blobs) and `regular_files`
  (a commit's regular files by exact path).
- Tests: `test_analysis_changes.py` (32: 30 table-driven cases, line spans, unreadable files),
  `test_analysis_symbols.py` (33), one in `test_gitops_snapshot.py`. pytest 805 → 871
  (869 pass and 2 skip on Windows: two POSIX-only tests).

## Evidence
- The table covers edits in a body, a decorator, a class body, a method, a property setter
  (`#1`), a nested function, module-level code and a docstring; comments and a reformat (no
  change); added and removed functions and an added method; a rename, a rename with its
  parameter renamed, a rewrite (removed + added); a function moved to another module; a renamed
  file (every symbol moved, `<module>` included); new and deleted files; the src layout, a
  package below a monorepo directory, an `__init__.py` added above an unchanged file (moved
  though not in the diff); a `.py` symlink and a non-Python file (nothing); overloads added,
  removed and edited across an ordinal shift.
- Unreadable files: a syntax error on either side, a 20,000-term expression, a NUL byte and a
  path with a space are each reported, and nothing about those files is claimed.
- On this repository's own history (C01 parent → C05, 627 symbol changes) the analysis takes
  0.24 s on the development machine, and names modules as Python and pytest would import them
  (`repro.api.stream`, `test_gitops_diff`). The first run named them `engine.src.repro…`, which
  is why module naming walks up through packages.
- CI run: linked in the PR.

## Deviations from spec
- "Changed lines → changed symbols": the diff selects files, and own code decides which symbols
  changed (Design notes). Line ownership remains in the symbol table for later attribution.
- Module naming walks up through `__init__.py` directories instead of only dropping a leading
  `src/`: the narrower rule misnamed packages below a monorepo directory.

## Known gaps
- PEP 420 namespace packages (no `__init__.py`) are named from their first regular package or
  their own directory, not from the true import root, which needs packaging metadata.
- Reordering top-level definitions changes `<module>`'s own code (the markers moved) and is
  reported as a change to `<module>`.
- Within a run of repeated names, pairing is by own-code similarity; two edits that swap the
  bodies of same-named definitions may pair the "wrong" way round.
- Rename and move matching compares every unpaired definition with every other: quadratic in
  the number of unpaired definitions (cheap per pair, with length-based pre-filters).

## Dependencies added
None (the standard library's `ast`, `tokenize` and `difflib`).

## Research notes
- Regular packages: "A regular package is typically implemented as a directory containing an
  `__init__.py` file." Python language reference §5.2.1; namespace packages have no
  `__init__.py` (§5.2.2). https://docs.python.org/3/reference/import.html **[V]** 2026-10-14
- pytest's default (`prepend`) import mode searches upwards for the last directory that still
  contains an `__init__.py` and inserts the directory above into `sys.path`; test files outside
  packages are imported by their basename and must have unique names.
  https://docs.pytest.org/en/stable/explanation/pythonpath.html **[V]** 2026-10-14
- `compile()` (and so `ast.parse`) raises `SyntaxError` for invalid source, including a null
  character (since 3.12; `ValueError` before), `MemoryError` or `RecursionError` if the source is
  too complex, and `OverflowError` if it is too large.
  https://docs.python.org/3/library/functions.html#compile **[V]** 2026-10-14
- Measured here: CPython 3.13's `ast.parse` raises `RecursionError` ("maximum recursion depth
  exceeded during ast construction") on `x = 1+1+…` with 20,000 terms, and `SyntaxError` ("too
  many nested parentheses") on 300 nested parentheses.
