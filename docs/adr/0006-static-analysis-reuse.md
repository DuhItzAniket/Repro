# ADR-0006: Reuse `ast`, grimp and griffe for static analysis

- **Status:** accepted
- **Date:** 2026-10-13
- **Phase:** A01 (implemented in C06–C07, E05)

## Context
The build stage needs a symbol table, a changed-lines → symbols mapping, a module import graph
and a public-API diff. Writing all of these from scratch would take months. Candidates were
verified on 2026-10-13 (research/03 §4):
- **grimp** 3.17: BSD-2, Rust core, handles lazy imports, actively maintained. Module-level only.
- **griffe** 2.3.2: ISC. `find_breaking_changes(old, new)` detects removed/moved parameters,
  changed defaults, removed objects and similar. It does not yet check return-type or
  attribute-type compatibility. It *imports* modules when static parsing fails unless
  `allow_inspection=False`.
- **LibCST**, **jedi** and **pyright** offer richer resolution. jedi executes the environment's
  Python, and pyright exposes call hierarchy only via its language server.

## Decision
- `ast` for symbols and line spans. Repro builds its own symbol identity across refs
  (`module:qualname#ordinal`, with AST-similarity matching for renames).
- grimp for the module import graph and downstream modules.
- griffe with **`allow_inspection=False`** for the API surface and breaking changes, plus
  Repro's own annotation-string comparison for return and attribute types.
- No code-executing analysers run on the host. jedi and pyright may run later inside the
  sandbox only.

## Implementation note (E05)
griffe 2.x is published as a meta-package (`griffe`) of `griffelib`, the library, and
`griffecli`, its command line; Repro depends on `griffelib` 2.3.2 only (the same `griffe`
import). Its `find_breaking_changes` still leaves return and attribute annotations as TODOs,
so Repro's annotation comparison stands as decided.

## Consequences
Symbol-level reverse dependencies come from the dynamic per-test map (ADR-0005), not static
call graphs. This is the right choice for Python's dynamism (STARTS found static selection
unsafe under reflection; research/02 §4.2). It also means changed code that no test reaches is
reported as `no_covering_test`, never silently ignored.
