---
title: "Did It Say So? Execution-Grounded Verification of AI-Agent Pull Requests against Their Claims"
status: "Draft 0 (J10 prepared, 2026-10-18). The study's results do not exist yet: every result section says what will fill it. Not for submission as is."
bibliography: references.bib
---

# Abstract

AI coding agents now open pull requests whose descriptions say what the change does.
Reviewers, human or model, mostly judge that text and the diff, and project tests often cannot
tell a correct patch from a plausible one. We present Repro, a tool that reproduces a change
before it merges. It runs the base and the head of a pull request in isolated snapshots, runs
the base twice to measure noise, and records what each side does: test outcomes and
function-level behaviour traces. It then diffs that behaviour, together with tests, public
API, dependencies and timings, and checks declared invariants. Reviewer agents judge each of
the change's claims, and a judgement stands only if it cites the evidence Repro produced and
the citation checks out mechanically. Each change gets a Reproduction Card: VERIFIED, FLAGGED
or UNVERIFIABLE, with its evidence and an explicit list of what could not be checked.

We describe the design and a pre-registered evaluation on fresh agent-written patches against
four baselines. *[Results pending: the study (S2) waits for its labels and budget; see §6.]*

# 1 Introduction

A pull request written by an agent comes with a claim: "fixes the crash on a status code the
standard library does not know". Whether the claim holds is a question about behaviour, and
the evidence most reviews rest on is not behavioural. A diff-only reviewer reads the change. A
CI-only gate runs the tests that exist, and the tests that would catch a wrong fix often do not
exist yet.

The problem is measurable on benchmarks. Of 877 patches that passed SWE-bench Verified's
tests, PatchDiff found 29.6% behaving differently from the maintainers' fix on generated tests.
Of the 77 it labelled by hand, 22 were incorrect, 4 correct and 51 uncertain
[@wang2026solvedissues]. UTBoost found tasks
whose tests were too weak to tell correct patches from incorrect ones [@yu2025utboost].
Language models also remember the benchmark: given only an issue, models name the files to
change far more accurately on SWE-bench Verified than on repositories outside it
[@liang2025swebenchillusion].

Repro takes the opposite starting point to a reviewer that reads. It reproduces the change: it
runs both sides and records what the code does, then asks whether the claims match what
happened. Two ideas make this usable as a gate:

- **Every behaviour difference must be explained by a claim, and every behavioural claim must
  be supported by a difference.** A difference no claim explains, or a claim nothing supports,
  is a reference-free signal that a change is wrong or misdescribed. It needs no gold patch and
  no specification. It generalises change contracts [@qi2012changecontracts;
  @yi2015changecontracts] from formal specifications to natural-language claims, and
  message–code inconsistency [@gong2026prmci] from text to execution.
- **A model's verdict counts only when it cites engine-produced evidence that checks out.**
  The verdict schema allows only the IDs of evidence about the claim. Quotes must be exact
  substrings of that evidence. A verdict that fails validation is rejected, never kept without
  its citations.

We make these contributions, each stated as a claim the evaluation tests rather than assumes:

1. **C1, the explained-delta oracle**: a reference-free, claim-relative check of agent pull
   requests (§3).
2. **C2, evidence-constrained adjudication**: verdicts that must cite verifiable evidence, with
   bias controls (§3.5).
3. **C3, function-level noise control**: an A/A′ pair of base runs, with the second in reverse
   order and a different hash seed, and a canonical encoding of arguments and results. This
   makes function-level diffs stable enough to act on (§3.3).
4. **C4, an empirical study** on fresh agent patches against CI-only, diff-only and agentic
   static reviewers and PR-Agent, with a registered protocol (§4). *[Results pending.]*
5. **C5, an artifact**: an open-source tool (Apache-2.0), replayable event logs, and the
   study's code and data (§7).

# 2 Related work

**Differential testing of program versions.** BERT generates tests on the old and new versions
and reports the behaviour that differs, leaving triage to the developer [@orso2008bert;
@jin2010bert]. Differential unit testing does the same at unit level [@evans2007differential].
Repro uses existing tests and its own differential probes, and judges the differences against
claims instead of leaving them.

**Patch correctness.** In program repair, plausible patches pass the tests and are often wrong.
PATCH-SIM judges a patch by test-execution similarity, assuming a failing test for the bug
[@xiong2018patchsim]. PatchDiff contrasts agent patches with the gold patch on generated tests
[@wang2026solvedissues], which needs the gold patch. Repro needs neither: it works on any pull
request with a natural-language description.

**Claims and intent.** Software change contracts check formally specified intended changes
across versions [@qi2012changecontracts; @yi2013changecontracts; @yi2015changecontracts].
PR-MCI measures text-level message–code inconsistency in agent pull requests [@gong2026prmci].
Testora, the closest work, generates tests for the old and new versions of a Python pull
request and asks a model whether each difference is intended, given the PR's text
[@pradel2025testora]. Repro differs in several ways:
- it adds function-level traces of the existing tests and probes;
- it works in both directions: unexplained differences, and claims nothing supports;
- it checks invariants, the public API, dependencies and timings;
- verdicts must cite evidence;
- it keeps an explicit inventory of what was not checked.

