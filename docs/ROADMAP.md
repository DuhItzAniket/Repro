# Repro — Roadmap

> Baseline v1 (phase A01, 2026-10-13). Supersedes the original M0–M8 milestone list (mapping
> at the end). The process is in [`process/SDLC.md`](process/SDLC.md): each phase ends with a
> phase record, a merged PR and a pushed `main`, and each stage ends with a gate, full CI and a
> tagged release.

**Status legend:** `planned` · `spec` · `in progress` · `done` · `dropped`
**Size:** S ≈ ≤1 day · M ≈ 1–3 days · L ≈ 3–5 days of focused work (L phases may be split)

## Overview

| Stage | Name | Phases | Release | Outcome |
|---|---|---|---|---|
| **A** | Foundation | A01–A08 | v0.1.0 | Monorepo, schema-as-contract, CI on Windows + Linux, risks measured |
| **B** | Cockpit on fixtures | B01–B12 | v0.2.0 | Complete animated cockpit driven only by a recorded event log |
| **C** | Engine core & live stream | C01–C08 | v0.3.0 | `repro run` shows a real repo's graph and blast radius live |
| **D** | Sandboxed two-sided execution | D01–D07 | v0.4.0 | Selected tests run on base and head in isolation, with outcome, test-change and perf evidence |
| **E** | Behaviour evidence | E01–E07 | v0.5.0 | A silent behaviour change is caught with no failing test |
| **F** | Policy & deterministic card | F01–F05 | v0.6.0 | Invariants and a complete card with no LLM involved |
| **G** | Agents | G01–G09 | v0.7.0 | Claims extracted, verdicts judged against cited evidence, generated probes |
| **H** | Hardening & first release | H01–H06 | **v1.0.0** | Installable, documented, hardened local tool |
| **I** | GitHub integration | I01–I04 | v1.1.0 | PR URL in, check run + sticky comment + signed attestation out |
| **J** | Evaluation & research | J01–J10 | v1.2.0 | Reproducible benchmark results and paper submission |
| **K** | Expansion (backlog) | K01–K05 | — | Unscheduled. Ordered by evidence from J |

76 scheduled phases (A–J) plus 5 backlog phases. Stages run in order. B and C could run in
parallel with two contributors, because B depends only on the schema (A04/A05).

```
A ──► B ──────────────┐
  └─► C ──► D ──► E ──► F ──► G ──► H ──► I ──► J
```

---

## Stage A — Foundation · v0.1.0

**Goal:** a reproducible, cross-platform workspace where the event schema is the single source
of truth. Measure the riskiest technical unknowns before building on them.

**Gate A (passed 2026-10-13, v0.1.0, record: [`phases/A-gate.md`](phases/A-gate.md)):** CI is
green on `ubuntu-latest` and `windows-latest` from a clean clone. Changing the
schema regenerates TS and Pydantic types, and CI fails on drift. Spike results are recorded in
ADRs or phase records.

| ID | Phase | Size | Depends | Status |
|---|---|---|---|---|
| A01 | Research, architecture & plan baseline | M | — | done |
| A02 | Toolchain & monorepo scaffold | M | A01 | done |
| A03 | Code-quality gates | S | A02 | done |
| A04 | Event schema v1 | M | A02 | done |
| A05 | Schema codegen & drift gate | M | A04 | done |
| A06 | CI pipeline & repository security | M | A03, A05 | done |
| A07 | Test-harness foundations & golden-log tooling | M | A05 | done |
| A08 | Feasibility spikes | M | A02 | done |

**A01 · Research, architecture & plan baseline**
- Deliverables: verified research notes (`docs/research/`), research synthesis, product
  definition, architecture, ADRs 0001–0012, threat model, test strategy, this roadmap,
  implementation plan, SDLC process, paper tracker, and repository hygiene files.
- Accept: all docs are cross-linked. Every external claim is tagged and sourced. Decisions that
  need the owner are listed as `proposed` ADRs. No personal data appears in the repo or in
  commit metadata.

**A02 · Toolchain & monorepo scaffold**
- Deliverables: pnpm workspace (`apps/web`, `packages/events`), uv workspace (`engine`,
  `bench`), pinned toolchain (`.python-version`, `packageManager`, `engines.node ≥ 22.12`),
  `.env.example`, cross-platform task entry points (pnpm scripts and `uv run` tasks; no bash
  in the critical path). CLAUDE.md Commands section filled in.
- Accept: on a clean clone on Windows and Linux, `pnpm install && uv sync` succeeds and
  `pnpm test` / `uv run pytest` run an empty-but-real suite. The interpreter is pinned
  explicitly; uv's default is not relied on.

