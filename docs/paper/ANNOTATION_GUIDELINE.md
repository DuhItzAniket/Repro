# Annotation guideline

> Version 1 (J02, 2026-10-18). Frozen with the protocol before the S2 study (J06); any later
> change is a dated amendment at the end of this file. The procedure it serves is
> [`EVALUATION_PROTOCOL.md`](EVALUATION_PROTOCOL.md) §4.

## What you decide
For each item, one agent-written patch for one task, decide:

> **Would the issue's author accept this patch as fixing the issue without breaking documented
> behaviour?**

Answer with one label:

| Label | When |
|---|---|
| **CORRECT** | The patch fixes what the issue asks for, in the cases the issue names and the cases a careful maintainer would expect from it. It breaks no behaviour the project documents or its tests assert. |
| **INCORRECT** | The issue is not fixed, or only partly; or it is fixed and something documented breaks. Give a defect class (below). |
| **UNCERTAIN** | The evidence does not decide it: the issue is ambiguous about the case where the patch differs from the maintainers' fix, or deciding needs knowledge of the project you do not have. Say what is missing. |

UNCERTAIN is an honest answer, not a failure. Do not force a label. PatchDiff's authors left
51 of 77 manually examined patches uncertain [research/06 §1.2]. The study excludes UNCERTAIN
from its primary metrics and reports what happens when it is counted either way.

## Defect classes (INCORRECT only)
| Class | The patch |
|---|---|
| `incomplete_fix` | fixes some of the cases the issue names, not all |
| `wrong_behaviour` | does something other than what the issue asks for |
| `regression` | fixes the issue but breaks behaviour that worked before |
| `api_break` | changes a public interface (signature, return type, raised error, name) the project documents |
| `edge_case` | fixes the main case but mishandles a boundary or input the issue implies |
| `performance` | is correct but much slower or heavier, in a way the project would reject |
| `other` | anything else: say what in the rationale |

Pick the first class that applies, in this order.

## What you are shown, and how to use it
- **The issue**: the task's problem statement. It is the specification.
- **The candidate patch**: what you judge.
- **The gold patch**: the fix the maintainers merged. It is *one* correct answer, not the only
  one. A candidate that differs from it can still be CORRECT. Use the gold patch to understand
  what the maintainers took the issue to mean.
- **The tests the maintainers added**: they show what the maintainers checked. They can be
  narrower than the issue (passing them is not proof of correctness) or stricter than it (a
  test can reject a valid alternative, e.g. an exact message).
- **The automatic tiers**: what tier A (hidden tests, full suite) and tier B (differential
  tests against the gold patch) found. A divergence means the two patches behave differently on
  some input. It does not mean the candidate is wrong: decide whether that difference matters to
  the issue.

You are **not** shown any reviewer's verdict, Repro's or another system's. Do not look one up.
Do not consult the pull request, the issue's later discussion or the project's later history
online: the item's text and patches are the evidence, the same for both annotators.

## Procedure
1. **Work alone.** Do not discuss items with the other annotator until both of you have
   exported your labels for the batch.
2. Open your page (`A1.html` or `A2.html`); the items come in your own order. For each item,
   read the issue first, then the candidate, then the gold patch and the tests.
3. Choose a label. For INCORRECT, choose a defect class. Write a rationale for every
   INCORRECT and UNCERTAIN, one or two sentences that would let the other annotator see why.
   A rationale for CORRECT is optional.
4. Budget about 10 minutes an item. If an item needs much longer, label it UNCERTAIN and say
   why.
5. Export when the batch is done and hand in the file.

You are named by a pseudonym (A1, A2) in everything the study keeps. The repository is public:
put no names, emails or other personal details in a rationale.

## After both have labelled
- Agreement is computed per source (tier-B divergences, audits of each automatic label) as
  Cohen's κ (`python -m repro_bench.labels kappa A1.jsonl A2.jsonl --sources ...`).
- Each disagreement, including the same label with a different defect class, is discussed by
  both annotators. The label you agree on is recorded with a short note and both pseudonyms.
  If you cannot agree, the item is UNCERTAIN.
- The final labels are written with their SHA-256 (`... adjudicate ... --out labels.jsonl`)
  and frozen before any system runs on the split.

## Calibration
Before the S2 batch, both annotators label a calibration batch of about 10 S0 items together,
discussing as they go. Calibration labels are never reported or counted in κ.

## Amendments
_None yet._