**Agent pull requests.** Corpora of agent-written pull requests now exist [@li2025aidev], as do
benchmarks whose freshness is controlled against contamination [@badertdinov2025swerebench].

**Noise.** Flaky tests and order dependence are common [@luo2014flaky; @parry2021flakysurvey].
In Python they have been studied at scale [@gruber2021pythonflaky]. Repro measures noise on
every run rather than assuming it away.

# 3 Repro

Repro is a pipeline whose every step emits events into an append-only log. The log is the
contract: the card is computed from the log alone, so any run can be replayed and its card
recomputed.

## 3.1 Snapshots and isolation

A change is two commits. Repro writes each into a snapshot from git's tree objects. The
snapshot has no `.git` directory and is never a working tree on the host, because the target is
untrusted code. Each side's environment is provisioned in two steps:
- the dependencies are installed from wheels, from the package index, with no build code run
  while the network is reachable;
- the project itself is then installed offline, in the sandbox.

Tests run in a sandbox whose level the card states:
- **L2**: a contained process, with network attempts detected by an audit hook;
- **L3**: a container with no network, a read-only root, no capabilities and resource limits;
- **L4**: the same under gVisor.

A run can also use a task's own environment image as it is, with the snapshot first on the
import path. Repro refuses to run when the image's installed copy of the project would be
imported instead of the change.

## 3.2 Selection and outcomes

Repro builds a per-test function map on base with its own `sys.monitoring` collector
[@pep669]. It selects:
- the tests that ran a changed function;
- the tests that import a module with module-level changes;
- the tests the change adds or edits.

Each selected test runs three times:
- **A**, on base;
- **A′**, on base again, in reverse order with another hash seed;
- **H**, on head.

A flip between base and head is rerun three times on both sides before it becomes evidence. A
test the change edited is also run in its base version against head. If that fails, an edit
may have hidden a regression. Removed tests, new skips and loosened assertions become
`test_change` evidence.

## 3.3 Function-level behaviour

During A, A′ and H, Repro traces the changed functions. For each call it records:
- the arguments, at entry;
- the result or exception, at exit;
- the arguments again, at exit, which reveals mutation.

Each is encoded canonically and within a budget. A difference between A and H that A and A′
agree on is a behaviour difference. A difference between A and A′ is noise, and the function's
observations in that test are marked unstable rather than compared. Each difference comes with
a reproducer: the test, and a preview of the call's encoded arguments and both results.

Probes add inputs the tests do not try. A model proposes arguments for the changed functions
without seeing the claims, and both versions run on them.

## 3.4 Other checks

Repro also diffs:
- the public API, with griffe;
- the dependencies, declared and installed;
- the timings, interleaved and with a measured A/A noise floor.

It checks the invariants the base commit declares in `repro.yml`.

## 3.5 Claims and verdicts

A reader agent splits the pull request's text into atomic claims, each tied to files of the
change. For each claim, a reviewer is given the evidence about the claim's files and the
diffs, inside delimited blocks marked as untrusted. It answers supported, contradicted or
unverifiable. Its schema's citations are an enumeration of that evidence's IDs, with at least
one required.

Validation checks four things:
- every cited item is about the claim;
- every quote is an exact substring of the evidence's rendering;
- a supported verdict does not rest only on unstable evidence;
- a claim that nothing changes is not supported while an unexplained stable difference
  stands.

A failed validation gets one retry, told why, then the verdict is rejected and listed as
missing.

Three further steps follow:
- a gap reviewer maps each still-unexplained difference to the claims that explain it, if any;
- contradicted verdicts are judged again with every list reversed, and a disagreement makes
  the verdict unverifiable;
- a QA pass withholds verdicts that cannot hold together.

When the commits name the model family that wrote the change, and every reviewer belongs to
it, the card says so.

## 3.6 The card

The status is computed deterministically from the log:
- **FLAGGED** when a claim is contradicted, a stable difference is unexplained, a test that
  passed fails, tests were weakened, an invariant fails, or the API breaks without a claim
  covering it;
- **UNVERIFIABLE** when the evidence is incomplete beyond a configured threshold;
- **VERIFIED** otherwise.

FLAGGED takes precedence: concrete evidence of a problem outweighs incompleteness. Every gap
item carries its origin. "Pre-existing" means also present on base, which Repro can say
because it ran base. Everything that could not be checked is a *missing* item with its reason
and what would resolve it; nothing unchecked is reported as a pass.

# 4 Evaluation design

The protocol is registered before any data on the main split exists
(`EVALUATION_PROTOCOL.md`, `PREREGISTRATION.md`). We summarise it here.

**Research questions:**
- **RQ1, effectiveness**: catch and false-flag rates against the baselines;
- **RQ2**: the contribution of each evidence source, by ablation;
- **RQ3, grounding and stability**;
- **RQ4, noise**;
- **RQ5, cost**;
- **RQ6**: behaviour on pull requests in the wild (exploratory).

