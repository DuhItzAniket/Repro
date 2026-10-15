# E05 — API & dependency diff

| | |
|---|---|
| **Stage** | E — Behaviour evidence |
| **Status** | in progress |
| **Depends on** | C06, D03 |
| **Branch / PR** | `phase/E05-api-deps` · PR pending |
| **Started / finished** | 2026-10-15 / — |

## Objective
Show what a change does to the project's contract with its users and to what it brings in: the
public API's breaking changes, read without running a line of the target, and the dependencies
it adds, removes or moves, as declared or locked and as actually installed on each side.

## Scope
- **API diff** (`repro.analysis.api`): the project's packages (import-root directories with an
  `__init__.py`, test packages left out) read by griffe with `allow_inspection=False` from
  files taken out of git; `griffe.find_breaking_changes` plus Repro's comparison of return and
  attribute annotations (which griffe 2.3.2 does not check); `api_diff` evidence and a
  `diff.api` check per break (`warn`); a package griffe cannot read is an `unsupported_project`
  item.
- **Dependency diff** (`repro.provision.deps`): each side's requirements as D03 read them (a
  lock's pins, or the declared requirements) and each side's installed distributions, listed
  in its sandbox by its own interpreter (`Side.installed`); `added`, `removed`, `upgraded`,
  `downgraded` (PEP 440 order, `packaging`), `changed`; `dep_diff` evidence and a `diff.deps`
  check each (`warn`).
- **Lock drift**: a locked project's package installed at another version than its pin,
  `lock_drift` evidence.
