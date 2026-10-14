# C07 — Import graph & blast radius

| | |
|---|---|
| **Stage** | C — Engine core & live stream |
| **Status** | in progress |
| **Depends on** | C06 |
| **Branch / PR** | `phase/C07-import-graph` · PR pending |
| **Started / finished** | 2026-10-14 / — |

## Objective
For a change, Repro knows each side's module import graph and the change's blast radius: the
changed symbols and the modules that import them, directly or not, with their distance. Both
become events: `graph.node`, `graph.edge` and `blast.computed`.

## Scope
- **Import graph** (`repro.analysis.imports`, ADR-0006): grimp 3.17 for the repository's regular
  packages; `ast` for the modules grimp cannot load as a package (test files outside a package,
  scripts, a root `conftest.py`), resolved against the same module names (C06). Problems are
  listed, never dropped.
- **Blast radius** (`repro.analysis.blast`): breadth-first over the import edges of both sides
  from the changed symbols' modules; affected modules as their `<module>` symbol with distance;
  modules whose own code changed as `module_level_changes`.
- **Events**: `graph.node` for every module of either side and for each changed function,
  method or class; `graph.edge` for every import of either side; `blast.computed`.
- **One call** (`repro.analysis.analyse`): changed symbols, both graphs and the blast radius of
  `base..head`, reading every Python file through one `git cat-file --batch`.

## Out of scope
- Emitting these events from a run (`repro run`, C08) and showing them live (C08).
- Symbol-level reverse dependencies: from the dynamic per-test map (Stage E, ADR-0005).
- Which tests a change selects (D05).

## Design notes
- **grimp never resolves a target name through the import system.** Its default package finder
  calls `importlib.util.find_spec`, which returns whatever `sys.modules` already holds: a target
  package named `logging`, `grimp` or `repro` (this repository) would be analysed as the wrong
  code, and a target tree on `sys.path` could shadow a module grimp imports lazily, which would
  then *run*. So grimp runs as `python -I -S` in a process of its own (`_grimp_worker.py`,
  standard library and grimp only), and each package's directory is handed to it through its
  `PACKAGE_FINDER` setting, the injection point grimp configures for itself in `grimp/main.py`.
  The tree is never on `sys.path`. That setting is not documented API, so grimp is pinned to
  `>=3.17,<3.18`, and the tests that prove no target code runs would fail on a change.
- **grimp reads a tree written from blobs**, holding only regular `.py` files of the packages
  (no symlinks, every path checked with C05's `path_problem`, case collisions caught on
  case-insensitive filesystems), and it is removed afterwards. A C05 snapshot is for running the
  target; on POSIX it keeps symlinks, which host-side analysis must not follow.
- **One bad file does not lose the graph.** grimp stops at the first file it cannot parse; the
  worker empties that file, reports it, and rebuilds (at most 100 times).
- **Modules outside packages**: grimp's `build_graph` takes packages only, but tests are the
  importers that matter most for test selection. Their `import`/`from … import` statements are
  read with `ast` and resolved like grimp does: the most specific existing module
  (`from a.b import c` is `a.b.c` if that module exists, else `a.b`), relative imports from the
  module's own package, none above the top level.
- **Both sides together**: the blast radius walks the union of base and head imports, so a
  module whose importer the change deleted still counts; the cockpit's graph shows both sides.
- **Module-level only**: an affected module appears as its `<module>` symbol. A module that
  changed is not also listed as affected.

## Acceptance criteria
- [ ] AC1 (roadmap): on fixture repositories and one pinned real repository, the blast radius
      matches hand-checked expectations.
- [ ] AC2: imports resolve inside and outside packages (absolute, relative, star, inside
      functions, `TYPE_CHECKING`), and no target code runs, whatever the names.
- [ ] AC3: `graph.node`, `graph.edge` and `blast.computed` payloads are schema-valid.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_analysis_imports.py`: four blast cases on a fixture repository; this repository at `705a9aa..929b9eb` |
| AC2 | `test_analysis_imports.py`: the `shop` fixture; shadowing names with a marker; unparsable files, unsafe paths, case collisions, a timeout |
| AC3 | `test_analysis_imports.py`: every payload validated with the generated event models |

---
*Filled in at the end of the phase:*

## What shipped
- `engine/src/repro/analysis/`: `imports.py` (import graphs), `_grimp_worker.py` (grimp in its
  own process), `blast.py` (blast radius, graph payloads), `static.py` (`analyse`).
  `SymbolChange` gains the symbol's `kind` (a changed symbol's graph node needs it).
- `repro.gitops.snapshot.case_insensitive` is public (the graph's tree uses it too).
- THREAT_MODEL T19; CI's test job checks out the full history (the pinned test needs it).
- Tests: `test_analysis_imports.py` (12). pytest 871 → 883 (881 pass and 2 skip on Windows: two
  POSIX-only tests).

## Evidence
- Hand-checked on this repository, `705a9aa..929b9eb` (C05 changed `repro.api.stream`): app
  (1), `repro.api` (2), `cli` through the import inside `serve` and the three API test modules
  (3), `__main__` and `test_cli` (4), each checked against the import lines at `929b9eb`; the
  whole analysis of that change (77 modules, 155 imports on head) takes 0.70 s on the
  development machine.
- Packages named `logging` and `grimp` whose every module would write a marker file if run are
  analysed from the tree, their edges found, and no marker appears.
- A package file grimp cannot parse is reported and emptied, and the package's other edges stay;
  a test file that does not parse is reported; `con/` and `pkg/aux.py` are reported, not
  written; on NTFS `pkg/Mod.py` and `pkg/mod.py` collide and one is reported; a 1 ms timeout is
  reported and the `ast`-read modules keep their edges.
- CI run: linked in the PR.

## Deviations from spec
- ADR-0006 names grimp for the import graph; grimp only loads packages, so modules outside
  packages are read with `ast` (Design notes). grimp still builds every package's graph.

## Known gaps
- A package module importing a module outside any package (`import helpers` of a root
  `helpers.py`) loses that edge: grimp treats it as external.
- Dynamic imports (`importlib.import_module`, `__import__`) are not seen.
- Relative imports in a module inside a package directory that lacks an `__init__.py` (an
  "orphan", which grimp skips) are resolved from the name C06 gives it, which is not its real
  package.
- Affected modules are module-level; which of their symbols use the change comes in Stage E.

## Dependencies added
- **grimp** `>=3.17,<3.18` (locked 3.17), BSD-2-Clause; no runtime dependencies of its own;
  wheels for Windows x64 and manylinux x86_64. Chosen in ADR-0006.

## Research notes
- grimp 3.17 is the current release (uploaded 2026-09-04), licence "BSD 2-Clause License",
  `requires_python >=3.10`, no `Requires-Dist`. https://pypi.org/pypi/grimp/json **[V]**
  2026-10-14
- `build_graph(package_name, ...)`: "For regular packages, this must be the top level package";
  namespace portions may be passed instead; `cache_dir=None` disables caching.
  https://grimp.readthedocs.io/en/stable/usage.html **[V]** 2026-10-14
- grimp 3.17's source (read in the installed wheel): `ImportLibPackageFinder` calls
  `importlib.util.find_spec(package_name)`; `ModuleFinder` does not descend into a directory
  without `__init__.py` inside a package ("orphans"), skips directories that are not
  identifiers and files with more than one dot; `SourceSyntaxError` carries the file name.
