# Research log

Append-only and dated. Record observations, decisions with research impact, measurements,
surprises and negative results. Link the phase record and any artifacts. Never rewrite an
entry. If something turns out wrong, add a correcting entry.

---

## 2026-10-13 · A01 · Research baseline

- Ran six research tracks (landscape, literature, engine technology, agents and standards, web
  stack, evaluation). Notes are in `docs/research/` with verification tags.
- **Positioning change.** Execution-capable AI reviewers already exist (Codex review, Greptile
  TREX, Claude ultrareview). Base-vs-head differencing has long prior art (BERT, PATCH-SIM) and
  recent agent-specific work (PatchDiff, **Testora**, both ICSE 2026). The novelty claim moved to
  the combination: claim-relative explained-delta oracle, evidence-constrained verdicts, Missing
  inventory, and a comparative study.
- **Design changes driven by the literature:**
  - differential probe generation, because existing tests rarely expose divergences
    (Shadow SE, PatchDiff);
  - test-tampering detection (ImpossibleBench);
  - A/A′ noise control and a DeFlaker check (Gruber et al.: 170 reruns for 95% confidence);
  - order-swap stability checks for verdicts (Wang et al. ACL 2024; CodeJudgeBench).
- **Evaluation redesign** (ADR-0010): fresh post-cutoff tasks, a CI-only baseline, Testora as
  the academic baseline, two blinded annotators, exact McNemar, k = 5.
- **Corrections to the original brief:** arXiv 2601.07189 is a position paper, not a survey.
  PaperBench's 21.0% is an average replication score.
- **Spot-checked on arXiv by the maintainers:**
  - Testora: sole author M. Pradel; ICSE 2026 per the arXiv comment.
  - PatchDiff: Wang, Pradel, Liu; DOI 10.1145/3744916.3764576.
  - PR-MCI: Gong et al.; 23,247 PRs; 45.4% "claim unimplemented changes".
- **Known gap:** literature discovery for 2025–2026 is incomplete (search budget exhausted). A
  follow-up search is needed before J10.
