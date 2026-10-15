# F01 — `repro.yml` schema & loader

| | |
|---|---|
| **Stage** | F — Policy & deterministic card |
| **Status** | in progress |
| **Depends on** | A04 |
| **Branch / PR** | `phase/F01-policy` · PR pending |
| **Started / finished** | 2026-10-15 / — |

## Objective
Give a repository a way to state what its changes must keep, in a file Repro reads from the
**base** ref, with errors precise enough to fix the file from the message alone; and catch a
change that edits that file to loosen the rules it is judged by.

## Scope
- **Schema** (`engine/src/repro/policy/repro-yml.schema.json`, JSON Schema 2020-12): PRODUCT.md's
  MVP set (`invariants`: `public_api_stable`, `no_new_dependencies`, `no_network`,
  `perf_budget`, `forbidden_paths`; `claims.require_explicit`;
  `missing.max_uncovered_changed_symbols`), an optional `version: 1`, defaults.
- **Loader** (`repro.policy.load`): PyYAML's safe loader, one document, UTF-8, at most 64 KiB,
  anchors and aliases refused, duplicate keys refused, each invariant at most once; every
  schema error with its file, line, column and path.
- **Weakening** (`repro.policy.weakenings`): an invariant removed or switched off, an `except` or
  `allow` list grown, a performance budget or the uncovered threshold raised, a forbidden path
  dropped, `require_explicit` turned off.
- **The `policy` job** (build stage, `repro.policy.stage`): base's file read from git; no file:
  the defaults (no invariant); an invalid one: no policy, and an `unsupported_project` item
  listing the issues; head's addition, removal or edit: `policy_change` evidence with what it
  would weaken. Head's file is never applied. `RunState.policy` for F02–F04.
- **Fixture** `policy-weaken`.

## Out of scope
- Evaluating the invariants (F02, F03); the status the change gets for a weakening (F04); the
  card (F05).

## Design notes
- **Read from base, compared with head.** The file a PR edits cannot change how the PR is
  judged (ARCHITECTURE §12, THREAT_MODEL T9); its edit is evidence instead.
- **An invalid policy is no policy, not the defaults.** Silently falling back would turn a
  typo in an invariant into "no invariant" and a pass; instead nothing is evaluated and the
  card says why, with each issue's line.
- **Untrusted YAML, bounded.** The file comes from the target repository: the safe loader
  constructs no Python objects from tags; aliases are refused because a few lines of them can
  expand without bound in whatever walks the result; the size is capped and deep nesting is
  refused.
- **Messages for people.** jsonschema's own words for `oneOf` and unknown keys are replaced by
  the closest alternative's message and the list of known keys.
- **PyYAML.** Python has no YAML parser in its standard library and the docs name `repro.yml`;
  PyYAML is the reference implementation for Python, MIT-licensed, with wheels for every
  supported Python, and its composer keeps each node's line and column, which the errors need.

## Acceptance criteria
- [x] AC1 (roadmap): invalid configs give actionable errors.
- [x] AC2 (roadmap): policy weakening in head is flagged.
- [x] AC3: the policy is read from base, never head; PRODUCT.md's example loads as written.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_actionable_errors` (13 cases, each with the exact message), `test_every_issue_at_once`, `test_untrusted_input_is_bounded`, `test_an_invalid_base_policy_is_no_policy` |
| AC2 | `test_weakenings`, `test_a_stricter_policy_is_no_weakening`, `test_head_removes_the_policy`; `test_a_run_reproduces_the_fixture[policy-weaken]` (`policy_change` with "no_network removed", base's two invariants in force) |
| AC3 | `test_products_example_loads`; the `policy-weaken` run logs base's invariants |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.policy`: `repro-yml.schema.json`, `load`, `Policy`, `Invariant`, `PolicyIssue`,
  `PolicyError`, `weakenings`; `repro.policy.stage`: `read_policy`, `PolicyRead`,
  `PolicyChange`, `file_at`.
- The `policy` job (build stage); `RunState.policy`.
- Fixture `policy-weaken`; `test_run_stage.py` names `policy_change` evidence and checks the
  policy in force.
- Tests: `test_policy.py` (26). pytest 1297 → 1326 (1314 pass and 12 skip on Windows with
  Docker Desktop stopped).

## Evidence
- AC1: the errors a person gets, verbatim from the tests:
  `repro.yml:2:5: invariants[0]: unknown key 'no_netwrk' (known: forbidden_paths, no_network,
  no_new_dependencies, perf_budget, public_api_stable)`;
  `repro.yml:2:36: invariants[0].perf_budget.max_regression: 0 is less than or equal to the
  minimum of 0`; `repro.yml:2:1: duplicate key 'claims'`;
  `repro.yml:1:4: anchors and aliases are not allowed`; a file with three mistakes reports all
  three at once. Files over 64 KiB, not UTF-8, or nested 5,000 deep are refused.
- AC2: `policy-weaken` through `repro run`: the log reads "policy (repro.yml on base):
  invariants no_network, forbidden_paths" (base's, in force), and head's edit is
  `policy_change` evidence with `weakened: ["no_network removed"]`. Every kind of weakening is
  named (`test_weakenings`), and a stricter policy gives none.
- AC3: PRODUCT.md's example loads as written, and its document reads back as the same policy.
- CI run: linked in the PR.

## Deviations from spec
- ROADMAP F01 says "a head-side policy change becoming a gap item": it is `policy_change`
  evidence now (the schema's evidence type for it); the status it gives the change is F04's.
- An optional `version: 1` key, not in PRODUCT.md's example, so the format can change later.

## Known gaps
- The invariants are read, not yet evaluated (F02, F03).
- Only `repro.yml` at the repository's root is read (not `.repro.yml` or `repro.yaml`).

## Dependencies added
- PyYAML ≥ 6.0.3 (MIT; 6.0.3 uploaded 2025-09-29, wheels for CPython 3.12+ on Windows and
  manylinux), https://pypi.org/project/PyYAML/6.0.3/ **[V]** 2026-10-15 (PyPI JSON API).
- `types-PyYAML` 6.0.12.20260906 (Apache-2.0), development only, for mypy.
- `jsonschema` (already locked through `repro-events`), now declared by the engine.

## Research notes
- PRODUCT.md's `repro.yml` (MVP invariant set); ARCHITECTURE §12; THREAT_MODEL T9.
