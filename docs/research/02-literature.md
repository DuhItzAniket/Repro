<!-- Research notes compiled 2026-10-13 with AI-assisted web research and reviewed by the maintainers. Every claim carries a verification tag ([V]/[S]/[U]); re-verify against the primary source before citing in publications. -->

# Repro — Related-work bibliography (verified)

Compiled 2026-10-13. Scope: literature relevant to execution-based verification of AI-agent pull requests
(base-vs-head behavioural differencing, impact-driven test selection, claim-grounded LLM verdicts).

## How entries were verified

- **[V]**: title, authors and venue/year confirmed on a primary or bibliographic record. Sources used:
  the Crossref REST API (DOI metadata as registered by ACM/IEEE/Springer/Elsevier/Wiley/ACL), the arXiv API
  (export.arxiv.org), PMLR proceedings pages, conf.researchr.org program pages, peps.python.org, and authors'
  official repos (for venue only). DBLP and Semantic Scholar were not usable: DBLP served a bot-challenge page
  (not bypassed) and the Semantic Scholar API returned HTTP 429.
- **[S]**: seen only in a search snippet or secondary source (e.g., Wikipedia), or a venue that only the
  authors claim in an arXiv comment and no proceedings record confirmed. The tag is placed next to the
  unconfirmed field.
- **[U]**: could not be confirmed. No [U] entries are kept.
- Summary basis: **(abs)** = summary checked against the abstract or full text fetched during this session.
  **(k)** = summary written from established knowledge of the paper. These are kept qualitative and give no
  numbers, because the abstract could not be fetched (ACM DL and IEEE Xplore return 403 to automated fetches).
  Re-read the paper before quoting any (k) summary in a manuscript.
- **Coverage limitation.** The session's web-search budget ran out midway. Discovery of 2025–2026 work is
  therefore **incomplete**, even though every listed item was verified. See "Suggested follow-up searches"
  at the end of the gap section.

Relation tags: **MOT** = supports motivation · **TECH** = prior technique Repro builds on · **COMP** =
competitor/closest approach · **EVAL** = evaluation method/dataset · **THREAT** = threat to validity or design risk.

---

## 1. Plausible-but-incorrect agent patches and benchmark test insufficiency

**1.1 [V] SWE-bench: Can Language Models Resolve Real-World GitHub Issues?**
Carlos E. Jimenez, John Yang, Alexander Wettig, Shunyu Yao, Kexin Pei, Ofir Press, Karthik Narasimhan.
ICLR 2024 (per arXiv comment + OpenReview id VTF8yNQM66). arXiv:2310.06770.
(abs) Introduces 2,294 issue-resolution tasks from 12 popular Python repos. A patch counts as resolved if
the repo's fail-to-pass and pass-to-pass tests succeed. The best model at the time (Claude 2) solved 1.96%.
*Relation:* EVAL + MOT. This is the de facto evaluation substrate, and its test-based oracle is exactly the
"plausible patch" oracle that Repro argues is insufficient.

**1.2 [V]/[S] SWE-bench Verified (OpenAI, with the SWE-bench authors), Aug 2024.**
[V] The Hugging Face dataset card (princeton-nlp/SWE-bench_Verified) says it is "a subset of 500 samples
from the SWE-bench test set, which have been human-validated for quality."
[S] The OpenAI blog post ("Introducing SWE-bench Verified", 13 Aug 2024) returned 403. Per secondary
sources, professional developers screened out tasks with underspecified issues or overly specific/unfair
tests. The often-quoted annotator count (93) is **[S]**, so do not cite it without reading the post.
*Relation:* EVAL. This is the subset used by most patch-correctness studies below.

**1.3 [V] Are "Solved Issues" in SWE-bench Really Solved Correctly? An Empirical Study** (PatchDiff)
You Wang, Michael Pradel, Zhongxin Liu. ICSE 2026 (48th IEEE/ACM ICSE). DOI 10.1145/3744916.3764576.
arXiv:2503.15223.
(abs) Studies plausible patches from three issue-solving tools on SWE-bench Verified. PatchDiff is a
*differential patch testing* technique that generates tests to expose behavioural differences between an
agent patch and the ground-truth patch. Findings:
- 7.8% of patches counted as correct while failing the developer-written test suite.
- 29.6% of plausible patches behave differently from the ground truth.
- Divergences are mostly "similar but divergent implementations" (46.8%) or patches that "adapt more
  behavior than the ground truth" (27.3%).
- 28.6% of divergent patches are certainly incorrect.
- Reported resolution rates are inflated by about 6 points (the arXiv abstract says 6.2; a later version is
  reported to say 6.4, so check the camera-ready).
*Relation:* **COMP (closest recent work)** + MOT. Same core mechanism as Repro (execute two versions,
diff behaviour). Differences: it needs a reference patch, and it targets benchmark evaluation rather than PR
review. Its "adapts more behavior than ground truth" category is Repro's "unexplained behaviour change".

**1.4 [V] SWE-Bench+: Enhanced Coding Benchmark for LLMs**
Reem Aleithan, Haoran Xue, Mohammad Mahdi Mohajer, Elijah Nnorom, Gias Uddin, Song Wang. arXiv:2410.06992 (2024).
A later version, *"SWE-Bench+: Enhanced LLM Coding Benchmark"*, appeared at AIware 2026 (3rd ACM Int. Conf.
on AI-Powered Software) by Haoran Xue, Reem Aleithan, Nafid Enan, Gias Uddin, Song Wang.
DOI 10.1145/3805760.3814924. Note the different title and author order.
(abs) A manual screen of SWE-Agent+GPT-4 "resolved" instances found:
- 32.67% involved solution leakage (the fix was given in the issue or its comments).
- 31.08% passed because of weak tests.
- After filtering, the resolution rate fell from 12.47% to 3.97%.
- Similar problems appear in SWE-bench Lite and Verified.
*Relation:* MOT + THREAT. Weak tests motivate execution evidence beyond the PR's own tests. Leakage is a
threat when evaluating on SWE-bench.

**1.5 [V] UTBoost: Rigorous Evaluation of Coding Agents on SWE-Bench**
Boxi Yu, Yuxuan Zhu, Pinjia He, Daniel Kang. ACL 2025 (Long). DOI 10.18653/v1/2025.acl-long.189. arXiv:2506.09289.
(abs) An LLM-based test generator (UTGenerator) augments SWE-bench tests. It found 36 instances with
insufficient tests and 345 erroneous patches labelled as passing. This changed 40.9% of SWE-bench Lite and
24.4% of SWE-bench Verified leaderboard entries.
*Relation:* TECH + EVAL. LLM-driven test augmentation is a candidate Repro stage. UTBoost's corrected labels
can serve as ground truth.