**Data.** The main split S2 takes fresh tasks: SWE-rebench's monthly leaderboard splits
[@badertdinov2025swerebench], all after the reviewer model's knowledge cutoff (1 June 2024 for
`gpt-oss-120b`). It keeps the tasks whose environment pins Python 3.12 or newer, which Repro's
tracer needs, and that are graded with pytest: 351 of 411 candidates from the splits 2025_09
to 2026_03.

Patches are generated by us, at most two per task, from at least two scaffolds and two model
families. A two-call localize-and-repair scaffold in Agentless's shape [@xia2024agentless] is
built. A second scaffold is specified. A contaminated split, S1, on SWE-bench Verified, and a
memorisation probe after [@liang2025swebenchillusion], measure the effect of memory.

**Input contract.** Every system gets the repository at base, the agent's diff, and the claim:
the issue and the agent's summary. It gets nothing of the ground truth, not even the task's
identifier, which leads to the fix. A test plants a canary in every withheld field and checks
that none reaches Repro's command line, event log or card.

**Ground truth.**
- **Tier A** runs the task's hidden tests and full suite in its image, graded as SWE-bench
  grades.
- **Tier B** runs augmented and model-written differential tests against the gold patch and
  the candidate, 20 times each, and counts only stable tests.
- **People:** two annotators, blinded to every system's output, label what neither tier
  settles, plus 15% audits of each automatic label. Agreement is Cohen's κ [@cohen1960kappa],
  per source.

**Systems:**
- **B0**, CI-only: the project's suite on base and head;
- **B1**, a diff-only reviewer with Repro's model and budget;
- **B2**, a reviewer with read-only repository tools;
- **B3**, PR-Agent, pinned.

Testora is omitted where it does not reproduce, for stated reasons. Every LLM system runs five
times per patch.

**Analysis.**
- **Rates:** catch and false-flag rates on covered items, with coverage and both bounding
  conversions of UNVERIFIABLE.
- **Tests:** exact McNemar [@mcnemar1947] for Repro against each baseline, Holm-adjusted
  [@holm1979].
- **Intervals:** a cluster bootstrap over repositories.
- **Sample size:** at a discordance of 0.2 and a 10-point difference, the exact test needs 168
  incorrect patches for power 0.8, where the normal approximation [@connor1987mcnemar] says
  155. The target is 200 of each label.

The analysis is code, tested on hand-worked values, before any data.

# 5 Preliminary observations (development set, not results)

*These come from S0, the development set, which the protocol says is never reported as
results. They are listed because they shaped the design, and each is in the research log.*

- **Real suites carry noise that fixtures do not.** On two fresh tasks, Repro's cards were
  UNVERIFIABLE for stated reasons:
  - one suite is order-dependent: two tests fail when a third runs first, and the reversed
    A′ run exposed it;
  - the other task's changed function receives log records that carry the time, so its
    traced calls differed between two runs of the same code.

  A reviewer that runs each test once, in one order, would have compared evidence it could not
  trust.
- **A plausible wrong patch appeared in the first try.** Our scaffold, with Qwen 3.8, wrote a
  patch for one task that reads as a reasonable fix. CI-only passes it, since no existing test
  covers the case. Only the task's hidden test catches it.
- **The baselines' details matter.** An agentic reviewer's tool named `search` drew calls with
  the arguments of the model's built-in browser tool, and the provider refused them. The free
  tier's per-request token cap shaped the reviewer's reading.

*[§5 is replaced by the study's results: RQ1–RQ6, with tables and figures generated by
`python -m repro_bench.analysis` from the frozen labels.]*

# 6 Threats to validity

- **Construct.** "Correct" is relative to the issue and the gold behaviour, and hidden tests
  are weak or narrow. Two tiers, people, audits and sensitivity analyses address it.
- **Labels.** Annotator bias and many UNCERTAIN labels. Blinding, two annotators, κ and a
  published guideline address it.
- **Contamination.** The headline uses post-cutoff tasks only. A memorisation probe and the
  S1/S2 gap are reported.
- **Selection.** S2 keeps tasks whose environment runs Python 3.12 or newer (351 of 411),
  because Repro's tracer needs it.
- **Coverage.** Repro answers UNVERIFIABLE rather than pass unchecked evidence. Its rates are
  reported on covered items, with coverage and both bounding conversions beside them.
- **Budget.** The registered study needs about 100 million tokens, beyond a free tier's daily
  limits. A smaller study would be stated as under-powered, with its achieved power.

# 7 Availability

Repro is open source (Apache-2.0) at a public repository. Its releases carry wheels, and its
GitHub Action signs each card as an in-toto attestation. The study's code, protocol, guideline, locked prompts and
candidate list are in the same repository. A 30-minute kick-the-tires script runs the
deterministic pipeline on one fresh task without keys. The archive with a DOI accompanies the
results. *[Repository link anonymised for review.]*

# Disclosure

AI assistance was used in research, coding and writing. Every citation is checked against its
primary source by a human before submission.
