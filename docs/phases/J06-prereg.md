# J06 — Annotation, κ & label freeze; pre-registration

| | |
|---|---|
| **Stage** | J — Evaluation & research |
| **Status** | paused: prepared; waiting for the owner (the budget, then two people's labels) |
| **Depends on** | J05 |
| **Branch / PR** | `phase/J06-prereg` · [#87](https://github.com/DuhItzAniket/Repro/pull/87) |
| **Started / finished** | 2026-10-18 / — |

## Objective
Two blinded annotators, adjudication, labels frozen and tagged with the analysis config
(roadmap). The labels must come from people. The owner decided (2026-10-18) that this phase
builds everything they need and that the labelling waits for them. Stage J pauses here.

## Scope (what this phase can do without people)
- **The registered analysis, as code, before any data** (`repro_bench.analysis`). It covers:
  - majority of k answers, with UNVERIFIABLE when there is no majority, and the flip rate;
  - catch and false-flag rates on covered items, with coverage and both bounding conversions;
  - exact McNemar, Repro against each baseline, separately on INCORRECT and CORRECT items,
    with UNVERIFIABLE counted as not flagging, and Holm's adjustment;
  - cluster-bootstrap intervals over repositories (10,000 resamples, a fixed seed).

  It refuses a label file whose content no longer matches its lock.
- **The pre-registration** (`docs/paper/PREREGISTRATION.md`): the hypotheses (H1 catch, H2
  false flags, the rest exploratory), what the tag freezes, the analysis choices, the sample
  size rule, the open budget decision, and the owner's freeze checklist.
- **The protocol's header** points at the pre-registration and the tag.

Already built for the people, in J02: the annotation guideline (version 1), the blinded
annotation pages, κ per source, adjudication, the label lock.

## Out of scope
- Labelling, κ and adjudication themselves: people do them.
- The freeze (the tag `prereg-v1`): the owner makes it, after the labels.

## Acceptance criteria
- [ ] AC1 (roadmap): two blinded annotators label S2's batch. *Waiting for people.*
- [ ] AC2 (roadmap): adjudication and κ. *The tools exist (J02); waiting for labels.*
- [ ] AC3 (roadmap): labels frozen and tagged with the analysis config. *The owner tags
  `prereg-v1`.*
- [x] AC4: the analysis is code, tested on hand-worked values, before any data.
- [x] AC5: a pre-registration states what the freeze fixes and how to make it.

## Test plan
| Criterion | Check |
|---|---|
| AC4 | `test_bench_analysis.py`: majority and flips; the exact McNemar p-value for 10 and 2 discordant pairs (158/4096); Holm on three p-values; rates with coverage and both conversions; a reproducible cluster bootstrap; the whole analysis on a small study, from a frozen label file |

---
*Filled in at the end of the phase:*

## What shipped (so far)
- `repro_bench.analysis` and `test_bench_analysis.py` (6).
- `docs/paper/PREREGISTRATION.md`.

## Evidence
- `test_bench_analysis.py` 6 passed: values worked out by hand in its comments.
- CI run: linked in the PR (#87).

## How to try the annotation page now
`python -m repro_bench.groundtruth` writes `items.jsonl` for any sealed patches.
`python -m repro_bench.annotate build --items items.jsonl --annotator A1 --seed calibration
--out A1.html` makes a page that opens in a browser, offline (J02).

## Known gaps
- Everything that needs people or the budget: see the acceptance criteria.

## Dependencies added
None.