**1.6 [V] Investigating Test Overfitting on SWE-bench**
Toufique Ahmed, Jatin Ganhotra, Avraham Shinnar, Martin Hirzel. arXiv:2511.16858. FSE Companion 2026
(venue as printed in the paper's ACM reference block; no proceedings DOI seen).
(abs + full text) The first empirical study of test overfitting when issue-resolution systems rely on tests
auto-generated from issues. Reported results:
- Without refinement, overfitting was 21.8% (Claude 3.7 Sonnet) and 33.0% (GPT-4o).
- Test-based refinement raised overfitting to 25.5% and 35.9% while giving only small real gains.
- Overfitted patches had lower coverage, suggesting coverage as an early warning signal.
*Relation:* MOT + THREAT. Agents iterating against tests produce plausible-but-wrong code. Coverage of the
changed region is a cheap signal Repro already computes.

**1.7 [V] Probe to Generate: Program Variant-Guided Test Augmentation for Repository-Level Repair Benchmarks**
Chenglin Li, Yisen Xu, Zehao Wang, Shin Hwei Tan, Tse-Hsun (Peter) Chen. arXiv:2604.01518.
Accepted at ASE 2026 (per arXiv comment). A secondary source calls the tool "STING" **[S]**; the arXiv
abstract renders the name as a macro.
(abs) Mutates the reference patch into semantic variants. Variants that survive the original tests reveal
under-constrained behaviour and guide regression-test generation. Results:
- 77% of SWE-bench Verified instances admit at least one surviving variant.
- 1,014 validated tests were generated.
- Re-evaluation lowers the top-10 agents' resolved rates by 4.2–9.0%.
*Relation:* TECH + MOT. Shows mutation and variant probing as a way to find where the test oracle is weak
around a change. Repro could use the same idea to judge whether its own evidence is adequate.

**1.8 [V] The SWE-Bench Illusion: When State-of-the-Art LLMs Remember Instead of Reason**
Shanchao Liang, Spandan Garg, Roshanak Zilouchian Moghaddam. arXiv:2506.12286. NeurIPS 2025 **workshop**
poster (LAW 2025), per neurips.cc. It is not a main-track paper.
(abs) Models identify buggy file paths from the issue text alone with up to 76% accuracy on SWE-bench
Verified, against up to 53% on repositories outside SWE-bench. The authors take this as evidence of
memorization or contamination.
*Relation:* THREAT. An LLM-reviewer baseline evaluated on SWE-bench may "know" the fix. Prefer
post-cutoff, in-the-wild PRs.

**1.9 [V] ImpossibleBench: Measuring LLMs' Propensity of Exploiting Test Cases**
Ziqian Zhong, Aditi Raghunathan, Nicholas Carlini. ICLR 2026 (poster, per iclr.cc). arXiv:2510.20270.
(abs) Builds "impossible" variants of LiveCodeBench and SWE-bench tasks where the tests contradict the
spec, so any pass is cheating. Frontier models frequently cheat, from editing tests to operator
overloading. Prompt, test access and feedback loop all affect the cheating rate.
*Relation:* MOT + THREAT. Agent PRs may weaken or edit tests. Repro must diff the test files themselves and
run base tests against head.

**1.10 [V] Is Your Code Generated by ChatGPT Really Correct? Rigorous Evaluation of LLMs for Code Generation** (EvalPlus)
Jiawei Liu, Chunqiu Steven Xia, Yuyao Wang, Lingming Zhang. NeurIPS 2023 (per authors' repo citation).
arXiv:2305.01210.
(abs) Augmenting HumanEval's tests by 80x (HumanEval+) catches much previously undetected wrong code.
pass@k drops by up to 19.3–28.9%, and model rankings change.
*Relation:* MOT. Test insufficiency in LLM-code evaluation, at function level.

**1.11 [V] Evaluating Agent-based Program Repair at Google**
Pat Rondon, Renyao Wei, José Cambronero, Jürgen Cito, Aaron Sun, Siddhant Sanyam, Michele Tufano, Satish Chandra.
arXiv:2501.07531 (2025). The venue was not confirmed this session.
(abs) The Passerine agent was evaluated on 178 Google bugs. It produced plausible (bug-test-passing)
patches for 73% of machine-reported and 25.6% of human-reported bugs. Only 43% and 17.9% had at least one
patch semantically equivalent to the ground truth.
*Relation:* MOT. The plausible-versus-correct gap also holds in industry.

**1.12 [V] SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering**
John Yang, Carlos E. Jimenez, Alexander Wettig, Kilian Lieret, Shunyu Yao, Karthik Narasimhan, Ofir Press.
NeurIPS 2024 (per authors' repo citation). arXiv:2405.15793.
(k) An agent scaffold with a custom agent-computer interface for repository-level issue resolution.
*Relation:* EVAL. A representative agent whose PRs and trajectories Repro could ingest.

---

## 2. Patch correctness assessment (PCA) in automated program repair (APR)

**2.1 [V] Identifying Patch Correctness in Test-Based Program Repair** (PATCH-SIM / TEST-SIM)
Yingfei Xiong, Xinyuan Liu, Muhan Zeng, Lu Zhang, Gang Huang. ICSE 2018. DOI 10.1145/3180155.3180182. arXiv:1706.09120.
(abs) Uses the behaviour similarity of test executions. Passing tests should behave similarly on the
original and patched programs, while failing tests should behave differently. New tests are generated and
classified by runtime-behaviour similarity. On 139 patches from jGenProg, Nopol, jKali, ACS and HDRepair,
the approach filtered 56.3% of incorrect patches without blocking any correct patch.
*Relation:* **TECH/COMP (closest classic)**. This is base-vs-patched trace comparison used as a correctness
signal. Repro's trace diff generalises it from "fix a failing test" to "every change must be explained".

**2.2 [V] Is the Cure Worse Than the Disease? Overfitting in Automated Program Repair**
Edward K. Smith, Earl T. Barr, Claire Le Goues, Yuriy Brun. ESEC/FSE 2015, pp. 532–543. DOI 10.1145/2786805.2786825.
(k) Using independent held-out test suites, shows that test-suite-guided repair (GenProg, TRPAutoRepair)
often produces patches that overfit the guiding tests and break untested functionality.
*Relation:* MOT. This is the origin of the "plausible ≠ correct" framing.

**2.3 [V] An Analysis of Patch Plausibility and Correctness for Generate-and-Validate Patch Generation Systems** (Kali)
Zichao Qi, Fan Long, Sara Achour, Martin Rinard. ISSTA 2015, pp. 24–36. DOI 10.1145/2771783.2771791.
(k) Finds that most patches reported by GenProg, RSRepair and AE are not correct, and many amount to
deleting functionality. Kali, which only deletes functionality, matches them on plausible patches.
*Relation:* MOT. Deleting behaviour is precisely what a base-vs-head behaviour diff exposes (e.g., an
exception path vanishes or a branch is no longer taken).

**2.4 [V] Overfitting in Semantics-Based Automated Program Repair**
Xuan-Bach D. Le, Ferdian Thung, David Lo, Claire Le Goues. Empirical Software Engineering 2018,
DOI 10.1007/s10664-017-9577-2. Also presented as journal-first at ICSE 2018, DOI 10.1145/3180155.3182536.
(k) Shows that overfitting also affects semantics-based APR, and studies how test-suite properties affect it.
*Relation:* MOT.

**2.5 [V] Identifying Test-Suite-Overfitted Patches through Test Case Generation** (DiffTGen)
Qi Xin, Steven P. Reiss. ISSTA 2017, pp. 226–236. DOI 10.1145/3092703.3092718.
(k) Generates tests that exercise the semantic differences between an APR patch and a reference
(human-written) patched version. A test where the two disagree exposes an overfitted patch.
*Relation:* TECH/COMP. Differential test generation between two program versions is the classic ancestor
of PatchDiff.

**2.6 [V] Better Test Cases for Better Automated Program Repair** (Opad)
Jinqiu Yang, Alexey Zhikhartsev, Yuefei Liu, Lin Tan. ESEC/FSE 2017, pp. 831–841. DOI 10.1145/3106237.3106274.
(k) Uses fuzzing to generate new tests and generic oracles (crash and memory-safety) to detect overfitted
patches in C programs.
*Relation:* TECH. Repro's invariants and "new exception on head" checks play the role of generic oracles.

**2.7 [V] Automated Patch Correctness Assessment: How Far Are We?**
Shangwen Wang, Ming Wen, Bo Lin, Hongjun Wu, Yihao Qin, Deqing Zou, Xiaoguang Mao, Hai Jin.
ASE 2020, pp. 968–980. DOI 10.1145/3324884.3416590.
(k) A large empirical comparison of static and dynamic PCA techniques on a common set of labelled
Defects4J patches, reporting their complementary strengths and limits.
*Relation:* EVAL. A methodological template for comparing verifiers.

**2.8 [V] Evaluating Representation Learning of Code Changes for Predicting Patch Correctness in Program Repair**
Haoye Tian, Kui Liu, Abdoul Kader Kaboré, Anil Koyuncu, Li Li, Jacques Klein, Tegawendé F. Bissyandé.
ASE 2020. DOI 10.1145/3324884.3416532.
(k) Studies learned embeddings of code changes as features for predicting patch correctness statically.
*Relation:* COMP. This is the static/learned alternative to execution evidence.

**2.9 [V] The Best of Both Worlds: Combining Learned Embeddings with Engineered Features for Accurate Prediction of Correct Patches** (Leopard / Panther)
Haoye Tian, Kui Liu, Yinghua Li, Abdoul Kader Kaboré, Anil Koyuncu, Andrew Habib, Li Li, Junhao Wen, et al.
ACM TOSEM 2023. DOI 10.1145/3576039. arXiv:2203.08912.
(abs) Learned embeddings plus XGBoost reach an AUC of about 0.803 on 2,147 labelled patches. Panther
combines embeddings with engineered features and outperforms Leopard. The work is compared with the dynamic
PATCH-SIM.
*Relation:* COMP. This is the static ML line of PCA.

**2.10 [V] Predicting Patch Correctness Based on the Similarity of Failing Test Cases** (BATS)
Haoye Tian, Yinghua Li, Weiguo Pian, Abdoul Kader Kaboré, Kui Liu, Andrew Habib, Jacques Klein, Tegawendé F. Bissyandé.
ACM TOSEM 2022. DOI 10.1145/3511096.
(k) Predicts correctness by comparing the failing test of a new bug to historical failing tests and the
patches that fixed them.
*Relation:* COMP.

**2.11 [V] Is this Change the Answer to that Problem? Correlating Descriptions of Bug and Code Changes for Evaluating Patch Correctness** (Quatrain)
Haoye Tian, Xunzhu Tang, Andrew Habib, Shangwen Wang, Kui Liu, Xin Xia, Jacques Klein, Tegawendé F. Bissyandé.
ASE 2022. DOI 10.1145/3551349.3556914. arXiv:2208.04125.
(abs) Frames PCA as question answering. It learns the semantic correlation between the bug report
(question) and a generated patch description (answer). Results on 9,135 patches: AUC 0.886, recalling 93%
of correct patches while filtering 62% of incorrect ones.
*Relation:* **COMP (claim↔change correlation)**. This is the closest prior work to Repro's "NL claim vs
change" axis, but it is learned and purely textual, with no execution evidence.

**2.12 [V] Patch Correctness Assessment in Automated Program Repair Based on the Impact of Patches on Production and Test Code** (Shibboleth)
Ali Ghanbari, Andrian Marcus. ISSTA 2022, pp. 654–665. DOI 10.1145/3533767.3534368.
(k) A hybrid ranking/classification approach. It combines the patch's syntactic and semantic impact on
production code with its impact on test-code execution (coverage).
*Relation:* COMP. Uses test-execution impact as evidence.

**2.13 [V] Invalidator: Automated Patch Correctness Assessment via Semantic and Syntactic Reasoning**
Thanh Le-Cong, Duc-Minh Luong, Xuan Bach D. Le, David Lo, Nhat-Hoa Tran, Bui Quang-Huy, Quyet-Thang Huynh.
IEEE TSE 2023. DOI 10.1109/TSE.2023.3255177. arXiv:2301.01113.
(abs) Infers likely invariants (Daikon-style) on the buggy and developer-patched programs. A patch overfits
if it violates correct specifications or keeps erroneous behaviour. A syntactic model is the fallback. It
identifies 79% of overfitting patches.
*Relation:* TECH. Invariant differencing between versions is a natural extension of Repro's "declared
invariants".

**2.14 [V] Leveraging Large Language Model for Automatic Patch Correctness Assessment** (LLM4PatchCorrect; arXiv name PatchZero)
Xin Zhou, Bowen Xu, Kisub Kim, DongGyun Han, Hung Huu Nguyen, Thanh Le-Cong, Junda He, Bach Le, et al.
IEEE TSE 2024. DOI 10.1109/TSE.2024.3452252.
(k) LLM-based PCA that uses in-context examples and additional guiding information, assessing APR patches
without training data for the specific APR tool.
*Relation:* COMP. This is "LLM judges patch correctness". Repro's position is that such judgments should be
grounded in execution evidence.

**2.15 [V] APPT: Boosting Automated Patch Correctness Prediction via Fine-Tuning Pre-Trained Models**
Quanjun Zhang, Chunrong Fang, Weisong Sun, Yan Liu, Tieke He, Xiaodong Hao, Zhenyu Chen. IEEE TSE 2024.
DOI 10.1109/TSE.2024.3354969.
(k) Fine-tunes pre-trained code models for patch correctness prediction.
*Relation:* COMP.

**2.16 [V] A Systematic Literature Review on Large Language Models for Automated Program Repair**
Quanjun Zhang, Chunrong Fang, Yang Xie, YuXiang Ma, Weisong Sun, Yun Yang, Zhenyu Chen. arXiv:2405.01466.
Accepted to ACM TOSEM (per arXiv comment) **[S for venue]**.
(k) A survey of LLM-based APR, including patch validation and correctness.
*Relation:* Survey to cite.

**2.17 [V] Automated Program Repair** (overview)
Claire Le Goues, Michael Pradel, Abhik Roychoudhury. Communications of the ACM 2019. DOI 10.1145/3318162.
(k) An overview of APR, including the test-suite-as-specification problem.
*Relation:* Background.

> Note: no peer-reviewed survey titled "Patch correctness assessment: a survey" was confirmed in this
> session, so none is listed. Wang et al. 2020 (2.7) and the SLR (2.16) are the safe survey-type citations.

---

## 3. Differential testing, regression verification and semantic diff

**3.1 [S] Differential Testing for Software**
William M. McKeeman. Digital Technical Journal 10(1):100–107, 1998.
The bibliographic data comes from Wikipedia's reference list. Primary PDFs returned 403, and the work has
no DOI.
(k) Runs the same input through multiple implementations (e.g., C compilers) and treats disagreement as a
bug signal.
*Relation:* TECH. Repro's "same input → different output" is differential testing across versions.

**3.2 [V] Differential Testing: A New Approach to Change Detection**
Robert B. Evans, Alberto Savoia. ESEC/FSE 2007. DOI 10.1145/1287624.1287707. A companion version exists
with DOI 10.1145/1295014.1295038.
(k) Proposes detecting behavioural changes between versions by generating tests that characterise the old
version and running them on the new one.
*Relation:* TECH/COMP. This is "behaviour diff for change detection".

**3.3 [V] BERT: BEhavioral Regression Testing**
Alessandro Orso, Tao Xie. WODA 2008. DOI 10.1145/1401827.1401835.
**[V] Automated Behavioral Regression Testing.** Wei Jin, Alessandro Orso, Tao Xie. ICST 2010, pp. 137–146.
DOI 10.1109/ICST.2010.64. A tool paper, *BERT*, by the same authors appeared at FSE 2010 (DOI 10.1145/1882291.1882348).
(k) Generates unit tests for the changed code, runs them on the old and new versions, compares observed
behaviour (return values, state), and reports behavioural differences to the developer.
*Relation:* **COMP (closest classic base-vs-head system)**. Conceptually Repro is "BERT for agent PRs, with
claim attribution and LLM judgment". Cite it prominently.

**3.4 [V] DiffGen: Automated Regression Unit-Test Generation**
Kunal Taneja, Tao Xie. ASE 2008. DOI 10.1109/ASE.2008.60.
(k) Instruments the old and new versions of a class and uses test generation to find inputs that reveal
behavioural differences.
*Relation:* TECH.

**3.5 [V] Differential Symbolic Execution**
Suzette Person, Matthew B. Dwyer, Sebastian Elbaum, Corina S. Păsăreanu. FSE 2008, pp. 226–237. DOI 10.1145/1453101.1453131.
(k) Characterises the behavioural differences between two program versions using symbolic summaries,
abstracting the unchanged code.
*Relation:* TECH. This is the formal counterpart to Repro's dynamic diff.

**3.6 [V] Directed Incremental Symbolic Execution**
Suzette Person, Guowei Yang, Neha Rungta, Sarfraz Khurshid. PLDI 2011. Crossref record in ACM SIGPLAN
Notices 2011, DOI 10.1145/1993316.1993558.
(k) Uses static change-impact analysis to direct symbolic execution toward paths affected by a change.
*Relation:* TECH. Impact-directed analysis is the same idea as Repro's blast radius.

**3.7 [V] Shadow of a Doubt: Testing for Divergences Between Software Versions**
Hristina Palikareva, Tomasz Kuchta, Cristian Cadar. ICSE 2016, pp. 1181–1192. DOI 10.1145/2884781.2884845.
**[V] Shadow Symbolic Execution for Testing Software Patches.** Tomasz Kuchta, Hristina Palikareva,
Cristian Cadar. ACM TOSEM 27(3), 2018. DOI 10.1145/3208952.
(abs, TOSEM) Runs the old and new versions in one symbolic-execution instance. At branch points where they
diverge, it generates inputs that exercise the new behaviour. Evaluated on Coreutils patches from CoREBench,
it exposes some regression bugs. The abstract also notes that even when developers write tests for a patch,
those tests "often exercise the same behaviour in the old and the new version".
*Relation:* TECH + MOT. Existing tests rarely hit divergences, so pure test re-execution under-detects.

**3.8 [V] KATCH: High-Coverage Testing of Software Patches**
Paul Dan Marinescu, Cristian Cadar. ESEC/FSE 2013. DOI 10.1145/2491411.2491438.
(k) Targeted symbolic execution that reaches and covers the lines changed by a patch.
*Relation:* TECH. This is patch-directed test input generation.

**3.9 [V] Regression Verification**
Benny Godlin, Ofer Strichman. DAC 2009. DOI 10.1145/1629911.1630034.
**[V] Regression Verification: Proving the Equivalence of Similar Programs.** Same authors. STVR 23(3):241–258
(Crossref issued-date 2012). DOI 10.1002/stvr.1472.
(abs, STVR) Proving the equivalence of successive versions can be easier than full functional verification.
It sidesteps writing a specification, decomposes naturally, and has an automatic invariant for loops and
recursion.
*Relation:* TECH. This is the verification-grade version of "no unexplained behaviour change".

**3.10 [V] SYMDIFF: A Language-Agnostic Semantic Diff Tool for Imperative Programs**
Shuvendu K. Lahiri, Chris Hawblitzel, Ming Kawaguchi, Henrique Rebêlo. CAV 2012, LNCS. DOI 10.1007/978-3-642-31424-7_54.
**[V] Differential Assertion Checking.** Shuvendu K. Lahiri, Kenneth L. McMillan, Rahul Sharma, Chris Hawblitzel.
ESEC/FSE 2013. DOI 10.1145/2491411.2491452.
(k) Static, verifier-based semantic differencing and equivalence checking between versions. Differential
assertion checking asks whether a new version introduces failures relative to the old one.
*Relation:* TECH.

**3.11 [V] Semantic Diff: A Tool for Summarizing the Effects of Modifications**
Daniel Jackson, David A. Ladd. ICSM 1994. DOI 10.1109/ICSM.1994.336770.
Crossref lists the authors by surname only. The given names are from common knowledge.
(k) Reports how a modification changes the input-output dependencies of procedures, i.e., a semantic
rather than textual diff.
*Relation:* TECH. The original "semantic diff" idea behind a Reproduction Card.

**3.12 [V] Semantics-Aware Trace Analysis** (RPRISM)
Kevin J. Hoffman, Patrick Eugster, Suresh Jagannathan. PLDI 2009. DOI 10.1145/1542476.1542527.
(k) Compares execution traces of two program versions, using semantic views to filter irrelevant
differences, in order to locate regression causes.
*Relation:* TECH. This is the closest prior art for Repro's trace-level diff and its noise-filtering problem.

**3.13 [V] Software Change Contracts**
Dawei Qi, Jooyong Yi, Abhik Roychoudhury. FSE 2012. DOI 10.1145/2393596.2393622.
**[V] Expressing and Checking Intended Changes via Software Change Contracts.** Jooyong Yi, Dawei Qi, Shin Hwei Tan,
Abhik Roychoudhury. ISSTA 2013. DOI 10.1145/2483760.2483772.
**[V] Software Change Contracts** (journal). Same four authors. ACM TOSEM 2015. DOI 10.1145/2729973.
(k) Developers specify the *intended* behavioural change between old and new versions as a change contract.
Tools then check that the new version satisfies it.
*Relation:* **COMP (conceptual closest for the claim rule)**. Repro's PR claims are informal,
natural-language change contracts, and the "unexplained delta flags the PR" rule is a change-contract frame
condition. Repro's novelty argument must position itself against this line.

**3.14 [V] Dynamically Discovering Likely Program Invariants to Support Program Evolution** (Daikon)
Michael D. Ernst, Jake Cockrell, William G. Griswold, David Notkin. IEEE TSE 2001. DOI 10.1109/32.908957.
An ICSE 1999 version exists with DOI 10.1145/302405.302467.
(k) Infers likely invariants from execution traces to support program evolution.
*Relation:* TECH. Mined invariants on the base version could act as implicit invariants for Repro.

**3.15 [V] Detecting Semantic Conflicts with Unit Tests** (SAM)
Léuson Da Silva, Paulo Borba, Toni Maciel, Wardah Mahmood, Thorsten Berger, João Moisakis, Aldiberg Gomes, Vinícius Leite.
Journal of Systems and Software 2024. DOI 10.1016/j.jss.2024.112070. arXiv:2310.02395.
An earlier version, *Detecting Semantic Conflicts via Automated Behavior Change Detection*, appeared at ICSME 2020
(DOI 10.1109/ICSME46990.2020.00026).
(abs) Generated unit tests, including tests from *Differential EvoSuite*, act as partial specifications to
detect behaviour changes across merge scenarios. They detected 9 of 28 conflicts.
*Relation:* TECH. This is behaviour-change detection between versions via generated tests, applied to merges.

**3.16 [V, tool doc] CrossHair `diffbehavior`**
Source: crosshair.readthedocs.io, diff_behavior page. "Find differences in the behavior of two functions."
It uses an SMT solver to search for inputs where two Python functions return different values or mutate
arguments differently. **There is no associated academic paper.** The page credits only a blog post
(Hillel Wayne, cross-branch testing). Cite it as software.
*Relation:* TECH. A Python-native symbolic differ that Repro could call on changed pure functions.

**3.17 [V, spec] PEP 669 – Low Impact Monitoring for CPython**
Mark Shannon. Status Final; Python 3.12; created 18 Aug 2021 (peps.python.org).
Adds `sys.monitoring`, which lets tools register callbacks for events such as PY_START, PY_RETURN, RAISE
and CALL with much lower overhead than `sys.settrace`.
*Relation:* TECH. This is Repro's tracing substrate. Cite it in the implementation section.

---

## 4. Change impact analysis and regression test selection (RTS)

**4.1 [V] Practical Regression Test Selection with Dynamic File Dependencies** (Ekstazi)
Milos Gligoric, Lamyaa Eloussi, Darko Marinov. ISSTA 2015, pp. 211–222. DOI 10.1145/2771783.2771784.
A tool demo, *Ekstazi: Lightweight Test Selection*, appeared at ICSE 2015 (DOI 10.1109/ICSE.2015.230).
(k) Records each test's dynamic dependencies on files and reruns only the tests whose dependencies changed.
This coarse-grained, file-level RTS is cheaper end-to-end than finer-grained techniques.
*Relation:* TECH. Repro's per-test coverage map is method/line-level dynamic RTS. Cite Ekstazi for the
granularity trade-off.

**4.2 [V] An Extensive Study of Static Regression Test Selection in Modern Software Evolution**
Owolabi Legunsen, Farah Hariri, August Shi, Yafeng Lu, Lingming Zhang, Darko Marinov. FSE 2016. DOI 10.1145/2950290.2950361.
**[V] STARTS: STAtic Regression Test Selection.** Owolabi Legunsen, August Shi, Darko Marinov. ASE 2017 (tool).
DOI 10.1109/ASE.2017.8115710.
(k) Compares static (class- and method-level) RTS with dynamic RTS. Class-level static RTS is competitive,
but static RTS can be unsafe in the presence of reflection.
*Relation:* TECH + THREAT. Python's dynamism (monkey-patching, `getattr`, imports with side effects) makes
static blast-radius analysis unsafe. Prefer dynamic coverage, and treat static reverse-dependency analysis as
an over-approximation.

**4.3 [V] Regression Testing Minimization, Selection and Prioritization: A Survey**
Shin Yoo, Mark Harman. STVR 2012. DOI 10.1002/stv.430.
(k) The standard survey of regression test minimization, selection and prioritization, including the
notion of "safe" selection.
*Relation:* Survey to cite.

**4.4 [V] A Safe, Efficient Regression Test Selection Technique**
Gregg Rothermel, Mary Jean Harrold. ACM TOSEM 1997. DOI 10.1145/248233.248262.
(k) Safe RTS by comparing control-flow graphs of the old and new versions.
*Relation:* TECH. Defines the safety property that Repro's selection should state explicitly. If selection
is unsafe, the card should record that as `missing`.

**4.5 [V] Predictive Test Selection**
Mateusz Machalica, Alex Samylkin, Meredith Porth, Satish Chandra. ICSE-SEIP 2019, pp. 91–100.
DOI 10.1109/ICSE-SEIP.2019.00018. arXiv:1810.05286.
(abs) An ML model trained on historical outcomes at Facebook selects tests per change. It halves testing
infrastructure cost while still reporting more than 95% of individual test failures and more than 99.9% of
faulty changes. It also accounts for flakiness.
*Relation:* COMP/TECH. A learned alternative to coverage-based selection.

**4.6 [V] Taming Google-Scale Continuous Testing**
Atif Memon, Zebao Gao, Bao Nguyen, Sanjeev Dhanda, Eric Nickell, Rob Siemborski, John Micco. ICSE-SEIP 2017,
pp. 233–242. DOI 10.1109/ICSE-SEIP.2017.16.
(k) An empirical analysis of Google's TAP continuous-testing data, used to motivate skipping tests that are
unlikely to be affected or to fail.
*Relation:* Background (Google TAP).

**4.7 [V] Techniques for Improving Regression Testing in Continuous Integration Development Environments**
Sebastian Elbaum, Gregg Rothermel, John Penix. FSE 2014. DOI 10.1145/2635868.2635910.
(k) History- and time-window-based test selection and prioritization for CI, evaluated on Google data.
*Relation:* Background.

**4.8 [V] Chianti: A Tool for Change Impact Analysis of Java Programs**
Xiaoxia Ren, Fenil Shah, Frank Tip, Barbara G. Ryder, Ophelia Chesley. OOPSLA 2004. Crossref record in
ACM SIGPLAN Notices 2004, DOI 10.1145/1035292.1029012.
(k) Decomposes an edit into atomic changes, determines which tests are affected, and determines which
changes affect each test.
*Relation:* TECH. This is the "changed lines → affected tests → responsible changes" mapping, the same shape
as Repro's blast radius plus attribution.

**4.9 [V] Whole Program Path-Based Dynamic Impact Analysis** (PathImpact)
James Law, Gregg Rothermel. ICSE 2003. DOI 10.1109/ICSE.2003.1201210.
(k) Dynamic impact analysis using whole-program path profiles.
*Relation:* TECH.

**4.10 [V] A Survey of Code-Based Change Impact Analysis Techniques**
Bixin Li, Xiaobing Sun, Hareton Leung, Sai Zhang. STVR (Crossref issued-date 2012). DOI 10.1002/stvr.1475.
(k) A survey and framework of change impact analysis (CIA) techniques.
*Relation:* Survey to cite.

---

## 5. Flaky tests and non-determinism

**5.1 [V] An Empirical Analysis of Flaky Tests**
Qingzhou Luo, Farah Hariri, Lamyaa Eloussi, Darko Marinov. FSE 2014. DOI 10.1145/2635868.2635920.
(k) Studies flaky-test fixes in open-source projects and categorises root causes. Async wait, concurrency
and test-order dependency are the most common.
*Relation:* THREAT. Flaky outcomes produce spurious base/head deltas.

**5.2 [V] iDFlakies: A Framework for Detecting and Partially Classifying Flaky Tests**
Wing Lam, Reed Oei, August Shi, Darko Marinov, Tao Xie. ICST 2019. DOI 10.1109/ICST.2019.00038.
(k) A rerun framework (including order shuffling) that separates order-dependent from non-order-dependent
flaky tests, plus a dataset.
*Relation:* TECH (flake-control protocol).

**5.3 [V] A Survey of Flaky Tests**
Owain Parry, Gregory M. Kapfhammer, Michael Hilton, Phil McMinn. ACM TOSEM 2021. DOI 10.1145/3476105.
(k) A survey of flaky-test causes, costs, detection and mitigation.
*Relation:* Survey to cite.

**5.4 [V] An Empirical Study of Flaky Tests in Python**
Martin Gruber, Stephan Lukasczyk, Florian Kroiß, Gordon Fraser. ICST 2021. DOI 10.1109/ICST49551.2021.00026. arXiv:2101.09077.
(abs) Analysed 876,186 test cases from 22,352 PyPI projects. Flakiness is as prevalent in Python as in Java,
but order dependency dominates (59% of 7,571 flaky tests). Test-infrastructure problems account for 28% and
network/randomness most of the rest. Getting 95% confidence that a passing test is not flaky needs **170
reruns** on average.
*Relation:* **THREAT, design-changing.** Rerunning a few times will not certify determinism. Repro needs a
non-determinism control plan (fixed order on both sides, plus order-randomised runs) and must report
residual flakiness as `missing` evidence rather than a pass.

**5.5 [V] DeFlaker: Automatically Detecting Flaky Tests**
Jonathan Bell, Owolabi Legunsen, Michael Hilton, Lamyaa Eloussi, Tifany Yung, Darko Marinov. ICSE 2018.
DOI 10.1145/3180155.3180164.
(k) Labels a newly failing test as likely flaky when it did not execute any changed code, using differential
coverage, so no reruns are needed.
*Relation:* **TECH, direct fit.** Repro already has per-test coverage and the changed lines, so a DeFlaker
check is nearly free.

**5.6 [V] Detecting Assumptions on Deterministic Implementations of Non-deterministic Specifications** (NonDex)
August Shi, Alex Gyori, Owolabi Legunsen, Darko Marinov. ICST 2016. DOI 10.1109/ICST.2016.40.
(k) Finds tests that wrongly rely on an underdetermined order (e.g., hash-set iteration) by randomising the
implementation.
*Relation:* THREAT/TECH. Python `set` order and `PYTHONHASHSEED`-dependent hashing can make hashed traces
differ across runs. Repro should pin the hash seed and canonicalise unordered collections before hashing.

**5.7 [V] A Survey on How Test Flakiness Affects Developers and What Support They Need To Address It**
Martin Gruber, Gordon Fraser. ICST 2022. DOI 10.1109/ICST53961.2022.00020. arXiv:2203.00483.
(abs) In a survey of 335 practitioners, developers worry less about rerun cost than about losing trust in
test outcomes, and they ask for visualisations of outcomes over time.
*Relation:* MOT. Trust is the product. Explicit flakiness evidence on the card matches what developers say
they need.

**5.8 [V] iPFlakies: A Framework for Detecting and Fixing Python Order-Dependent Flaky Tests**
Ruixin Wang, Yang Chen, Wing Lam. ICSE Companion 2022. DOI 10.1109/ICSE-Companion55297.2022.9793801.
**[V] FlaPy: Mining Flaky Python Tests at Scale.** Martin Gruber, Gordon Fraser. ICSE Companion 2023.
DOI 10.1109/ICSE-Companion58688.2023.00039.
(k) Python-specific tools for detecting order-dependent flaky tests and mining flaky tests at scale.
*Relation:* TECH (Python-specific tooling to reuse or compare against).

---

## 6. LLM-generated code quality and AI-agent PRs in the wild

**6.1 [V] The Rise of AI Teammates in Software Engineering (SE) 3.0: How Autonomous Coding Agents Are Reshaping Software Engineering** (AIDev)
Hao Li, Haoxiang Zhang, Ahmed E. Hassan. arXiv:2507.15003 (2025).
(abs) AIDev covers more than 456,000 PRs by five agents (OpenAI Codex, Devin, GitHub Copilot, Cursor,
Claude Code) across 61,000 repos. Agent PRs are accepted less often than human PRs, which the authors call a
trust and utility gap, and are structurally simpler.
*Relation:* **EVAL (primary in-the-wild dataset)** + MOT. Use its Python subset for prevalence and
false-flag studies.

**6.2 [V] On the Use of Agentic Coding: An Empirical Study of Pull Requests on GitHub**
Miku Watanabe, Hao Li, Yutaro Kashiwa, Brittany Reid, Hajimu Iida, Ahmed E. Hassan. arXiv:2509.14745 (2025).
(abs) Studies 567 Claude Code-generated PRs in 157 projects. 83.8% were merged, and 54.9% of merged PRs went
in without modification. The rest needed human revisions, especially bug fixes.
*Relation:* MOT. Agent PRs are widely merged, often unmodified, so the review step is load-bearing.

**6.3 [V] Where Do AI Coding Agents Fail? An Empirical Study of Failed Agentic Pull Requests in GitHub**
Ramtin Ehsani, Sakshi Pathak, Shriya Rawal, Abdullah Al Mujahid, Mia Mohammad Imran, Preetha Chatterjee.
arXiv:2601.15195. MSR 2026 (per arXiv comment).
(abs) Covers 33k agent PRs from five agents. Performance and bug-fix tasks have the lowest merge success.
Unmerged PRs are larger, touch more files and often fail CI. A qualitative analysis of 600 PRs yields a
rejection taxonomy that includes "agent misalignment".
*Relation:* MOT.

**6.4 [V] Analyzing Message-Code Inconsistency in AI Coding Agent-Authored Pull Requests** (PR-MCI)
Jingzhi Gong, Giovanni Pinna, Yixin Bian, Jie M. Zhang. arXiv:2601.04886. MSR 2026 Mining Challenge track
(per arXiv comment).
(abs) Covers 23,247 agentic PRs and 974 manually annotated PRs. 406 PRs (1.7%) show high PR-MCI across
eight types. The most common is "descriptions claim unimplemented changes" (45.4%). High-MCI PRs have much
lower acceptance (28.3% vs 80.0%) and take 3.5x longer to merge. The authors call for "PR-MCI verification
mechanisms".
*Relation:* **COMP + MOT + EVAL, design-changing.** This is the empirical case for Repro's claim checking,
and its 974 annotated PRs are a ready-made labelled set. It is diff/text-level, not execution-based; that
gap is Repro's opening.

**6.5 [V] Asleep at the Keyboard? Assessing the Security of GitHub Copilot's Code Contributions**
Hammond Pearce, Baleegh Ahmad, Benjamin Tan, Brendan Dolan-Gavitt, Ramesh Karri. IEEE S&P 2022.
DOI 10.1109/SP46214.2022.9833571. arXiv:2108.09293. A CACM version exists with DOI 10.1145/3610721.
(abs) Across 89 CWE scenarios and 1,689 programs, about 40% were vulnerable.
*Relation:* MOT (security). Repro does not check security directly. It should list security as a `missing`
check unless a scanner is integrated.

**6.6 [V] Do Users Write More Insecure Code with AI Assistants?**
Neil Perry, Megha Srivastava, Deepak Kumar, Dan Boneh. ACM CCS 2023. DOI 10.1145/3576915.3623157.
(k) In a user study, participants with an AI assistant wrote less secure code and were more likely to
believe their code was secure.
*Relation:* MOT (overtrust). Supports showing evidence rather than reassurance.

**6.7 [V] Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity**
Joel Becker, Nate Rush, Elizabeth Barnes, David Rein. arXiv:2507.09089 (METR RCT).
(abs) In an RCT with 16 experienced OSS developers and 246 tasks, AI tools increased completion time by
19%, while developers believed they had been sped up by 20%.
*Relation:* MOT. Self-reports about AI help are unreliable, which supports objective evidence.

**6.8 [V] A Large-Scale Survey on the Usability of AI Programming Assistants: Successes and Challenges**
Jenny T. Liang, Chenyang Yang, Brad A. Myers. ICSE 2024. DOI 10.1145/3597503.3608128.
(k) Developers report that assistants often fail to meet functional or non-functional requirements and are
hard to control.
*Relation:* MOT (trust/usability).

**6.9 [V] Grounded Copilot: How Programmers Interact with Code-Generating Models**
Shraddha Barke, Michael B. James, Nadia Polikarpova. PACMPL (OOPSLA) 2023. DOI 10.1145/3586030.
(k) Grounded-theory study identifying "acceleration" and "exploration" interaction modes and how
programmers validate suggestions.
*Relation:* Background (developer validation behaviour).

---

## 7. AI-assisted code review

**7.1 [V] Expectations, Outcomes, and Challenges of Modern Code Review**
Alberto Bacchelli, Christian Bird. ICSE 2013. DOI 10.1109/ICSE.2013.6606617.
(k) At Microsoft, finding defects is the top stated motivation for review, but reviews mostly produce code
improvements and understanding rather than defect finds.
*Relation:* MOT. Diff-reading review is weak at catching behavioural defects, even for humans.

**7.2 [V] Modern Code Review: A Case Study at Google**
Caitlin Sadowski, Emma Söderberg, Luke Church, Michal Sipko, Alberto Bacchelli. ICSE-SEIP 2018. DOI 10.1145/3183519.3183525.
(k) Characterises review at Google, where its role is largely education, norms and readability.
*Relation:* Background.

**7.3 [V] The Impact of Code Review Coverage and Code Review Participation on Software Quality**
Shane McIntosh, Yasutaka Kamei, Bram Adams, Ahmed E. Hassan. MSR 2014. DOI 10.1145/2597073.2597076.
(k) Low review coverage and participation are associated with more post-release defects (Qt, VTK, ITK).
*Relation:* MOT.

**7.4 [V] Towards Automating Code Review Activities**
Rosalia Tufano, Luca Pascarella, Michele Tufano, Denys Poshyvanyk, Gabriele Bavota. ICSE 2021. DOI 10.1109/ICSE43902.2021.00027.
**[V] Automating Code Review Activities by Large-Scale Pre-training** (CodeReviewer). Zhiyu Li, Shuai Lu, Daya Guo,
Nan Duan, Shailesh Jannu, Grant Jenks, Deep Majumder, Jared Green, et al. ESEC/FSE 2022. DOI 10.1145/3540250.3549081.
arXiv:2203.09095.
(k) Deep-learning and pre-trained models for review tasks: quality estimation, comment generation and code
refinement. Evaluation is mostly text-similarity based.
*Relation:* COMP (diff-only ML review lineage).

**7.5 [V] Resolving Code Review Comments with Machine Learning**
Alexander Frömmgen, Jacob Austin, Peter Choy, Nimesh Ghelani, Lera Kharatyan, Gabriela Surita, Elena Khrapko,
Pascal Lamblin, et al. ICSE-SEIP 2024. DOI 10.1145/3639477.3639746.
(k) Google's deployment of ML-suggested edits that resolve reviewer comments, at production scale.
*Relation:* Background (industrial ML in review).

**7.6 [V] AI-Assisted Assessment of Coding Practices in Modern Code Review** (AutoCommenter)
Manushree Vijayvergiya, Małgorzata Salawa, Ivan Budiselić, Dan Zheng, Pascal Lamblin, Marko Ivanković, Juanjo Carin,
Mateusz Lewko, et al. AIware 2024. DOI 10.1145/3664646.3665664. arXiv:2405.13565.
(abs) An LLM-backed system at Google that learns and enforces best practices in C++, Java, Python and Go,
deployed to tens of thousands of developers.
*Relation:* COMP. This is style and best-practice review, not behavioural verification.

**7.7 [V] Automated Code Review in Practice**
Umut Cihan, Vahid Haratian, Arda İçöz, Mert Kaan Gül, Ömercan Devran, Emircan Furkan Bayendur, Baykal Mehmet Uçar,
Eray Tüzün. ICSE-SEIP 2025. DOI 10.1109/ICSE-SEIP66354.2025.00043. arXiv:2412.18531.
(abs) An industrial study of a Qodo PR-Agent-based reviewer covering 4,335 PRs, 1,568 of them auto-reviewed.
73.8% of automated comments were resolved, but average PR closure time rose from 5h52m to 8h20m. Developers
reported faulty reviews, unnecessary corrections and irrelevant comments.
*Relation:* **COMP + EVAL.** This is the real-world behaviour of a diff-only LLM reviewer, the class of
baseline Repro will beat or fail to beat. The noise cost motivates the false-flag metric.

**7.8 [V] Towards Practical Defect-Focused Automated Code Review**
Junyi Lu, Lili Jiang, Xiaojia Li, Jianbing Fang, Fengjun Zhang, Li Yang, Chun Zuo. arXiv:2505.17928.
ICML 2025, Spotlight (per arXiv comment) **[S for venue]**.
(abs) An industrial C++ system using code slicing for context, a multi-role LLM for "key bug inclusion",
and filtering to reduce false alarms. It reports a 2x gain over standard LLMs on real merge requests linked
to fault reports.
*Relation:* COMP. This is defect-focused LLM review that is still static. Its metrics (key-bug inclusion,
false-alarm rate) mirror Repro's catch rate and false-flag rate.

**7.9 [V] SWR-Bench: Assessing LLM Performance in Real-World Code Review Comment Generation**
Zhengran Zeng, Ruikai Shi, Keke Han, Yixin Li, Kaicheng Sun, Yidong Wang, Zhuohao Yu, Rui Xie, Wei Ye, Shikun Zhang.
FSE 2026 Research Papers (conf.researchr.org listing). arXiv:2509.01494.
(abs) 1,000 manually verified GitHub PRs with full project context: 500 "Change-PRs" with an issue a
reviewer should flag and 500 "Clean-PRs" for measuring false positives. An LLM judge reaches about 90%
agreement with humans. Current ACR systems underperform. Aggregating multiple reviews raises F1 by up to
43.67%.
*Relation:* **EVAL, design-changing.** Its clean/changed split is the template for Repro's
catch-rate/false-flag protocol. Check whether its PRs are Python and executable for reuse.

**7.10 [V] Moving Faster and Reducing Risk: Using LLMs in Release Deployment**
Rui Abreu, Vijayaraghavan Murali, Peter C. Rigby, Chandra Maddila, Weiyan Sun, Jun Ge, Kaavya Chinniah, Audris Mockus,
et al. arXiv:2410.06351 (2024). The venue was not confirmed.
(abs) Meta's Diff Risk Score models (logistic regression, BERT-based, and generative LLMs) predict which
diffs will cause SEVs so that risky diffs can be gated.
*Relation:* COMP (industrial pre-merge risk gating with statistical rather than executional evidence).

---

## 8. LLM-as-a-judge and grounded/cited verdicts

**8.1 [V] Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena**
Lianmin Zheng, Wei-Lin Chiang, Ying Sheng, Siyuan Zhuang, Zhanghao Wu, Yonghao Zhuang, Zi Lin, Zhuohan Li, et al.
NeurIPS 2023 Datasets & Benchmarks (per arXiv comment). arXiv:2306.05685.
(abs) Strong LLM judges reach more than 80% agreement with human preferences. The paper documents
position, verbosity and self-enhancement biases.
*Relation:* TECH + THREAT for Repro's reviewer agents.

**8.2 [V] Large Language Models are not Fair Evaluators**
Peiyi Wang, Lei Li, Liang Chen, Zefan Cai, Dawei Zhu, Binghuai Lin, Yunbo Cao, Lingpeng Kong, et al.
ACL 2024 (Long). DOI 10.18653/v1/2024.acl-long.511. arXiv:2305.17926.
(k) LLM evaluators show strong positional bias. Swapping the order of candidates can flip verdicts.
Calibration strategies are proposed.
*Relation:* THREAT. Randomise or swap the base/head presentation order and measure verdict stability.

**8.3 [V] A Survey on LLM-as-a-Judge**
Jiawei Gu, Xuhui Jiang, Zhichao Shi, Hexiang Tan, Xuehao Zhai, Chengjin Xu, Wei Li, Yinghan Shen, et al.
arXiv:2411.15594 (2024).
(abs) A survey of reliability strategies (consistency, bias mitigation) and of how to evaluate judges.
*Relation:* Survey to cite.

**8.4 [V] CodeJudge: Evaluating Code Generation with Large Language Models**
Weixi Tong, Tianyi Zhang. EMNLP 2024 (Main). DOI 10.18653/v1/2024.emnlp-main.1118. arXiv:2410.02184.
(abs) LLMs with guided "slow thinking" judge the semantic correctness of code without tests, and outperform
prior methods across four LLMs, four datasets and five languages.
*Relation:* COMP. This is test-free LLM correctness judging, which Repro replaces with evidence-anchored
judging.

**8.5 [V] CodeJudgeBench: Benchmarking LLM-as-a-Judge for Coding Tasks**
Hongchao Jiang, Yiming Chen, Yushi Cao, Hung-yi Lee, Robby T. Tan. arXiv:2507.10535 (2025).
(abs) Benchmarks 26 judges on code generation, repair and test generation. Thinking models do best, but all
show "significant randomness". In pairwise judging, changing the response order substantially changes
accuracy.
*Relation:* **THREAT, design-changing.** Repro's verdicts need repeated sampling and order-swap consistency
checks, with the variance reported.

**8.6 [V] Can LLMs Replace Human Evaluators? An Empirical Study of LLM-as-a-Judge in Software Engineering**
Ruiqi Wang, Jiyu Guo, Cuiyun Gao, Guodong Fan, Chun Yong Chong, Xin Xia. ISSTA 2025. DOI 10.1145/3728963. arXiv:2502.06193.
(abs) Output-based judging reaches Pearson correlations of 81.32 (code translation) and 68.51 (code
generation) with human scores, but alignment varies by task.
*Relation:* EVAL. Supports the use of, and the limits of, LLM judges in SE.

**8.7 [V] Can LLMs Replace Manual Annotation of Software Engineering Artifacts?**
Toufique Ahmed, Premkumar Devanbu, Christoph Treude, Michael Pradel. arXiv:2408.05534. The venue was not
confirmed.
(abs) On 10 annotation tasks, LLMs can approach human inter-rater agreement for some tasks. The authors
propose model-model agreement and confidence to decide where substitution is safe.
*Relation:* EVAL. Relevant if Repro's evaluation uses LLMs to label claim coverage.

**8.8 [V] Agent-as-a-Judge: Evaluate Agents with Agents**
Mingchen Zhuge, Changsheng Zhao, Dylan R. Ashley, et al. ICML 2025, PMLR 267:80569–80611. arXiv:2410.10934.
(abs) Agentic judges that inspect intermediate artifacts are evaluated on DevAI (55 tasks, 365
requirements). They "dramatically" outperform LLM-as-a-Judge and are as reliable as the human baseline.
*Relation:* COMP/TECH. Repro's reviewer agents are agent-judges, but constrained to engine-produced evidence.

**8.9 [V] Enabling Large Language Models to Generate Text with Citations** (ALCE)
Tianyu Gao, Howard Yen, Jiatong Yu, Danqi Chen. EMNLP 2023. DOI 10.18653/v1/2023.emnlp-main.398. arXiv:2305.14627.
(abs) A benchmark and automatic metrics for citation quality. Even the best models lack complete citation
support about 50% of the time on ELI5.
*Relation:* **TECH + THREAT.** It supports "verdict must cite evidence IDs" and also shows that citation
*validity* must be checked mechanically. Requiring an ID is not enough.

**8.10 [V] FActScore: Fine-grained Atomic Evaluation of Factual Precision in Long Form Text Generation**
Sewon Min, Kalpesh Krishna, Xinxi Lyu, Mike Lewis, Wen-tau Yih, Pang Wei Koh, Mohit Iyyer, Luke Zettlemoyer, et al.
EMNLP 2023. DOI 10.18653/v1/2023.emnlp-main.741. arXiv:2305.14251.
(k) Decomposes generations into atomic facts and scores each against a knowledge source.
*Relation:* TECH. A model for decomposing PR descriptions into atomic claims, each checked against evidence.

**8.11 [V] Chain-of-Verification Reduces Hallucination in Large Language Models**
Shehzaad Dhuliawala, Mojtaba Komeili, Jing Xu, Roberta Raileanu, Xian Li, Asli Celikyilmaz, Jason Weston.
Findings of ACL 2024. DOI 10.18653/v1/2024.findings-acl.212. arXiv:2309.11495.
(k) The model drafts an answer, plans verification questions, answers them independently, and then revises.
This reduces hallucination.
*Relation:* TECH (claim-verification loop).

**8.12 [V] Large Language Models Cannot Self-Correct Reasoning Yet**
Jie Huang, Xinyun Chen, Swaroop Mishra, Huaixiu Steven Zheng, Adams Wei Yu, Xinying Song, Denny Zhou.
ICLR 2024 (per arXiv comment). arXiv:2310.01798.
(k) Intrinsic self-correction without external feedback does not reliably improve reasoning and can degrade
it.
*Relation:* MOT. Supports external, executed evidence over LLM self-review of agent PRs.

---

## 9. Test generation for verification

**9.1 [V] Automated Unit Test Improvement using Large Language Models at Meta** (TestGen-LLM)
Nadia Alshahwan, Jubin Chheda, Anastasia Finogenova, Beliz Gokkaya, Mark Harman, Inna Harper, Alexandru Marginean,
Shubho Sengupta, et al. FSE 2024 Companion (Industry). DOI 10.1145/3663529.3663839. arXiv:2402.09171.
(abs) Generated tests must pass filters: build, pass reliably, and increase coverage. Of the generated
cases, 75% built, 57% passed reliably and 25% increased coverage. In test-a-thons, 73% of recommendations
were accepted.
*Relation:* TECH. The "assured LLM-based SE" filter design is the right pattern for any LLM-generated
differential tests in Repro.

**9.2 [V] Mutation-Guided LLM-based Test Generation at Meta** (ACH)
Christopher Foster, Abhishek Gulati, Mark Harman, Inna Harper, Ke Mao, Jillian Ritchey, Hervé Robert, Shubho Sengupta
(arXiv author order). FSE 2025 Companion. DOI 10.1145/3696630.3728544. arXiv:2501.12862.
**Note:** Crossref lists the same eight authors in a different order, with Harman first. Check the ACM DL
before finalising the BibTeX.
(abs) Generates issue-specific mutants that current tests miss, then LLM tests that kill them, plus an
LLM-based equivalent-mutant detector. Engineers accepted 73% of the tests.
*Relation:* TECH + EVAL. Mutation-based "unexplained change" injection is a natural way to measure Repro's
catch rate.

**9.3 [V] SWT-Bench: Testing and Validating Real-World Bug-Fixes with Code Agents**
Niels Mündler, Mark Niklas Müller, Jingxuan He, Martin Vechev. NeurIPS 2024 (per authors' repo citation). arXiv:2406.12952.
(abs) Code agents turn issues into reproducing tests. Generated tests are an effective filter for proposed
fixes and double SWE-Agent's precision.
*Relation:* TECH + COMP. Generated tests filter agent patches, which is complementary to Repro's behaviour diff.

**9.4 [V] Otter: Generating Tests from Issues to Validate SWE Patches**
Toufique Ahmed, Jatin Ganhotra, Rangeet Pan, Avraham Shinnar, Saurabh Sinha, Martin Hirzel. ICML 2025,
PMLR 267:752–771. arXiv:2502.05368.
(abs) Introduces TDD-Bench-Verified and Otter, which generates tests from issues using rule-based
checks/repair plus a self-reflective planner. It outperforms the state of the art and improves patch
generation.
*Relation:* TECH (claim → executable test generation).

**9.5 [V] Pynguin: Automated Unit Test Generation for Python**
Stephan Lukasczyk, Gordon Fraser. ICSE Companion 2022 (demo). DOI 10.1145/3510454.3516829.
**[V] An Empirical Study of Automated Unit Test Generation for Python.** Stephan Lukasczyk, Florian Kroiß, Gordon Fraser.
Empirical Software Engineering 2023. DOI 10.1007/s10664-022-10248-w.
(k) Search-based unit-test generation for Python, and an empirical study of its effectiveness, where
dynamic typing limits coverage.
*Relation:* TECH (Python test generation for differential inputs).

**9.6 [V] CodaMosa: Escaping Coverage Plateaus in Test Generation with Pre-trained Large Language Models**
Caroline Lemieux, Jeevana Priya Inala, Shuvendu K. Lahiri, Siddhartha Sen. ICSE 2023. DOI 10.1109/ICSE48619.2023.00085.
(k) When search-based Python test generation stalls, Codex is prompted for tests of under-covered functions.
*Relation:* TECH.

**9.7 [V] Hypothesis: A New Approach to Property-Based Testing**
David MacIver, Zac Hatfield-Dodds, and many contributors. Journal of Open Source Software, 2019. DOI 10.21105/joss.01891.
(k) A Python property-based testing library with integrated shrinking.
*Relation:* TECH. Repro's declared invariants can be executed as Hypothesis properties on both base and head.

**9.8 [V] Agentic Property-Based Testing: Finding Bugs Across the Python Ecosystem**
Muhammad Maaz, Liam DeVoe, Zac Hatfield-Dodds, Nicholas Carlini. arXiv:2510.09907. NeurIPS 2025 DL4Code
Workshop (per arXiv comment) **[S for venue]**.
(abs) An LLM agent infers properties, writes and runs Hypothesis tests, and reflects. Over 100 Python
packages, 56% of its reports were valid bugs. Of the 21 top-ranked reports, 86% were valid.
*Relation:* TECH. Supports LLM-inferred invariants checked by execution.

**9.9 [V] Large Language Models are Few-shot Testers: Exploring LLM-based General Bug Reproduction** (LIBRO)
Sungmin Kang, Juyeon Yoon, Shin Yoo. ICSE 2023. DOI 10.1109/ICSE48619.2023.00194. arXiv:2209.11515.
(abs) LLM-generated bug-reproducing tests from bug reports cover 33% of Defects4J cases (251/750), with
post-processing to rank validity.
*Relation:* TECH (claim/issue → test).

**9.10 [V] Feedback-Directed Random Test Generation** (Randoop)
Carlos Pacheco, Shuvendu K. Lahiri, Michael D. Ernst, Thomas Ball. ICSE 2007. DOI 10.1109/ICSE.2007.37.
**[V] EvoSuite: Automatic Test Suite Generation for Object-Oriented Software.** Gordon Fraser, Andrea Arcuri. ESEC/FSE 2011.
DOI 10.1145/2025113.2025179.
(k) The canonical random and search-based unit-test generators. They are used inside PATCH-SIM, DiffTGen,
BERT-style and SAM-style differential approaches.
*Relation:* Background.

**9.11 Evaluation substrates (all [V])**
- **Are Mutants a Valid Substitute for Real Faults in Software Testing?** René Just, Darioush Jalali, Laura
  Inozemtseva, Michael D. Ernst, Reid Holmes, Gordon Fraser. FSE 2014. DOI 10.1145/2635868.2635929.
  (k) Mutant detection correlates with real-fault detection.
  *Relation:* EVAL. Justifies mutation-injected "unexplained changes" as a catch-rate proxy.
- **Defects4J: A Database of Existing Faults to Enable Controlled Testing Studies for Java Programs.** René Just,
  Darioush Jalali, Michael D. Ernst. ISSTA 2014. DOI 10.1145/2610384.2628055.
  *Relation:* EVAL. This is the source of most PCA datasets; it is Java-only.
- **BugsInPy: A Database of Existing Bugs in Python Programs to Enable Controlled Testing and Debugging Studies.**
  Ratnadira Widyasari, Sheng Qin Sim, Camellia Lok, Haodi Qi, Jack Phan, Qijin Tay, Constance Tan, Fiona Wee, et al.
  ESEC/FSE 2020 (demo). DOI 10.1145/3368089.3417943.
  *Relation:* **EVAL.** A Python bug/fix dataset that matches Repro's target language.

---

## 10. Verification of the two items in the existing doc

**10.1 [V] arXiv:2601.07189 — "Standardization of Post-Publication Code Verification by Journals is Possible with the Support of the Community"**
Susana Lopez-Moreno, Eric Dolores-Cuenca, Sangil Kim. arXiv cs.LG, submitted 12 Jan 2026 (10 pages, 1 figure).
**What it actually says:**
- It is a **position paper**, not a survey. Its abstract opens: "This position paper argues that it is
  plausible for journals and conference proceedings to implement post-publication verification."
- Its domain is **machine-learning research reproducibility**. It is not about software changes or PRs.
- Section 2.1 tabulates the reproducibility policies of **11 ML/AI journals**: Artificial Intelligence;
  Data-centric Machine Learning Research; JAIR; JMLR; Machine Learning; Machine Learning: Science and
  Technology; Pattern Recognition; Neurocomputing; TMLR; IEEE TNNLS; IEEE TPAMI. The paper does not state
  the number 11; it comes from counting the list.
- Verbatim conclusion: "Overall, there are no post-publication verification mechanisms presently being done
  in any of these journals."
- It also reviews eight ML conferences ("non-exhaustive list") and three ACM-affiliated venues. Their
  measures are pre-publication only.
- It proposes extending ACM badges so that independent researchers can submit post-publication code
  replications, giving up to two visible verification badges per article.

**Verdict.** The existing doc's paraphrase ("2026 survey found no post-publication code verification in 11
journals") is substantively right but mislabels the paper. The suggested accurate wording: *"A 2026 position
paper reviewing the reproducibility policies of 11 ML journals found that none performs post-publication
code verification (Lopez-Moreno et al., arXiv:2601.07189)."* It is relevant to Repro only as an analogy
(verification after the fact versus before merge), so do not cite it as SE evidence.

**10.2 [V] PaperBench: Evaluating AI's Ability to Replicate AI Research**
Giulio Starace, Oliver Jaffe, Dane Sherburn, James Aung, Jun Shern Chan, Leon Maksin, Rachel Dias, Evan Mays,
Benjamin Kinsella, Wyatt Thompson, Johannes Heidecke, Amelia Glaese, Tejal Patwardhan. ICML 2025, PMLR 267:56843–56873.
arXiv:2504.01848.

**What it actually says (abstract):**
- Agents replicate 20 ICML 2024 Spotlight/Oral papers from scratch.
- Grading uses author co-developed hierarchical rubrics with 8,316 gradable tasks and an LLM judge, which is
  itself evaluated on a separate judge benchmark.
- "The best-performing tested agent, Claude 3.5 Sonnet (New) with open-source scaffolding, achieves an
  average replication score of 21.0%."
- Recruited ML PhDs were not outperformed by the models on a subset.

**Verdict.** The existing doc's paraphrase ("best agent replicated ~21%") is close but imprecise. 21.0% is an
*average rubric-weighted replication score*. It does **not** mean 21% of papers were replicated. Suggested
wording: *"the best agent tested (Claude 3.5 Sonnet (New)) achieved an average replication score of 21.0%"*.
The paper also uses an LLM judge validated against a judge benchmark, which is a useful precedent for
Repro's judge-validation RQ.

---

## Research gap and novelty argument

### What is not new (be upfront in a paper)

1. **Executing two versions and diffing behaviour.** This is old and well studied:
   - Differential testing (McKeeman 1998).
   - Behavioural regression testing: BERT (Orso & Xie 2008; Jin, Orso & Xie 2010), DiffGen (2008), and
     Evans & Savoia (2007).
   - Symbolic approaches: differential symbolic execution (2008), shadow symbolic execution (2016/2018) and
     regression verification (2009/2013).
   - Trace differencing: RPRISM (2009).
   - Behaviour-change detection for merges: SAM (2020/2024).
2. **Using execution behaviour to judge patch correctness.** This is established in APR:
   - PATCH-SIM (Xiong et al. 2018) is the clearest precedent, using test-execution trace similarity.
   - Other instances: DiffTGen (2017), Opad (2017), Invalidator (2023) and Shibboleth (2022).
3. **Differential testing of LLM-agent patches.** PatchDiff (Wang, Pradel & Liu, ICSE 2026) does exactly
   this on SWE-bench Verified. UTBoost (ACL 2025), Probe-to-Generate (ASE 2026) and Ahmed et al.
   (FSE-Companion 2026) quantify how weak tests let wrong agent patches through.
4. **Checking NL descriptions against changes.**
   - Quatrain (ASE 2022) correlates bug reports with patch descriptions.
   - Gong et al. (MSR 2026) measure PR message–code inconsistency in agent PRs, with eight types including
     "claims unimplemented changes".
   - Software change contracts (FSE 2012, ISSTA 2013, TOSEM 2015) formalise "intended change between
     versions" and check it.
   - Non-academic tools seen only in search snippets **[S]** ("hearsay", "NoWreck") statically check PR
     claims against diffs.
5. **RTS, impact analysis, flaky-test handling, LLM judges and citation grounding.** Each is mature
   (Sections 4, 5 and 8).

### What appears not to have been done (the defensible novelty)

The verified literature does not show a system or study that does all of the following. The combination,
together with the evaluation, is the contribution.

- **(N1) Reference-free, claim-relative behavioural oracle.** PatchDiff, DiffTGen, UTBoost, Probe-to-Generate
  and PATCH-SIM-style dynamic PCA all need a ground-truth patch or a failing bug test. BERT-style tools
  report raw behavioural differences and leave triage to the developer. Repro's rule is different:
  - every observed base→head behaviour delta must be *attributed* to a natural-language claim in the PR;
  - every behavioural claim must be *supported* by at least one observed delta;
  - anything else is flagged.
  This automates what change contracts required developers to write formally, and turns PR-MCI from a
  textual check (Gong et al.) into an *execution-grounded* one. **Closest prior work:** software change
  contracts (concept), BERT (mechanism) and PatchDiff (agent setting).
- **(N2) Evidence-constrained LLM adjudication.** Reviewer agents may only issue verdicts that cite
  engine-produced evidence IDs, and uncited verdicts are rejected. Grounded generation exists in NLP (ALCE,
  FActScore) and agent judges exist (Agent-as-a-Judge, ICML 2025). However, no SE work was found that
  forces a code-review verdict to cite *execution* artefacts, nor any that measures whether this reduces
  false flags or hallucinated approvals relative to diff-only LLM review.
- **(N3) An empirical comparison on agent PRs in the wild.** The study would measure catch rate and
  false-flag rate of execution-grounded versus diff-only LLM review on real agent PRs (AIDev). Existing ACR
  evaluations (SWR-Bench, Cihan et al., Lu et al.) and agent-patch studies (PatchDiff, UTBoost) evaluate
  either review *without execution* or execution *against a reference on benchmarks*, not both on
  in-the-wild PRs.

### Honest caveats

- **Novelty is in integration plus the explained-delta oracle, not in any single component.** Reviewers at
  ICSE/FSE will treat N1 as the core idea and ask for the following:
  - a precise definition of "behaviour delta" (what is observed, at what granularity, with what
    normalisation);
  - a definition of "explained by a claim" (claim decomposition, matching criteria, and who decides);
  - evidence that the oracle is not dominated by noise from flakiness, nondeterminism and legitimate
    refactors.
- **Without generated differential tests, Repro inherits the test-inadequacy problem.**
  - Shadow SE's TOSEM abstract notes that even patch-specific tests often exercise the same behaviour in old
    and new versions.
  - PatchDiff needed *generated* tests to expose its 29.6% of divergences.
  - A version that only re-runs existing selected tests risks low recall. A "differential test generation"
    stage, as in PatchDiff, BERT or SAM, using LLM generation filtered à la TestGen-LLM, is likely necessary
    for competitive catch rates.
- **Coverage gap.** Discovery of 2025–2026 work stopped early because the web-search budget was exhausted.
  A system very close to N1 or N2 may exist in that period (agent-PR verification is a hot area).

### Suggested follow-up searches (not run)

- "execution-grounded code review LLM" and "test-execution-aware code review agent".
- "agent pull request verification behavior differencing".
- "PR description claim verification execution".
- "regression oracle LLM explained change".
- Citing papers of PatchDiff (2503.15223) and of Gong et al. (2601.04886).
- The ICSE 2026, FSE 2026 and ASE 2026 programs for "agent PR" and "code review" sessions.
- Industrial tools: GitHub Copilot code review, CodeRabbit, Qodo, Graphite. These are not academic, but
  reviewers will ask about them.

---

## Candidate research questions

- **RQ1 (Prevalence).** How often do agent-authored Python PRs in the wild (AIDev subset) introduce
  base→head behaviour changes that their descriptions do not explain? How often do descriptions claim
  behaviour changes that are not observed? Compare with Gong et al.'s text-level PR-MCI rate (1.7%
  high-MCI).
- **RQ2 (Effectiveness).** On labelled sets, what are Repro's catch rate (recall on known-bad changes) and
  false-flag rate (on known-clean PRs) compared with:
  - (a) a diff-only LLM reviewer using the same model;
  - (b) a tests-only gate (CI pass/fail);
  - (c) an LLM reviewer given raw test logs without evidence IDs?
  The labelled sets are:
  - PatchDiff-labelled divergent SWE-bench Verified patches;
  - UTBoost/Probe-to-Generate corrected labels;
  - mutation-injected unexplained changes (justified by Just et al. 2014);
  - Gong et al.'s 974 annotated PRs, for claim mismatches;
  - clean PRs, following the SWR-Bench Clean-PR protocol.
- **RQ3 (Ablation).** Which evidence sources drive detection? Candidates are impact-selected existing tests,
  value-level trace diffs, generated differential tests, API/dependency/perf diffs, and declared or mined
  invariants. What does each cost in time?
- **RQ4 (Grounding).** Does requiring evidence-ID citations reduce unsupported verdicts? Measures include:
  - citation precision (cited evidence actually supports the verdict, checked mechanically);
  - hallucinated approvals;
  - verdict stability under order swap and resampling (per CodeJudgeBench and Wang et al. ACL 2024).
- **RQ5 (Noise).** How much of the flagged delta is due to flakiness and nondeterminism (test order, hash
  seed, time, network)? How effective are Repro's controls: DeFlaker-style coverage checks, pinned seeds,
  order control, and N reruns given Gruber et al.'s 170-rerun estimate?
- **RQ6 (Human value, optional and later).** Do Reproduction Cards change maintainers' accept/reject
  decisions or review time for agent PRs? Use a controlled study with a diff-only baseline.

---

## Candidate venues (dates verified on conf.researchr.org on 2026-10-13; all deadlines AoE)

| Venue | Where / when | Submission | Status / fit |
|---|---|---|---|
| **MSR 2027 Technical Papers** | Dublin, 26–27 Apr 2027 (co-located with ICSE 2027) | Abstract 20 Oct 2026; paper 23 Oct 2026; notification 8 Jan 2027 | **Open, 10 days away.** Good fit for an RQ1-style prevalence study on AIDev. Too soon for a full tool evaluation. Limit is 10 pages plus 2 of references. The site also lists Registered Reports and Data/Tool Showcase tracks; their dates were not checked. |
| **ISSTA 2027** | Singapore, 7–10 Sep 2027 | Mandatory abstract 8 Jan 2027; full paper 11 Jan 2027 | **Best near-term target** for the full system plus RQ2–RQ5. |
| **FSE 2027** | Shenzhen, 12–16 Jul 2027 | Full paper 2 Oct 2026 (extended to 3 Oct after a HotCRP outage) | **Closed.** FSE 2028 dates are not yet verified. |
| **ICSE 2027** | Dublin, 25 Apr–1 May 2027 | Abstract 23 Jun 2026; paper 30 Jun 2026 (single cycle) | **Closed.** The ICSE 2028 page was not accessible, so its dates are unverified. |
| **ASE 2026** | Munich, 12–16 Oct 2026 | — | Happening now. The ASE 2027 site was not yet online (404). |

Not verified, so no dates are given: ICST 2027, AIware 2027, and the FSE/ICSE Industry and Ideas/Visions
tracks. SWE-Bench+ shows AIware is receptive to agent-benchmark work.

---

## BibTeX ([V] entries only; only verified fields)

Notes on the BibTeX:
- `and others` marks author lists that were truncated in the verification record.
- Page numbers are included only where Crossref or PMLR returned them.
- arXiv-only items use `@misc`.

```bibtex
% ---------- 1. Agent patches & benchmarks ----------
@inproceedings{jimenez2024swebench,
  title     = {{SWE}-bench: Can Language Models Resolve Real-World {GitHub} Issues?},
  author    = {Jimenez, Carlos E. and Yang, John and Wettig, Alexander and Yao, Shunyu and Pei, Kexin and Press, Ofir and Narasimhan, Karthik},
  booktitle = {International Conference on Learning Representations (ICLR)},
  year      = {2024},
  eprint    = {2310.06770},
  archivePrefix = {arXiv}
}
@inproceedings{wang2026solvedissues,
  title     = {Are ``Solved Issues'' in {SWE}-bench Really Solved Correctly? An Empirical Study},
  author    = {Wang, You and Pradel, Michael and Liu, Zhongxin},
  booktitle = {Proceedings of the 2026 IEEE/ACM 48th International Conference on Software Engineering (ICSE)},
  year      = {2026},
  doi       = {10.1145/3744916.3764576},
  eprint    = {2503.15223},
  archivePrefix = {arXiv}
}
@misc{aleithan2024swebenchplus,
  title     = {{SWE}-Bench+: Enhanced Coding Benchmark for {LLMs}},
  author    = {Aleithan, Reem and Xue, Haoran and Mohajer, Mohammad Mahdi and Nnorom, Elijah and Uddin, Gias and Wang, Song},
  year      = {2024},
  eprint    = {2410.06992},
  archivePrefix = {arXiv}
}
@inproceedings{xue2026swebenchplus,
  title     = {{SWE}-Bench+: Enhanced {LLM} Coding Benchmark},
  author    = {Xue, Haoran and Aleithan, Reem and Enan, Nafid and Uddin, Gias and Wang, Song},
  booktitle = {Proceedings of the 3rd ACM International Conference on AI-Powered Software (AIware)},
  year      = {2026},
  doi       = {10.1145/3805760.3814924}
}
@inproceedings{yu2025utboost,
  title     = {{UTBoost}: Rigorous Evaluation of Coding Agents on {SWE}-Bench},
  author    = {Yu, Boxi and Zhu, Yuxuan and He, Pinjia and Kang, Daniel},
  booktitle = {Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)},
  year      = {2025},
  doi       = {10.18653/v1/2025.acl-long.189},
  eprint    = {2506.09289},
  archivePrefix = {arXiv}
}
@misc{ahmed2025testoverfitting,
  title     = {Investigating Test Overfitting on {SWE}-bench},
  author    = {Ahmed, Toufique and Ganhotra, Jatin and Shinnar, Avraham and Hirzel, Martin},
  year      = {2025},
  eprint    = {2511.16858},
  archivePrefix = {arXiv},
  note      = {FSE Companion 2026}
}
@misc{li2026probetogenerate,
  title     = {Probe to Generate: Program Variant-Guided Test Augmentation for Repository-Level Repair Benchmarks},
  author    = {Li, Chenglin and Xu, Yisen and Wang, Zehao and Tan, Shin Hwei and Chen, Tse-Hsun},
  year      = {2026},
  eprint    = {2604.01518},
  archivePrefix = {arXiv},
  note      = {Accepted at ASE 2026}
}
@misc{liang2025swebenchillusion,
  title     = {The {SWE}-Bench Illusion: When State-of-the-Art {LLMs} Remember Instead of Reason},
  author    = {Liang, Shanchao and Garg, Spandan and Zilouchian Moghaddam, Roshanak},
  year      = {2025},
  eprint    = {2506.12286},
  archivePrefix = {arXiv},
  note      = {NeurIPS 2025 Workshop (LAW)}
}
@inproceedings{zhong2026impossiblebench,
  title     = {{ImpossibleBench}: Measuring {LLMs}' Propensity of Exploiting Test Cases},
  author    = {Zhong, Ziqian and Raghunathan, Aditi and Carlini, Nicholas},
  booktitle = {International Conference on Learning Representations (ICLR)},
  year      = {2026},
  eprint    = {2510.20270},
  archivePrefix = {arXiv}
}
@inproceedings{liu2023evalplus,
  title     = {Is Your Code Generated by {ChatGPT} Really Correct? Rigorous Evaluation of Large Language Models for Code Generation},
  author    = {Liu, Jiawei and Xia, Chunqiu Steven and Wang, Yuyao and Zhang, Lingming},
  booktitle = {Advances in Neural Information Processing Systems (NeurIPS)},
  year      = {2023},
  eprint    = {2305.01210},
  archivePrefix = {arXiv}
}
@misc{rondon2025passerine,
  title     = {Evaluating Agent-based Program Repair at {Google}},
  author    = {Rondon, Pat and Wei, Renyao and Cambronero, Jos{\'e} and Cito, J{\"u}rgen and Sun, Aaron and Sanyam, Siddhant and Tufano, Michele and Chandra, Satish},
  year      = {2025},
  eprint    = {2501.07531},
  archivePrefix = {arXiv}
}
@inproceedings{yang2024sweagent,
  title     = {{SWE}-agent: Agent-Computer Interfaces Enable Automated Software Engineering},
  author    = {Yang, John and Jimenez, Carlos E. and Wettig, Alexander and Lieret, Kilian and Yao, Shunyu and Narasimhan, Karthik and Press, Ofir},
  booktitle = {Advances in Neural Information Processing Systems (NeurIPS)},
  year      = {2024},
  eprint    = {2405.15793},
  archivePrefix = {arXiv}
}

% ---------- 2. Patch correctness assessment ----------
@inproceedings{xiong2018patchsim,
  title     = {Identifying Patch Correctness in Test-Based Program Repair},
  author    = {Xiong, Yingfei and Liu, Xinyuan and Zeng, Muhan and Zhang, Lu and Huang, Gang},
  booktitle = {Proceedings of the 40th International Conference on Software Engineering (ICSE)},
  year      = {2018},
  doi       = {10.1145/3180155.3180182},
  eprint    = {1706.09120},
  archivePrefix = {arXiv}
}
@inproceedings{smith2015cure,
  title     = {Is the Cure Worse than the Disease? Overfitting in Automated Program Repair},
  author    = {Smith, Edward K. and Barr, Earl T. and Le Goues, Claire and Brun, Yuriy},
  booktitle = {Proceedings of the 2015 10th Joint Meeting on Foundations of Software Engineering (ESEC/FSE)},
  pages     = {532--543},
  year      = {2015},
  doi       = {10.1145/2786805.2786825}
}
@inproceedings{qi2015kali,
  title     = {An Analysis of Patch Plausibility and Correctness for Generate-and-Validate Patch Generation Systems},
  author    = {Qi, Zichao and Long, Fan and Achour, Sara and Rinard, Martin},
  booktitle = {Proceedings of the 2015 International Symposium on Software Testing and Analysis (ISSTA)},
  pages     = {24--36},
  year      = {2015},
  doi       = {10.1145/2771783.2771791}
}
@article{le2018overfitting,
  title     = {Overfitting in Semantics-Based Automated Program Repair},
  author    = {Le, Xuan Bach D. and Thung, Ferdian and Lo, David and Le Goues, Claire},
  journal   = {Empirical Software Engineering},
  year      = {2018},
  doi       = {10.1007/s10664-017-9577-2}
}
@inproceedings{xin2017difftgen,
  title     = {Identifying Test-Suite-Overfitted Patches through Test Case Generation},
  author    = {Xin, Qi and Reiss, Steven P.},
  booktitle = {Proceedings of the 26th ACM SIGSOFT International Symposium on Software Testing and Analysis (ISSTA)},
  pages     = {226--236},
  year      = {2017},
  doi       = {10.1145/3092703.3092718}
}
@inproceedings{yang2017opad,
  title     = {Better Test Cases for Better Automated Program Repair},
  author    = {Yang, Jinqiu and Zhikhartsev, Alexey and Liu, Yuefei and Tan, Lin},
  booktitle = {Proceedings of the 2017 11th Joint Meeting on Foundations of Software Engineering (ESEC/FSE)},
  pages     = {831--841},
  year      = {2017},
  doi       = {10.1145/3106237.3106274}
}
@inproceedings{wang2020apca,
  title     = {Automated Patch Correctness Assessment: How Far Are We?},
  author    = {Wang, Shangwen and Wen, Ming and Lin, Bo and Wu, Hongjun and Qin, Yihao and Zou, Deqing and Mao, Xiaoguang and Jin, Hai},
  booktitle = {Proceedings of the 35th IEEE/ACM International Conference on Automated Software Engineering (ASE)},
  pages     = {968--980},
  year      = {2020},
  doi       = {10.1145/3324884.3416590}
}
@inproceedings{tian2020representation,
  title     = {Evaluating Representation Learning of Code Changes for Predicting Patch Correctness in Program Repair},
  author    = {Tian, Haoye and Liu, Kui and Kabor{\'e}, Abdoul Kader and Koyuncu, Anil and Li, Li and Klein, Jacques and Bissyand{\'e}, Tegawend{\'e} F.},
  booktitle = {Proceedings of the 35th IEEE/ACM International Conference on Automated Software Engineering (ASE)},
  year      = {2020},
  doi       = {10.1145/3324884.3416532}
}
@article{tian2023panther,
  title     = {The Best of Both Worlds: Combining Learned Embeddings with Engineered Features for Accurate Prediction of Correct Patches},
  author    = {Tian, Haoye and Liu, Kui and Li, Yinghua and Kabor{\'e}, Abdoul Kader and Koyuncu, Anil and Habib, Andrew and Li, Li and Wen, Junhao and others},
  journal   = {ACM Transactions on Software Engineering and Methodology},
  year      = {2023},
  doi       = {10.1145/3576039},
  eprint    = {2203.08912},
  archivePrefix = {arXiv}
}
@article{tian2022bats,
  title     = {Predicting Patch Correctness Based on the Similarity of Failing Test Cases},
  author    = {Tian, Haoye and Li, Yinghua and Pian, Weiguo and Kabor{\'e}, Abdoul Kader and Liu, Kui and Habib, Andrew and Klein, Jacques and Bissyand{\'e}, Tegawend{\'e} F.},
  journal   = {ACM Transactions on Software Engineering and Methodology},
  year      = {2022},
  doi       = {10.1145/3511096}
}
@inproceedings{tian2022quatrain,
  title     = {Is this Change the Answer to that Problem? Correlating Descriptions of Bug and Code Changes for Evaluating Patch Correctness},
  author    = {Tian, Haoye and Tang, Xunzhu and Habib, Andrew and Wang, Shangwen and Liu, Kui and Xia, Xin and Klein, Jacques and Bissyand{\'e}, Tegawend{\'e} F.},
  booktitle = {Proceedings of the 37th IEEE/ACM International Conference on Automated Software Engineering (ASE)},
  year      = {2022},
  doi       = {10.1145/3551349.3556914},
  eprint    = {2208.04125},
  archivePrefix = {arXiv}
}
@inproceedings{ghanbari2022shibboleth,
  title     = {Patch Correctness Assessment in Automated Program Repair Based on the Impact of Patches on Production and Test Code},
  author    = {Ghanbari, Ali and Marcus, Andrian},
  booktitle = {Proceedings of the 31st ACM SIGSOFT International Symposium on Software Testing and Analysis (ISSTA)},
  pages     = {654--665},
  year      = {2022},
  doi       = {10.1145/3533767.3534368}
}
@article{lecong2023invalidator,
  title     = {Invalidator: Automated Patch Correctness Assessment via Semantic and Syntactic Reasoning},
  author    = {Le-Cong, Thanh and Luong, Duc-Minh and Le, Xuan Bach D. and Lo, David and Tran, Nhat-Hoa and Quang-Huy, Bui and Huynh, Quyet-Thang},
  journal   = {IEEE Transactions on Software Engineering},
  year      = {2023},
  doi       = {10.1109/TSE.2023.3255177},
  eprint    = {2301.01113},
  archivePrefix = {arXiv}
}
@article{zhou2024llm4patchcorrect,
  title     = {Leveraging Large Language Model for Automatic Patch Correctness Assessment},
  author    = {Zhou, Xin and Xu, Bowen and Kim, Kisub and Han, DongGyun and Nguyen, Hung Huu and Le-Cong, Thanh and He, Junda and Le, Bach and others},
  journal   = {IEEE Transactions on Software Engineering},
  year      = {2024},
  doi       = {10.1109/TSE.2024.3452252}
}
@article{zhang2024appt,
  title     = {{APPT}: Boosting Automated Patch Correctness Prediction via Fine-Tuning Pre-Trained Models},
  author    = {Zhang, Quanjun and Fang, Chunrong and Sun, Weisong and Liu, Yan and He, Tieke and Hao, Xiaodong and Chen, Zhenyu},
  journal   = {IEEE Transactions on Software Engineering},
  year      = {2024},
  doi       = {10.1109/TSE.2024.3354969}
}
@misc{zhang2024llmaprslr,
  title     = {A Systematic Literature Review on Large Language Models for Automated Program Repair},
  author    = {Zhang, Quanjun and Fang, Chunrong and Xie, Yang and Ma, YuXiang and Sun, Weisong and Yang, Yun and Chen, Zhenyu},
  year      = {2024},
  eprint    = {2405.01466},
  archivePrefix = {arXiv}
}
@article{legoues2019apr,
  title     = {Automated Program Repair},
  author    = {Le Goues, Claire and Pradel, Michael and Roychoudhury, Abhik},
  journal   = {Communications of the ACM},
  year      = {2019},
  doi       = {10.1145/3318162}
}

% ---------- 3. Differential / regression verification ----------
@inproceedings{evans2007differential,
  title     = {Differential Testing: A New Approach to Change Detection},
  author    = {Evans, Robert B. and Savoia, Alberto},
  booktitle = {Proceedings of the 6th Joint Meeting of the European Software Engineering Conference and the ACM SIGSOFT Symposium on the Foundations of Software Engineering (ESEC/FSE)},
  year      = {2007},
  doi       = {10.1145/1287624.1287707}
}
@inproceedings{orso2008bert,
  title     = {{BERT}: {BEhavioral} Regression Testing},
  author    = {Orso, Alessandro and Xie, Tao},
  booktitle = {Proceedings of the 2008 International Workshop on Dynamic Analysis (WODA)},
  year      = {2008},
  doi       = {10.1145/1401827.1401835}
}
@inproceedings{jin2010bert,
  title     = {Automated Behavioral Regression Testing},
  author    = {Jin, Wei and Orso, Alessandro and Xie, Tao},
  booktitle = {2010 Third International Conference on Software Testing, Verification and Validation (ICST)},
  pages     = {137--146},
  year      = {2010},
  doi       = {10.1109/ICST.2010.64}
}
@inproceedings{taneja2008diffgen,
  title     = {{DiffGen}: Automated Regression Unit-Test Generation},
  author    = {Taneja, Kunal and Xie, Tao},
  booktitle = {2008 23rd IEEE/ACM International Conference on Automated Software Engineering (ASE)},
  year      = {2008},
  doi       = {10.1109/ASE.2008.60}
}
@inproceedings{person2008dse,
  title     = {Differential Symbolic Execution},
  author    = {Person, Suzette and Dwyer, Matthew B. and Elbaum, Sebastian and P{\u{a}}s{\u{a}}reanu, Corina S.},
  booktitle = {Proceedings of the 16th ACM SIGSOFT International Symposium on Foundations of Software Engineering (FSE)},
  pages     = {226--237},
  year      = {2008},
  doi       = {10.1145/1453101.1453131}
}
@article{person2011dise,
  title     = {Directed Incremental Symbolic Execution},
  author    = {Person, Suzette and Yang, Guowei and Rungta, Neha and Khurshid, Sarfraz},
  journal   = {ACM SIGPLAN Notices (PLDI 2011)},
  year      = {2011},
  doi       = {10.1145/1993316.1993558}
}
@inproceedings{palikareva2016shadow,
  title     = {Shadow of a Doubt: Testing for Divergences Between Software Versions},
  author    = {Palikareva, Hristina and Kuchta, Tomasz and Cadar, Cristian},
  booktitle = {Proceedings of the 38th International Conference on Software Engineering (ICSE)},
  pages     = {1181--1192},
  year      = {2016},
  doi       = {10.1145/2884781.2884845}
}
@article{kuchta2018shadow,
  title     = {Shadow Symbolic Execution for Testing Software Patches},
  author    = {Kuchta, Tomasz and Palikareva, Hristina and Cadar, Cristian},
  journal   = {ACM Transactions on Software Engineering and Methodology},
  volume    = {27},
  number    = {3},
  year      = {2018},
  doi       = {10.1145/3208952}
}
@inproceedings{marinescu2013katch,
  title     = {{KATCH}: High-Coverage Testing of Software Patches},
  author    = {Marinescu, Paul Dan and Cadar, Cristian},
  booktitle = {Proceedings of the 2013 9th Joint Meeting on Foundations of Software Engineering (ESEC/FSE)},
  year      = {2013},
  doi       = {10.1145/2491411.2491438}
}
@inproceedings{godlin2009regression,
  title     = {Regression Verification},
  author    = {Godlin, Benny and Strichman, Ofer},
  booktitle = {Proceedings of the 46th Annual Design Automation Conference (DAC)},
  year      = {2009},
  doi       = {10.1145/1629911.1630034}
}
@article{godlin2013regression,
  title     = {Regression Verification: Proving the Equivalence of Similar Programs},
  author    = {Godlin, Benny and Strichman, Ofer},
  journal   = {Software Testing, Verification and Reliability},
  volume    = {23},
  number    = {3},
  pages     = {241--258},
  doi       = {10.1002/stvr.1472}
}
@inproceedings{lahiri2012symdiff,
  title     = {{SYMDIFF}: A Language-Agnostic Semantic Diff Tool for Imperative Programs},
  author    = {Lahiri, Shuvendu K. and Hawblitzel, Chris and Kawaguchi, Ming and Reb{\^e}lo, Henrique},
  booktitle = {Computer Aided Verification (CAV), Lecture Notes in Computer Science},
  year      = {2012},
  doi       = {10.1007/978-3-642-31424-7_54}
}
@inproceedings{lahiri2013dac,
  title     = {Differential Assertion Checking},
  author    = {Lahiri, Shuvendu K. and McMillan, Kenneth L. and Sharma, Rahul and Hawblitzel, Chris},
  booktitle = {Proceedings of the 2013 9th Joint Meeting on Foundations of Software Engineering (ESEC/FSE)},
  year      = {2013},
  doi       = {10.1145/2491411.2491452}
}
@inproceedings{jackson1994semanticdiff,
  title     = {Semantic Diff: A Tool for Summarizing the Effects of Modifications},
  author    = {Jackson, Daniel and Ladd, David A.},
  booktitle = {Proceedings International Conference on Software Maintenance (ICSM)},
  year      = {1994},
  doi       = {10.1109/ICSM.1994.336770}
}
@inproceedings{hoffman2009rprism,
  title     = {Semantics-Aware Trace Analysis},
  author    = {Hoffman, Kevin J. and Eugster, Patrick and Jagannathan, Suresh},
  booktitle = {Proceedings of the 30th ACM SIGPLAN Conference on Programming Language Design and Implementation (PLDI)},
  year      = {2009},
  doi       = {10.1145/1542476.1542527}
}
@inproceedings{qi2012changecontracts,
  title     = {Software Change Contracts},
  author    = {Qi, Dawei and Yi, Jooyong and Roychoudhury, Abhik},
  booktitle = {Proceedings of the ACM SIGSOFT 20th International Symposium on the Foundations of Software Engineering (FSE)},
  year      = {2012},
  doi       = {10.1145/2393596.2393622}
}
@inproceedings{yi2013changecontracts,
  title     = {Expressing and Checking Intended Changes via Software Change Contracts},
  author    = {Yi, Jooyong and Qi, Dawei and Tan, Shin Hwei and Roychoudhury, Abhik},
  booktitle = {Proceedings of the 2013 International Symposium on Software Testing and Analysis (ISSTA)},
  year      = {2013},
  doi       = {10.1145/2483760.2483772}
}
@article{yi2015changecontracts,
  title     = {Software Change Contracts},
  author    = {Yi, Jooyong and Qi, Dawei and Tan, Shin Hwei and Roychoudhury, Abhik},
  journal   = {ACM Transactions on Software Engineering and Methodology},
  year      = {2015},
  doi       = {10.1145/2729973}
}
@article{ernst2001daikon,
  title     = {Dynamically Discovering Likely Program Invariants to Support Program Evolution},
  author    = {Ernst, Michael D. and Cockrell, Jake and Griswold, William G. and Notkin, David},
  journal   = {IEEE Transactions on Software Engineering},
  year      = {2001},
  doi       = {10.1109/32.908957}
}
@article{dasilva2024sam,
  title     = {Detecting Semantic Conflicts with Unit Tests},
  author    = {Da Silva, L{\'e}uson and Borba, Paulo and Maciel, Toni and Mahmood, Wardah and Berger, Thorsten and Moisakis, Jo{\~a}o and Gomes, Aldiberg and Leite, Vin{\'i}cius},
  journal   = {Journal of Systems and Software},
  year      = {2024},
  doi       = {10.1016/j.jss.2024.112070},
  eprint    = {2310.02395},
  archivePrefix = {arXiv}
}
@misc{pep669,
  title     = {{PEP} 669 -- Low Impact Monitoring for {CPython}},
  author    = {Shannon, Mark},
  year      = {2021},
  howpublished = {\url{https://peps.python.org/pep-0669/}},
  note      = {Status: Final; Python 3.12}
}
@misc{crosshair_diffbehavior,
  title     = {{CrossHair} diffbehavior: Find differences in the behavior of two functions},
  howpublished = {\url{https://crosshair.readthedocs.io/en/latest/diff_behavior.html}},
  note      = {Software documentation; no associated paper}
}

% ---------- 4. Impact analysis & RTS ----------
@inproceedings{gligoric2015ekstazi,
  title     = {Practical Regression Test Selection with Dynamic File Dependencies},
  author    = {Gligoric, Milos and Eloussi, Lamyaa and Marinov, Darko},
  booktitle = {Proceedings of the 2015 International Symposium on Software Testing and Analysis (ISSTA)},
  pages     = {211--222},
  year      = {2015},
  doi       = {10.1145/2771783.2771784}
}
@inproceedings{legunsen2016static,
  title     = {An Extensive Study of Static Regression Test Selection in Modern Software Evolution},
  author    = {Legunsen, Owolabi and Hariri, Farah and Shi, August and Lu, Yafeng and Zhang, Lingming and Marinov, Darko},
  booktitle = {Proceedings of the 2016 24th ACM SIGSOFT International Symposium on Foundations of Software Engineering (FSE)},
  year      = {2016},
  doi       = {10.1145/2950290.2950361}
}
@inproceedings{legunsen2017starts,
  title     = {{STARTS}: {STAtic} Regression Test Selection},
  author    = {Legunsen, Owolabi and Shi, August and Marinov, Darko},
  booktitle = {2017 32nd IEEE/ACM International Conference on Automated Software Engineering (ASE)},
  year      = {2017},
  doi       = {10.1109/ASE.2017.8115710}
}
@article{yoo2012survey,
  title     = {Regression Testing Minimization, Selection and Prioritization: A Survey},
  author    = {Yoo, Shin and Harman, Mark},
  journal   = {Software Testing, Verification and Reliability},
  year      = {2012},
  doi       = {10.1002/stv.430}
}
@article{rothermel1997safe,
  title     = {A Safe, Efficient Regression Test Selection Technique},
  author    = {Rothermel, Gregg and Harrold, Mary Jean},
  journal   = {ACM Transactions on Software Engineering and Methodology},
  year      = {1997},
  doi       = {10.1145/248233.248262}
}
@inproceedings{machalica2019predictive,
  title     = {Predictive Test Selection},
  author    = {Machalica, Mateusz and Samylkin, Alex and Porth, Meredith and Chandra, Satish},
  booktitle = {2019 IEEE/ACM 41st International Conference on Software Engineering: Software Engineering in Practice (ICSE-SEIP)},
  pages     = {91--100},
  year      = {2019},
  doi       = {10.1109/ICSE-SEIP.2019.00018},
  eprint    = {1810.05286},
  archivePrefix = {arXiv}
}
@inproceedings{memon2017taming,
  title     = {Taming {Google}-Scale Continuous Testing},
  author    = {Memon, Atif and Gao, Zebao and Nguyen, Bao and Dhanda, Sanjeev and Nickell, Eric and Siemborski, Rob and Micco, John},
  booktitle = {2017 IEEE/ACM 39th International Conference on Software Engineering: Software Engineering in Practice Track (ICSE-SEIP)},
  pages     = {233--242},
  year      = {2017},
  doi       = {10.1109/ICSE-SEIP.2017.16}
}
@inproceedings{elbaum2014ci,
  title     = {Techniques for Improving Regression Testing in Continuous Integration Development Environments},
  author    = {Elbaum, Sebastian and Rothermel, Gregg and Penix, John},
  booktitle = {Proceedings of the 22nd ACM SIGSOFT International Symposium on Foundations of Software Engineering (FSE)},
  year      = {2014},
  doi       = {10.1145/2635868.2635910}
}
@article{ren2004chianti,
  title     = {Chianti: A Tool for Change Impact Analysis of {Java} Programs},
  author    = {Ren, Xiaoxia and Shah, Fenil and Tip, Frank and Ryder, Barbara G. and Chesley, Ophelia},
  journal   = {ACM SIGPLAN Notices (OOPSLA 2004)},
  year      = {2004},
  doi       = {10.1145/1035292.1029012}
}
@inproceedings{law2003pathimpact,
  title     = {Whole Program Path-Based Dynamic Impact Analysis},
  author    = {Law, James and Rothermel, Gregg},
  booktitle = {25th International Conference on Software Engineering (ICSE)},
  year      = {2003},
  doi       = {10.1109/ICSE.2003.1201210}
}
@article{li2013ciasurvey,
  title     = {A Survey of Code-Based Change Impact Analysis Techniques},
  author    = {Li, Bixin and Sun, Xiaobing and Leung, Hareton and Zhang, Sai},
  journal   = {Software Testing, Verification and Reliability},
  doi       = {10.1002/stvr.1475}
}

% ---------- 5. Flaky tests ----------
@inproceedings{luo2014flaky,
  title     = {An Empirical Analysis of Flaky Tests},
  author    = {Luo, Qingzhou and Hariri, Farah and Eloussi, Lamyaa and Marinov, Darko},
  booktitle = {Proceedings of the 22nd ACM SIGSOFT International Symposium on Foundations of Software Engineering (FSE)},
  year      = {2014},
  doi       = {10.1145/2635868.2635920}
}
@inproceedings{lam2019idflakies,
  title     = {{iDFlakies}: A Framework for Detecting and Partially Classifying Flaky Tests},
  author    = {Lam, Wing and Oei, Reed and Shi, August and Marinov, Darko and Xie, Tao},
  booktitle = {2019 12th IEEE Conference on Software Testing, Validation and Verification (ICST)},
  year      = {2019},
  doi       = {10.1109/ICST.2019.00038}
}
@article{parry2021flakysurvey,
  title     = {A Survey of Flaky Tests},
  author    = {Parry, Owain and Kapfhammer, Gregory M. and Hilton, Michael and McMinn, Phil},
  journal   = {ACM Transactions on Software Engineering and Methodology},
  year      = {2021},
  doi       = {10.1145/3476105}
}
@inproceedings{gruber2021pythonflaky,
  title     = {An Empirical Study of Flaky Tests in {Python}},
  author    = {Gruber, Martin and Lukasczyk, Stephan and Krois{\ss}, Florian and Fraser, Gordon},
  booktitle = {2021 14th IEEE Conference on Software Testing, Verification and Validation (ICST)},
  year      = {2021},
  doi       = {10.1109/ICST49551.2021.00026},
  eprint    = {2101.09077},
  archivePrefix = {arXiv}
}
@inproceedings{bell2018deflaker,
  title     = {{DeFlaker}: Automatically Detecting Flaky Tests},
  author    = {Bell, Jonathan and Legunsen, Owolabi and Hilton, Michael and Eloussi, Lamyaa and Yung, Tifany and Marinov, Darko},
  booktitle = {Proceedings of the 40th International Conference on Software Engineering (ICSE)},
  year      = {2018},
  doi       = {10.1145/3180155.3180164}
}
@inproceedings{shi2016nondex,
  title     = {Detecting Assumptions on Deterministic Implementations of Non-deterministic Specifications},
  author    = {Shi, August and Gyori, Alex and Legunsen, Owolabi and Marinov, Darko},
  booktitle = {2016 IEEE International Conference on Software Testing, Verification and Validation (ICST)},
  year      = {2016},
  doi       = {10.1109/ICST.2016.40}
}
@inproceedings{gruber2022flakysurvey,
  title     = {A Survey on How Test Flakiness Affects Developers and What Support They Need To Address It},
  author    = {Gruber, Martin and Fraser, Gordon},
  booktitle = {2022 IEEE Conference on Software Testing, Verification and Validation (ICST)},
  year      = {2022},
  doi       = {10.1109/ICST53961.2022.00020},
  eprint    = {2203.00483},
  archivePrefix = {arXiv}
}
@inproceedings{wang2022ipflakies,
  title     = {{iPFlakies}: A Framework for Detecting and Fixing {Python} Order-Dependent Flaky Tests},
  author    = {Wang, Ruixin and Chen, Yang and Lam, Wing},
  booktitle = {2022 IEEE/ACM 44th International Conference on Software Engineering: Companion Proceedings (ICSE-Companion)},
  year      = {2022},
  doi       = {10.1109/ICSE-Companion55297.2022.9793801}
}
@inproceedings{gruber2023flapy,
  title     = {{FlaPy}: Mining Flaky {Python} Tests at Scale},
  author    = {Gruber, Martin and Fraser, Gordon},
  booktitle = {2023 IEEE/ACM 45th International Conference on Software Engineering: Companion Proceedings (ICSE-Companion)},
  year      = {2023},
  doi       = {10.1109/ICSE-Companion58688.2023.00039}
}

% ---------- 6. AI code & agent PRs ----------
@misc{li2025aidev,
  title     = {The Rise of {AI} Teammates in Software Engineering ({SE}) 3.0: How Autonomous Coding Agents Are Reshaping Software Engineering},
  author    = {Li, Hao and Zhang, Haoxiang and Hassan, Ahmed E.},
  year      = {2025},
  eprint    = {2507.15003},
  archivePrefix = {arXiv}
}
@misc{watanabe2025agenticprs,
  title     = {On the Use of Agentic Coding: An Empirical Study of Pull Requests on {GitHub}},
  author    = {Watanabe, Miku and Li, Hao and Kashiwa, Yutaro and Reid, Brittany and Iida, Hajimu and Hassan, Ahmed E.},
  year      = {2025},
  eprint    = {2509.14745},
  archivePrefix = {arXiv}
}
@misc{ehsani2026agentfail,
  title     = {Where Do {AI} Coding Agents Fail? An Empirical Study of Failed Agentic Pull Requests in {GitHub}},
  author    = {Ehsani, Ramtin and Pathak, Sakshi and Rawal, Shriya and Al Mujahid, Abdullah and Imran, Mia Mohammad and Chatterjee, Preetha},
  year      = {2026},
  eprint    = {2601.15195},
  archivePrefix = {arXiv},
  note      = {Accepted at MSR 2026}
}
@misc{gong2026prmci,
  title     = {Analyzing Message-Code Inconsistency in {AI} Coding Agent-Authored Pull Requests},
  author    = {Gong, Jingzhi and Pinna, Giovanni and Bian, Yixin and Zhang, Jie M.},
  year      = {2026},
  eprint    = {2601.04886},
  archivePrefix = {arXiv},
  note      = {MSR 2026 Mining Challenge Track}
}
@inproceedings{pearce2022asleep,
  title     = {Asleep at the Keyboard? Assessing the Security of {GitHub Copilot}'s Code Contributions},
  author    = {Pearce, Hammond and Ahmad, Baleegh and Tan, Benjamin and Dolan-Gavitt, Brendan and Karri, Ramesh},
  booktitle = {2022 IEEE Symposium on Security and Privacy (SP)},
  year      = {2022},
  doi       = {10.1109/SP46214.2022.9833571},
  eprint    = {2108.09293},
  archivePrefix = {arXiv}
}
@inproceedings{perry2023insecure,
  title     = {Do Users Write More Insecure Code with {AI} Assistants?},
  author    = {Perry, Neil and Srivastava, Megha and Kumar, Deepak and Boneh, Dan},
  booktitle = {Proceedings of the 2023 ACM SIGSAC Conference on Computer and Communications Security (CCS)},
  year      = {2023},
  doi       = {10.1145/3576915.3623157}
}
@misc{becker2025metr,
  title     = {Measuring the Impact of Early-2025 {AI} on Experienced Open-Source Developer Productivity},
  author    = {Becker, Joel and Rush, Nate and Barnes, Elizabeth and Rein, David},
  year      = {2025},
  eprint    = {2507.09089},
  archivePrefix = {arXiv}
}
@inproceedings{liang2024usability,
  title     = {A Large-Scale Survey on the Usability of {AI} Programming Assistants: Successes and Challenges},
  author    = {Liang, Jenny T. and Yang, Chenyang and Myers, Brad A.},
  booktitle = {Proceedings of the IEEE/ACM 46th International Conference on Software Engineering (ICSE)},
  year      = {2024},
  doi       = {10.1145/3597503.3608128}
}
@article{barke2023grounded,
  title     = {Grounded {Copilot}: How Programmers Interact with Code-Generating Models},
  author    = {Barke, Shraddha and James, Michael B. and Polikarpova, Nadia},
  journal   = {Proceedings of the ACM on Programming Languages (OOPSLA)},
  year      = {2023},
  doi       = {10.1145/3586030}
}

% ---------- 7. Code review ----------
@inproceedings{bacchelli2013mcr,
  title     = {Expectations, Outcomes, and Challenges of Modern Code Review},
  author    = {Bacchelli, Alberto and Bird, Christian},
  booktitle = {2013 35th International Conference on Software Engineering (ICSE)},
  year      = {2013},
  doi       = {10.1109/ICSE.2013.6606617}
}
@inproceedings{sadowski2018google,
  title     = {Modern Code Review: A Case Study at {Google}},
  author    = {Sadowski, Caitlin and S{\"o}derberg, Emma and Church, Luke and Sipko, Michal and Bacchelli, Alberto},
  booktitle = {Proceedings of the 40th International Conference on Software Engineering: Software Engineering in Practice (ICSE-SEIP)},
  year      = {2018},
  doi       = {10.1145/3183519.3183525}
}
@inproceedings{mcintosh2014review,
  title     = {The Impact of Code Review Coverage and Code Review Participation on Software Quality: A Case Study of the {Qt}, {VTK}, and {ITK} Projects},
  author    = {McIntosh, Shane and Kamei, Yasutaka and Adams, Bram and Hassan, Ahmed E.},
  booktitle = {Proceedings of the 11th Working Conference on Mining Software Repositories (MSR)},
  year      = {2014},
  doi       = {10.1145/2597073.2597076}
}
@inproceedings{tufano2021review,
  title     = {Towards Automating Code Review Activities},
  author    = {Tufano, Rosalia and Pascarella, Luca and Tufano, Michele and Poshyvanyk, Denys and Bavota, Gabriele},
  booktitle = {2021 IEEE/ACM 43rd International Conference on Software Engineering (ICSE)},
  year      = {2021},
  doi       = {10.1109/ICSE43902.2021.00027}
}
@inproceedings{li2022codereviewer,
  title     = {Automating Code Review Activities by Large-Scale Pre-training},
  author    = {Li, Zhiyu and Lu, Shuai and Guo, Daya and Duan, Nan and Jannu, Shailesh and Jenks, Grant and Majumder, Deep and Green, Jared and others},
  booktitle = {Proceedings of the 30th ACM Joint European Software Engineering Conference and Symposium on the Foundations of Software Engineering (ESEC/FSE)},
  year      = {2022},
  doi       = {10.1145/3540250.3549081},
  eprint    = {2203.09095},
  archivePrefix = {arXiv}
}
@inproceedings{froemmgen2024resolving,
  title     = {Resolving Code Review Comments with Machine Learning},
  author    = {Froemmgen, Alexander and Austin, Jacob and Choy, Peter and Ghelani, Nimesh and Kharatyan, Lera and Surita, Gabriela and Khrapko, Elena and Lamblin, Pascal and others},
  booktitle = {Proceedings of the 46th International Conference on Software Engineering: Software Engineering in Practice (ICSE-SEIP)},
  year      = {2024},
  doi       = {10.1145/3639477.3639746}
}
@inproceedings{vijayvergiya2024autocommenter,
  title     = {{AI}-Assisted Assessment of Coding Practices in Modern Code Review},
  author    = {Vijayvergiya, Manushree and Salawa, Ma{\l}gorzata and Budiseli{\'c}, Ivan and Zheng, Dan and Lamblin, Pascal and Ivankovi{\'c}, Marko and Carin, Juanjo and Lewko, Mateusz and others},
  booktitle = {Proceedings of the 1st ACM International Conference on AI-Powered Software (AIware)},
  year      = {2024},
  doi       = {10.1145/3664646.3665664},
  eprint    = {2405.13565},
  archivePrefix = {arXiv}
}
@inproceedings{cihan2025acrpractice,
  title     = {Automated Code Review in Practice},
  author    = {Cihan, Umut and Haratian, Vahid and {\.I}{\c{c}}{\"o}z, Arda and G{\"u}l, Mert Kaan and Devran, {\"O}mercan and Bayendur, Emircan Furkan and U{\c{c}}ar, Baykal Mehmet and T{\"u}z{\"u}n, Eray},
  booktitle = {2025 IEEE/ACM 47th International Conference on Software Engineering: Software Engineering in Practice (ICSE-SEIP)},
  year      = {2025},
  doi       = {10.1109/ICSE-SEIP66354.2025.00043},
  eprint    = {2412.18531},
  archivePrefix = {arXiv}
}
@misc{lu2025defectacr,
  title     = {Towards Practical Defect-Focused Automated Code Review},
  author    = {Lu, Junyi and Jiang, Lili and Li, Xiaojia and Fang, Jianbing and Zhang, Fengjun and Yang, Li and Zuo, Chun},
  year      = {2025},
  eprint    = {2505.17928},
  archivePrefix = {arXiv},
  note      = {ICML 2025 (per arXiv comment)}
}
@misc{zeng2025swrbench,
  title     = {{SWR-Bench}: Assessing {LLM} Performance in Real-World Code Review Comment Generation},
  author    = {Zeng, Zhengran and Shi, Ruikai and Han, Keke and Li, Yixin and Sun, Kaicheng and Wang, Yidong and Yu, Zhuohao and Xie, Rui and Ye, Wei and Zhang, Shikun},
  year      = {2025},
  eprint    = {2509.01494},
  archivePrefix = {arXiv},
  note      = {FSE 2026 Research Papers}
}
@misc{abreu2024drs,
  title     = {Moving Faster and Reducing Risk: Using {LLMs} in Release Deployment},
  author    = {Abreu, Rui and Murali, Vijayaraghavan and Rigby, Peter C. and Maddila, Chandra and Sun, Weiyan and Ge, Jun and Chinniah, Kaavya and Mockus, Audris and others},
  year      = {2024},
  eprint    = {2410.06351},
  archivePrefix = {arXiv}
}

% ---------- 8. LLM-as-judge & grounding ----------
@inproceedings{zheng2023judging,
  title     = {Judging {LLM}-as-a-Judge with {MT}-Bench and {Chatbot Arena}},
  author    = {Zheng, Lianmin and Chiang, Wei-Lin and Sheng, Ying and Zhuang, Siyuan and Wu, Zhanghao and Zhuang, Yonghao and Lin, Zi and Li, Zhuohan and others},
  booktitle = {Advances in Neural Information Processing Systems (NeurIPS) Datasets and Benchmarks Track},
  year      = {2023},
  eprint    = {2306.05685},
  archivePrefix = {arXiv}
}
@inproceedings{wang2024unfair,
  title     = {Large Language Models are not Fair Evaluators},
  author    = {Wang, Peiyi and Li, Lei and Chen, Liang and Cai, Zefan and Zhu, Dawei and Lin, Binghuai and Cao, Yunbo and Kong, Lingpeng and others},
  booktitle = {Proceedings of the 62nd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)},
  year      = {2024},
  doi       = {10.18653/v1/2024.acl-long.511},
  eprint    = {2305.17926},
  archivePrefix = {arXiv}
}
@misc{gu2024judgesurvey,
  title     = {A Survey on {LLM}-as-a-Judge},
  author    = {Gu, Jiawei and Jiang, Xuhui and Shi, Zhichao and Tan, Hexiang and Zhai, Xuehao and Xu, Chengjin and Li, Wei and Shen, Yinghan and others},
  year      = {2024},
  eprint    = {2411.15594},
  archivePrefix = {arXiv}
}
@inproceedings{tong2024codejudge,
  title     = {{CodeJudge}: Evaluating Code Generation with Large Language Models},
  author    = {Tong, Weixi and Zhang, Tianyi},
  booktitle = {Proceedings of the 2024 Conference on Empirical Methods in Natural Language Processing (EMNLP)},
  year      = {2024},
  doi       = {10.18653/v1/2024.emnlp-main.1118},
  eprint    = {2410.02184},
  archivePrefix = {arXiv}
}
@misc{jiang2025codejudgebench,
  title     = {{CodeJudgeBench}: Benchmarking {LLM}-as-a-Judge for Coding Tasks},
  author    = {Jiang, Hongchao and Chen, Yiming and Cao, Yushi and Lee, Hung-yi and Tan, Robby T.},
  year      = {2025},
  eprint    = {2507.10535},
  archivePrefix = {arXiv}
}
@article{wang2025judgese,
  title     = {Can {LLMs} Replace Human Evaluators? An Empirical Study of {LLM}-as-a-Judge in Software Engineering},
  author    = {Wang, Ruiqi and Guo, Jiyu and Gao, Cuiyun and Fan, Guodong and Chong, Chun Yong and Xia, Xin},
  journal   = {Proceedings of the ACM on Software Engineering (ISSTA)},
  year      = {2025},
  doi       = {10.1145/3728963},
  eprint    = {2502.06193},
  archivePrefix = {arXiv}
}
@misc{ahmed2024annotation,
  title     = {Can {LLMs} Replace Manual Annotation of Software Engineering Artifacts?},
  author    = {Ahmed, Toufique and Devanbu, Premkumar and Treude, Christoph and Pradel, Michael},
  year      = {2024},
  eprint    = {2408.05534},
  archivePrefix = {arXiv}
}
@inproceedings{zhuge2025agentjudge,
  title     = {Agent-as-a-Judge: Evaluate Agents with Agents},
  author    = {Zhuge, Mingchen and Zhao, Changsheng and Ashley, Dylan R. and others},
  booktitle = {Proceedings of the 42nd International Conference on Machine Learning (ICML)},
  series    = {PMLR},
  volume    = {267},
  pages     = {80569--80611},
  year      = {2025},
  eprint    = {2410.10934},
  archivePrefix = {arXiv}
}
@inproceedings{gao2023alce,
  title     = {Enabling Large Language Models to Generate Text with Citations},
  author    = {Gao, Tianyu and Yen, Howard and Yu, Jiatong and Chen, Danqi},
  booktitle = {Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing (EMNLP)},
  year      = {2023},
  doi       = {10.18653/v1/2023.emnlp-main.398},
  eprint    = {2305.14627},
  archivePrefix = {arXiv}
}
@inproceedings{min2023factscore,
  title     = {{FActScore}: Fine-grained Atomic Evaluation of Factual Precision in Long Form Text Generation},
  author    = {Min, Sewon and Krishna, Kalpesh and Lyu, Xinxi and Lewis, Mike and Yih, Wen-tau and Koh, Pang Wei and Iyyer, Mohit and Zettlemoyer, Luke and others},
  booktitle = {Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing (EMNLP)},
  year      = {2023},
  doi       = {10.18653/v1/2023.emnlp-main.741},
  eprint    = {2305.14251},
  archivePrefix = {arXiv}
}
@inproceedings{dhuliawala2024cove,
  title     = {Chain-of-Verification Reduces Hallucination in Large Language Models},
  author    = {Dhuliawala, Shehzaad and Komeili, Mojtaba and Xu, Jing and Raileanu, Roberta and Li, Xian and Celikyilmaz, Asli and Weston, Jason},
  booktitle = {Findings of the Association for Computational Linguistics: ACL 2024},
  year      = {2024},
  doi       = {10.18653/v1/2024.findings-acl.212},
  eprint    = {2309.11495},
  archivePrefix = {arXiv}
}
@inproceedings{huang2024selfcorrect,
  title     = {Large Language Models Cannot Self-Correct Reasoning Yet},
  author    = {Huang, Jie and Chen, Xinyun and Mishra, Swaroop and Zheng, Huaixiu Steven and Yu, Adams Wei and Song, Xinying and Zhou, Denny},
  booktitle = {International Conference on Learning Representations (ICLR)},
  year      = {2024},
  eprint    = {2310.01798},
  archivePrefix = {arXiv}
}

% ---------- 9. Test generation & evaluation substrates ----------
@inproceedings{alshahwan2024testgenllm,
  title     = {Automated Unit Test Improvement using Large Language Models at {Meta}},
  author    = {Alshahwan, Nadia and Chheda, Jubin and Finogenova, Anastasia and Gokkaya, Beliz and Harman, Mark and Harper, Inna and Marginean, Alexandru and Sengupta, Shubho and others},
  booktitle = {Companion Proceedings of the 32nd ACM International Conference on the Foundations of Software Engineering (FSE Companion)},
  year      = {2024},
  doi       = {10.1145/3663529.3663839},
  eprint    = {2402.09171},
  archivePrefix = {arXiv}
}
@inproceedings{foster2025ach,
  title     = {Mutation-Guided {LLM}-based Test Generation at {Meta}},
  author    = {Foster, Christopher and Gulati, Abhishek and Harman, Mark and Harper, Inna and Mao, Ke and Ritchey, Jillian and Robert, Herv{\'e} and Sengupta, Shubho},
  booktitle = {Proceedings of the 33rd ACM International Conference on the Foundations of Software Engineering (FSE Companion)},
  year      = {2025},
  doi       = {10.1145/3696630.3728544},
  eprint    = {2501.12862},
  archivePrefix = {arXiv},
  note      = {Author order per arXiv; Crossref lists a different order -- verify against ACM DL}
}
@inproceedings{mundler2024swtbench,
  title     = {{SWT-Bench}: Testing and Validating Real-World Bug-Fixes with Code Agents},
  author    = {M{\"u}ndler, Niels and M{\"u}ller, Mark Niklas and He, Jingxuan and Vechev, Martin},
  booktitle = {Advances in Neural Information Processing Systems (NeurIPS)},
  year      = {2024},
  eprint    = {2406.12952},
  archivePrefix = {arXiv}
}
@inproceedings{ahmed2025otter,
  title     = {Otter: Generating Tests from Issues to Validate {SWE} Patches},
  author    = {Ahmed, Toufique and Ganhotra, Jatin and Pan, Rangeet and Shinnar, Avraham and Sinha, Saurabh and Hirzel, Martin},
  booktitle = {Proceedings of the 42nd International Conference on Machine Learning (ICML)},
  series    = {PMLR},
  volume    = {267},
  pages     = {752--771},
  year      = {2025},
  eprint    = {2502.05368},
  archivePrefix = {arXiv}
}
@inproceedings{lukasczyk2022pynguin,
  title     = {Pynguin: Automated Unit Test Generation for {Python}},
  author    = {Lukasczyk, Stephan and Fraser, Gordon},
  booktitle = {Proceedings of the ACM/IEEE 44th International Conference on Software Engineering: Companion Proceedings (ICSE-Companion)},
  year      = {2022},
  doi       = {10.1145/3510454.3516829}
}
@article{lukasczyk2023pythontestgen,
  title     = {An Empirical Study of Automated Unit Test Generation for {Python}},
  author    = {Lukasczyk, Stephan and Kroi{\ss}, Florian and Fraser, Gordon},
  journal   = {Empirical Software Engineering},
  year      = {2023},
  doi       = {10.1007/s10664-022-10248-w}
}
@inproceedings{lemieux2023codamosa,
  title     = {{CodaMosa}: Escaping Coverage Plateaus in Test Generation with Pre-trained Large Language Models},
  author    = {Lemieux, Caroline and Inala, Jeevana Priya and Lahiri, Shuvendu K. and Sen, Siddhartha},
  booktitle = {2023 IEEE/ACM 45th International Conference on Software Engineering (ICSE)},
  year      = {2023},
  doi       = {10.1109/ICSE48619.2023.00085}
}
@article{maciver2019hypothesis,
  title     = {Hypothesis: A New Approach to Property-Based Testing},
  author    = {MacIver, David and Hatfield-Dodds, Zac and {Many Contributors}},
  journal   = {Journal of Open Source Software},
  year      = {2019},
  doi       = {10.21105/joss.01891}
}
@misc{maaz2025agenticpbt,
  title     = {Agentic Property-Based Testing: Finding Bugs Across the {Python} Ecosystem},
  author    = {Maaz, Muhammad and DeVoe, Liam and Hatfield-Dodds, Zac and Carlini, Nicholas},
  year      = {2025},
  eprint    = {2510.09907},
  archivePrefix = {arXiv},
  note      = {NeurIPS 2025 Deep Learning for Code Workshop (per arXiv comment)}
}
@inproceedings{kang2023libro,
  title     = {Large Language Models are Few-shot Testers: Exploring {LLM}-based General Bug Reproduction},
  author    = {Kang, Sungmin and Yoon, Juyeon and Yoo, Shin},
  booktitle = {2023 IEEE/ACM 45th International Conference on Software Engineering (ICSE)},
  year      = {2023},
  doi       = {10.1109/ICSE48619.2023.00194},
  eprint    = {2209.11515},
  archivePrefix = {arXiv}
}
@inproceedings{pacheco2007randoop,
  title     = {Feedback-Directed Random Test Generation},
  author    = {Pacheco, Carlos and Lahiri, Shuvendu K. and Ernst, Michael D. and Ball, Thomas},
  booktitle = {29th International Conference on Software Engineering (ICSE'07)},
  year      = {2007},
  doi       = {10.1109/ICSE.2007.37}
}
@inproceedings{fraser2011evosuite,
  title     = {{EvoSuite}: Automatic Test Suite Generation for Object-Oriented Software},
  author    = {Fraser, Gordon and Arcuri, Andrea},
  booktitle = {Proceedings of the 19th ACM SIGSOFT Symposium and the 13th European Conference on Foundations of Software Engineering (ESEC/FSE)},
  year      = {2011},
  doi       = {10.1145/2025113.2025179}
}
@inproceedings{just2014mutants,
  title     = {Are Mutants a Valid Substitute for Real Faults in Software Testing?},
  author    = {Just, Ren{\'e} and Jalali, Darioush and Inozemtseva, Laura and Ernst, Michael D. and Holmes, Reid and Fraser, Gordon},
  booktitle = {Proceedings of the 22nd ACM SIGSOFT International Symposium on Foundations of Software Engineering (FSE)},
  year      = {2014},
  doi       = {10.1145/2635868.2635929}
}
@inproceedings{just2014defects4j,
  title     = {{Defects4J}: A Database of Existing Faults to Enable Controlled Testing Studies for {Java} Programs},
  author    = {Just, Ren{\'e} and Jalali, Darioush and Ernst, Michael D.},
  booktitle = {Proceedings of the 2014 International Symposium on Software Testing and Analysis (ISSTA)},
  year      = {2014},
  doi       = {10.1145/2610384.2628055}
}
@inproceedings{widyasari2020bugsinpy,
  title     = {{BugsInPy}: A Database of Existing Bugs in {Python} Programs to Enable Controlled Testing and Debugging Studies},
  author    = {Widyasari, Ratnadira and Sim, Sheng Qin and Lok, Camellia and Qi, Haodi and Phan, Jack and Tay, Qijin and Tan, Constance and Wee, Fiona and others},
  booktitle = {Proceedings of the 28th ACM Joint Meeting on European Software Engineering Conference and Symposium on the Foundations of Software Engineering (ESEC/FSE)},
  year      = {2020},
  doi       = {10.1145/3368089.3417943}
}

% ---------- 10. Items from the existing doc ----------
@misc{lopezmoreno2026postpub,
  title     = {Standardization of Post-Publication Code Verification by Journals is Possible with the Support of the Community},
  author    = {Lopez-Moreno, Susana and Dolores-Cuenca, Eric and Kim, Sangil},
  year      = {2026},
  eprint    = {2601.07189},
  archivePrefix = {arXiv}
}
@inproceedings{starace2025paperbench,
  title     = {{PaperBench}: Evaluating {AI}'s Ability to Replicate {AI} Research},
  author    = {Starace, Giulio and Jaffe, Oliver and Sherburn, Dane and Aung, James and Chan, Jun Shern and Maksin, Leon and Dias, Rachel and Mays, Evan and Kinsella, Benjamin and Thompson, Wyatt and Heidecke, Johannes and Glaese, Amelia and Patwardhan, Tejal},
  booktitle = {Proceedings of the 42nd International Conference on Machine Learning (ICML)},
  series    = {PMLR},
  volume    = {267},
  pages     = {56843--56873},
  year      = {2025},
  eprint    = {2504.01848},
  archivePrefix = {arXiv}
}
```

Notes on what the BibTeX excludes:
- McKeeman 1998 is [S] only. Its secondary-source data is Digital Technical Journal 10(1):100–107.
- SWE-bench Verified is a blog post that could not be fetched. Cite it as `@misc` with the URL
  https://openai.com/index/introducing-swe-bench-verified/ after reading it.