- **Schema**: `diff.deps`'s `source` gains `declared` (requirements without a lock).
- **Jobs** `api` and `deps` (diff stage, after `tests`).
- **Dependencies added**: `griffelib` 2.3.2 (griffe's library, without its CLI) and `packaging`
  (already locked through other packages, now declared).
- **Fixtures** `api-break` and `new-dep`.

## Out of scope
- Whether a break or a new dependency is allowed: invariants (`public_api_stable`,
  `no_new_dependencies`, Stage F); probes (E06); the cockpit's panels from these events (E07).

## Design notes
- **The API is the packages.** A top-level module file (`setup.py`, `conftest.py`, a test
  file, a script) is not API; a package is. Single-module libraries are a known gap.
- **griffe reads files, never imports.** `allow_inspection=False`, the files written from git
  to a scratch tree laid out by module name, no extension loaded beyond griffe's defaults. A
  test package whose module raises on import and writes a marker file shows nothing ran.
- **Repro's own explanations.** griffe's `explain()` names the scratch tree's absolute paths
  and colours its text; the evidence states the object's dotted path, griffe's description of
  the kind, and the old and new values.
- **Annotations as text.** Two annotations that read differently are a change of the declared
  type (`int` → `int | None` included); deciding compatibility would need a type checker.
- **Installed sets from inside the sandbox.** The listing runs the side's interpreter with
  `-I -S`: no `site`, no `.pth` file, no distribution's code. Without `site` the interpreter
  does not know it is in a virtual environment (`site` sets `sys.prefix` from `pyvenv.cfg`), so
  the environment's root is passed and its `site-packages` found from it.
- **`declared` is not `lockfile`.** A project without a lock declares ranges, not versions;
  calling those a lock would misstate the evidence, so the schema's `source` gains `declared`.

## Acceptance criteria
- [x] AC1 (roadmap): the `api-break` and `new-dep` fixtures pass.
- [x] AC2 (roadmap): griffe never imports target code, tested with a module that raises on
  import.
- [x] AC3: every break and dependency difference is evidence with a `warn` check, schema-valid,
  through `repro run`; the other fixtures gain none.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_a_run_reproduces_the_fixture[api-break, new-dep]` |
| AC2 | `test_breaking_changes_without_importing_anything` (a trap module: `raise SystemExit` after writing a marker) |
| AC3 | `test_run_stage.py` over every fixture; `test_api_diff.py`, `test_deps.py` (schema validation of evidence and payloads) |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.analysis.api`: `api_diff`, `ApiBreak` (evidence, `diff.api` payload), `ApiDiff`
  (missing items).
- `repro.provision.deps`: `project_requirements`, `compare`, `DepChange`, `lock_drift`,
  `LIST_INSTALLED`, `parse_installed`; `Side.installed`.
- The `api` and `deps` jobs; `diff.deps` `source` gains `declared` (TS and Pydantic
  regenerated); ADR-0006's implementation note.
- Fixtures `api-break`, `new-dep`; `test_run_stage.py` names `api_diff` and `dep_diff`
  evidence.
- Tests: `test_api_diff.py` (4), `test_deps.py` (8), both fixtures in `test_twosided.py` and
  `test_run_stage.py`. pytest 1248 → 1266 (1254 pass and 12 skip on Windows with Docker
  Desktop stopped).

## Evidence
- AC1: through `repro run`, `api-break` gives `parameter_removed` on `greet` (griffe:
  "greeting.hello.greet: Parameter was removed (punctuation = '!')") and
  `return_changed_type` on `shout` (Repro's comparison: "str → str | None"), with every test
  P2P; `new-dep` gives `six` `added` as declared (1.17.0) and as installed (1.17.0 listed in
  head's environment, absent from base's).
- AC2: the API test's package has a module that writes a marker file and raises `SystemExit`
  at import; after the diff of both sides no marker exists, and its breaks were all found.
- The unit repository's breaks (`test_api_diff.py`): a required parameter added, an
  attribute's value changed, an object removed, a parameter removed, a default turned into a
  required keyword (griffe), two attribute annotations and a return annotation changed
  (Repro); a private function's change, the tests, `conftest.py` and `setup.py` give none.
- AC3: the six other fixtures run through `repro run` gain no `api_diff` or `dep_diff` evidence
  (their expectations unchanged and met); the evidence and payloads validate against the
  schema.
- The installed listing, run against Repro's own environment, finds `griffelib` and
  `packaging` and leaves out the workspace's editable `repro-engine`.
- CI run: linked in the PR.

## Deviations from spec
- The schema's `diff.deps` `source` gains `declared` (additive): requirements without a lock
  are not a lockfile.
- ARCHITECTURE §4.5 lists installed sets from `uv pip list --format json`; E05 lists them with
  the side's own interpreter and `importlib.metadata`, inside its sandbox, which needs no uv
  there and reads the same metadata.
- Lock drift is evidence without a check event: the event schema has no `diff.*` kind for a
  single side's environment, and its `dep_diff` checks compare sides.

## Known gaps
- A library that is a single module, not a package, has no API diff.
- Annotation changes are compared as text: an equivalent spelling (`List[int]` to
  `list[int]`) is reported.
- Packages a lock pins but whose marker excludes this platform are not checked for drift.
- Without a lock, a range that resolves to a newer release on head than on base shows only in
  the installed comparison.

## Dependencies added
- `griffelib` 2.3.2 (ISC), griffe's library distribution: griffe 2.x is a meta-package of
  `griffelib` and `griffecli`, and Repro needs no CLI. Requires-Python ≥ 3.11, no required
  dependencies. https://pypi.org/project/griffelib/2.3.2/ **[V]** 2026-10-15 (PyPI JSON API).
- `packaging` ≥ 26.3 (Apache-2.0 OR BSD-2-Clause), already in the lock through other
  packages, now a direct dependency for PEP 440 versions and PEP 508 requirements.

## Research notes
- griffe 2.3.2 source (`griffe/_internal/diff.py`): `_returns_are_compatible` returns True
  for any two present annotations ("TODO: Support annotation breaking changes"), and
  `_attribute_incompatibilities` compares values only ("TODO: Support annotation breaking
  changes"): what Repro's annotation comparison adds. Read from the installed package,
  2026-10-15 **[V]**.