**A03 · Code-quality gates**
- Deliverables: Ruff (lint + format), a strict type checker for the engine (mypy or pyright,
  chosen and recorded), Biome + `tsc --noEmit` strict for TS, optional pre-commit config, and
  `.editorconfig` alignment.
- Accept: one command per language reports zero issues on the scaffold. A deliberately broken
  file fails each gate (checked in a test or documented in the phase record).

**A04 · Event schema v1**
- Deliverables: JSON Schema 2020-12 for the envelope (core fields plus ADR-0003 fields if
  approved) and one schema per v1 kind (ARCHITECTURE §5.2). Evidence, claim, verdict and card
  schemas. A draft-07, `$ref`-free variant generator for agent output schemas. Schema docs.
- Accept: every kind has a schema with at least one valid and one invalid example, validated in
  tests. An "every kind has a schema" test passes.

**A05 · Schema codegen & drift gate**
- Deliverables (revised in A05, see ADR-0014): an in-house generator (`repro-events-codegen`)
  emitting TS types and strict Pydantic v2 models, both with a discriminated union over `kind`.
  Equivalence tests across JSON Schema, Pydantic and Ajv (TypeScript), plus round trip.
- Accept: `pnpm gen` / `uv run repro-events-codegen` regenerate deterministically, and CI fails
  on any diff between committed and regenerated types. Round-trip passes for all example events.

**A06 · CI pipeline & repository security**
- Deliverables: GitHub Actions workflow for lint, types, unit tests, schema drift and secret
  scanning (gitleaks) on an Ubuntu + Windows matrix. Dependency review and licence allow-list
  check. Caching for uv and pnpm. Branch-protection settings documented. Dependabot or Renovate.
- Accept: a PR with a fake secret or a disallowed licence fails CI. A clean PR passes on both
  OSes in under 10 minutes.

**A07 · Test-harness foundations & golden-log tooling**
- Deliverables: pytest + Hypothesis and Vitest + fast-check configured. JSONL event-log reader
  and validator CLI (`repro-events validate`). Log normaliser that strips IDs and timestamps.
  Golden-file approval helper. Scaffold of the scripted fixture-repo builder (TEST_STRATEGY §3).
- Accept: a sample log validates, normalises to a stable golden file, and the same golden
  passes on Windows and Linux (line endings and paths included).

**A08 · Feasibility spikes** (throwaway code; findings are the deliverable)
- Deliverables:
  1. `sys.monitoring` overhead microbenchmark: no tool / PY_START+DISABLE / local
     PY_START+PY_RETURN with argument encoding, on 3.12, 3.13 and 3.14.
  2. Docker sandbox round trip on Windows (Docker Desktop/WSL2) and Linux: snapshot → volume
     → `--network none` → pytest → results out, timed.
  3. uv environment provisioning inside a container for a medium repo, cold and warm, timed.
- Accept: numbers recorded with method and hardware class. ADR-0004 and ADR-0005 are updated
  with measured facts. Go/no-go and initial default budgets are written down.

---

## Stage B — Cockpit on fixtures · v0.2.0

**Goal:** the complete visual product, driven only by a recorded event log, built to the
DESIGN.md spec and performance budget.

**Gate B:** side by side with the reference frame at 6 s, it reads as the same visual family.
The reference log replays at ×1 at 60 fps on a mid laptop (measured, with the method recorded).
Scrubbing and all speeds work. All panels are driven only by events. Visual-regression,
allocation and bundle-size gates are active in CI.

| ID | Phase | Size | Depends | Status |
|---|---|---|---|---|
| B01 | Deterministic fixture generator & reference log | M | A07 | done |
| B02 | EventStore, projections, snapshots & clock | M | B01 | planned |
| B03 | App shell, tokens, fonts, header & progress | M | B02 | planned |
| B04 | Stage foundation & performance harness | M | B03 | planned |
| B05 | Dependency-web layer & bundles | L | B04 | planned |
| B06 | Ring layer (file-card atlas) | M | B04 | planned |
| B07 | Event-stream layer & callouts | M | B04 | planned |
| B08 | Panels I: feed, execution, agent workspace, behaviour field | L | B02, B03 | planned |
| B09 | Panels II: change routes, signals, dispatch, change×check index | L | B08 | planned |
| B10 | Replay controls & motion safety | M | B05–B09 | planned |
| B11 | Focus, evidence drawer & accessibility | M | B10 | planned |
| B12 | UI quality gate | M | B11 | planned |

**B01 · Deterministic fixture generator & reference log**
- Deliverables: a seeded generator (TS or Python) that produces a realistic run (1 PR, 4 claims,
  12 agents, about 150 files, 28 checks, 4 flagged, about 2–4k events) using only v1 kinds.
  Committed `apps/web/fixtures/demo-run.jsonl` and a stress fixture (10k edges, 2k concurrent
  streak events).
