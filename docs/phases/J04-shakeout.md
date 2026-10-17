# J04 — S0 dev set & S1 pilot

| | |
|---|---|
| **Stage** | J — Evaluation & research |
| **Status** | in progress |
| **Depends on** | J02, J03 |
| **Branch / PR** | `phase/J04-shakeout` · PR pending |
| **Started / finished** | 2026-10-18 / — |

## Objective
Shake the pipeline out on real tasks before any study data exists: every system runs on S0
(never reported). Decide what J01 left open. Update the power analysis. Build the
memorisation probe. Size the study against the budget the owner set (Groq's free tier).

## Scope
- **Repro in the task's own image** (engine): the setting `sandbox_image`, pinned by digest.
  - The Docker sandbox runs in that image and `ImageProvisioner` installs nothing. Tests run
    with the image's interpreter: its named conda environment's (`CONDA_DEFAULT_ENV`, as
    SWE-bench-style images have, activated only in root's shell profile), else `python3`.
    That environment's programs come first on `PATH`.
  - The snapshot goes first on the import path. Before any test, each of its top-level
    packages must import from the snapshot. Otherwise the side has no environment
    (UNVERIFIABLE), never a run of the image's installed copy.
- **Long test selections** (engine fix): past 8,000 characters of node IDs, the runner passes
  the IDs' files and writes the IDs to `select.json`. Repro's pytest plugin then keeps exactly
  those tests, in that order (the A2 run reverses it), as its last collection step.
- **S0 tooling** (`bench`):
  - `repro_bench.seed`: LM-Modify-style plausible-but-wrong patches. A locked prompt
    (`seed/1`) asks for one defect class as exact edits to the gold patch's files; `difflib`
    writes the diff. Only seeds tier A finds plausible are kept.
  - `repro_bench.memo`: the memorisation probe, after "The SWE-Bench Illusion". Given the
    repository's name and the issue alone, the model names files and writes code; the
    scores are file recall and 5-gram overlap with the gold patch.
  - `repro_bench.power`: McNemar sample sizes, by the normal approximation and exactly.
- **The bench runner** keeps the card of a run whose job failed. That run still ends with an
  UNVERIFIABLE card.
- **Protocol decisions** (§2, §3, §5, §9), recorded before any S2 data.

## Acceptance criteria
- [ ] AC1 (roadmap): the pipeline runs end to end on S0 (never reported), and what it found is
  fixed or recorded.
- [ ] AC2 (roadmap): the power analysis is updated.
- [ ] AC3 (roadmap): the memorisation probe exists and runs.
- [ ] AC4 (roadmap): the S1 pilot. See Deviations.

---
*Filled in at the end of the phase:*

## What shipped

## Evidence

## Deviations from spec

## Known gaps

## Dependencies added
None.

## Research notes
