# Pre-registration: Repro's evaluation on fresh agent patches (S2)

> **Status: prepared, not frozen** (J06, 2026-10-18). The owner freezes it by the checklist at
> the end. The freeze is a git tag, `prereg-v1`, on the commit that adds the frozen label file.
> No system runs on S2 before that tag exists. After it, every change is a dated amendment at
> the end of the relevant document.

## What is registered
The study is the one [`EVALUATION_PROTOCOL.md`](EVALUATION_PROTOCOL.md) describes, as these
documents and this code state it at the tag:

| Part | Where |
|---|---|
| Design, data, labels, systems, metrics, threats | `docs/paper/EVALUATION_PROTOCOL.md` |
| Each baseline's input and answer rule | `docs/paper/BASELINES.md` |
| How people label | `docs/paper/ANNOTATION_GUIDELINE.md` (version 1) |
| The analysis, as code | `bench/src/repro_bench/analysis.py` |
| Every prompt, by its locked digest | `bench/src/repro_bench/prompts/lock.json`, `engine/src/repro/agents/prompts/lock.json` |
| S2's candidate tasks | `bench/data/s2-candidates.jsonl` (351 tasks, dataset revision `34d5a588`) |
| Repro itself | the release the tag is on, with its configuration (sandbox image per task, agents on Groq `openai/gpt-oss-120b`) |

## Hypotheses (confirmatory)
On S2's adjudicated patches (UNCERTAIN left out):
- **H1 (catch).** Repro flags INCORRECT patches more often than each baseline (B0 CI-only, B1
  diff-only reviewer, B2 agentic static reviewer, B3 PR-Agent). The test is exact McNemar,
  two-sided, α = 0.05, Holm-adjusted across the four baselines.
- **H2 (false flags).** On CORRECT patches, Repro's false-flag rate does not differ from each
  baseline's, under the same test. A significant difference in either direction is reported as
  found.

Everything else is exploratory and reported as such: the ablations (RQ2), grounding and
stability (RQ3), noise (RQ4), cost (RQ5), and in-the-wild behaviour (RQ6). These RQs are
those of `docs/paper/README.md`.

## Analysis choices fixed here
These follow `analysis.py`, which is tested against hand-worked values
(`engine/tests/test_bench_analysis.py`):
- **k = 5 runs per LLM system and patch**, reduced to their majority status. Without a
  majority the patch is UNVERIFIABLE for that system. The flip rate is the share of patches
  whose five answers differ.
- **Primary rates** are on covered patches (answer not UNVERIFIABLE), always reported with
  coverage and with both bounding conversions (all UNVERIFIABLE as FLAGGED; all as VERIFIED).
- **In McNemar's test an UNVERIFIABLE answer is "not flagged"**: a miss on an INCORRECT patch,
  no false flag on a CORRECT one. This is the conservative reading for a system that often says
  it cannot tell. Repro is such a system (J04).
- **95% intervals** come from a cluster bootstrap over repositories: 10,000 resamples, seed
  20261018.
- **Stratification** (reported, not tested): plausible (tier A PLAUSIBLE) against test-failing
  patches, defect class, repository, patch size, and the memorisation probe's score.

## Sample size and what happens with fewer patches
The target is ≥ 200 INCORRECT and ≥ 200 CORRECT adjudicated patches (protocol §3). The exact
test needs 168 INCORRECT patches for power 0.8 at discordance 0.2 and a 10-point difference
(`python -m repro_bench.power`). If the study ends with fewer, it is reported as
under-powered, with the power achieved at the observed discordance. No patch is added after a
system has answered on S2.

## Budget (decided at the freeze)
At J04's measured token counts, S2 at this size is about 100 million tokens before patch
generation: about 500 days of Groq's free tier, or $15 to $60 at its list prices on a paid
plan. The freeze records which of the following was chosen:
- [ ] a paid plan, and the study as registered; or
- [ ] a smaller study on the free tier, stated as under-powered, with its size and power fixed
  here before any system runs.

## Freeze checklist (for the owner)
1. Decide the budget above, and tick it.
2. Generate S2's patches (`python -m repro_bench.generate`, both scaffolds, both model
   families; J05's record says what the free tier allows). Seal them (`python -m
   repro_bench.swe seal`).
3. Run the ground-truth tiers (`python -m repro_bench.groundtruth`).
4. Two annotators (pseudonyms A1, A2) first label a calibration batch of about 10 S0 items
   together, which is never counted. Then each labels the batch alone, from their own page
   (`python -m repro_bench.annotate build`).
5. Compute agreement (`python -m repro_bench.labels kappa`), adjudicate disagreements, and
   write the final labels with their lock (`python -m repro_bench.labels adjudicate`).
6. Commit the labels, their lock and this file with the budget ticked, then tag the commit
   `prereg-v1`. Only then do the systems run (J07).

## Amendments
_None yet._