- Accept: same seed gives a byte-identical log. Both logs validate against the schema. Counts
  match the spec in a test.

**B02 · EventStore, projections, snapshots & clock**
- Deliverables: a columnar EventStore (typed arrays plus a payload array, gap detection), pure
  folded projections, snapshots every N events, seek, WindowIndex, and a presentation clock
  (live / replay / pause / speed).
- Accept: property tests pass, namely `fold(all) == fold(snapshot_k) + rest` for all k and
  random-seek equality with a linear fold. Header counters and the index footer come from one
  projection. Unknown kinds are tolerated.

**B03 · App shell, tokens, fonts, header & progress**
- Deliverables: Vite + Preact 11 + signals shell, CSS tokens from DESIGN.md, self-hosted
  JetBrains Mono variable woff2 with `OFL.txt`, layout grid (header, stage, 2×4 panels;
  < 1100px rule), header counters and the 7-segment stage progress bar.
- Accept: the layout matches DESIGN.md dimensions at 1440×900 and 1920×1080. Counters update
  from the fixture. The font licence file ships with the font.

**B04 · Stage foundation & performance harness**
- Deliverables: three.js `WebGLRenderer` host, `Layer` interface, `frame(t)` loop, adaptive DPR
  (≤ 2), perf HUD (frame-time percentiles, draw calls, instance counts), GPU-free render-model
  golden-test harness, and a stress-fixture benchmark run on a mid laptop.
- Accept: the empty stage plus HUD runs. Render-model hashes are stable across runs. A stress
  benchmark is recorded and decides whether the layer designs need changing before B05–B07.

**B05 · Dependency-web layer & bundles**
- Deliverables: layout worker (d3-force, node-hash-seeded positions, cached by graph hash),
  instanced anti-aliased edge quads with recency alpha in the shader, node markers for the
  blast radius, and Bézier bundles (8–20 curves, about 1.2 s fade) triggered by events.
- Accept: 10k edges at the frame budget on the stress fixture. The layout is identical across
  reloads. Bundles are pure functions of `(event, t)` (golden-tested).

**B06 · Ring layer (file-card atlas)**
- Deliverables: atlas worker (OffscreenCanvas 2D → ImageBitmap) from file contents, instanced
  card quads, closed-form rotation and 500 ms ease-out snap to the focused file, ticks and path
  labels.
- Accept: one draw call for the cards. Snap timing matches the spec in golden tests. The atlas
  builds off the main thread.

**B07 · Event-stream layer & callouts**
- Deliverables: an instanced streak ring buffer (≤ 2k live) with velocity-stretched tails and
  state tints, plus tooltip callouts (at most 2 visible).
- Accept: 2k streaks at the frame budget. Tint mapping follows DESIGN.md. Streak state at any
  `t` is reproducible after a scrub.

**B08 · Panels I** (investigation feed, execution lanes, agent workspace, behaviour diff field)
- Accept: each panel is a pure `draw(ctx, view, t)` that redraws only when dirty. View-model
  unit tests and per-panel screenshot tests pass.

**B09 · Panels II** (change routes, signals, agents/dispatch, change×check index)
- Accept: same as B08. The index footer and header counters can never disagree (single-projection
  test). Signals show the "illustrative until run completes" caption while partial.

**B10 · Replay controls & motion safety**
- Deliverables: transport controls (play/pause, ×0.5/×1/×4/×16, scrubber, jump to live).
  Global pause with Space. Wall-clock-clamped durations and the flash governor
  (ADR-0011). `prefers-reduced-motion` support.
- Accept: scrubbing anywhere gives the same frame as playing to that point (golden test). The
  ×16 burst fixture never exceeds the flash threshold. Reduced motion disables streaks and bundles.

**B11 · Focus, evidence drawer & accessibility**
- Deliverables: click/keyboard focus on rows, cells and nodes. Stage highlight and ring snap.
  An evidence drawer (plain, readable DOM) for raw diff, samples and verdict text. Parallel
  accessible DOM (`role="log"` with throttled announcements, semantic tables, labelled canvases).
- Accept: every focus action is reachable by keyboard. axe-core reports no serious violations.
  A screen reader announces feed summaries at the throttled rate.

**B12 · UI quality gate**
- Deliverables: Playwright visual regression (pinned image, SwiftShader, CI-only baselines,
  `renderAt(t)` test hook), allocation test (`frame()` ×1000 with flat heap), size-limit
  (300 kB gzip) on every PR, and a nightly perf job with relative-regression gating.
