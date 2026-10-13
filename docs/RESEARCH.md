# Repro — Research Synthesis & Positioning

> Research date: **2026-10-13**. This is the curated summary. The detailed, source-tagged notes
> are in [`research/`](research/README.md), about 560 unique source URLs in all. Re-verify any fact before
> using it in a publication or public claim.

## Method

The research ran as six parallel tracks, each required to cite primary sources:
1. Commercial and open-source landscape.
2. Academic literature.
3. Python engine technology.
4. Agents, standards and transport.
5. Web rendering stack.
6. Evaluation methodology and datasets.

The tracks used AI-assisted web research. Every claim carries a tag:
- **[V]** the primary source was fetched and the claim seen there;
- **[S]** the claim comes from a search snippet or secondary source;
- **[U]** the claim is unverified.

The claims this synthesis relies on most were re-checked against the primary source by the
maintainers: Testora (arXiv 2503.18597), PatchDiff (arXiv 2503.15223) and PR-MCI (arXiv
2601.04886).

**Limits.** The tracks' web-search budget ran out partway through. Later checks used direct
fetches of known URLs. As a result, **discovery of 2025–2026 academic work is incomplete**, and
a very close recent system may exist. Follow-up searches are listed in
[`research/02-literature.md`](research/02-literature.md) and scheduled before paper submission (J10).

## Ten findings that shaped the plan

1. **"AI reviewers read the diff; Repro runs it" is no longer true, so the slogan is retired.**
   - OpenAI's Codex review states that it "executes code and tests to validate behavior".
   - Greptile TREX (June 2026) runs code in a sandbox and attaches logs and traces.
   - Claude ultrareview reproduces each finding in a cloud sandbox.
   - Ito, QA.tech, Qodex and Jazzberry also execute.

   All of these run the **head** side to find bugs. None documents a base-vs-head,
   per-claim verdict. *(research/01 §0, §4)*
2. **Base-vs-head differencing is old, and Repro must say so.** Prior work includes:
   - BERT, behavioural regression testing (Orso & Xie 2008; Jin et al. ICST 2010);
   - DiffGen (2008);
   - shadow symbolic execution (ICSE 2016, TOSEM 2018);
   - PATCH-SIM (ICSE 2018);
   - Collector-Sahab (TSE 2023);
   - PatchDiff (ICSE 2026);
   - **Testora (ICSE 2026)**, which runs generated tests on old and new versions of Python PRs and
     has an LLM classify each difference as intended or unintended from the PR text. This is the
     closest prior work, and Repro will cite it and compare against it.

   *(research/02 §3, research/01 §2.2)*
3. **The defensible novelty is a combination.** No verified source shows a system that does all
   of the following:
   - (N1) a *reference-free, claim-relative* oracle: every base→head delta must be attributed
     to a claim, and every behavioural claim must show up as a delta;
   - (N2) *evidence-constrained* LLM verdicts that cite execution artifacts;
   - (N3) an empirical comparison against diff-only and execution-capable reviewers.

   Software change contracts (FSE 2012, ISSTA 2013, TOSEM 2015) are the conceptual precedent for
   N1, but they need a formal specification written by the developer. *(research/02 gap section)*
4. **Re-running existing tests is not enough.** PatchDiff needed *generated* tests to expose its
   29.6% of divergences. Shadow symbolic execution notes that patch tests "often exercise the same
   behaviour in the old and the new version". As a result, generated differential probes are in
   the plan (E06, G07). *(research/02 §1.3, §3.7)*
5. **Agents tamper with tests.** ImpossibleBench (ICLR 2026) shows frontier models editing or
   deleting tests to pass. Repro therefore diffs test files and runs base tests against head
   (D06). *(research/02 §1.9)*
6. **The claim-mismatch problem is measured, and it is costly.** In 23,247 agent PRs:
   - 1.7% show high message–code inconsistency;
   - the most common type, at 45.4%, is "descriptions claim unimplemented changes";
   - such PRs are accepted at 28.3% vs 80.0% and take about 3.5× longer to merge.

   *(Gong et al., arXiv 2601.04886; verified)*
