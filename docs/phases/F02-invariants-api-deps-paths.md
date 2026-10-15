# F02 — Invariants I: API, dependencies, forbidden paths

| | |
|---|---|
| **Stage** | F — Policy & deterministic card |
| **Status** | in progress |
| **Depends on** | F01, E05 |
| **Branch / PR** | `phase/F02-invariants` · PR pending |
| **Started / finished** | 2026-10-15 / — |

## Objective
Turn three of `repro.yml`'s invariants into results a reviewer can trust: whether a change
breaks the public API, adds a dependency, or touches a forbidden path, each decided from the
run's own evidence and citing it, and "not evaluated" whenever that evidence is missing.

## Scope
- **Rules** (`repro.policy.invariants`): `public_api_stable` (E05's breaks outside `except`,
  dotted object patterns), `no_new_dependencies` (packages added to the lock or the declared
  requirements outside `allow`), `forbidden_paths` (any path the change adds, removes, modifies
  or renames, against `*`, `**`, `?` patterns).
- **Results**: `invariant` evidence (the result, the options, the details and the evidence it
  cites) and an `invariant.result` check whose `evidence_ids` start with it; `ok` / `fail` /
  `warn` (ADR-0015 §2).
- **Not evaluated, never assumed**: the API not compared or a package unread, the
  dependencies not compared, the changed files unknown. `no_network` and `perf_budget` are
  `not_evaluated` until F03.
- **The `invariants` job** (check stage): it needs `policy` and comes `after` `api` and
  `deps` (a new `Job.after`: it waits for them however they end, so a failed or skipped job
  before it leaves an invariant `not_evaluated` instead of skipping them all). The `api` and
  `deps` jobs hand their breaks and differences, with their evidence IDs, through `RunState`,
  and themselves come `after` `tests`: the API is read from git, the requirements from the
  snapshots, so both are compared when a side could not be installed.
- **The declared dependencies, whatever the project installs from**: `Project.declared` (the
  `[project]`, `setup.py` and `setup.cfg` requirements, None when they cannot be read
  statically), compared beside a lock or requirement files; unread metadata without a lock is
  an `unsupported_project` item and makes `no_new_dependencies` not evaluated.
- **Path patterns that cannot match are refused**: a leading `/`, a backslash, an empty, `.`
  or `..` segment is a `repro.yml` error with its line; a pattern that matches a directory
  forbids everything under it.
- **Fixtures**: `invariants-pass` (every invariant enabled, a change that keeps them),
  `forbidden-path`; `api-break` and `new-dep` gain a base `repro.yml` enabling the invariant
  they break.

## Out of scope
- `no_network` and `perf_budget` (F03); what a failed invariant does to the card's status
  (F04).

## Design notes
- **One result per declared invariant.** Each is its own evidence, so a verdict (Stage G) can
  cite exactly the invariant it explains, and the result cites the evidence it rests on (the
  `api_diff` and `dep_diff` items).
- **Installed-only additions are not the change's dependencies.** A package that only the
  installed sets show was pulled in by another; the invariant judges what the change declares
  or locks.
- **Patterns are paths, not regular expressions.** `*` stays within a segment, `**` crosses
  them, `?` is one character, everything else is literal (brackets too). A pattern that
  matches a directory matches what is under it, so `migrations`, `migrations/` and
  `migrations/**` protect the same files; a trailing `/` matches directories only.
- **A rule that could pass vacuously is an error or "not evaluated".** A pattern that can
  never match and metadata Repro cannot read would otherwise pass every change.

## Acceptance criteria
- [x] AC1 (roadmap): each invariant emits `invariant.result` plus evidence.
- [x] AC2 (roadmap): a passing and a failing fixture per invariant.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_invariants.py` (each rule's pass, fail and not-evaluated cases, schema-valid evidence and payloads); `test_run_stage.py` checks every `invariant.result`'s status and that it cites its evidence |
| AC2 | `test_a_run_reproduces_the_fixture[invariants-pass]` (three passes, two not evaluated until F03); `[api-break]`, `[new-dep]`, `[forbidden-path]` (one failure each); `test_invariants_are_evaluated_when_head_cannot_be_built` (head adds a dependency that does not install: `public_api_stable` passes, `no_new_dependencies` and `forbidden_paths` fail) |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.policy.invariants`: `InvariantResult` (`invariant` evidence, `invariant.result`
  payload), `public_api_stable`, `no_new_dependencies`, `forbidden_paths`, `matches`,
  `dotted`, `not_yet`; `repro.policy.loader.path_problem`.