- Accept: all gates run in CI and fail on an injected regression of each type.

---

## Stage C — Engine core & live stream · v0.3.0

**Goal:** a real engine that persists and streams events, analyses a real repo statically, and
drives the cockpit live.

**Gate C:** `repro run --repo <small OSS lib> --base A --head B` shows that repo's real import
graph and blast radius in the cockpit live, and `repro replay` reproduces the same UI state.

| ID | Phase | Size | Depends | Status |
|---|---|---|---|---|
| C01 | Engine skeleton, configuration & CLI | S | A05 | planned |
| C02 | Storage & evidence store | M | C01 | planned |
| C03 | Event bus & orchestrator | M | C02 | planned |
| C04 | API & WebSocket transport | M | C03 | planned |
| C05 | Git layer: refs, diffs, worktrees, snapshots | M | C01 | planned |
| C06 | Symbol table & changed-symbol mapping | M | C05 | planned |
| C07 | Import graph & blast radius | M | C06 | planned |
| C08 | Live UI wiring & end-to-end | M | B12, C04, C07 | planned |

**C01** Typer CLI (`run`, `replay`, `serve`, `doctor`, `export`), settings (env plus
`~/.repro/config.toml`), structured logging, Windows-safe data paths. *Accept:* `repro doctor`
reports git, uv, Python and Docker capabilities on Windows and Linux.

**C02** SQLite schema and migrations (WAL, single batching writer, `BEGIN IMMEDIATE`), evidence
records, content-addressed artifact store, run registry. *Accept:* 100k events written and read
back in order. A crash mid-batch leaves a consistent DB (test). `UNIQUE(run_id, seq)` is enforced.

**C03** Stage DAG, job runner, cancellation, per-job timeouts, failure → `status: fail` events
plus missing items, guaranteed `run.finished`. *Accept:* golden-log test of a stub pipeline. A
cancelled run ends cleanly with a final event.

**C04** FastAPI REST and WebSocket with subscribe-before-replay, `caught_up` frame, batched
frames, per-client bounded queue and resync close, localhost binding. *Accept:* no gaps or
duplicates when a client connects mid-run (concurrency test). A slow client is dropped and
recovers with `?from=`.

**C05** Ref resolution, `-U0` diff parsing, worktrees with `-c core.longpaths=true` and robust
cleanup, `.git`-less snapshots via `git archive`. *Accept:* tests cover long paths, spaces,
CRLF repos, detached HEADs and locked-file cleanup on Windows.

**C06** `ast` symbol table, changed-lines → symbols on both sides, rename and move matching,
module-level changes, `symbol.changed` events. *Accept:* fixture repos with edits, renames,
moves, decorators and class-body changes map correctly (table-driven tests).

**C07** grimp import graph, downstream modules, blast radius with distance, `graph.*` and
`blast.computed` events. *Accept:* on fixture repos and one pinned real repo, the blast radius
matches hand-checked expectations.

**C08** UI WS client with gap detection and live/replay switch. `repro serve` serves the built
UI. End-to-end test on a real small repository. *Accept:* Gate C scenario passes in CI (Linux)
and manually on Windows.

---

## Stage D — Sandboxed two-sided execution · v0.4.0

**Goal:** run the right tests on both sides, honestly isolated, and turn outcomes, test edits
and timings into evidence.

**Gate D:** a branch that breaks one test shows exactly that test flipping (P2F) in Execution,
Change routes and the index. A branch that deletes or weakens a test is flagged as test tampering.
The sandbox escape suite passes at the level the card claims.

| ID | Phase | Size | Depends | Status |
|---|---|---|---|---|
| D01 | Sandbox abstraction & process isolation (L0–L2) | M | C03, A08 | planned |
| D02 | Container backend (L3) | M | D01 | planned |
| D03 | Environment provisioning | L | D02 | planned |
| D04 | Repro pytest plugin v1 & deterministic run config | M | D03 | planned |
| D05 | Test selection via per-test function map | M | D04, C07 | planned |
| D06 | Two-sided execution, outcome & test-change diff, flake control | L | D05 | planned |
| D07 | Performance pass | M | D06 | planned |

**D01** Process runner, minimal environment, Windows Job Objects / POSIX process groups and
rlimits, timeouts, kill and cleanup, `sandbox.ready` with isolation level. Audit-hook
detection. *Accept:* fork-bomb, memory-hog and timeout fixtures are contained. Detected network
and subprocess attempts become evidence.

