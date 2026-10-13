# ADR-0010: Evaluate on fresh SWE-format tasks against execution-aware baselines

- **Status:** accepted (replaces the original M8 plan: a demo repo, about 30 seeded PRs and a
  diff-only baseline)
- **Date:** 2026-10-13
- **Phase:** A01 (executed in Stage J)

## Context
The original benchmark plan would not support a credible claim in late 2026 (research/01 §5.5,
research/06):
- Execution-capable reviewers already exist: Codex review, Greptile TREX and Claude ultrareview.
  Testora (ICSE '26) published run-old-and-new plus intent classification for Python PRs.
  "Better than a diff-only reviewer" is a necessary result but not a sufficient one.
- Synthetic seeded bugs are valid for sensitivity analysis only. 17% of real faults are not
  coupled to any mutant (Just et al., FSE 2014).
- SWE-bench Verified is contaminated, and models reproduce gold fixes from memory. Fresh,
  post-cutoff tasks are needed: SWE-rebench monthly splits (CC-BY-4.0) and SWE-bench-Live
  (MIT), both of which ship Docker images.
- SWE-bench instances already have the base/head shape: `base_commit` plus agent patch.
  Hidden tests plus the gold patch provide ground truth that Repro must never see.
- Detecting a 10-point difference with McNemar's test (α = 0.05, power 0.8, discordance about
  0.2) needs about 155 incorrect patches. The estimate is in research/06 §4.

## Decision
- **Input contract:** each system gets the repo at base, the diff and the claim text. The gold
  patch, hidden tests, F2P/P2P lists and hints are withheld, enforced in code and tested.
- **Data:**
  - S0 dev set (never reported).
  - S1 pilot on SWE-bench Verified, using PatchDiff and UTBoost labels (reported as
    "contaminated").
  - **S2 main study** on fresh Python tasks with patches we generate (at least 2 scaffolds ×
    at least 2 model families), targeting **≥ 200 adjudicated incorrect and ≥ 200 correct**.
  - S3 exploratory in-the-wild sample from AIDev.
  - S4 synthetic sensitivity.
- **Baselines:** B0 CI-only (existing tests); B1 diff-only LLM; B2 agentic static LLM (read-only
  repo access, no execution); B3 PR-Agent; **Testora** as the academic execution baseline where
  reproducible. Commercial tools appear only with written permission, because some terms of
  service forbid publishing benchmark results.
- **Labels:** automatic tiers (hidden tests plus the full suite; augmented and differential
  tests), then two blinded annotators with Cohen's κ and adjudication. Labels are frozen
  before S2.
- **Statistics:** exact McNemar per baseline with Holm correction, cluster bootstrap CIs, k = 5
  runs per LLM system, flip rate, cost and time. The analysis is pre-registered by tagging the
  config before S2.

## Consequences
Stage J is a substantial piece of work. Annotation, not compute, is the main cost. Docker
images need about 30 GiB for Verified (Epoch's rebuilt images), plus fresh-task images. All
evaluation numbers must be regenerable from scripts and pinned manifests.