- The `invariants` job (check stage); `RunState.projects`, `api_breaks`, `api_unread`,
  `dep_changes`, `dep_unread`.
- The orchestrator's `Job.after`; the `api` and `deps` jobs come `after` `tests`.
- `Project.declared` and `declared_file`; `deps.by_name`, `declared_changes`, `undeclared`.
- Fixtures `forbidden-path` and `invariants-pass`; `api-break` and `new-dep` gain a base
  `repro.yml`; `policy-weaken` and the others list their `invariant.result` events.
- Tests: `test_invariants.py` (27), three `test_policy.py` cases, three
  `test_orchestrator.py` cases, `test_deps.py` (1), `test_provision_project.py` (7),
  `test_run_stage.py` (two fixtures and `test_invariants_are_evaluated_when_head_cannot_be_built`).
  pytest 1326 → 1374 (1362 pass and 12 skip on Windows with Docker Desktop stopped).

## Evidence
Through `repro run` (Windows, process sandbox), each fixture's `invariant.result` events:

| Fixture | Results |
|---|---|
| `invariants-pass` | `forbidden_paths` pass, `no_new_dependencies` pass, `public_api_stable` pass; `no_network` and `perf_budget` not evaluated ("evaluated from F03 on") |
| `api-break` | `public_api_stable` fail, citing the `api_diff` evidence of the two breaks |
| `new-dep` | `no_new_dependencies` fail ("new dependencies: six"), citing its `dep_diff` |
| `forbidden-path` | `forbidden_paths` fail, `migrations/0001_initial.sql` |
| `policy-weaken` | `forbidden_paths` pass, `no_network` not evaluated: base's policy, with head's removal of `no_network` not applied |
| head that does not install | `public_api_stable` pass; `no_new_dependencies` fail, citing the `declared` `dep_diff` of the package that does not install; `forbidden_paths` (`migrations/`) fail |

- Every `invariant.result` is `ok`, `fail` or `warn` as its result is pass, fail or not
  evaluated, and its first evidence ID is its own `invariant` evidence (`test_run_stage.py`).
- Pattern errors, verbatim from the tests: `repro.yml:2:40: invariants[0].forbidden_paths[1]:
  '/etc/**': paths are relative to the repository root: no leading /`.
- A review before the PR found three ways a rule could be skipped or pass without evidence;
  each is fixed and tested here: one failed job skipped every invariant (now `after`); a
  dependency declared in `pyproject.toml` went unseen in a project installed from requirement
  files (now compared); `migrations/`, `migrations` and `/migrations/**` matched nothing (now a
  directory match, or an error).
- CI run: linked in the PR.

## Deviations from spec
- The roadmap's "a passing and a failing fixture per invariant": `invariants-pass` passes all
  three; `api-break` and `new-dep` (E05's fixtures) fail theirs, with a base `repro.yml`, and
  `forbidden-path` is new.
- Beyond the invariants, for them to be trustworthy: the orchestrator's `after` (C03), the
  `api` and `deps` jobs running when the tests did not (E05), and the declared metadata read
  for every project kind (D03, E05). The last adds `declared` `dep_diff` evidence beside a
  lock or requirement files, and an `unsupported_project` item for unreadable metadata
  without a lock, on every run, invariants or not.

## Known gaps
- Dependencies that setuptools reads from a requirement file Repro already compares
  (`dynamic`) still count as unread: `no_new_dependencies` is not evaluated, not passed.
- Poetry's own `[tool.poetry.dependencies]` table is not read: without `poetry.lock`,
  `no_new_dependencies` is not evaluated for such a project.
- A head whose project cannot be read at all (a URL requirement) leaves the dependencies
  uncompared: `no_new_dependencies` is not evaluated.
- `public_api_stable`'s `except` patterns are `fnmatch` patterns over dotted paths: `*` crosses
  dots. `forbidden_paths` patterns are case-sensitive, as git's paths are.
- A failed invariant does not change the card's status yet (F04).

## Dependencies added
None.

## Research notes
- PRODUCT.md (the invariants' meaning), ARCHITECTURE §4.6, ADR-0015 §2.