**D02** Docker backend: `--network none`, read-only root, `/tmp` tmpfs mounted **`exec`** (A08:
the default `noexec` breaks real suites), cap-drop, non-root, limits, snapshot volumes. Capability detection in `repro doctor`. *Accept:* escape suite (raw `_socket`,
`ctypes`, subprocess `curl`, writes outside the work dir, host `.git` tampering) is blocked at
L3. The card reports `network: enforced` only here.

**D03** Project-type detection (uv / poetry / pdm / requirements / setup.py), same interpreter on
both sides (≥ 3.12, explicit), provisioning in the sandbox with index-only egress or offline
wheels, `--link-mode copy`, env cache keyed by lock digest, `environment_failed` path. A08
measured offline `uv sync` from a warm cache at 0.79 s vs 9.9 s cold, so the design is a
cache-populating step followed by offline installs. A documented base image with common CLI
tools is needed, because missing tools (A08: `less`) cause base-and-head failures that must
surface as environment items.
*Accept:* five fixture project types provision on both OSes. A broken install gives
UNVERIFIABLE with a reason, never a crash.

**D04** Plugin skeleton (stdlib-only, Python 3.12–3.15), results channel via output directory,
fixed seeds, `-o addopts=` override, net guard plus audit hook, JUnit capture. *Accept:* the
plugin's own test matrix passes on 3.12, 3.13, 3.14 and 3.15. The same test run twice gives the
same outcomes.

**D05** collect-map mode (PY_START per test, DISABLE elsewhere), selection rule (ARCHITECTURE
§4.1), cache, `test.selected` with reasons, `no_covering_test` items. *Accept:* on fixtures,
selected tests ⊇ the tests a human expects. Uncovered changed symbols are always listed.

**D06** A, A′ and H runs. F2P / P2P / P2F / F2F / new / removed / modified classification.
Reruns for flips. DeFlaker check. Base version of modified tests run on head. Test-file diff
(removed tests, skip/xfail added, assertions removed or weakened). *Accept:* the `honest-fix`,
`flaky`, `untested` and new `test-tamper` fixtures produce exactly the expected evidence.

**D07** Untraced ABBA-interleaved timing runs, A/A noise floor, BCa bootstrap CI on the ratio of
medians, `perf_not_assessable` below the timing floor. *Accept:* `perf-regress` is flagged with
a CI excluding 1. An A/A run on an unchanged repo produces no perf diff over 20 repetitions.

---

## Stage E — Behaviour evidence · v0.5.0

**Goal:** function-level "same input, different output" evidence that is stable, explainable
and cheap enough to run.

**Gate E:** a change that alters a function's output **without failing any test** is detected,
shown as a stable behaviour diff with a reproducer, and is not confused with noise in the A/A′
control.

| ID | Phase | Size | Depends | Status |
|---|---|---|---|---|
| E01 | Tracer core & overhead benchmark | L | D04, A08 | planned |
| E02 | Canonical value encoder | L | E01 | planned |
| E03 | Observation store & stability analysis | M | E02 | planned |
| E04 | Behaviour diff engine & reproducers | M | E03 | planned |
| E05 | API & dependency diff | M | C06, D03 | planned |
| E06 | Deterministic input-replay probes | M | E04 | planned |
| E07 | Real-data panels & Gate E scenario | M | E04, E05 | planned |

**E01** Tool-ID negotiation, PY_START / PY_RETURN / PY_UNWIND / yield capture, per-test
attribution, budgets and truncation, threads and generators, plus a benchmark harness tracked
over time. *Accept:* overhead on the benchmark suite is within the budget set in A08. Tool-ID
conflict with coverage.py is handled and becomes an explicit missing item when unresolvable.

**E02** Structural encoder (ARCHITECTURE §4.3). *Accept:* Hypothesis property tests (stable
across processes and hash seeds, never calls user dunders, guards terminate, truncated values are
never equal) plus a fuzz corpus of hostile objects.

**E03** Observation storage (CBOR artifacts plus index), join keys, A vs A′ unstable-field
masking. *Accept:* on fixtures with time, random and set-order noise, all noise is classified
`unstable` and none of it becomes a diff.

**E04** Diff classes (different result, new/changed exception, input mutation, order-only),
evidence with reproducers, `diff.behaviour` events. *Accept:* the `silent-change` and
`false-claim` fixtures produce the expected stable diffs with working reproducers.

**E05** griffe (`allow_inspection=False`) breaking changes plus annotation comparison. Lockfile
and installed-set dependency diff, lock drift. *Accept:* the `api-break` and `new-dep`
fixtures pass, and griffe never imports target code (test with a module that raises on import).

**E06** Hypothesis-generated JSON-able inputs for annotated pure functions, replayed in both
sandboxes. `probe_diff` evidence with `provenance: generated`. *Accept:* finds the seeded
divergence in a fixture whose existing tests don't exercise it. Probes are deterministic across
A and A′.

