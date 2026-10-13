# Repro — Product

> Baseline v1 (phase A01, 2026-10-13). The evidence for statements about the market and the
> literature is in [`RESEARCH.md`](RESEARCH.md) and [`research/`](research/).

## One line

Repro runs **both sides** of every agent-written change, shows what actually changed in
behaviour, and checks each change against what the PR **claims**. It calls a change verified
only when the evidence says so.

> Not "does it work?", but **"what did it change, and did it say so?"**

## Problem

Coding agents now produce pull requests faster than people can review them. The bottleneck has
moved from *writing* code to *trusting* it:

- Copilot code review alone accounts for more than one in five code reviews on GitHub.
- High-AI teams report PR review time up 91% (Faros AI 2025).
- In the 2026 Stack Overflow survey, the most common condition for trusting AI output is
  "when I can easily verify the output" (48%).

A change can look convincing while doing the wrong thing:

- About 30% of "plausible" agent patches on SWE-bench Verified behave differently from the
  reference fix (PatchDiff, ICSE 2026).
- The most common inconsistency between an agent PR's description and its code is *claiming
  changes that were not made* (45.4% of inconsistent PRs; Gong et al., MSR 2026).

What teams have today:

| Option | What it tells you | What it misses |
|---|---|---|
| Read the diff | Text | Behaviour. A 6-line change can alter what 40 call sites do |
| CI | Whether the existing tests pass | Behaviour the tests don't assert. Whether the description is true. Tests the PR weakened |
| AI reviewers (diff-reading) | An opinion about the diff | They share the authoring agent's blind spot: no execution |
| AI reviewers (execution-capable, 2025–26: Codex review, Greptile TREX, Claude ultrareview, Ito, QA.tech) | Bugs found by running the head side | What changed relative to base. Whether each change was claimed. What could not be checked |

## Positioning

**For** developers and small teams merging code written by AI agents, **Repro is** a local-first
verification tool. It reproduces each change base-vs-head, attributes every observed behaviour
difference to a stated claim, and publishes a replayable card listing what is supported,
contradicted, unexplained and unchecked. **Unlike** AI reviewers that comment on the diff or hunt
for bugs on the head side, Repro compares both sides at function level, and every verdict cites
execution evidence you can replay on your own machine.

What Repro does **not** claim:

- It is not the first tool to execute PRs.
- It is not the first to diff two versions. BERT (2008–2010), PATCH-SIM (2018), PatchDiff (2026)
  and Testora (2026) did this before.
- Its contribution is the combination: a reference-free, claim-relative oracle, evidence-
  constrained verdicts, an explicit "missing" inventory, and local replay. It also measures that
  combination against the alternatives (see [`paper/README.md`](paper/README.md)).

### The wedge

1. **Unexplained behaviour change, at function level.** "Same input, different output" in the
   blast radius, for library and backend code. Any change no claim explains flags the PR.
2. **Per-claim verdicts and an explicit Missing list.** Each claim gets *supported*,
   *contradicted* or *unverifiable*, with cited evidence. Everything not checked is itemised
   with a reason.
3. **Fail-to-pass evidence for "fixes …" claims, computed automatically.** This is GitHub's own
   advice to reviewers ("require a test that fails on the pre-change behaviour"), done for them.
4. **Test-tampering detection.** Deleted or weakened tests, and base tests that fail on head.
5. **Independent, local-first, replayable.** It is not the agent grading itself and not a
   vendor cloud. Code stays on the machine, and every card regenerates from its event log.

## Users

1. **Primary:** developers running coding agents on their own repositories who need to merge
   agent PRs with confidence. CLI plus web cockpit, local.
2. **Secondary (Stage I+):** small teams and tech leads gating agent PRs in GitHub through a
   check run and a sticky comment.
3. **Research (Stage J):** researchers evaluating agent patch correctness. Repro's event logs
   and cards are reproducible artifacts.

## The core loop

```
PR / branch ─► READ ─► BUILD ─► RUN (base ‖ base′ ‖ head) ─► DIFF ─► CHECK ─► REVIEW ─► CARD
```

1. **Read:** parse the PR (description, commits, diff) into atomic claims C1…Cn, each with
   targets and a kind (fix / feature / refactor / no-change / perf / deps / test / docs).
2. **Build:** check out both sides as isolated snapshots, provision identical environments,
   build the symbol table and import graph, and compute the blast radius.
