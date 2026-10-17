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
- [x] AC1 (roadmap): the pipeline ran end to end on S0 tasks (never reported); what it found is
  fixed or recorded below.
- [x] AC2 (roadmap): the power analysis is updated (exact McNemar).
- [x] AC3 (roadmap): the memorisation probe exists and ran.
- [ ] AC4 (roadmap): the S1 pilot was not run (see Deviations).

---
*Filled in at the end of the phase:*

## What shipped
- **Engine:**
  - the `sandbox_image` setting (`REPRO_SANDBOX_IMAGE`), pinned by digest;
  - `ImageProvisioner`;
  - `DockerSandbox.python_path` and `.variables`;
  - long selections through `select.json` and the plugin's `pytest_collection_modifyitems`.
- **Bench:**
  - `repro_bench.seed` (prompt `seed/1`), `repro_bench.memo` (prompt `memorisation/1`) and
    `repro_bench.power`;
  - the runner keeps a failed run's card.
- **Docs:**
  - ARCHITECTURE §8 (an image's own environment, and its trust boundary);
  - the engine README's settings and troubleshooting;
  - protocol §2, §3, §5 and §9.
- **Tests:**
  - new: `test_provision_image.py` (12, two of them in real containers), `test_bench_power.py`
    (4), `test_bench_memo.py` (3), `test_bench_seed.py` (7);
  - added to existing files: the selection file (`test_pytest_plugin.py`) and the failed run's
    card (`test_bench_swe.py`).

## Evidence
**S0 shake-out** (SWE-rebench leaderboard 2026_03, each task in its own image pinned by
digest; never reported):
- **`pypa__twine-1309`**, Repro in the image on the three J02 patches. After the fixes below,
  every side provisioned from the image's conda environment (Python 3.13.13, 36
  distributions), 3 tests were selected, and every card was UNVERIFIABLE. Two of the three
  tests fail when run after `test_no_color_exception`. Repro's second base run (A2, the
  selection reversed) caught that. Confirmed by hand in the image: 3 passed in one order, 2
  failed in the other.
- **`delgan__loguru-1451`**, the gold patch:
  - **Tier A:** PLAUSIBLE (resolved; a full suite of 1,588 tests kept).
  - **Tier B:** no source given, so NEEDS_REVIEW, as designed.
  - **Repro in the image:** 889 tests selected, 1,397 s, UNVERIFIABLE. The traced calls of
    `Handler.emit` differed between base's two runs in 880 tests. Its arguments are log
    records carrying times, so the changed function's behaviour could not be compared.
- **Faults found and fixed:**
  - **The image's `python` was conda's base interpreter** (3.12, without the project). The
    task's environment is activated only in root's shell profile. The provisioner now uses
    the named conda environment and puts its programs first on `PATH`.
  - **889 node IDs passed Windows' 32,767-character command line** (`WinError 206`), and
    every test step failed. Long selections now go through `select.json`.
  - **The bench runner dropped the card of a run whose job had failed.** That run still ends
    with an UNVERIFIABLE card, which is now kept.

**Power** (`python -m repro_bench.power`): at p_d 0.2 and a 10-point difference, the normal
approximation gives 155 incorrect patches (research/06 §4) and the exact test 168. The full
table is in the module's output. The protocol's 200 covers both.

**Memorisation probe**, live, on seeded random samples of five tasks each (seed `j04-memo`).
Calls that timed out on Groq are excluded, not scored as zero.

| Sample | Answered | Named a gold code file | Mean 5-gram overlap |
|---|---|---|---|
| SWE-bench Verified | 3 of 5 | 3 of 3 | 0.23 |
| SWE-rebench 2026_03 | 3 of 5 | 1 of 3 | 0.03 |

From `django__django-13410`'s issue alone, the model named `django/core/files/locks.py` and
reproduced 69% of the fix's 5-grams. Three answers per sample are a smoke test, not a result.

**Seeding**: see below.

**Budget against the free tier.** Measured tokens per patch on `openai/gpt-oss-120b`:

| Use | Tokens per call | Source |
|---|---|---|
| Repro's agents | 24,138 per PR | G09, 5 PRs |
| B1 | 1,677–1,800 in, 574–1,364 out | J03, 3 patches |
| B2 | 18,826–25,685 in, without finishing | J03 |
| Written differential tests | 2,455–2,574 in, 1,041–2,833 out | J02 |
| Memorisation probe | 449–802 in, 160–628 out | J04 |

Groq's limits for this model, as its response headers state them: 1,000 requests a day and
8,000 tokens a minute. Groq's rate-limit page lists 200,000 tokens a day for it [console.groq.com/docs/rate-limits,
checked 2026-10-18; the page's layout leaves unclear which plan that row is for]. S2 at the
protocol's size is 400 labelled patches, with Repro, B1 and B2 five times each and
differential tests once. That is 248,000 to 266,000 tokens a patch, about 100 million in all,
before PR-Agent and before generating the patches (J05). At 200,000 tokens a day this is
about 500 days. At Groq's list prices on a paid plan ($0.15 per million input tokens, $0.60
per million output; `GROQ_PRICES`, read 2026-10-16) it is $15 if every token were input and
$60 if every token were output. Most are input.

**Locally**: the new tests above passed, with `test_bench_swe.py`, `test_runner_pytest.py`
and `test_config.py`.
- CI run: linked in the PR.

## Deviations from spec
- **No S1 pilot.** It needs SWE-bench Verified's images and harness for tier A (J02's tier A
  reads SWE-rebench's `install_config`), PatchDiff's and UTBoost's patches, and every system
  on about 300 patches. Under the free tier that is months of quota. The power analysis keeps
  the protocol's p_d = 0.2 until a pilot measures it.
- **S0 is three tasks, not about 100 patches.** It was enough to find and fix the faults
  above, which is S0's purpose.

## Known gaps
- **S2 as registered does not fit the owner's budget** (Groq's free tier). The protocol's
  design stands. Running it needs either a paid plan (tens of dollars, above) or a smaller,
  explicitly under-powered study. This is the owner's decision, and J06 records it before the
  freeze.
- **Coverage.** All of S0's Repro cards were UNVERIFIABLE, each for a stated reason: an
  order-dependent suite, and a time-dependent function. How often real tasks end this way is
  RQ-level data for J07. It is the cost of Repro's rule never to call unstable evidence a pass.
- **Compiled extensions.** A task whose code needs building does not import from a bare
  snapshot in image mode. Its card is UNVERIFIABLE and counted.

## Dependencies added
None.

## Research notes
- **Real suites are less deterministic than fixtures.** Of two S0 tasks, one has
  order-dependent tests and the other a changed function whose arguments carry the time. The
  reversed second run of base (A2) caught both. A reviewer that runs each test once, in one
  order, would have compared what it could not trust.
- **The task's image is part of the task.** Its environment is reachable only as its own
  scripts reach it (a conda environment activated in a shell profile). A tool that runs "in
  the image" without that runs other code.
- **The exact test needs about 8% more patches than the approximation** at the protocol's
  assumptions (168 against 155).
