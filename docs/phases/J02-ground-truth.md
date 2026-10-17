# J02 — Ground-truth pipeline & annotation tooling

| | |
|---|---|
| **Stage** | J — Evaluation & research |
| **Status** | in progress |
| **Depends on** | J01 |
| **Branch / PR** | `phase/J02-ground-truth` · PR pending |
| **Started / finished** | 2026-10-18 / — |

## Objective
Every (task, patch) pair gets a ground-truth label by the protocol's procedure
(`docs/paper/EVALUATION_PROTOCOL.md` §4): two automatic tiers run in the task's own
environment, then two blinded annotators for what the tiers cannot settle, with κ,
adjudication and a frozen label file.

## Scope
- **Tier A** (`repro_bench.truth`): the hidden tests and the full suite in the task's image.
  - The task's image is SWE-rebench's `docker_image`, pinned by digest (J01).
  - Each run is a fresh container, `--network none`, with memory and PID limits. Nothing is
    mounted: patches go in base64-encoded in the script on standard input.
  - The command is the task's own `install_config.test_cmd`. The full suite is that command
    without the test patch's files.
  - A full-suite regression (passes with gold, not with the candidate) counts only if it holds
    over 3 reruns of both sides.
- **Grading**: SWE-bench's semantics, reimplemented [SWE-bench `swebench/harness/grading.py` and
  `log_parsers/python.py` at 02e7a74, 2026-09-02, MIT]:
  - test statuses come from pytest's `-rA` summary, IDs cut at the first space as SWE-bench
    cuts them;
  - a missing test is failed; a skipped FAIL_TO_PASS does not resolve; a skipped PASS_TO_PASS
    is kept;
  - an ID cut inside its brackets matches the IDs it starts when they agree;
  - a log with no result and no sign the suite ran, or a non-zero exit with no failure, is
    invalid, not a pass.
- **Tier B** (`truth.differential`): a test source runs against the gold patch and the
  candidate, 20 times each, as PatchDiff did [research/06 §4]. A test counts only when its
  outcome is the same in every rerun on both sides; a counted test whose outcome differs is a
  divergence. There are two sources:
  - UTBoost's augmented test patches, where the task has them (`truth.utboost_patch`, checked
    to be the same task) [HF `Bertsekas/SWE-Bench_Verified_UTBoost`, MIT, revision
    `4747cce3`];
  - tests written for the task (`repro_bench.difftest`): one locked prompt (`difftest/1`, in
    `bench/src/repro_bench/prompts/` with its own `lock.json`). The model sees the issue, the
    gold patch, the maintainers' tests and the candidate, each in an untrusted block, and
    answers with one pytest module, checked to parse and to hold a test.
- **The pipeline** (`python -m repro_bench.groundtruth`) runs both tiers per task, reusing the
  gold patch's full-suite run, and writes two files:
  - `truth.jsonl`: each tier's verdict and evidence, the automatic label, and the tokens spent;
  - `items.jsonl`: the annotators' batch. It holds every patch the tiers could not settle,
    plus a reproducible 15% of each automatic label.
- **Annotation** (`repro_bench.annotate`): one self-contained HTML page per annotator.
  - Items come from an allow-list (the issue, both patches, the maintainers' tests, the tiers'
    evidence); a batch with any other field, such as a system's verdict, is refused.
  - Each annotator gets their own order (seeded).
  - Task text is shown as text, never as HTML, and cannot leave the page's data block.
  - Answers stay in the browser until exported as JSONL. Annotators are named by pseudonym only.
- **Labels** (`repro_bench.labels`):
  - Cohen's κ, overall and per source, undefined (not 1) when one label is used throughout;
  - adjudication, which needs a resolution agreed by both annotators for every disagreement,
    a different defect class included;
  - reproducible 15% audit samples;
  - the freeze: the final file's SHA-256 beside it, with a check that refuses a changed file.
- **The guideline** (`docs/paper/ANNOTATION_GUIDELINE.md`): the decision rule, the three labels,
  seven defect classes, what each shown piece is evidence of, the procedure, adjudication and a
  calibration round.

## Out of scope
- Labelling itself (J06: two people).
- SWE-bench Verified's own test commands. Tier A needs `install_config.test_cmd` (SWE-rebench),
  so S1's tier A uses the official harness in J04, or the sources' published labels.
- Running at scale (J04, J05).

