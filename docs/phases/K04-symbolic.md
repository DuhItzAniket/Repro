# K04 — Symbolic deep checks

| | |
|---|---|
| **Stage** | K — Expansion backlog |
| **Status** | done |
| **Depends on** | — |
| **Branch / PR** | `phase/K04-symbolic` · [#91](https://github.com/DuhItzAniket/Repro/pull/91) |
| **Started / finished** | 2026-10-18 / 2026-10-18 |

## Objective
CrossHair `diffbehavior` on small pure functions in the blast radius (roadmap): search for an
input on which base's version of a changed function and head's behave differently.

## Scope
- **`repro.symbolic`** and **`repro symbolic --repo --base --head [--json]`** (experimental).
- **Which functions.** A top-level function the change edits, in a Python file present on both
  sides, must be:
  - at most 60 lines;
  - annotated with plain data types only: numbers, text, bytes, `None`, and lists, tuples,
    dicts and sets of them;
  - free of calls that reach the world: files, processes, the network, the clock, randomness,
    `print`, `exec`.

  Methods, decorated functions, generators, coroutines, and functions with `*args` or no
  parameters are left out. Each one left out is listed with why.
- **How:**
  - Head is snapshotted and provisioned as for a run (D03). CrossHair 0.0.111 is added to that
    environment from PyPI; installing it runs no target code.
  - A shim imports head's module and loads base's body of the function into a copy of the
    module's namespace. So the comparison isolates the function's own change: the helpers it
    calls are head's for both.
  - `diffbehavior` runs in the process sandbox, at most 60 s a function (`per_path_timeout`
    2 s, 20 uninteresting iterations).
- **What it says.** A counterexample is reported as `Given: (…)` with each side's answer.
  "none_found" is no difference found within the search's budget, which is not a proof, and
  the report says so. CrossHair's own wording is "functions are likely the same".

## Out of scope
- Evidence on the card: it needs an evidence type in the event schema, a schema change for
  the owner to approve. Until then, the check reports beside the card, like `repro js-run`.
- The blast radius beyond the edited functions themselves.

## Acceptance criteria
- [x] AC1: eligible changed functions are found and checked, and the rest are named with why.
- [x] AC2: a real behavioural difference is found symbolically, with its input.
- [x] AC3: no target code runs outside the sandbox. The tool's install runs none.
- [ ] AC4: the result as card evidence. *Needs a schema change: the owner's decision.*

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_symbolic.py`: module names; every reason a function is left out; the functions a real change edits (unchanged and new ones skipped) |
| AC2 | The shim loads base's body beside head's (10 → 10 against 9). The output is read from CrossHair's real wording. End to end on a tiny repository: head provisioned, CrossHair added, `x > 10` against `x >= 10` found at `x=10` |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.symbolic`, `repro symbolic`.
- Tests: `test_symbolic.py` (21, one of them end to end through CrossHair).

## Evidence
- **End to end**: the change `if x > 10` → `if x >= 10`. CrossHair found `x=10`: base returns
  10, head returns 9. A function calling `print` in the same change was left out, with that
  reason.
- **By hand** (CrossHair 0.0.111, Python 3.13): `x * 2` against `x + x` gave "No differences
  found … functions are likely the same!", exit status 0. The boundary pair took 0.8 s.
- CI run: linked in the PR (#91).

## Deviations from spec
- The roadmap says "in the blast radius". This phase checks the edited functions themselves,
  which the blast radius starts from. Their callers would need the change's own arguments,
  and that is the probes' work (G07).

## Known gaps
- CrossHair's search is bounded: no difference found is not equivalence.
- Base's body runs with head's helpers. A change that edits a helper and its caller together
  checks the caller against head's helper on both sides, and the helper on its own.
- Type annotations decide eligibility: an unannotated function is not checked.

## Dependencies added
None in Repro. CrossHair (`crosshair-tool==0.0.111`, MIT, with Apache-2.0 and PSF-licensed
parts per its LICENSE at that tag) is installed into the target's own environment when the
check runs.
