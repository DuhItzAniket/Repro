# J10 — Paper writing & submission

| | |
|---|---|
| **Stage** | J — Evaluation & research |
| **Status** | paused: draft prepared; results, review and submission wait |
| **Depends on** | J08 |
| **Branch / PR** | `phase/J10-paper` · PR pending |
| **Started / finished** | 2026-10-18 / — |

## Objective
Paper drafting from `docs/paper/`, internal review, submission (roadmap). The owner decided
(2026-10-18): "I prepare, you submit". This phase writes the draft and the checklist. The
results, the internal review and the submission wait for J07–J08 and the owner.

## Scope
- **`docs/paper/draft.md`, draft 0**:
  - the problem, with sources;
  - related work, differentiated: BERT, PATCH-SIM, PatchDiff, change contracts, PR-MCI,
    Testora;
  - the system as built, from ARCHITECTURE: snapshots and isolation, selection and outcomes,
    function-level behaviour, the other checks, claims and evidence-constrained verdicts, the
    card;
  - the registered evaluation design;
  - the S0 observations, marked as not results;
  - threats, availability, and the AI-assistance disclosure.

  Every citation is a key of `references.bib`; a script checked that none is missing.
- **Six references added** to `references.bib`, each checked on 2026-10-18: SWE-rebench and
  Agentless (arXiv's API), McNemar, Cohen and Connor (Crossref), Holm (several references).
- **`docs/paper/SUBMISSION.md`**: the owner's checklist (venue, call for papers,
  anonymisation, citations, internal review, artifact).

## Acceptance criteria
- [x] AC1: a draft written from `docs/paper/`, with no claim beyond the evidence.
- [ ] AC2: results in it. *After J07–J08.*
- [ ] AC3: internal review. *Someone who has not worked on Repro.*
- [ ] AC4: submission. *The owner.*

---
*Filled in at the end of the phase:*

## Evidence
- All 23 citation keys in the draft resolve in `references.bib`.
- CI run: linked in the PR.

## Deviations from spec
- Drafted before J07–J08, by the owner's decision to prepare while Stage J waits.

## Dependencies added
None.