3. **Run:**
   - select the tests that exercise the blast radius;
   - run them on base twice (to measure noise) and on head, recording function-level behaviour;
   - generate probes for changed code that existing tests don't reach;
   - time everything untraced.
4. **Diff:** test outcomes (F2P / P2F / …), test-file changes, behaviour, API, dependencies,
   performance. Each difference becomes evidence with an ID, an origin (introduced or
   pre-existing) and a stability label.
5. **Check:** evaluate the invariants declared in `repro.yml`, read from base.
6. **Review:** agents judge each claim against the evidence and map every gap item to the claims
   that explain it. They must cite evidence IDs, and uncited verdicts are rejected.
7. **Card:** status is computed by deterministic rules, not by an LLM.

## The Reproduction Card

| Section | Content |
|---|---|
| **Claim** | Atomic claims C1…Cn from the PR |
| **Conditions** | Base/head SHAs, interpreter, lock digests, selected tests, seeds, isolation level and network enforcement, platform, Repro version, model IDs |
| **Gap** | Behavioural differences (behaviour, probe, outcome, test-change, API, dependency, perf), each with evidence, origin, stability and explained-by claims |
| **Verdicts** | Per claim: supported / contradicted / unverifiable, with cited evidence and agreement |
| **Invariants** | Result per declared invariant |
| **Missing** | What could not be verified, and why (taxonomy in ARCHITECTURE §6.1) |
| **Status** | `VERIFIED` · `FLAGGED` · `UNVERIFIABLE` |
| **Replay** | Event-log digest; `repro replay <run-id>` |

Rules:
- An **unexplained behaviour change always flags**.
- Something that could not be checked is **never** shown as a pass.
- A finding the engine cannot back with evidence does not appear on the card.

## `repro.yml` (MVP invariant set)

```yaml
invariants:
  - public_api_stable: { except: ["mypkg.experimental.*"] }
  - no_new_dependencies: true
  - no_network: true                       # head tests must not attempt network access
  - perf_budget: { max_regression: 0.20 }  # per selected test, CI-based, vs base
  - forbidden_paths: ["migrations/**", ".github/**"]
claims:
  require_explicit: true                   # PRs with no extractable claim -> UNVERIFIABLE
missing:
  max_uncovered_changed_symbols: 0.25      # above this fraction -> UNVERIFIABLE
```

Policy is always read from the **base** ref. If the PR edits `repro.yml`, that edit is itself a
flagged gap item.

## Scope by release

| Release | Scope |
|---|---|
| v0.2 (Stage B) | Cockpit on recorded logs |
| v0.3–v0.6 (C–F) | Local engine: static analysis, sandboxed two-sided runs, behaviour evidence, invariants, deterministic card. Useful without any LLM |
| v0.7 (G) | Claim extraction, evidence-constrained review, generated probes |
| **v1.0 (H)** | Hardened, installable, documented local tool. Exports: Markdown, JSON, in-toto, JUnit, SARIF |
| v1.1 (I) | GitHub: PR URL input, check run, sticky comment, signed attestation via Action |
| v1.2 (J) | Published benchmark and paper artifact |

## Non-goals (for now)

- **Generating fixes.** Repro verifies and never writes code to the target. Exposing evidence to
  agents through MCP is in the backlog (K03), but the verifier stays independent.
- **Generic bug-finding leaderboards.** Repro competes on "what changed and was it claimed", not
  on code-review comment F1.
- **Languages other than Python** before Stage K.
- **Hosted multi-tenant SaaS.** Repro is local-first.
- **Replacing CI.** Repro complements it.
- **Production traffic record/replay.** This space is occupied by Speedscale, Keploy and
  Signadot, and was abandoned by Tusk in 2026.

## Success metrics

**Headline (Stage J, ADR-0010):** on fresh, post-cutoff Python tasks with agent-generated patches
and adjudicated labels:
- catch rate (incorrect patches flagged);
- false-flag rate (correct patches flagged);
- coverage (share of patches that are not UNVERIFIABLE).

Each is reported against B0 CI-only, B1 diff-only LLM, B2 agentic static LLM, B3 PR-Agent and
Testora, with paired statistics. Results are broken down by defect class. Repro is expected to
win on silent behaviour change, unclaimed side effects and API breaks hidden by passing tests.
It is not expected to win on crash bugs, which every executing tool finds.

**Product (from v1.0):**
- median time to card on reference repositories;
- UNVERIFIABLE rate and its reasons;
- false flags reported by users;
- share of verdicts with valid citations (target 100%, enforced).