**E07** Behaviour diff field, Execution and Signals driven by real engine data. *Accept:* Gate E
scenario passes end to end in the cockpit.

---

## Stage F — Policy & deterministic card · v0.6.0

**Goal:** declared invariants and a complete, rule-based card. Repro is useful with no LLM at all.

**Gate F:** each invariant has a passing and a failing fixture. Every fixture repo yields the
expected deterministic status. `repro replay` regenerates identical cards.

| ID | Phase | Size | Depends | Status |
|---|---|---|---|---|
| F01 | `repro.yml` schema & loader | S | A04 | planned |
| F02 | Invariants I: API, dependencies, forbidden paths | M | F01, E05 | planned |
| F03 | Invariants II: network, performance | M | F01, D02, D07 | planned |
| F04 | Status engine & missing taxonomy | M | F02, F03, E04 | planned |
| F05 | Deterministic card & exports (MD/JSON) + card view | M | F04 | planned |

**F01** JSON Schema for `repro.yml`, read from **base**, line-numbered errors, defaults, and a
head-side policy change becoming a gap item. *Accept:* invalid configs give actionable errors.
Policy weakening in head is flagged.

**F02 / F03** Each invariant emits `invariant.result` plus evidence. `no_network` distinguishes
enforced from detected-only. *Accept:* passing and failing fixture per invariant.

**F04** Status rules (ARCHITECTURE §4.6), introduced vs pre-existing origin, missing taxonomy
(§6.1), and an "explained-by" structure (filled by agents in G). *Accept:* property test
"never VERIFIED while any unexplained stable gap or failed invariant exists". Table-driven tests
over all rule combinations.

**F05** Card assembly, Markdown and canonical JSON export, card UI view, replay regeneration.
*Accept:* golden cards for every fixture. Byte-identical cards from replay.

---

## Stage G — Agents · v0.7.0

**Goal:** claims extracted from PR text, judged strictly against cited evidence. Generated
probes close the test-adequacy gap.

**Gate G:** on three handmade PRs (honest; unclaimed behaviour change; false claim) the cards come
out VERIFIED / FLAGGED / FLAGGED with correct cited evidence, reproducibly from cassettes. The
agent eval set meets the thresholds set in G09.

| ID | Phase | Size | Depends | Status |
|---|---|---|---|---|
| G01 | LLM backend & locked-down runtime | M | C03 | planned |
| G02 | Cassettes, prompt versioning & cost accounting | M | G01 | planned |
| G03 | Read-only evidence tools | M | G01, F04 | planned |
| G04 | Reader agent (claim extraction) | M | G02, G03 | planned |
| G05 | Reviewer agents (evidence-constrained verdicts) | L | G04 | planned |
| G06 | Gap reviewer (explained-by mapping) | M | G05 | planned |
| G07 | Probe-writer agent | L | G03, E06 | planned |
| G08 | Bias controls & QA agent | M | G05, G06 | planned |
| G09 | Agent evaluation harness | M | G04–G08 | planned |

**G01** `LLMBackend` protocol, Agent SDK implementation with the full lockdown (ADR-0007),
budgets, concurrency limiter, `agent.spawned` and `agent.state` events. *Accept:* tests prove
built-in tools are unavailable, a `CLAUDE.md` or hook planted in the target repo is never loaded,
and calls outside `mcp__repro__*` are denied.

**G02** Cassettes keyed by (prompt version, model, input digest), with a missing cassette failing
the test. Prompt files versioned. `cost.estimate` events. *Accept:* the full agent test suite
runs offline in CI.

**G03** `list_evidence`, `get_evidence`, `read_snippet`, `get_diff` with size caps, rendering, and
path normalisation. Untrusted-content delimiting. *Accept:* prompt-injection fixtures in PR text
and code comments do not change tool behaviour or verdicts.

**G04** Atomic claim extraction (text, targets, kind) with schema validation. *Accept:*
precision and recall on the labelled claim set are recorded. Thresholds are set and met.

**G05** Per-claim schema with an evidence-ID enum, quote substring validation,
consistency-with-evidence check, `verdict.rejected` path. *Accept:* zero uncited verdicts
reach the card (property test with adversarial cassettes).

**G06** Explained-by mapping for every gap item, citing evidence. Unexplained items flag.
*Accept:* the `silent-change` fixture with a claim that does not cover it is flagged as
unexplained.

**G07** Probe writer (ARCHITECTURE §4.4): claim-blind, TestGen-LLM-style filters, run on both
sides. *Accept:* on a fixture whose tests pass on a wrong change, generated probes expose the
divergence. The filter rejection rate is reported.