## Acceptance criteria
- [x] AC1 (roadmap): tier A (hidden tests and the full suite) labels a patch automatically.
- [x] AC2 (roadmap): tier B (UTBoost and PatchDiff-style differential tests against gold).
- [x] AC3 (roadmap): an annotation guideline and a tool.
- [x] AC4 (roadmap): κ computation, checked against a published worked example.
- [x] AC5: annotators cannot be shown a system's output through the tool.
- [x] AC6: the tiers run on a real task in its own image.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_bench_truth.py`: SWE-bench's parsing and resolution rules case by case; tier A's decisions (unresolved, a confirmed regression, a flaky one dropped, no valid result) with a fake container |
| AC2 | Stable/unstable/divergent counting over reruns; UTBoost records checked to be the task's; the pipeline through both tiers |
| AC3, AC5 | `test_bench_labels.py`: a batch field outside the allow-list refused; a task's text cannot close the page's script; per-annotator order; the page checked by hand in a browser (label, move, export) |
| AC4 | Wikipedia's worked example (p_o 0.7, p_e 0.5, κ 0.4); undefined κ; per-source κ; adjudication; audits; the freeze |
| AC6 | SWE-rebench `pypa__twine-1309`, with three hand-written candidates |

---
*Filled in at the end of the phase:*

## What shipped
- `repro_bench.truth`, `repro_bench.difftest` (and the `difftest/1` prompt with its lock),
  `repro_bench.groundtruth`, `repro_bench.labels`, `repro_bench.annotate`.
- `docs/paper/ANNOTATION_GUIDELINE.md` (version 1).
- The protocol (§4): the procedure as built; §2's open question gains the S2 pool's Python
  versions.
- Tests: `test_bench_truth.py` (27), `test_bench_labels.py` (18).

## Evidence
- **A real task in its own image**: SWE-rebench leaderboard `pypa__twine-1309` (split 2026_03;
  image `swerebench/sweb.eval.x86_64.pypa_1776_twine-1309@sha256:0ab70a15…`, 4.5 GB; Python
  3.13). The candidates were written by hand for this check and are never reported:
  - the gold patch: tier A PLAUSIBLE (resolved; the full suite of 226 tests kept), then tier B
    CORRECT_auto (4 written tests, stable over 20 reruns a side, none diverging);
  - a seeded wrong patch (the fallback phrase emptied): INCORRECT_auto, its FAIL_TO_PASS test
    failing;
  - a rewrite with the same behaviour (a lookup with a default, no `try`): PLAUSIBLE, then
    CORRECT_auto;
  - a variant that says "Unknown Status Code": tier A already INCORRECT_auto (the hidden test
    checks the phrase). Tier B on its own also flagged it: a written test diverged.
- **The pipeline** on those three predictions wrote three rows (2 CORRECT_auto, 1
  INCORRECT_auto) and an annotators' batch of 2 (one audit of each automatic label). Writing
  tests cost 2,455 to 2,574 input and 1,041 to 2,833 output tokens per patch on Groq's free
  tier.
- **The annotation page**, built from that batch and used in a browser: a label, a defect class
  and a rationale were kept across items, and the export was the JSONL `labels` reads.
- **Locally**: `test_bench_truth.py` 27 and `test_bench_labels.py` 18 passed, with
  `test_bench_swe.py`'s 18.
- CI run: linked in the PR.

## Deviations from spec
None.

## Known gaps
- **Tier A needs a pytest task with `install_config`** (SWE-rebench). SWE-bench Verified
  instances (S1) carry no test command; J04 uses the official harness or the published labels
  there.
- **Generated tests know the candidate.** The model sees both patches, so its tests can aim at
  a surface difference (one asserted that the candidate's wording does not appear). A
  divergence goes to people, never to a label, for this reason.
- **Few written tests can count.** For one candidate, only one written test was stable on
  both sides. `NEEDS_REVIEW` is used when none is; a low count is reported with the label.
- **The containers run as the image's user (root)** with no network, a memory limit and a PID
  limit. This is acceptable for benchmark tasks and their tests, run by the person running the
  study. It is not Repro's product sandbox (ADR-0004).

## Dependencies added
None.

## Research notes
- **The gold patch is one answer.** The guideline says so explicitly, and tier B never labels
  a divergence: a stable difference in behaviour is evidence for people, not a verdict.
- **The S2 pool fits Repro's interpreter.** In SWE-rebench's leaderboard splits 2025_09 to
  2026_03, 351 of 411 tasks pin Python 3.12 or 3.13, and all use pytest. This informs J04's
  decision on J01's open question.