7. **Flakiness needs a plan, not a few reruns.** In Python, 59% of flaky tests are
   order-dependent, and reaching 95% confidence that a passing test isn't flaky takes about 170
   reruns (Gruber et al., ICST 2021). Repro responds in three ways:
   - it pins seed and order on base and head;
   - it measures noise with an A/A′ base pair (the Diffy idea);
   - it uses a DeFlaker-style check: a newly failing test that executed no changed code is
     likely flaky.

   *(research/02 §5, research/01 §2.2)*
8. **"Network off" needs an OS boundary.** In-process socket guards and audit hooks are
   bypassable, and Python's docs say so. Docker `--network none` is the practical default on
   Windows Home (where Windows Sandbox and Hyper-V are unavailable) and on Linux. Untrusted code
   must not run in a linked worktree, which shares the host repo's `.git`. *(research/03 §6, §8)*
9. **Reusable building blocks save months, and two assumptions were wrong.**
   - Reuse grimp (import graph) and griffe (API breaking changes, with
     `allow_inspection=False`).
   - The original plan to select tests via coverage.py per-test contexts was wrong: those
     contexts are incompatible with coverage's fast `sysmon` core. Repro builds its own
     `sys.monitoring` per-test function map.
   - pytest-testmon compares against the last run, not a base ref, and has been idle for about
     10 months.

   *(research/03 §2–4)*
10. **The benchmark plan had to change.** The changes:
    - SWE-bench Verified is contaminated.
    - Synthetic mutants are valid for sensitivity analysis only (17% of real faults are not
      coupled to any mutant).
    - Some commercial terms of service forbid publishing benchmark results without written
      consent.
    - The headline study therefore uses fresh, post-cutoff SWE-format tasks (SWE-rebench,
      SWE-bench-Live) with agent patches generated for the study, two blinded annotators, and
      paired statistics. Baselines include a CI-only gate and Testora.

    *(research/06; ADR-0010)*

## Landscape summary

| Category | Examples (2026) | Executes? | Base vs head? | Per-claim verdict? |
|---|---|---|---|---|
| Diff-reading AI reviewers | CodeRabbit, Graphite Agent (acquired by Cursor), Qodo 2.x, Copilot code review, Cursor Bugbot, Sourcery, Bito | mostly no (CodeRabbit runs linters and verification scripts in a sandbox) | no | no |
| Execution-capable reviewers | Codex review, Greptile TREX, Claude ultrareview, Ito, QA.tech, Qodex, Jazzberry | yes (head) | no | no (findings, not claim verdicts). QA.tech marks a PR "unverified" when the change was not exercised |
| Behaviour diff products | Meticulous (UI pixels), Signadot / Curtail / Speedscale / Keploy / Diffy (HTTP) | yes | **yes**, at UI or API level | no |
| Agent self-verification | Copilot cloud agent, Codex cloud, Devin, Jules, Cursor agents, Claude Code `/verify` | yes | no | no. Produced by the authoring agent |
| Research prototypes | Testora, PatchDiff, Collector-Sahab | yes | **yes** | Testora: intended/unintended per difference |
| Repro | — | yes (both sides, isolated) | **yes, function level** | **yes**, plus a Missing list |

The market is consolidating quickly:
- Cursor acquired Graphite (Dec 2025).
- Tusk sunset its traffic-replay "verification layer" (Jun 2026).
- Sonar acquired Gitar, Boost Security acquired Korbit, Cisco acquired Galileo, and ClickHouse
  acquired Langfuse.
- Google shut down the consumer Gemini Code Assist GitHub app.

Platform risk is real: "also run base and diff" is a small step for any vendor with a sandbox.
Repro's moat has to be **evidence quality** (trace normalisation, noise control, probes, claim
and missing semantics) and **trust** (local-first, independent, replayable, published
benchmark). *(research/01 §5.5)*

## Demand evidence (verified on primary sources)

- **Volume:**
  - Copilot code review handles more than one in five GitHub code reviews (GitHub, Mar 2026).
  - Copilot's coding agent opened more than 1M PRs between May and Sep 2025 (Octoverse 2025).