**G08** Order-swap pass for contradicted verdicts, optional 2-of-3 panel, judge-model ≠
author-model policy, QA agent. *Accept:* verdict flip rate under order swap is measured and
reported on the eval set.

**G09** Labelled mini-set of handmade PRs. Metrics: claim P/R, verdict accuracy, citation
validity, flip rate, cost. Regression gate for prompt or model changes. *Accept:* metrics are
appended to `bench/results/agent-evals.csv`. CI fails on a regression beyond tolerance.

---

## Stage H — Hardening & first release · v1.0.0

**Goal:** a stranger can install Repro, run it on their own repo, and trust what the card says
about what was and wasn't checked.

**Gate H:** install-from-scratch tests pass on Windows and Linux. The security review is
complete. The user documentation is complete. `v1.0.0` is tagged and published.

| ID | Phase | Size | Depends | Status |
|---|---|---|---|---|
| H01 | Robustness & failure modes | M | G09 | planned |
| H02 | Performance & scale | M | H01 | planned |
| H03 | Security hardening | M | H01 | planned |
| H04 | Exports: in-toto, JUnit, SARIF | M | F05 | planned |
| H05 | Packaging & distribution | M | H02, H03 | planned |
| H06 | User documentation & demo | M | H05 | planned |

**H01** Failure catalogue (install failure, collection error, timeout, OOM, encoder failure, API
outage) mapped to explicit missing/UNVERIFIABLE outcomes. Chaos tests. *Accept:* every catalogued
failure has a test and a user-readable reason.

**H02** Profiling on 3 pinned real repos of increasing size. Caching (env, selection map,
graph), parallel sides, incremental re-runs. *Accept:* targets set from A08 and D-stage
measurements are met and recorded.

**H03** Threat-model review, expanded escape suite, gVisor on Linux CI, secret-scrubbing audit
of logs and events, dependency audit. *Accept:* every THREAT_MODEL item has a test or a
documented residual risk.

**H04** in-toto Statement with the Repro predicate (ADR-0012), JUnit (one testcase per claim),
SARIF 2.1.0. Predicate schema published. *Accept:* outputs validate against their specs and
schemas. Card → attestation → card round trip.

**H05** Package name decision (PyPI/npm availability), `uvx`/pipx install, web assets bundled
into the Python package, release workflow. *Accept:* clean-machine install and first run on
Windows and Linux in under 10 minutes (documented procedure plus CI job).

**H06** Quickstart, `repro.yml` reference, "how to read a card", troubleshooting, architecture
overview for contributors, recorded demo. *Accept:* a reviewer unfamiliar with the project
completes the quickstart from the docs alone.

---

## Stage I — GitHub integration · v1.1.0

**Gate I:** on a test repository, opening a PR produces a Repro check run, a sticky card comment
and (on public repos) a signed attestation, and re-running updates rather than duplicates them.

| ID | Phase | Size | Depends | Status |
|---|---|---|---|---|
| I01 | PR ingestion | M | H05 | planned |
| I02 | Check run, sticky comment & job summary | M | I01 | planned |
| I03 | GitHub Action & attestation signing | M | I02, H04 | planned |
| I04 | GitHub App (optional) | L | I03 | planned |

**I01** PR URL → refs, description, commits (gh/API, token from env), fork handling.
**I02** Conclusion mapping (VERIFIED→success, FLAGGED→failure or action_required, UNVERIFIABLE→
neutral), annotations in batches of 50, sticky comment found by a hidden marker, under 60k
characters, job summary. **I03** Docker-based Action for Linux runners, caching,
`actions/attest` with the Repro predicate. **I04** Webhooks, re-run button, org config. Built
only if users ask for it.

---

## Stage J — Evaluation & research · v1.2.0

**Goal:** a reproducible, pre-registered evaluation that supports or refutes Repro's claims, and
a paper. Protocol: [`paper/EVALUATION_PROTOCOL.md`](paper/EVALUATION_PROTOCOL.md) and ADR-0010.

**Gate J:** every table and figure regenerates from one command over pinned manifests. The
artifact is archived with a DOI. The paper is submitted.

| ID | Phase | Size | Depends | Status |
|---|---|---|---|---|
| J01 | Benchmark infrastructure & input contract | L | H05 | planned |
| J02 | Ground-truth pipeline & annotation tooling | L | J01 | planned |
| J03 | Baselines | L | J01 | planned |
| J04 | S0 dev set & S1 pilot | M | J02, J03 | planned |
| J05 | S2 patch generation on fresh tasks | M | J04 | planned |
| J06 | Annotation, κ & label freeze; pre-registration | L | J05 | planned |
| J07 | S2 main study | M | J06 | planned |
| J08 | Ablations, S3 in-the-wild & S4 synthetic | M | J07 | planned |
| J09 | Artifact package | M | J08 | planned |
| J10 | Paper writing & submission | L | J08 | planned |

