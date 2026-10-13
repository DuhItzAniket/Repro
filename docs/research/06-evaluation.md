<!-- Research notes compiled 2026-10-13 with AI-assisted web research and reviewed by the maintainers. Every claim carries a verification tag ([V]/[S]/[U]); re-verify against the primary source before citing in publications. -->

# Research 6: Evaluation methodology and datasets for Repro

Accessed: 2026-10-13. Scope: how to evaluate Repro (execution-based verification of agent-authored PRs) to a standard that would hold up in a paper.

**Tag legend.** **[V]** means I fetched the primary source this session (arXiv abstract or HTML, GitHub repo or API, Hugging Face dataset API or card, official docs, the vendor's own ToS). **[S]** means the fact comes from a search snippet or a secondary source. **[U]** means I did not verify it this session; it is standard knowledge or my own inference. **[calc]** marks my own arithmetic from stated assumptions. That arithmetic is not a sourced fact.

**Process note.** Partway through, the shared web-search budget ran out, so later facts were checked only by direct fetches of known primary URLs. Three classic statistics references (Cohen 1960, Landis & Koch 1977, Efron 1979) were **not** re-verified and are tagged [U]. A few primary pages returned HTTP 403: openai.com and acm.org. Facts from those pages are tagged [S].

---

## 1. Existing datasets of labelled correct vs incorrect Python patches

### 1.1 The key framing: SWE-bench is already a base/head triple

Every SWE-bench-style instance has a `base_commit`, a gold `patch`, and a hidden `test_patch` with `FAIL_TO_PASS`/`PASS_TO_PASS` lists [V, HF API features for princeton-nlp/SWE-bench]. An agent's prediction is `{instance_id, model_name_or_path, model_patch}` [V, SWE-bench evaluation guide]. For Repro this maps as follows:

- **base** = `base_commit`.
- **head** = `base_commit + model_patch`.
- **Ground-truth oracle (hidden from Repro)** = `test_patch` + gold `patch` + the full developer test suite.
- **Claim** = the issue text (`problem_statement`), plus the agent's own final summary when a trajectory exists.

"Resolved" in the harness means every FAIL_TO_PASS test passes and every PASS_TO_PASS test is maintained. That is `get_resolution_status` → FULL only if `f2p == 1 and p2p == 1`. A skipped F2P test counts as "not a resolution", and an empty status map counts as "invalid, not a pass" [V, `swebench/harness/grading.py` on main]. So the harness gives a free, deterministic, *but weak* incorrectness label. The weakness is documented below (PatchDiff, UTBoost, SWE-bench+, OpenAI audit).

### 1.2 Dataset inventory

| Dataset | Size | Language / tests | License (as verified) | Labels relevant to Repro | Env / Docker | Usability for Repro |
|---|---|---|---|---|---|---|
| **SWE-bench (full)** | test 2,294; dev 225; train 19,008 [V HF API]; 12 Python repos [V arXiv 2310.06770] | Python; mostly pytest, with some repos (e.g., Django, Sympy) using their own runners [U] | **HF card declares no license** [V]; GitHub repo is MIT [V] | Gold patch + F2P/P2P | Per-instance images, 3-layer (base / ~60 env / instance) [V docs] | Good source of instances; older and contaminated (see §7) |
| **SWE-bench Lite** | test 300, dev 23 [V HF API] | Python | No license on HF card [V] | Same | Same | Many leaderboard predictions exist; UTBoost relabels [V] |
| **SWE-bench Verified** | 500 [V HF API] | Python | No license on HF card [V] | Human-screened: 93 Python developers, 1,699 samples annotated, 0–3 severity scale [S, OpenAI post 403 → snippet]; 3 annotators per sample [S, Epoch] | Same; Epoch's optimized images are **30 GiB for all 500** [V] | Best-studied; PatchDiff and UTBoost labels exist. **OpenAI stopped reporting it in Feb 2026** over flawed tests and contamination [S] |
| **SWE-bench Multimodal** | dev 102, test 510 [V HF API]; paper says 617 instances from 17 JS libraries [V arXiv 2410.03859] | **JavaScript** | No license on card [V] | — | — | Out of scope (not Python) |
| **Multi-SWE-bench** | 1,632 instances; 7 languages: Java, TS, JS, Go, Rust, C, C++ [V arXiv 2504.02605] | **No Python** [V] | not checked | — | — | Out of scope for the first target language |
| **SWE-Gym** | 2,438 instances, 11 Python repos [V HF + arXiv 2412.21139] | Python | MIT [V HF] | Executable tasks; released trajectories with `resolved` flag: `SWE-Gym/OpenHands-Sampled-Trajectories`, 6,055 rows, `test_result.git_patch` + `report` [V HF API; no license field] | Yes | Source of agent patches labelled pass/fail by hidden tests; the trained "verifier" is a related baseline idea [V abstract] |
| **SWE-smith** | 50k instances from 128 repos (paper) [V]; HF train split 59,136 rows vs card text "50137" [V, discrepancy on card] | Python | MIT [V HF] | Synthetic bugs that break ≥1 passing test | One image per repo; ~295 GB total vs 50–150 TB for SWE-bench-style per-instance builds [V paper] | Bug-seeding pipeline (§3); trajectories `SWE-bench/SWE-smith-trajectories` with `resolved` bool, MIT [V HF API] |
| **SWE-rebench** | test 21,336; filtered 6,542 [V HF API] | Python | **CC-BY-4.0** [V HF] | F2P/P2P, plus LLM-predicted quality metadata (clarity, complexity, test-patch correctness; accuracies 79/81/67%) [V paper HTML] | Install recipes; leaderboard problems have Docker images [V swe-rebench.com news] | **Primary fresh source.** Leaderboard dataset `nebius/SWE-rebench-leaderboard` has monthly splits 2025_01 … 2026_03 (e.g., 2026_01: 48, 2026_02: 57, 2026_03: 110) with `docker_image`/`image_name` fields, CC-BY-4.0 [V HF API]. Site's latest window is 15/05/2026–01/07/2026 (111 problems) [V] |
| **nebius/SWE-agent-trajectories** | 80,036 trajectories (13,389 resolved / 66,647 not) [V HF] | Python (SWE-bench-extra + SWE-bench dev) | CC-BY-4.0; model outputs subject to the Llama 3.1 license [V] | `target` (resolved) + `generated_patch` + `eval_logs` | via SWE-bench-extra | Large pool of *test-failing* (incorrect) agent patches; resolved ones are "plausible" only |
| **nebius/SWE-rebench-openhands-trajectories** | 10K–100K rows (67,074 per a search snippet [S]) | Python | CC-BY-4.0 [V] | trajectories | — | Same use; one scaffold and one model family |
| **SWE-bench-Live** | test 1,000; lite 300; verified 500; full 1,888 [V HF API, lastModified 2026-09-04] | Python for lite/verified/full; a Feb 2026 update added C/C++/C#/Java/Go/JS/TS/Rust and a Windows dataset [V site] | MIT [V HF] | F2P/P2P | Instance images on Docker Hub, `starryzhang` namespace [V GitHub] | **Second fresh source.** The `test` split receives new issues [V site]. Since Aug 2026 the leaderboard requires trajectories [V] |
| **SWE-bench Pro** | 1,865 tasks / 41 repos; public 11 repos, held-out 12, commercial 18 [V arXiv 2509.16941]; HF: default 642, v1 731, hard 51 [V HF API] | Multi-language (Python, JS, TS, Go per secondary [S]) | No license on HF card [V]; public set drawn from copyleft (GPL) repos [S] | F2P/P2P, `docker_image` field [V] | Yes | Contamination-resistant by design, but copyleft code needs care when redistributing. A follow-up "SWE-Bench Pro Verified" (arXiv 2609.08149) reports leakage and flawed tasks [V abstract] |
| **PatchDiff study data** (Wang, Pradel, Liu; ICSE 2026 [S researchr]) | 877 plausible patches from CodeStory 311, LearnByInteract 301, OpenHands 265 on SWE-bench Verified; **260 (29.6%) behaviourally divergent**; **77 manually labelled: 22 incorrect, 4 correct, 51 uncertain** [V arXiv HTML v2] | Python | Code on GitHub with **no license file** shown [V]; results on Zenodo 10.5281/zenodo.17074796, **CC BY 4.0**, 40.7 MB 7z (record v3; a newer version exists) [V] | Manual labels by the first author, with a second author consulted on uncertain cases; **no kappa reported** [V] | ~3 GB per instance image; ~200 GB temp; ~420 GB if caching all developer-test results [V README] | **Highest-value existing labels** for "plausible but incorrect". Small (22 certain-incorrect); 66% "uncertain" is a warning about label difficulty |
| **UTBoost** (Yu, Zhu, He, Kang; ACL 2025) | 36 instances with insufficient tests; **345 erroneous patches** labelled passed in original SWE-bench (176 Lite + 169 Verified) [V arXiv HTML]; internal counts not fully reconciled in paper (§4.2 vs §4.3; 23 + 26 instances ≠ 36) [V] | Python | Code **MIT** [V GitHub]; HF `Bertsekas/SWE-Bench_Verified_UTBoost` MIT [V]; Lite variant exists [V] | Augmented tests (`augTest.json`); two authors reviewed to consensus [V] | SWE-bench images | **Use the augmented tests as extra ground-truth oracle.** The repo does not ship a full list of the 345 patch IDs [V]; they must be re-derived by re-running predictions against augmented tests |
| **SWE-bench+** (Aleithan et al. 2024) | Analysed SWE-Agent+GPT-4 patches: 32.67% "solution leakage", 31.08% weak tests; resolution 12.47% → 3.97% after filtering; >94% of issues pre-date LLM cutoffs [V abstract] | Python | not checked | Manual categories | — | Methodological evidence of label noise and leakage; no direct reuse planned |
| **SWE-bench experiments repo** | Entries for lite/verified/multimodal/multilingual/test [V] | — | **No license file visible** [V] | Per-instance `report.json`, `patch.diff`, `test_output.txt.gz`, trajectories. **The repo now holds entries, not artifacts.** Artifacts live in each submitter's public repo, or at `s3://swe-bench-submissions/` for pre-mid-2026 entries, fetched via `python -m analysis.download_logs evaluation/<split>/<entry>` [V] | — | Main source of **many systems' predictions on the same instances**. Licensing per entry is unclear, so cite and re-download rather than redistribute |
| **BugsInPy** | 493 real bugs from 17 Python programs (FSE 2020 demo) [V arXiv 2401.15481] | Python; framework mix [U] | **No license** (GitHub API `license: null`) [V] | Buggy/fixed versions + triggering tests (Defects4J-style) | Dockerfile [V] | Real faults, but *developer* fixes rather than agent PRs. No-license means redistribution is a risk; use as an optional "real-fault" seeding source only |
| **PyTraceBugs** (APSEC 2021) | ~24k buggy / 5.7M correct snippets (secondary) [S] | Python snippets | MIT on a third-party HF mirror [S] | Snippet-level defect labels | No executable env [U] | **Not usable**: no executable before/after programs |
| **PyBugHive** (IEEE Access) | 149 reproducible bugs, 11 projects [S] | Python | not checked | Manually validated | CLI | Small optional real-fault set |
| **AIDev** (Li, Zhang, Hassan) | v4 "AIDev-2.7M": 2,743,854 PRs, 327,477 repos, 159,056 devs, cutoff Nov 2025 (v5 WIP to 31 Mar 2026) [V HF card]. Earlier paper: 932,791 PRs, curated AIDev-pop 33,596 PRs from 2,807 repos >100 stars [V arXiv 2602.09185] | Mixed languages; filter to Python | **CC-BY-4.0**; "each source repository retains its original copyright and license" [V] | PR state (open/closed/merged; 80.5% merged overall), reviews, review comments, commit diffs [V] | None | **The only large real-world agent-PR corpus.** Merge ≠ correctness. Better proxies: reverts (2.66% of agentic PRs contain a reverting commit [S, MSR'26 challenge paper]) or **verified follow-up fixes** (Takerngsaksiri et al. 2026: merged agent PRs draw verified fixes at 1.62× the odds of human PRs; LLM-judge κ = 0.78 vs human–human 0.77) [V arXiv 2609.26847]. Login field present despite "PII removed" [V] |

### 1.3 What this means for Repro

- **No public dataset gives Repro what it needs off the shelf.** That would be agent patches + an NL claim + a reliable correct/incorrect label + an executable env, all post-cutoff. The closest are PatchDiff's labels (small, contaminated, mostly "uncertain") and the trajectory datasets (large, but labelled only by weak hidden tests).
- **Two-tier labels are available almost for free:**
  - (a) patch **fails** hidden F2P/P2P or the full developer suite → *likely incorrect*;
  - (b) patch **passes** → *plausible*, and needs differential testing (PatchDiff-style vs gold) plus augmented tests (UTBoost) plus human labels to separate correct from plausible-but-incorrect.
- The interesting, publishable cases for Repro are in tier (b).

---

## 2. SWE-bench harness infrastructure and reuse for Repro

**How evaluation runs** [V, `run_evaluation.py` and `grading.py` on main]:

1. Pull or build the instance image (`sweb.eval.<arch>.<instance_id>` naming), then create a container named `sweb.eval.<instance>.<run_id>`. It is created with `cap_add=["SYS_ADMIN"]`, needed by browser-sandbox tests [V].
2. Write `model_patch` to `patch.diff` and try in order: `git apply --verbose`, `--3way`, `--reject`, then `patch --batch --forward --fuzz=5 -p1`. The tree is reset (`git checkout -- . ; git clean -fd`) between attempts [V].
3. Run `/eval.sh` (from `test_spec.eval_script`, which applies the test patch and runs the test directives) with a timeout. Output goes to `test_output.txt` [V].
4. Parse logs with repo-specific parsers and grade F2P/P2P → `report.json`. Results are cached by `run_id`/`instance_id` [V].
5. **Networking:** the harness sets no explicit network mode, so containers use Docker's default network [V]. Repro's "network off by default" rule (CLAUDE.md §5) means Repro should launch its own containers from the same images with `network_mode="none"` after build. The harness itself does not do this.

**Reuse for Repro (recommended).**
- Use the per-instance image as the sealed environment. Inside one container (or two from the same image), materialize base = repo at `base_commit` and head = base + `model_patch`. Then run Repro's own selection/tracing over both.
- The instance image already contains the installed environment, and the harness applies patches inside it [V]. The exact repo path inside the image (commonly `/testbed`) is [U]; check it from `test_spec`.
- **Never** let Repro see `test_patch`, gold `patch`, F2P/P2P lists, or `hints_text`. Only the ground-truth stage uses those, and it runs separately and after Repro has emitted its verdict.

**Resources and platforms.**
- Official recommendation: x86_64, ≥120 GB free disk, 16 GB RAM, 8 cores; arm64 experimental; `--max_workers` < `min(0.75·cpu, 24)` [V].
- Cache levels: `none`/`base` ~120 GB during run, `env` (default) ~100 GB, `instance` ~2,000 GB [V docs].
- **Windows:** Docker Desktop with WSL 2, with 8 CPUs / 16 GB / 120 GB disk image [V docs]. The harness code has no Windows-specific handling; only a Linux `resource`/`RLIMIT_NOFILE` guard [V]. **Practical implication:** run Repro's engine and its workers inside WSL2 on the developer's Windows box, or on a Linux VM. Keep Windows-native only for the UI and CLI front end. Test path handling both ways, per CLAUDE.md.

**Smaller images.**
- Epoch AI rebuilt the registry: 67 GiB for 2,290/2,294 images and **30 GiB for all 500 Verified**, at `ghcr.io/epoch-research/swe-bench.eval.<arch>.<instance_id>`. These are MIT-licensed and x86_64; arm64 is best-effort for 1,819 images. Verified ran in 62 min on a 32-core / 128 GB GitHub Actions VM [V].
- LogicStar compressed Verified from 240 GiB (Docker layers) to 31 GiB uncompressed / 5.0 GiB zstd archive via delta layering. Published at HF `LogicStar/SWE-Bench-Verified-Compressed`; license not stated [V blog].

**Other harness-compatible pools.**
- SWE-bench-Live is a fork of the harness, with images in Docker Hub `starryzhang` [V].
- SWE-rebench leaderboard rows carry `docker_image`/`image_name` [V].
- SWE-bench Pro rows carry `docker_image` [V].
- Repro can therefore write **one adapter** for "SWE-bench-format instance + image + model patch" and cover all of them.

**Submission and trajectory policy.**
- The SWE-bench leaderboard requires reasoning traces, one per instance [V].
- Since 2025-11-18, Verified and Multilingual accept only academic or research submissions with an arXiv paper or tech report [V].
- Re-grading without Docker is possible: `swebench submit verify …` [V].

---

## 3. Seeding bugs (synthetic incorrect PRs)

**Rule-based mutation tools (Python).**
- **mutmut:** BSD-3-Clause; v3.8.0 released 2026-09-12; requires Python ≥3.10. It **needs `fork`, so Windows users must use WSL** [V PyPI + GitHub API].
- **cosmic-ray:** MIT; v8.7.0 released 2026-08-09; Python ≥3.9; "OS Independent" [V].
- **MutPy:** last release 0.6.1 on 2019-11-17; classifiers stop at Python 3.7; repo last pushed 2024-04-23. **Effectively unmaintained**, do not use [V].

**LLM-based seeding.**
- SWE-smith's five strategies [V arXiv HTML], with yield and cost per candidate:
  - **LM Modify:** 56.0% yield, 0.38¢.
  - **LM Rewrite:** 35.0%, 3.93¢. It works from header + docstring and is not explicitly asked for bugs.
  - **Procedural AST modification:** 13 transforms, 40.2%, 0¢.
  - **Combine bugs:** 96.9%.
  - **PR Mirror** (invert a real PR): 33.8%, 5.53¢.
- Validation: SWE-smith keeps a candidate only if it breaks ≥1 passing test, with a 2-minute test cap. 50,137 instances cost ≈ $1,360 in total [V].
- Note for Repro: SWE-smith's acceptance criterion (must break a test) **selects exactly the bugs a test-running tool will catch trivially**. For Repro's evaluation, seed bugs where existing tests **still pass**, i.e., the plausible-but-wrong regime. Validate them as wrong with a held-out oracle instead (gold tests, the original behaviour, or human review).
- LLM mutants vs rule-based: on 851 real Java bugs, LLM mutants reached 87.98% real-fault detection vs 41.64% for rule-based approaches. Mutants were "behaviorally closer to real bugs", at the cost of more non-compilable, duplicate and equivalent mutants (Wang et al., arXiv 2406.09843, v5 Jan 2026) [V]. This is Java evidence, so transfer to Python is [U].

**Threats to validity of synthetic bugs.**
- Just et al. (FSE 2014): 357 real faults, 5 Java programs, 321K LOC, 230,000 mutants (Major tool). A coupling effect holds for **73% of real faults**; 10% need a new or stronger operator; **17% are not coupled to mutants at all**. Mutant detection correlates with real-fault detection independently of coverage [V, PDF text].
- Papadakis et al. (ICSE 2018): the mutation-score / real-fault correlation is largely confounded by test-suite size. Once size is controlled, the correlation is weak [S].
- **Implication:** synthetic bugs may be used for **ablation and sensitivity analysis per bug class**. They must not be used for the headline catch rate. The headline must come from real agent patches. Report synthetic results in a separate table and say so explicitly.

---

## 4. Metrics and statistics

**Unit of analysis.** One (instance, agent patch) pair. Ground truth is ∈ {CORRECT, INCORRECT, UNCERTAIN}. Repro's output is ∈ {VERIFIED, FLAGGED, UNVERIFIABLE}.

**Primary metrics** (positive class = INCORRECT):
- **Catch rate** = recall on INCORRECT = P(FLAGGED | INCORRECT).
- **False-flag rate** = P(FLAGGED | CORRECT).
- **Precision** of FLAGGED; F1; optionally MCC, because class balance differs across sources.

**UNVERIFIABLE.** Report the **coverage** (fraction not UNVERIFIABLE) and the metrics on covered items. Also report two bounding conversions: UNVERIFIABLE→FLAGGED (pessimistic for false flags) and UNVERIFIABLE→VERIFIED (pessimistic for catches). CLAUDE.md rule 3 ("never unverified silently") requires that it never be folded into pass. This is selective classification, so a risk–coverage curve is the natural plot [U, standard ML practice].

**Repro-specific metrics.**
- Evidence-citation validity: fraction of agent verdicts whose cited evidence IDs exist and support the verdict, as rated by a human on a sample.
- Missing-item rate.

**Cost metrics.**
- Wall-clock time per PR (median, p90), split into environment, test, trace and LLM phases.
- LLM tokens and $ per PR at list price on a stated date.
- CPU-minutes.
- Report the hardware and OS. Docker-in-WSL2 vs native Linux matters.

**Paired comparison (Repro vs baseline on the same patches).**
- Use **McNemar's test**, exact binomial on discordant pairs. Do this separately on the INCORRECT set (catch rate) and the CORRECT set (false-flag rate).
- McNemar 1947, *Psychometrika* 12(2):153–157, DOI 10.1007/BF02295996 [S].
- Dietterich 1998, *Neural Computation* 10(7):1895–1924: McNemar has acceptably low Type-I error when an algorithm can be run only once [S]. That fits Repro, where each run is expensive.

**Confidence intervals.**
- Use the **cluster bootstrap**: resample instances, or repositories, with all their patches. Patches on the same issue and repo are correlated.
- Miller (Anthropic, arXiv 2411.00640) recommends clustered standard errors when items come in related groups (naive SEs can be badly anti-conservative; clustered adjustment up to ~3×), paired-difference SEs for model comparisons, and averaging multiple samples per item. He warns that temperature should **not** be changed to reduce variance [V].
- Wilson intervals for single proportions [U].
- Efron 1979 for the bootstrap [U, not re-verified].

**Multiple comparisons.** Holm–Bonferroni across the set of baselines and ablations [U, standard].

**Human labels.**
- Use two independent annotators per patch, with Cohen's κ (Cohen 1960 [U]) or Krippendorff's α, plus adjudication by discussion.
- Report κ per label and per source. Landis & Koch (1977, *Biometrics* 33:159–174) bands are [U, not re-verified this session].
- The SIGSOFT IRR supplement makes it *essential* to state what was rated and by how many raters. Use ≥2 independent raters, or justify a single one. Describe how disagreements were resolved, and report an IRR/IRA statistic [V].
- PatchDiff used a single labeller with consultation and reported no κ [V]. Repro's study should do better.

**LLM nondeterminism.**
- Temperature 0 does not guarantee determinism. In code generation, 47.6–75.8% of tasks had zero equal test outputs across requests (Ouyang et al., TOSEM, DOI 10.1145/3697010) [V].
- Run Repro and every LLM baseline **k = 5 times per patch**. Report:
  - (i) mean ± SD of each metric across runs;
  - (ii) the majority-vote verdict;
  - (iii) the **verdict flip rate** (fraction of patches whose verdict changes across runs).
- Use the vendor default or one pre-registered temperature for all systems.
- SWE-rebench uses 5 runs and reports SEM [V]. That is a good precedent.

**Power / sample size** [calc]. For McNemar with α = 0.05 (two-sided), power 0.8, and the usual normal approximation, n ≈ [z₀.₉₇₅·√p_d + z₀.₈·√(p_d − δ²)]² / δ².
- To detect a +20 pp catch-rate gain (p_d = 0.30 discordant) you need ≈ 57 INCORRECT patches.
- To detect +10 pp (p_d = 0.20) you need ≈ 155.
- The same applies to false-flag rate on CORRECT patches.
- **Target: ≥200 adjudicated INCORRECT and ≥200 adjudicated CORRECT patches in the main study**, after excluding UNCERTAIN.

**Empirical-standards checklist** (ACM SIGSOFT Empirical Standards, Ralph et al., arXiv 2010.03525) [V]:
- **Engineering Research (Design Science)**, essentials:
  - empirically evaluate with a named method;
  - compare to state-of-the-art alternatives or justify why not.
  - Anti-patterns: "toy examples", single-group non-repeated evaluation [V].
- **Benchmarking (of Software Systems)**, essentials:
  - justify or define the benchmark (quality, metrics, workload);
  - give a replicable setup;
  - allow fair configurations;
  - use **sufficient repetitions**;
  - discuss **construct validity**.
  - Anti-patterns: tailoring the benchmark to the tool; too few repetitions; persisting only aggregates instead of raw results [V].
- **Repository Mining**, essentials:
  - justified selection and inclusion criteria;
  - define the unit of analysis;
  - for manual annotation, multiple annotators + IRR;
  - external-validity discussion.
  - Desirable: discuss data privacy [V].
- **Supplements:** Inter-Rater Reliability, Open Science, Ethics (Engineering Research), Ethics (Secondary Human Data), Registered Reports, Sampling [V].

---

## 5. Baselines

**Prior practice.**
- Code-review benchmarks evaluate tools by issue *coverage* against human-review ground truth:
  - **SWR-Bench**: 1,000 manually verified PRs; LLM-based evaluation agrees with humans ~90%; multi-review aggregation improves F1 by up to 43.67% (arXiv 2509.01494) [V].
  - **c-CRAB**: converts human reviews into tests; evaluated the open-source **PR-Agent** and commercial **Devin, Claude Code, Codex** reviewers; all together solve ~40% of tasks (arXiv 2603.23448, 2026) [V].
  - **MCR-Bench**: 2,269 multi-round review tasks, ISSTA 2026; "dynamic" there means cross-round state, not execution [V].
- **Patch-correctness assessment (APCA)** from program repair is the closest prior art to Repro's *execution* side:
  - **PATCH-SIM** (Xiong et al., ICSE 2018): test-execution behaviour similarity between original and patched programs, plus generated tests. It filtered 56.3% of incorrect patches out of 139 without discarding correct ones [V arXiv 1706.09120]. It needs no oracle patch, so it is a fair no-oracle comparator.
  - **Invalidator** (TSE 2023): Daikon invariants on buggy vs developer-patched programs plus a syntactic model; 79% of overfitting patches identified, 23% more than the best baseline [V arXiv 2301.01113]. **It needs the developer patch**, so it is an oracle-assisted reference.
  - **PatchDiff**: differential tests vs the gold patch, using gpt-4o-mini at temperature 1 [V]. Also oracle-assisted.
  - **LLM4PatchCorrect/PatchZero** (arXiv 2303.00202): LLM zero-shot APCA, using bug description, traces, failing tests and similar labelled patches; 84.4% accuracy on Java [S].
  - **SWE-Gym verifiers**: trained on agent trajectories to rank them [V abstract].

**Recommended baseline set** (all given the same inputs Repro gets: issue/claim text, diff, repo at base; none get the hidden tests):
- **B0 "CI-only"** (deterministic, cheap): run the repo's existing tests on head (plus any tests the patch adds). Flag on any failure or regression vs base. **Essential.** Without it, a reviewer could argue Repro is "just running tests".
- **B1 "Diff-only LLM reviewer"**: the same model family and token budget as Repro's reviewer agents. Prompt with issue + diff → {VERIFIED, FLAGGED} + rationale. k = 5. Pre-register the prompt in the artifact.
- **B2 "Agentic static reviewer"**: an LLM agent with read-only repo access (grep, open files) but **no execution**. This isolates "execution evidence" from "more context". Repro-without-execution is effectively this.
- **B3 PR-Agent** (open source; **MIT** per GitHub API and repo sidebar [V]). Qodo has donated it to a community "PR-Agent" org [V README]. A secondary source claims a return to Apache-2.0 [S, conflicting], so **re-check the license at the pinned commit**. It supports OpenAI, Anthropic, Gemini and others via LiteLLM [V]. The CLI takes a `--pr_url`, not a raw diff [V], so the study must mirror each patch as a PR on a sandbox Git host. Map its output to flag/not-flag with a pre-registered rule.
- **B4 Commercial reviewers.**
  - **CodeRabbit ToS §4.2(iv)** (updated 2026-04-20) forbids customers to "disclose the results of any benchmarking of the Services" without prior written consent [V].
  - Greptile's terms page returned 404. GitHub Copilot terms were not verified [U].
  - **Do not publish named commercial results without written permission.** Either obtain it, or omit commercial tools and say why.
  - Vendor-run benchmarks (Qodo: 100 PRs / 580 injected issues; Martian; etc.) are self-reported [S] and not comparable.
- **Oracle reference (not a competitor):** PatchDiff-style differential testing vs gold. It shows the ceiling achievable with the answer key and helps build labels.

---

## 6. Reproducibility and artifact evaluation

**ACM badges** (ICSE 2026 AE track, which follows the ACM definitions) [V researchr; the acm.org policy page returned 403]:
- **Artifacts Available**: the artifact is in a public **archival** repository with a DOI. "GitHub alone is not considered archival"; Zenodo, Figshare and Software Heritage are accepted.
- **Evaluated – Functional**: documented, consistent, complete, exercisable.
- **Evaluated – Reusable**: Functional + well-structured for reuse.
- **Results Reproduced / Replicated**: for prior work only.
- Requirements:
  - one README with Purpose / Provenance / Data / Setup / Usage;
  - a LICENSE file;
  - Docker/VM "strongly encouraged", and a container image is *required* for non-trivial tooling;
  - **setup should take ≤30 minutes** of reviewer time [V].
- ACM v1.1 (Aug 2020) swapped the meanings of "Reproduced" and "Replicated" to follow NISO terminology [S].

**What Repro's artifact should contain:**
1. The Repro source at a tagged release, with a Zenodo DOI via the GitHub integration.
2. A Docker/WSL-ready image or compose file for the engine.
3. The **benchmark manifest**: instance IDs, patch source and checksum, image digest, label, label provenance.
4. All **raw event logs**. Repro's replayable event stream (CLAUDE.md rule 2) is a strong reproducibility story: `repro replay <run-id>` regenerates every card without rerunning LLMs.
5. Raw per-run verdicts for every system and repetition. This satisfies the Benchmarking anti-pattern "persist raw results".
6. Annotation guidelines, per-annotator raw labels, adjudication notes, and κ.
7. Analysis notebooks producing every table and figure.
8. Baseline prompts and configs.
9. A 30-minute "kick-the-tires" subset of ~10 instances, using the 30 GiB Epoch images or a smaller pre-pulled set.

**Licensing and ethics.**
- Redistribute only what licenses allow:
  - SWE-rebench, AIDev, nebius trajectories and the PatchDiff Zenodo record are CC-BY-4.0 [V];
  - SWE-Gym, SWE-smith, SWE-bench-Live and UTBoost are MIT [V];
  - **SWE-bench HF cards declare no license** [V], so reference them by ID rather than re-hosting;
  - **BugsInPy and the SWE-bench experiments repo show no license** [V], so link, don't copy;
  - SWE-bench Pro public repos are copyleft [S], so keep GPL code out of permissively licensed bundles.
- Code inside patches retains each source repository's license (AIDev states this explicitly) [V].
- **Personal data:** AIDev's user tables still carry `login` [V]. Pseudonymize author handles in released data, and never publish per-developer analyses. SIGSOFT Repository Mining lists data privacy as desirable, and the Ethics (Secondary Human Data) supplement applies [V].
- **Untrusted code:** run all targets with network off (CLAUDE.md rule 5). SWE-bench's own harness does not disable networking [V].

---

## 7. Contamination

**Evidence.**
- **The SWE-Bench Illusion** (Liang, Garg, Zilouchian Moghaddam; arXiv 2506.12286 v4, Dec 2025):
  - models identify buggy file paths from the issue text alone at up to 76% on Verified vs up to 53% on repos outside SWE-bench;
  - 5-gram reproduction of ground-truth functions reaches up to 35% on Verified/Full vs ≤18% on other benchmarks [V].
- **SWE-rebench:**
  - DeepSeek-V3 scores 39.7% / 35.2% on Verified but ~21–22% on fresh SWE-rebench tasks;
  - the leaderboard flags evaluations on issues created before a model's release date [V].
- **SWE-bench+:** >94% of SWE-bench issues pre-date LLM knowledge cutoffs; 32.67% of "successful" patches showed solution leakage via issue text [V].
- **OpenAI (Feb 2026)** stopped reporting Verified. Its audit of 138 hard problems found 59.4% with material test or spec flaws, and it reported evidence that frontier models reproduce original fixes from memory. It recommended SWE-bench Pro [S, primary page 403].
- **SWE-Bench Pro Verified** (Sep–Oct 2026) reports reward-hacking via leaked gold solutions and flawed tasks in Pro [V abstract].

**Why it matters for Repro specifically.** Contamination cuts in a direction not usually discussed. The **reviewer** LLM, in Repro's agents and in the B1/B2 baselines, may have memorized the *gold fix*. It could then recognize a wrong agent patch by comparing it with the remembered fix rather than reasoning from evidence. This inflates the LLM-only baselines more than Repro's execution evidence, but both would be inflated.

**Mitigations.**
- (i) Run the headline study only on instances created **after the reviewer model's training cutoff**:
  - SWE-rebench monthly splits and site windows [V];
  - SWE-bench-Live `test` split [V];
  - or self-curated tasks via their open pipelines.
- (ii) Report the result on SWE-bench Verified (contaminated, but comparable with PatchDiff/UTBoost) and on fresh data. Show the gap.
- (iii) Run a memorization probe: ask the reviewer model to reproduce the gold patch from the issue alone and stratify results by that score (Illusion-style).
- (iv) **Generate fresh agent patches yourself** on fresh tasks with ≥2 scaffolds × ≥2 model families. Do not rely only on leaderboard predictions; the experiments repo's artifacts are mostly on old instances.

---

## Recommended evaluation design for Repro

### Research questions
- **RQ1 (effectiveness):** Does Repro flag incorrect agent patches more often than B0–B3, without flagging more correct ones?
- **RQ2 (ablation):** Which evidence sources (traces, test selection, invariants, reviewer agents, claim judging) drive that?
- **RQ3 (cost):** What is the time and $ per PR?
- **RQ4 (robustness):** How stable are verdicts across repeated runs, and across fresh vs contaminated data?
- **RQ5 (external validity, exploratory):** How does Repro behave on real agent PRs in the wild?

### Input contract (the most important design rule)

Every system under test receives exactly:
- the repo at `base_commit` in its sealed image;
- the agent diff;
- the claim text, i.e. `problem_statement` + the agent's final summary if a trajectory exists, else a templated "Fixes the issue above without regressions".

**Withheld from all systems:** gold patch, `test_patch`, F2P/P2P, `hints_text`, post-PR discussion.

Enforce this in code. The benchmark adapter writes a sanitized instance, and a test asserts that no withheld field reaches the engine. Log the hash of what each system saw.

### Ground-truth procedure (per patch)

1. **Automatic tier A:** run the hidden `test_patch` (F2P + P2P) **and the full developer suite** in the official image. Fail → `INCORRECT_auto`. PatchDiff showed 7.8% of "resolved" patches fail the full developer suite [V], so do not stop at F2P/P2P.
2. **Automatic tier B (plausible patches only):**
   - add UTBoost augmented tests where available [V];
   - run PatchDiff-style LLM-generated differentiating tests vs the gold patch, with ×20 reruns to drop flaky tests, as PatchDiff did [V].
   - No divergence → `CORRECT_auto`. Divergence → go to step 3.
3. **Human adjudication:**
   - all tier-B divergent patches;
   - a random 15% sample of `CORRECT_auto`;
   - a random 15% of `INCORRECT_auto`. The OpenAI audit found many tests reject valid alternatives [S], so some "failing" patches are actually fine.
   - Two independent annotators (Python-experienced), blinded to every system's verdict. Labels: CORRECT / INCORRECT / UNCERTAIN, plus a defect category.
   - Written guideline with a decision rule: "would the issue author accept this as fixing the issue without breaking documented behaviour?"
   - Disagreements resolved by discussion; report κ.
   - Use the sample audits to estimate the auto-label error rate, and report metrics with that error rate propagated in a sensitivity analysis.
4. **UNCERTAIN** is excluded from primary metrics. Report a sensitivity analysis treating it as INCORRECT and as CORRECT. PatchDiff's sample was 66% uncertain [V], so budget annotation time accordingly.
5. **Freeze labels** before running any system on the main split, and version the label file.

### Staged plan

| Stage | Data | Size target | Purpose |
|---|---|---|---|
| **S0 Dev / tuning** | 2–3 SWE-bench repos (e.g., ones with fast suites) + ~50 synthetic plausible-but-wrong patches made with LM-Modify-style seeding, keeping only those that pass existing tests | ~100 patches | Debug the adapter, tracing and claim parsing; tune prompts and thresholds. **Never reported as results.** |
| **S1 Pilot (comparability)** | SWE-bench Verified, using (a) PatchDiff's 877 plausible patches incl. its 22 certain-incorrect / 4 correct labels [V], (b) UTBoost-flagged Verified patches (169) [V], (c) failing predictions from 2–3 systems in the experiments repo | ~300 patches (~120 INCORRECT, ~120 CORRECT, rest UNCERTAIN) | Calibrate; estimate discordance rates for the power analysis; run the contamination probe. **Report as "contaminated benchmark" results** |
| **S2 Main (headline)** | Fresh Python tasks created after the reviewer model's cutoff: SWE-rebench leaderboard monthly splits / site windows [V] + SWE-bench-Live `test` [V]; Docker images exist for both [V]. Generate patches with ≥2 open scaffolds (e.g., SWE-agent, OpenHands) × ≥2 model families; keep ≤2 patches per instance to limit clustering | ~400–600 tasks → **≥200 adjudicated INCORRECT, ≥200 CORRECT** [calc §4]. Over-sample *plausible* patches, because that's where the oracle-free problem is hard | Headline RQ1–RQ4; pre-registered analysis |
| **S3 In-the-wild (exploratory)** | AIDev-pop Python PRs with pytest that can be rebuilt at base: merged PRs with a **verified follow-up fix** or revert (proxy INCORRECT) vs merged with neither over ≥60 days (proxy CORRECT), following Takerngsaksiri et al.'s verification approach [V] | ~100–150 PRs | External validity, plus real PR descriptions as claims. Labels are noisy proxies, so report a confusion matrix and qualitative cases rather than headline numbers |
| **S4 Synthetic sensitivity** | mutmut/cosmic-ray operators + SWE-smith-style LLM mutants seeded into S2 repos, stratified by bug class (logic, boundary, exception handling, API contract, perf) | ~300 mutants | Per-class sensitivity and ablation support; caveated by Just et al. (17% of real faults uncoupled) [V] |

**Pre-registration.** Before S2, freeze the following and post them in the repo with a tag, or as a Registered Report if the venue allows [V supplement exists]:
- the Repro config, prompts and model versions;
- the baseline prompts;
- the PR-Agent mapping rule;
- the metric definitions;
- the analysis script.

### Systems compared
Repro (full) vs **B0 CI-only**, **B1 diff-only LLM**, **B2 agentic static LLM**, and **B3 PR-Agent** (pinned commit, same model). B4 commercial tools appear only with written permission (CodeRabbit ToS §4.2(iv) [V]). An oracle-assisted **PatchDiff-vs-gold** row is shown as a ceiling, not a competitor.

### Ablations (each run on all of S2, k = 5)
- **−traces:** no function-level I/O/exception diffs; tests and diffs only.
- **−test-selection:** run the full suite, to measure time saved and catch-rate change.
- **−invariants:** no declared or inferred invariants.
- **−agents** (deterministic-only): flag iff any test regression, behaviour diff on a changed function, API break or invariant violation. This approximates a PATCH-SIM-like no-LLM verifier [V prior art].
- **−claims:** the reviewer judges without NL claim text, which shows how much the claim-vs-evidence check contributes.
- **−evidence-citation rule:** allow uncited verdicts, to measure how much the "evidence before opinion" rule costs or gains.
- **Model swap:** one smaller and one different-vendor reviewer model.
- **Single run vs majority-of-5.**

### Metrics and tests (pre-registered)
- **Primary:** catch rate and false-flag rate on S2 adjudicated labels (UNVERIFIABLE handled as in §4). Exact McNemar vs each baseline, Holm-corrected; 95% cluster-bootstrap CIs (clustered by repo; 10,000 resamples [U, conventional]).
- **Secondary:**
  - precision, F1, coverage;
  - risk–coverage curve;
  - flip rate across k = 5;
  - time per PR (median/p90);
  - $ per PR and tokens;
  - evidence-citation validity on a 50-verdict human sample.
- **Stratify** by: plausible vs test-failing patches (the headline should emphasize *plausible*), defect category, repo, patch size, and fresh (S2) vs contaminated (S1).

### Threats to validity (to write up)
- **Construct:**
  - "correct" is relative to the issue plus gold behaviour; hidden tests are weak (UTBoost, PatchDiff) or over-narrow (OpenAI audit [S]);
  - mitigated by two-tier auto labels + human adjudication + audit samples + sensitivity analysis.
- **Label noise / annotator bias:**
  - blinding, two annotators, κ, published guideline;
  - many UNCERTAIN cases, reported transparently.
- **Contamination:** fresh post-cutoff tasks for the headline; memorization probe; S1 vs S2 gap reported.
- **Benchmark tailoring** (SIGSOFT anti-pattern [V]): dev and test split by repo and time; config frozen before S2; no prompt tuning on S2.
- **Baseline strength:** same model, budget and inputs for the LLM baselines; prompts published; PR-Agent used as shipped plus a documented mapping.
- **External validity:**
  - Python + pytest, popular OSS repos, issue-fix PRs only. Agent PRs in the wild include features and refactors (AIDev).
  - S3 is exploratory. Do not generalize beyond the sampled repos (Repository Mining anti-pattern [V]).
- **Synthetic-bug validity:** S4 only for sensitivity [V Just et al.].
- **Environment:**
  - flaky tests: rerun detection; PatchDiff's ×20 [V] is a precedent;
  - Docker-on-WSL2 timing differs from Linux, so report hardware and run cost experiments on Linux;
  - images pinned by digest.
- **LLM nondeterminism and model drift:** k = 5; record model IDs and dates; keep raw outputs.
- **Leakage into Repro:** the input contract is enforced and tested; hashes of system inputs are logged.

### Artifact plan
- **Zenodo DOI:** `repro-eval` bundle containing:
  - code (tagged release);
  - the benchmark manifest (IDs, image digests, patch hashes, label + provenance);
  - our generated agent patches and trajectories for S2 (we own them; license CC-BY-4.0 / MIT, while respecting each source repo's license for code excerpts);
  - annotation guideline + raw labels + κ;
  - raw per-run verdicts for all systems;
  - Repro event logs, replayable;
  - analysis notebooks;
  - baseline prompts and configs;
  - a 10-instance quickstart that runs in ≤30 min on a 16 GB machine [V ICSE AE].
- **Do not re-host** unlicensed sources (SWE-bench HF datasets, the experiments repo, BugsInPy). Fetch them by ID in scripts.
- **Pseudonymize** any GitHub logins from S3.
- **Target badges:** Available + Functional + Reusable.

### Rough budget [calc, order of magnitude]
- **Disk:** ~30 GiB for Verified images (Epoch) [V]; S2 images additional, size not documented [U].
- **Compute:** k = 5 × (Repro + 3 LLM baselines) × ~1,000 patches ≈ 20,000 LLM-reviewer runs, plus agent patch generation on ~500 tasks × 4 configurations.
- **Annotation:** ~300–500 patches × 2 annotators. This, not compute, is the main cost driver.

---

## Sources (all accessed 2026-10-13)

| # | URL | What | Tag |
|---|---|---|---|
| 1 | https://arxiv.org/abs/2503.15223 | PatchDiff / "Are 'Solved Issues' in SWE-bench Really Solved Correctly?" abstract | V |
| 2 | https://arxiv.org/html/2503.15223v2 | PatchDiff full text: 877/260/77 labels, method, repo link | V |
| 3 | https://github.com/ZJU-CTAG/PatchDiff | PatchDiff code; no license shown; resource needs | V |
| 4 | https://zenodo.org/records/17074796 | PatchDiff results, CC BY 4.0 | V |
| 5 | https://conf.researchr.org/details/icse-2026/icse-2026-research-track/59/Are-Solved-Issues-in-SWE-bench-Really-Solved-Correctly-An-Empirical-Study | ICSE 2026 listing | S |
| 6 | https://arxiv.org/html/2506.09289v1 | UTBoost full text | V |
| 7 | https://aclanthology.org/2025.acl-long.189 | UTBoost ACL 2025 listing | S |
| 8 | https://github.com/CUHK-Shenzhen-SE/UTBoost | UTBoost code, MIT, augmented tests | V |
| 9 | https://huggingface.co/api/datasets/Bertsekas/SWE-Bench_Verified_UTBoost | UTBoost Verified dataset, MIT | V |
| 10 | https://arxiv.org/abs/2410.06992 | SWE-Bench+ | V |
| 11 | https://arxiv.org/abs/2310.06770 | SWE-bench paper | V |
| 12 | https://huggingface.co/api/datasets/princeton-nlp/SWE-bench | SWE-bench splits, features, no license | V |
| 13 | https://huggingface.co/api/datasets/princeton-nlp/SWE-bench_Verified | Verified 500, no license | V |
| 14 | https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified | Verified card fields | V |
| 15 | https://huggingface.co/api/datasets/princeton-nlp/SWE-bench_Lite | Lite 300/23 | V |
| 16 | https://huggingface.co/api/datasets/princeton-nlp/SWE-bench_Multimodal | Multimodal 510/102 | V |
| 17 | https://arxiv.org/abs/2410.03859 | SWE-bench Multimodal (JavaScript) | V |
| 18 | https://openai.com/index/introducing-swe-bench-verified/ | Verified construction (page 403; via search snippets) | S |
| 19 | https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/ | Verified retirement (page 403; via snippets) | S |
| 20 | https://blog.pebblous.ai/blog/swe-bench-verified-retired/en/ | Secondary summary of retirement (Feb 2026, 138 tasks, 59.4%) | S |
| 21 | https://github.com/SWE-bench/SWE-bench | Harness README: MIT, 120 GB / 16 GB / 8 cores, CLI | V |
| 22 | https://www.swebench.com/SWE-bench/guides/docker_setup/ | Image layers, cache-level disk, Windows/WSL2 | V |
| 23 | https://www.swebench.com/SWE-bench/guides/evaluation/ | Predictions format, options, outputs | V |
| 24 | https://raw.githubusercontent.com/SWE-bench/SWE-bench/main/swebench/harness/grading.py | Resolution logic | V |
| 25 | https://raw.githubusercontent.com/SWE-bench/SWE-bench/main/swebench/harness/run_evaluation.py | Per-instance run, patch apply, networking | V |
| 26 | https://github.com/SWE-bench/experiments | Experiments repo structure, artifacts policy | V |
| 27 | https://epoch.ai/blog/swebench-docker | Epoch optimized images (67/30 GiB) | V |
| 28 | https://logicstar.ai/blog/how-we-made-swe-bench-50x-smaller | LogicStar compression | V |
| 29 | https://arxiv.org/abs/2412.21139 | SWE-Gym | V |
| 30 | https://huggingface.co/api/datasets/SWE-Gym/SWE-Gym | SWE-Gym 2,438, MIT | V |
| 31 | https://huggingface.co/api/datasets/SWE-Gym/OpenHands-Sampled-Trajectories | SWE-Gym trajectories (resolved flag) | V |
| 32 | https://arxiv.org/abs/2504.21798 | SWE-smith abstract | V |
| 33 | https://arxiv.org/html/2504.21798v2 | SWE-smith bug strategies, yields, costs | V |
| 34 | https://huggingface.co/api/datasets/SWE-bench/SWE-smith | SWE-smith dataset, MIT | V |
| 35 | https://huggingface.co/api/datasets/SWE-bench/SWE-smith-trajectories | SWE-smith trajectories, MIT | V |
| 36 | https://arxiv.org/abs/2505.20411 | SWE-rebench abstract | V |
| 37 | https://arxiv.org/html/2505.20411v2 | SWE-rebench decontamination, 5 runs + SEM, quality labels | V |
| 38 | https://huggingface.co/api/datasets/nebius/SWE-rebench | SWE-rebench 21,336 / 6,542, CC-BY-4.0 | V |
| 39 | https://huggingface.co/api/datasets/nebius/SWE-rebench-leaderboard | Monthly splits, docker_image | V |
| 40 | https://swe-rebench.com | Leaderboard window, Docker images news | V |
| 41 | https://huggingface.co/api/datasets/nebius/SWE-agent-trajectories | 80,036 trajectories, CC-BY-4.0 | V |
| 42 | https://huggingface.co/datasets/nebius/SWE-agent-trajectories | Card: resolved/unresolved counts, Llama license note | V |
| 43 | https://huggingface.co/api/datasets/nebius/SWE-rebench-openhands-trajectories | OpenHands trajectories, CC-BY-4.0 | V |
| 44 | https://arxiv.org/abs/2505.23419 | SWE-bench-Live | V |
| 45 | https://huggingface.co/api/datasets/SWE-bench-Live/SWE-bench-Live | Live splits, MIT | V |
| 46 | https://swe-bench-live.github.io/ | Live updates, multi-language/Windows | V |
| 47 | https://github.com/SWE-bench-Live/SWE-bench-Live | Live harness fork, starryzhang images | V |
| 48 | https://arxiv.org/abs/2504.02605 | Multi-SWE-bench (no Python) | V |
| 49 | https://arxiv.org/abs/2509.16941 | SWE-Bench Pro | V |
| 50 | https://huggingface.co/api/datasets/ScaleAI/SWE-bench_Pro | Pro dataset fields, no license | V |
| 51 | https://scale.com/leaderboard/swe_bench_pro_public | Pro copyleft rationale (via snippet) | S |
| 52 | https://arxiv.org/abs/2609.08149 | SWE-Bench Pro Verified | V |
| 53 | https://arxiv.org/abs/2506.12286 | The SWE-Bench Illusion | V |
| 54 | https://arxiv.org/abs/2506.17208 | Dissecting the SWE-Bench Leaderboards | V |
| 55 | https://arxiv.org/abs/2507.15003 | AIDev v1 paper | V |
| 56 | https://arxiv.org/abs/2602.09185 | AIDev: Studying AI Coding Agents on GitHub | V |
| 57 | https://huggingface.co/datasets/hao-li/AIDev | AIDev v4 card, CC-BY-4.0, tables, PII note | V |
| 58 | https://huggingface.co/api/datasets/hao-li/AIDev | AIDev configs, license | V |
| 59 | https://arxiv.org/abs/2609.26847 | Follow-up fixes on agent PRs | V |
| 60 | https://2026.msrconf.org/details/msr-2026-mining-challenge/27/ | MSR'26 challenge (reverts 2.66%, via snippet) | S |
| 61 | https://arxiv.org/abs/2401.15481 | BugsInPy (493 bugs / 17 programs) | V |
| 62 | https://api.github.com/repos/soarsmu/BugsInPy | BugsInPy license null | V |
| 63 | https://github.com/soarsmu/BugsInPy | BugsInPy commands, Dockerfile | V |
| 64 | https://huggingface.co/datasets/gurudesh/pytracebugs/blob/main/README.md | PyTraceBugs mirror (via snippet) | S |
| 65 | https://www.sed.inf.u-szeged.hu/node/16768 | PyBugHive announcement (via snippet) | S |
| 66 | https://api.github.com/repos/boxed/mutmut | mutmut BSD-3 | V |
| 67 | https://pypi.org/pypi/mutmut/json | mutmut 3.8.0, fork/WSL note | V |
| 68 | https://api.github.com/repos/sixty-north/cosmic-ray | cosmic-ray MIT | V |
| 69 | https://pypi.org/pypi/cosmic-ray/json | cosmic-ray 8.7.0 | V |
| 70 | https://api.github.com/repos/mutpy/mutpy | MutPy repo status | V |
| 71 | https://pypi.org/pypi/MutPy/json | MutPy 0.6.1 (2019), Py ≤3.7 | V |
| 72 | https://homes.cs.washington.edu/~mernst/pubs/mutation-effectiveness-fse2014.pdf | Just et al. FSE 2014 (73% / 10% / 17%) | V |
| 73 | https://homes.cs.washington.edu/~mernst/pubs/mutation-effectiveness-fse2014-abstract.html | Just et al. citation | V |
| 74 | https://conf.researchr.org/details/icse-2018/icse-2018-Technical-Papers/78/Are-Mutation-Scores-Correlated-with-Real-Fault-Detection-A-Large-Scale-Empirical-stu | Papadakis et al. ICSE 2018 | S |
| 75 | https://arxiv.org/abs/2406.09843 | LLMs for mutation testing | V |
| 76 | https://www2.sigsoft.org/EmpiricalStandards/docs/standards?standard=Benchmarking | SIGSOFT Benchmarking + Repository Mining | V |
| 77 | https://www2.sigsoft.org/EmpiricalStandards/docs/standards?standard=EngineeringResearch | SIGSOFT Engineering Research | V |
| 78 | https://www2.sigsoft.org/EmpiricalStandards/docs/supplements | IRR, Open Science, Ethics supplements | V |
| 79 | https://arxiv.org/abs/2010.03525 | Empirical Standards citation (linked from SIGSOFT page) | S |
| 80 | https://conf.researchr.org/track/icse-2026/icse-2026-artifact-evaluation | ICSE 2026 AE badges and criteria | V |
| 81 | https://www.acm.org/publications/policies/artifact-review-and-badging-current | ACM badging policy (403; via snippets) | S |
| 82 | https://link.springer.com/doi/10.1007/BF02295996 | McNemar 1947 | S |
| 83 | https://web.engr.oregonstate.edu/~tgd/publications/dietterich-approximate-statistical-tests-nc1998.pdf | Dietterich 1998 | S |
| 84 | https://arxiv.org/abs/2411.00640 and https://arxiv.org/html/2411.00640 | Miller, Adding Error Bars to Evals | V |
| 85 | https://arxiv.org/abs/2308.02828 | Ouyang et al., ChatGPT nondeterminism | V |
| 86 | (not fetched) Cohen 1960; Landis & Koch 1977, Biometrics 33:159–174; Efron 1979, Ann. Stat. 7(1):1–26 | Classic stats references | U |
| 87 | https://api.github.com/repos/qodo-ai/pr-agent | PR-Agent MIT | V |
| 88 | https://github.com/qodo-ai/pr-agent | PR-Agent donation notice, LLM support, CLI | V |
| 89 | https://itnext.io/automating-code-reviews-for-the-ai-era-236de2ff17ac | Secondary claim of Apache-2.0 relicense (conflicts with #87) | S |
| 90 | https://www.coderabbit.ai/terms-of-service | CodeRabbit ToS §4.2(iv) benchmarking clause | V |
| 91 | https://arxiv.org/abs/2509.01494 | SWR-Bench | V |
| 92 | https://arxiv.org/abs/2603.23448 | c-CRAB | V |
| 93 | https://arxiv.org/abs/2608.27442 | MCR-Bench | V |
| 94 | https://www.qodo.ai/blog/how-we-built-a-real-world-benchmark-for-ai-code-review/ | Qodo vendor benchmark (via snippet) | S |
| 95 | https://arxiv.org/abs/1706.09120 | PATCH-SIM (Xiong et al. ICSE 2018) | V |
| 96 | https://arxiv.org/abs/2301.01113 | Invalidator (TSE 2023) | V |
| 97 | https://arxiv.org/pdf/2303.00202 | LLM4PatchCorrect / PatchZero (via snippet) | S |