- **Trust:**
  - Stack Overflow 2025: 46% distrust AI output accuracy versus 33% who trust it.
  - Stack Overflow 2026: the most common trust condition is "when I can easily verify the
    output" (48%).
  - DORA 2025: AI correlates with higher throughput but lower delivery stability.
- **Review cost:**
  - Faros AI 2025: PR review time up 91% on high-AI teams.
  - LinearB 2026: AI PRs wait 4.6× longer before review.
- **GitHub's guidance** to reviewers of agent PRs (May 2026) includes "Require a new test that
  fails on the pre-change behavior". Repro automates this as F2P evidence.

Vendor-published numbers are marked as such in research/01 §3. They are motivation, not proof.

## Technical findings → decisions

| Finding | Decision |
|---|---|
| `sys.monitoring` callback cost with argument capture is unpublished | Measure first (A08), then budgets (ADR-0005) |
| coverage `sysmon` core cannot do per-test contexts | Own per-test function map (ADR-0005) |
| griffe imports modules unless `allow_inspection=False` | Always disabled on host (ADR-0006) |
| Audit hooks and socket patches are not a sandbox | Layered isolation, Docker default, card states the level (ADR-0004) |
| Linked worktrees share the host `.git` | Target code runs from `.git`-less snapshots |
| uv hardlinks share files with its cache | `--link-mode copy` in sandboxes |
| Agent SDK loads CLAUDE.md, hooks and skills from `cwd`; `allowed_tools` does not restrict | `tools=[]`, `dontAsk`, deny hook, `setting_sources=[]`, scratch `cwd` (ADR-0007) |
| Agent SDK validates structured output as draft-07 | Draft-07 `$ref`-free agent schemas with evidence-ID enums |
| LLM judges show position, verbosity and self-preference bias | Order swap, reference-guided prompts, panel, judge ≠ author model |
| WebGPURenderer is experimental and rejects GLSL; WebGPU reaches about 18% of Linux | three.js `WebGLRenderer` + custom instanced layers (ADR-0008) |
| At ×16 replay, a 1.2 s fade becomes a 75 ms flash (WCAG 2.3.1) | Wall-clock clamping + flash governor (ADR-0011) |
| in-toto supports custom predicates; `actions/attest@v4` signs them | Card as an in-toto attestation export (ADR-0012) |

## Corrections to the original brief

- **The tagline "AI reviewers read the diff; Repro runs it" is retired** (finding 1).
- **arXiv 2601.07189 is a position paper on ML research reproducibility, not a survey.** It
  tabulates 11 ML journals and finds none performs post-publication code verification. It is an
  analogy only, not software-engineering evidence.
- **PaperBench's 21.0% is the best agent's *average replication score*.** It does not mean that
  21% of papers were replicated.
- **The benchmark design is replaced** (ADR-0010). **Docker moves from M7+ to Stage D**
  (ADR-0004). **Selection no longer uses coverage contexts** (ADR-0005).

## Naming note (unchanged; still open)

"Repro" is a common word, used for example by ReproZip and by many repositories named `repro`.
Check PyPI, npm and domain availability before publishing in phase H05. Fallbacks: `repro-dev`,
`reprocheck`, `getrepro`.

## Detailed notes

| File | Scope |
|---|---|
| [01-landscape.md](research/01-landscape.md) | About 55 tools compared, market events, demand statistics |
| [02-literature.md](research/02-literature.md) | About 100 verified papers, novelty argument, RQs, venues, BibTeX |
| [03-engine-tech.md](research/03-engine-tech.md) | `sys.monitoring`, coverage, RTS, static analysis, isolation, uv, git, perf, determinism |
| [04-agents-standards.md](research/04-agents-standards.md) | Agent SDK, judge bias, in-toto/SLSA, SARIF/Checks, CloudEvents, codegen, SQLite, WS |
| [05-web-stack.md](research/05-web-stack.md) | three.js, rendering techniques, WebGPU support, layout, replay, tooling, accessibility |
| [06-evaluation.md](research/06-evaluation.md) | Datasets, SWE-bench harness, bug seeding, statistics, baselines, artifacts, contamination |