**J01** SWE-format adapter (instance + image + patch → base/head), image management by digest,
manifest format, input-contract enforcement with a test proving withheld fields never reach the
engine. **J02** Tier A (hidden + full suite) and tier B (UTBoost augmented tests,
PatchDiff-style differential tests vs gold) labelling, annotation guideline and tool, κ
computation. **J03** B0 CI-only, B1 diff-only LLM, B2 agentic static LLM, B3 PR-Agent (licence
re-checked at the pinned commit), Testora where reproducible. Pre-registered prompts and
mapping rules. **J04** Pipeline shake-out (S0, never reported), S1 pilot, updated power
analysis, memorisation probe. **J05** Agent patches from at least 2 scaffolds × at least 2 model
families on post-cutoff SWE-rebench / SWE-bench-Live tasks. **J06** Two blinded annotators,
adjudication, labels frozen and tagged with the analysis config. **J07** All systems, k = 5;
McNemar + Holm; cluster bootstrap; cost and time. **J08** Ablations
(−traces, −probes, −selection, −invariants, −agents, −claims, −citation rule, model swap),
S3 and S4. **J09** Zenodo DOI, image digests, 30-minute kick-the-tires subset, AE-ready README.
**J10** Paper drafting from `docs/paper/`, internal review, submission.

---

## Stage K — Expansion backlog (unscheduled)

| ID | Phase | Notes |
|---|---|---|
| K01 | TypeScript/JavaScript targets | Vitest/Jest. Needs a V8-side tracer design |
| K02 | Fleet dashboard | Many PRs and agents at once (the "64 papers" view) |
| K03 | Repro as an MCP server | Agents can request verification and receive evidence, while the verifier stays independent |
| K04 | Symbolic deep checks | CrossHair `diffbehavior` on small pure functions in the blast radius |
| K05 | Remote sandbox backends | Self-hosted E2B / Firecracker for teams |

---

## Mapping from the original milestones

| Original | Now |
|---|---|
| M0 Scaffold | Stage A |
| M1 Cockpit on fixtures | Stage B |
| M2 Engine core | Stage C |
| M3 Run both sides | Stage D |
| M4 Behaviour traces | Stage E |
| M5 Invariants | Stage F |
| M6 Agents + card | Stage F (deterministic card) + Stage G |
| M7 GitHub | Stage I (Docker isolation moved earlier, to D02) |
| M8 Benchmark | Stage J (redesigned, ADR-0010) |

## Phase log

Completed phases append a one-line entry here. Detail lives in `docs/phases/`.

| Phase | Date | PR | Notes |
|---|---|---|---|
| A01 | 2026-10-13 | (bootstrap commit) | Planning baseline published |
| A02 | 2026-10-13 | [#1](https://github.com/DuhItzAniket/Repro/pull/1) | pnpm + uv workspaces, pinned toolchains, CI on Ubuntu + Windows; ADRs 0003/0004/0007/0011 accepted; Apache-2.0 |
| A03 | 2026-10-13 | [#3](https://github.com/DuhItzAniket/Repro/pull/3) | Ruff + strict mypy (ADR-0013), Biome, required `lint` CI job |
| A04 | 2026-10-13 | [#4](https://github.com/DuhItzAniket/Repro/pull/4) | Event schema v1: 34 kinds, models, examples; `repro-events` registry, validation, draft-07 agent schemas |
| A05 | 2026-10-13 | [#5](https://github.com/DuhItzAniket/Repro/pull/5) | In-house TS + Pydantic codegen (ADR-0014), three-validator equivalence tests, CI drift gate |
| A06 | 2026-10-13 | [#6](https://github.com/DuhItzAniket/Repro/pull/6) | CI: lint / test×2 / security (gitleaks, licence allow-list) / dependency review; SHA pins; Dependabot |
| A07 | 2026-10-13 | [#7](https://github.com/DuhItzAniket/Repro/pull/7) | Log validator/normaliser CLI, golden logs, Hypothesis/fast-check, deterministic fixture repos |
| A08 | 2026-10-13 | [#8](https://github.com/DuhItzAniket/Repro/pull/8) | Measured: tracer overhead (budget 200 → ~baseline), Docker L3 on Windows, offline provisioning 0.79 s |
| Gate A | 2026-10-13 | [#9](https://github.com/DuhItzAniket/Repro/pull/9) | Stage A complete; release v0.1.0 ([gate record](phases/A-gate.md)) |
