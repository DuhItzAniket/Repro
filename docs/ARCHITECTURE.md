# Repro — Architecture

> Status: **baseline v1** (phase A01, 2026-10-13). This document is the target architecture.
> Decisions that are expensive to reverse are recorded as ADRs in [`adr/`](adr/); this document
> links them. Facts about third-party tools were verified on 2026-10-13, and the sources are in
> [`research/`](research/).

## 1. Purpose and quality attributes

Repro takes a code change (base ref, head ref, and the change's natural-language description).
It executes both sides in isolation and records what each side *does*. From those
observations it produces evidence, judges the change's claims against that evidence, and
publishes a **Reproduction Card**.

Quality attributes, in priority order. When two conflict, the higher one wins.

| # | Attribute | What it means here |
|---|---|---|
| Q1 | **Honesty** | Nothing is reported as verified unless evidence supports it. Anything that could not be checked appears as an explicit *missing* item. The isolation level actually achieved is stated on the card. |
| Q2 | **Correctness of evidence** | Behaviour differences are real, not noise. Non-determinism is measured (A/A′ runs), not guessed. |
| Q3 | **Isolation** | Target code is untrusted. It never runs in the host's Python, never touches the host repo's `.git`, and runs without network wherever the platform can enforce that. |
| Q4 | **Replayability** | Every run can be reconstructed from its stored event log. The UI and the card are pure projections of that log. |
| Q5 | **Explainability** | Every verdict cites evidence IDs. Every evidence item links to raw artifacts with content digests. |
| Q6 | **Portability** | The engine runs on Windows x64 and Linux, and CI covers both. Target execution happens inside a Linux container when one is available. |
| Q7 | **Performance** | A typical small-to-medium Python PR is verified in minutes, and the cockpit renders at 60 fps (see DESIGN.md budget). |

## 2. System context

```
                    ┌──────────────────────────────────────────────────────────────┐
  developer ──CLI──►│                          Repro                               │
  (or CI)           │                                                              │
                    │  engine ──► sandbox (Docker / process) ──► target repo code  │
  web browser ◄─WS──│     │                                                        │
                    │     ├──► Anthropic API (reviewer agents; optional)           │
                    │     └──► GitHub API (PR ingestion + reporting; Stage I)      │
                    └──────────────────────────────────────────────────────────────┘
  inputs:  local git repo + base/head refs + PR description   (or a PR URL, Stage I)
  outputs: event log, evidence store, Reproduction Card (MD / JSON / in-toto / SARIF / JUnit)
```

External dependencies and how much Repro depends on each:

| Dependency | Required? | Without it |
|---|---|---|
| git ≥ 2.40 | yes | — |
| uv (pinned version) | yes | — |
| Python ≥ 3.12 for the engine | yes | — |
| Python ≥ 3.12 **in the target environment** | for behaviour traces | Tests still run. Traces become a `missing` item (`trace_unavailable`). |
| Docker (Desktop on Windows/macOS, Engine on Linux) | strongly recommended | Falls back to process isolation. Card states `network: detected-only`, `isolation: process`. |
| Anthropic API key | optional | Deterministic-only mode: no claim extraction or judging. The card shows deterministic evidence only, and claims are `unverifiable`. |

## 3. Component view

```
repro/
├─ packages/events/            THE contract: JSON Schema (2020-12) + generated TS & Pydantic types
├─ engine/src/repro/            (import package `repro`; distribution `repro-engine`)
│   ├─ cli.py                  Typer: run · replay · serve · doctor · export
│   ├─ config/                 engine settings (env/file), repro.yml loader + schema
│   ├─ orchestrator/           run lifecycle, stage DAG, job runner, cancellation, timeouts
│   ├─ bus/                    event construction, seq assignment, single-writer persistence, fan-out
│   ├─ store/                  SQLite (runs/events/evidence/cards), artifact store, migrations
│   ├─ api/                    FastAPI REST + WebSocket (replay-then-live)
│   ├─ gitops/                 ref resolution, diff parsing, worktrees, .git-less snapshots
│   ├─ analysis/               symbol table (ast), changed-lines→symbols, import graph (grimp),
│   │                          blast radius, API extraction (griffe)
│   ├─ sandbox/                isolation backends: process (L0–L2), docker (L3), [gvisor (L4)]
│   ├─ envs/                   project-type detection, interpreter choice, uv provisioning, env cache
│   ├─ runner/                 test selection, two-sided execution, reruns, perf passes
│   ├─ plugin/                 the Repro pytest plugin (shipped INTO the sandbox):
│   │                          selection collector, tracer, canonical encoder, net guard, audit hook
│   ├─ diff/                   outcome, behaviour, API, dependency, perf differs
│   ├─ policy/                 invariants, status rules, missing taxonomy
│   ├─ agents/                 LLM backend, locked-down runtime, tools, prompts, validators, cassettes
│   ├─ card/                   card assembly + exporters (md, json, in-toto, sarif, junit)
│   └─ integrations/github/    PR ingestion, check runs, sticky comments (Stage I)
├─ engine/tests/               unit, property, integration (scripted fixture repos), sandbox security
├─ apps/web/                   Vite + TS cockpit (see §13)
├─ bench/                      evaluation harness: dataset adapters, baselines, analysis (Stage J)
└─ docs/                       this documentation set
```

Dependency rule: `plugin/` is **stdlib-only**. It runs inside arbitrary target environments
with Python 3.12–3.15, so it cannot import engine code or third-party packages. It talks to the
engine through files written to an output directory that the engine mounts or collects.

## 4. Run pipeline

The seven **stages** drive the UI progress bar and the `stage` field of every event. Inside
them, the engine runs several **passes**, each with an explicit trust level.

| Stage | Pass | Where | Executes target code? | Output |
|---|---|---|---|---|
| **read** | Ingest | host | no | PR metadata, diff, description |
| | Claim extraction | host → LLM | no | `claim.extracted` (atomic claims with targets and kind) |
| **build** | Prepare | host | no | two worktrees (`git -c core.longpaths=true worktree add --detach`) and two `.git`-less snapshots (`git archive`) |
| | Static analysis | host | **no** (griffe `allow_inspection=False`) | symbols, changed symbols, import graph, blast radius, API surface |
| | Provision | sandbox (egress limited to the package index, or offline from prefetched wheels) | **yes** (build backends, `setup.py`) | one environment per side, same interpreter version |
| **run** | Selection map | sandbox, network off | yes | test → functions-touched map (base; head for new/changed tests) |
| | Trace runs A, A′, H | sandbox, network off | yes | outcomes + behaviour observations: base, base again (different seed and order), head |
| | Probe pass | host → LLM (writing), then sandbox, network off (running) | yes | generated differential tests aimed at changed functions, run on both sides (§4.4) |
| | Perf pass | sandbox, network off, untraced | yes | interleaved timings (ABBA) |
| **diff** | Differ | host | no | outcome / behaviour / API / dependency / perf diffs → evidence |
| **check** | Policy | host | no | invariant results → evidence |
| **review** | Judgement | host → LLM | no | per-claim verdicts and an explained-by map, all citing evidence |
| **card** | Status | host | no | deterministic status computation → card → exports |

Determinism controls applied to every sandboxed run: fixed `PYTHONHASHSEED` (A and H use
the same seed; A′ uses a different one), `-p no:randomly` (or a fixed `--randomly-seed`),
no xdist (Repro shards deterministically itself if needed), `-o addopts=` override with
Repro's own flags, `PYTHONUTF8=1`, pinned `TZ`/locale, and a minimal environment with no host
secrets.

### 4.1 Test selection (`runner/selection`)
Selection uses a **function-level per-test map** built by Repro's own `sys.monitoring` collector
in "collect-map" mode. It does not use coverage.py contexts, because those force coverage's
slower settrace core and cannot use the `sysmon` core (see research/03 §2).

```
selected = tests touching any blast-radius function            (dynamic map, base)
         ∪ tests importing a module with module-level changes  (grimp downstream)
         ∪ tests added or modified by the change               (always run on both sides)
```

The map is cached keyed by `(base commit, lockfile digest, interpreter)`. If a change has no
selected tests, the card gets a `no_covering_test` missing item for each uncovered changed symbol.

### 4.2 Outcome classification (`diff/outcome`)
Every selected test is classified on base vs head: **F2P** (fail→pass), **P2P**, **P2F**,
**F2F**, **new**, **removed**, **modified** (test code differs between sides, so outcomes
are not directly comparable), or **flaky** (A and A′ disagree, or reruns don't reach quorum).
P2F and F2P flips are re-run *k* times on both sides before they become evidence. An F2P test
whose target matches a "fixes …" claim is the strongest supporting evidence Repro produces.

Two further checks come from the literature (research/02 §1.9, §5.5):
- **Test tampering.** Agents are known to edit or delete tests to make them pass
  (ImpossibleBench). Repro therefore diffs the test files themselves. Removed tests, newly added
  `skip`/`xfail` markers, deleted or loosened assertions, and widened `pytest.raises` become
  `test_change` evidence. Repro also runs the **base version of each modified test against
  head**. If the old test fails on head, that is a P2F on the unmodified test.
- **DeFlaker check.** A test that newly fails without executing any changed code (per the
  selection map) is marked *likely flaky* before any rerun is spent on it.

### 4.3 Behaviour tracing (`plugin/tracer`, `plugin/encoder`) — see ADR-0005
- `sys.monitoring` tool, claimed in order **4, 3, 2, 5**. IDs 0 (debugger) and 1 (coverage) are
  avoided. If no ID is free, the result is an explicit `trace_unavailable` missing item.
- Global `PY_START`. Non-target code objects return `DISABLE` once. Target code objects get local
  `PY_RETURN | PY_YIELD | PY_RESUME`. `PY_UNWIND` is filtered by code object (it can only be
  global before 3.15).
- Arguments are read at `PY_START` from the callee frame (`sys._getframe(1)`), and results come
  from the `PY_RETURN` callback. In-flight calls are keyed by `id(frame)` with per-thread stacks.
  Code objects are kept alive to prevent `id` reuse.
- Records are attributed to the current test and phase through pytest hooks and flushed per test
  to the output directory.
- **Budgets.** Each (test, function) pair gets *N* fully encoded calls (default 200, measured in A08). After that only counts and
  rolling digests are kept, then the location is disabled and marked `truncated`. The per-call
  overhead of `sys.monitoring` with Python callbacks is **not published** (research/03 §1.3),
  so Repro measured it in A08 (`spikes/A08/RESULTS.md`). Dispatch costs 114–197 ns per call,
  capture 2.3–11.4 µs per call (dominated by encoding), and budgeted capture runs at about
  baseline speed.

**Canonical encoder.** A structural, CBOR-like tagged encoding is hashed with BLAKE2b-128.
It **never calls user-defined dunders** (`__repr__`, `__eq__`, properties, iterators). It
normalises paths (`<ROOT>`, `<TMP>`, `<HOME>`, `/`) and memory addresses. Floats use
`float.hex()` with explicit NaN and −0.0 tokens. Sets are sorted by encoded bytes. Dicts get
ordered and order-insensitive digests. Generators, files, sockets and locks are opaque, and
exceptions are recorded as type plus args plus cause chain. Cycle, depth, node and time guards
apply. A truncated or failed encoding is never treated as equal to anything.

**Stability.** Fields that differ between A and A′ (same code, different seed and order) are
*unstable*. They are masked from the A-vs-H comparison and listed on the card. This is the
Diffy noise-floor idea (research/01 §2.2) applied at the function level.

### 4.4 Differential probes (`runner/probes`, Stage G)
Re-running existing tests misses most divergences. Shadow symbolic execution observed that
patch tests "often exercise the same behaviour in the old and the new version". PatchDiff,
Testora and BERT all needed *generated* tests to expose differences (research/02 §3.3, §3.7, gap
analysis). Repro adds a probe pass:
1. A **probe-writer agent** gets the changed functions' signatures and bodies on both sides,
   plus nearby existing tests. It writes pytest probes that call those functions with concrete
   inputs. It sees no claims, so it cannot write probes that merely confirm them.
2. Probes are filtered with the TestGen-LLM pattern (research/02 §9.1). A probe must collect,
   run on base, and be deterministic across A and A′. Probes that fail these filters are
   discarded and counted.
3. Surviving probes run on head under the tracer. A differing result is `probe_diff`
   evidence, tagged `provenance: generated`. Its reproducer is the probe source itself.

For annotated pure functions, a deterministic alternative is input replay. Hypothesis-generated
JSON-able inputs are serialised on the host and replayed in both sandboxes. CrossHair
`diffbehavior` is optional and kept for later (K04). Probe evidence is reported separately from
evidence derived from existing tests. The card always shows which kind supports a finding.

### 4.5 Diffs (`diff/`)
| Differ | Input | Evidence produced |
|---|---|---|
| Outcome | per-test outcomes A, A′, H, reruns | `test_outcome` (F2P / P2F / flaky …) |
| Behaviour | observations joined on `(test, function, args_hash)` | `behaviour_diff`: different result, new or changed exception, input mutation, order-only. Each item has a minimal reproducer (test node ID plus encoded args preview) |
| API | griffe `find_breaking_changes(base, head)` plus Repro's annotation-string comparison of return and attribute types (griffe does not check these yet) | `api_diff` |
| Dependencies | lockfiles (uv.lock, poetry.lock, pdm.lock, requirements) **and** installed sets (`uv pip list --format json`) on both sides | `dep_diff`, `lock_drift` |
| Perf | untraced interleaved runs with an A/A noise floor | `perf_diff` with ratio of medians, BCa bootstrap 95 % CI and noise floor. Tests below the timing floor are `perf_not_assessable` |

### 4.6 Card status rules (`policy/status`) — deterministic, no LLM
```
FLAGGED       if any: claim contradicted · unexplained stable behaviour or probe diff · P2F on an
              unmodified test (incl. base version of a modified test run on head) · unexplained
              test weakening/removal · invariant failed · API break not covered by a supported claim
UNVERIFIABLE  else if any: no extractable claim (and claims.require_explicit) · environment
              failed · missing coverage above threshold (config) · all reviewer verdicts rejected
VERIFIED      otherwise (all claims supported, no unexplained gap, invariants pass)
```
`FLAGGED` takes precedence over `UNVERIFIABLE`, because concrete evidence of a problem
outweighs incompleteness. Every gap item also carries an **origin**: *introduced* (absent on
base) or *pre-existing* (present on base, e.g. F2F). Repro can determine origin rigorously
because it actually ran base.

## 5. Event model — see ADR-0002 and ADR-0003

### 5.1 Envelope
```jsonc
{
  "id": "evt_01J…",            // ULID
  "run_id": "run_01J…",
  "seq": 1042,                 // monotonic per run, assigned by the single writer; replay order
  "ts": "2026-10-13T13:40:01.123Z",
  "stage": "read|build|run|diff|check|review|card",
  "agent": "a07",              // null for engine-internal events
  "kind": "test.finished",
  "target": { "file": "pkg/dates.py", "symbol": "parse_date", "test": "tests/test_dates.py::test_tz" },
  "status": "start|progress|ok|warn|fail",
  "payload": { },              // schema'd per kind
  // additive fields (ADR-0003):
  "v": 1,                      // envelope schema version
  "pv": 1,                     // payload schema version for this kind
  "parent": "evt_…",           // causation (optional)
  "producer": "repro/0.3.0+abc1234"
}
```
The core fields are unchanged from the original brief. The four additive fields were accepted
in ADR-0003. In schema v1, `v`, `pv` and `producer` are required (no older logs exist), and
`parent` is optional. The authoritative definition is `packages/events/schema/` (A04): the
envelope, one payload schema per kind, shared definitions, and the models (claim, evidence,
verdict, missing item, artifact, card). Execution sides are named `base`, `base_repeat` (A′) and
`head`.

### 5.2 Kinds (v1)
| Group | Kinds |
|---|---|
| Run | `run.started`, `run.finished`, `stage.started`, `stage.finished`, `log.line` |
| Agents | `agent.spawned`, `agent.state`, `cost.estimate` |
| Read | `claim.extracted` |
| Build | `snapshot.ready`, `graph.node`, `graph.edge`, `symbol.changed`, `blast.computed`, `sandbox.ready`, `env.provisioned` |
| Run | `test.selected`, `test.started`, `test.finished`, `trace.sample`, `perf.sample` |
| Diff | `diff.outcome`, `diff.tests`, `diff.behaviour`, `diff.probe`, `diff.api`, `diff.deps`, `diff.perf` |
| Check | `invariant.result` |
| Evidence | `evidence.created`, `missing.recorded` |
| Review | `verdict.issued`, `verdict.rejected` |
| Card | `card.published` |

Compared with the original brief, the new kinds are `stage.*`, `symbol.changed`,
`sandbox.ready`, `env.provisioned`, `perf.sample`, `diff.outcome`, `diff.tests`, `diff.probe`,
`missing.recorded`, `verdict.rejected` and `cost.estimate`. `worktree.ready` is renamed to `snapshot.ready`, because
target code runs from snapshots, not worktrees. Adding kinds does not change core fields.

### 5.3 Rules
- **Append-only.** Corrections are new events (e.g. `verdict.rejected` follows a
  `verdict.issued` that failed validation). Stored events are never edited.
- **Schema evolution.** Consumers ignore unknown fields. Upcasters keyed by `(kind, pv)` live in
  `packages/events` so old JSONL logs keep replaying.
- **Result-bearing events (ADR-0015).** `diff.*` and `invariant.result` events are the run's
  *checks*. Their envelope `status` is `ok` for a passed check, `fail` for a problem on its own
  terms (P2F, test tampering, failed invariant), and `warn` for a difference that needs a claim
  to explain it or could not be compared. The cockpit's CHECKS and FLAGGED counters and the
  change×check index are computed from these rules alone.
- **Secrets.** Payloads never contain environment variables, API keys or tokens. The bus scrubs
  known secret patterns before persistence, as defence in depth.
- **Interop (export only).** Lossless mapping to CloudEvents 1.0: `type = dev.repro.<kind>`,
  `source = /repro/runs/<run_id>`, `sequence` as a zero-padded string, and `target` mapped to
  `subject` (canonical string) with the full object kept in `data`. OpenTelemetry export is
  deferred until the GenAI semantic conventions leave "Development" status (research/04 §5.2).

## 6. Evidence model

```jsonc
{
  "id": "ev_01J…",
  "run_id": "run_01J…",
  "type": "test_outcome|test_change|behaviour_diff|probe_diff|api_diff|dep_diff|lock_drift|perf_diff|invariant|selection|network_attempt|environment|static_change|policy_change",
  "targets": [{ "file": "...", "symbol": "...", "test": "..." }],
  "summary": "parse_date('2026-03-29T02:30', tz='Europe/Berlin'): base → 2026-03-29T01:30Z, head → raises NonExistentTimeError",
  "data": { },                         // type-specific, schema'd
  "artifacts": [{ "path": "runs/<run>/obs/…", "sha256": "…", "media_type": "application/cbor" }],
  "stability": "stable|unstable|n/a",
  "origin": "introduced|pre-existing|n/a",
  "produced_by": { "component": "diff.behaviour", "version": "0.5.0" },
  "seq": 2210                          // seq of the evidence.created event
}
```
Evidence IDs are what verdicts cite. Validation rejects a verdict whose cited IDs do not exist,
do not relate to the claim's targets, or whose quoted text is not an exact substring of the
rendered evidence (§10.3).

### 6.1 Missing taxonomy
`no_covering_test` · `environment_failed` · `collection_error` · `timeout` ·
`unstable_observation` · `trace_unavailable` · `trace_truncated` · `subprocess_untraced` ·
`encoding_failed` · `network_not_enforced` · `perf_not_assessable` · `unsupported_project` ·
`verdict_rejected` · `claim_unverifiable`. Every item has a reason, the affected targets, and
where possible what would resolve it.

## 7. Reproduction Card

| Section | Content |
|---|---|
| Claim | Atomic claims C1…Cn extracted from the PR (text, targets, kind: fix / feature / refactor / no-change / perf / deps / test / docs) |
| Conditions | base and head SHAs, interpreter, lock digests, selected tests, seeds, **isolation level achieved**, platform, Repro version, model IDs |
| Gap | Behaviour, outcome, API, dependency and perf differences, each with origin (introduced or pre-existing), stability, evidence ID and explained-by claim(s) |
| Verdicts | Per claim: `supported` / `contradicted` / `unverifiable`, cited evidence, rationale, agreement (panel) |
| Invariants | Result per declared invariant, with evidence |
| Missing | Missing items (§6.1) |
| Status | `VERIFIED` / `FLAGGED` / `UNVERIFIABLE` (§4.6) |
| Replay | Event-log digest and count, plus `repro replay <run-id>` |

Exports (phase H04, Stage I): Markdown (PR comment and job summary), canonical JSON,
**in-toto Statement v1** with a Repro predicate (subject = head commit digest; SCAI-like
attributes whose evidence is digested ResourceDescriptors; see ADR-0012), JUnit XML (one
testcase per claim), and SARIF 2.1.0 (`kind` = `fail` / `open` / `review`). The attestation
records *who ran what and what was observed*. It does not certify correctness, and LLM
verdicts are labelled as judgements.

## 8. Isolation and sandbox — see ADR-0004 and THREAT_MODEL.md

| Level | Mechanism | Windows dev box | Linux / CI |
|---|---|---|---|
| L0 | separate process per side, minimal env, fixed seeds | ✓ | ✓ |
| L1 detect | in-process socket guard + `sys.addaudithook` → evidence of network, subprocess and file attempts | ✓ | ✓ |
| L2 contain | Windows Job Objects (kill-on-close, memory, CPU, process count) or POSIX process groups + rlimits, plus wall-clock timeouts | ✓ | ✓ |
| L3 enforce | Linux container: `--network none`, read-only root + tmpfs `/tmp` (mounted `exec`; A08 found `noexec` breaks real suites), `--cap-drop ALL`, `no-new-privileges`, non-root, pids/memory/cpu limits, snapshot copied into a volume (no bind-mounted live worktree, no `.git`) | Docker Desktop (WSL2) | Docker / Podman |
| L4 harden | gVisor `runsc` (or a microVM) | — | optional |

Rules:
- L1 is **detection, not a boundary**. Python's audit-hook docs say hooks are not a sandbox, and
  in-process socket patches are trivially bypassed (research/03 §6.1).
- Network can be reported as *enforced* only at L3 or above. Otherwise the card says
  `network: detected-only`.
- The provision pass is the only pass with egress, limited to the package index. Alternatively,
  wheels are prefetched on the host and installed with `UV_OFFLINE=1`. Sdist builds run inside
  the sandbox.
- Sandboxed uv uses `--link-mode copy` with a read-only cache, so target code cannot poison the
  shared cache through hardlinks (research/03 §7).
- Target code never runs in a linked worktree on the host. A linked worktree shares the host
  repo's `.git` config and hooks.

## 9. Static analysis — see ADR-0006

- **Symbols:** `ast` with `lineno`/`end_lineno`. Symbol ID = `module:qualname#ordinal`, the
  module named by walking up through `__init__.py` directories. A symbol changed when its own
  code changed: its AST without positions, nested definitions reduced to markers, so comments
  and reformatting are not changes. A class body change belongs to the class, and module code
  outside definitions to the symbol `<module>`. Repeated names are aligned by own code. Rename
  and move matching across sides uses AST similarity when qualnames differ. Files that cannot
  be parsed are reported, never guessed (C06).
- **Import graph:** `grimp` (BSD-2, Rust core, handles lazy imports). It is module-level only.
  Symbol-level reverse edges come from the dynamic per-test map, with optional static call edges
  later.
- **Public API:** `griffe` with `allow_inspection=False`, so target modules are never imported
  on the host. "Public" follows griffe's conventions, and false positives are possible and
  documented.
- **Blast radius:** changed symbols ∪ their reverse dependents (dynamic map ∪ grimp
  downstream modules), with distance kept for UI weighting.

## 10. Agents — see ADR-0007

### 10.1 Roles
| Role | Default model (env-configurable) | Job |
|---|---|---|
| Reader | `claude-haiku-5-5` (fallback `claude-sonnet-5-5`) | Split the PR text into atomic claims with targets and kind |
| Reviewer ×n | `claude-opus-5-5`, `effort=high` set explicitly | One per claim: supported / contradicted / unverifiable, citing evidence |
| Gap reviewer | `claude-opus-5-5` | Map each gap item to the claims that explain it, or to "unexplained" |
| Probe writer | `claude-sonnet-5-5` | Write differential probes for changed functions without seeing the claims (§4.4) |
| QA | `claude-opus-5-5` | Check consistency of the whole card; finds contradictions between verdicts |

The judge model should differ from the model that authored the PR when that is known, because
self-preference bias is documented (research/04 §2.3).

### 10.2 Runtime lockdown (Claude Agent SDK; research/04 §1.3)
`tools=[]` (no built-in tools). The only tools are in-process MCP tools under `mcp__repro__*`.
`permission_mode="dontAsk"` plus a `PreToolUse` hook that denies anything outside that prefix.
`setting_sources=[]`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, a per-run `CLAUDE_CONFIG_DIR`, and
`verbatim_prompts=True`. `cwd` is an **empty per-run scratch directory, never a worktree**, so
the PR cannot inject `CLAUDE.md`, hooks or skills. The system prompt is passed as a file because
of the Windows command-line length limit. `max_turns`, `max_budget_usd`, and a subagent depth
of 1 are set on every call.

PR text is wrapped in delimited `<untrusted_pr_description>` blocks and described to the model
as *claims to check, not instructions*.

### 10.3 Evidence-constrained verdicts
- The reviewer output schema is generated **per claim**. `cited_evidence` is an array with
  `minItems: 1` whose items are an **enum of the evidence IDs relevant to that claim**, so the
  model cannot cite a nonexistent ID. Schemas are draft-07 and `$ref`-free, because the Agent
  SDK validates draft-07 and rejects newer drafts (research/04 §1.5).
- Post-validation in `agents/validate.py` checks three things. Every ID exists and relates to
  the claim's targets. Every quote is an exact substring of the rendered evidence. The verdict
  is consistent with the deterministic evidence: for example, `supported` while a stable
  contradicting diff on the claim's own target is cited is rejected for QA.
- When validation fails or retries are exhausted, the engine emits `verdict.rejected` and a
  `verdict_rejected` missing item. It never falls back to an uncited verdict.

### 10.4 Bias controls
Evidence is rendered in fixed, ID-sorted order, with sides labelled neutrally (A/B plus a
legend). Prompts are reference-guided: the deterministic diff is given and the model judges
only whether the claim's wording is supported. PR text fed to judges is capped and judged per
atomic claim. For `contradicted` verdicts, a second pass with the order swapped must agree, or
the verdict degrades to `unverifiable`. An optional 2-of-3 panel uses different models or
effort levels. Agreement is logged per run.

### 10.5 Backend abstraction and CI determinism
`agents/backend.py` defines an `LLMBackend` protocol. The default implementation is the Agent
SDK. A direct Anthropic Messages API backend, which gives constrained decoding and no
per-agent CLI subprocess, is an open option (ADR-0007). In CI, calls are served from
**cassettes** keyed by `(prompt version, model, input digest)`. A missing cassette fails the
test and never silently calls the API. Concurrency defaults to `min(12, free RAM in GiB)`
(research/04 §1.10: about 1 GiB per SDK subprocess). The UI always shows 12 dispatch slots, with
queued agents shown as `waiting`.

## 11. Storage and transport

- **SQLite** at `~/.repro/repro.db` (`%USERPROFILE%\.repro` on Windows), opened with WAL,
  `synchronous=NORMAL`, `busy_timeout`, and `foreign_keys=ON`. The tables are `runs`,
  `events (PRIMARY KEY(run_id, seq), UNIQUE(id))`, `evidence`, `cards` and `artifacts`.
  **One writer task** batches events (N events or about 20–50 ms) into a `BEGIN IMMEDIATE`
  transaction, assigns `seq`, commits, and only then publishes to subscribers. Readers use
  separate read-only connections. `wal_checkpoint(TRUNCATE)` runs at run end.
- **The schema enforces the log's rules** (C02, `repro.store.schema`): triggers make `events`
  and `evidence` append-only and reject any event whose `seq` is not its run's next number;
  `PRIMARY KEY (run_id, seq)` rejects duplicates; an evidence row must belong to an
  `evidence.created` event. Migrations are numbered by `PRAGMA user_version`, one transaction
  each; a database from a newer Repro is refused. The writer fills `seq` into the envelope and,
  for `evidence.created`, into `payload.evidence`, and inserts the evidence row in the same
  transaction. The run registry (`runs`) holds `running`, then the `run.finished` outcome.
- **Artifacts** live at `~/.repro/runs/<run_id>/`: observations, JUnit, logs, snapshots
  manifest and reproducers. Each artifact is content-addressed by SHA-256 in the `artifacts`
  table, written to a temporary file, hashed, flushed and renamed into place, and never changed.
  Paths are relative POSIX paths confined to the run's directory.
- **WebSocket** `GET /runs/{id}/events?from=<seq>` uses replay-then-live without gaps. The
  client's bounded queue is subscribed **first**. Then rows with `seq > from` are streamed in
  pages, the queue is drained with `seq ≤ last_sent` deduplicated, and a `caught_up` frame is
  sent before live events continue. Frames carry arrays of events batched every 16–33 ms. A
  client that falls behind is closed with a "resync" reason and reconnects with `?from=`. The
  writer never waits for clients.
- **Frames and closes (C04):** `{"type": "events", "events": [...]}` carries stored bodies
  verbatim; `{"type": "caught_up", "seq": n}` ends the replay. The server closes with 1000
  "finished" after `run.finished`, 4000 "resync" when a client falls behind, 4400 for a bad
  request and 4404 for an unknown run. A handshake whose `Origin` is not allow-listed is refused
  (HTTP 403), and every request must name a local `Host` (THREAT_MODEL T16).
- **REST:** `/runs`, `/runs/{id}`, `/runs/{id}/evidence/{ev}`, `/runs/{id}/card`, and
  `/runs/{id}/artifacts/{sha}` (served only while the file matches its digest). Read-only. All
  bind to `127.0.0.1` by default; `repro serve` listens on loopback only until H03.

## 12. Configuration

| Layer | Where | Examples |
|---|---|---|
| Engine settings | env (`REPRO_*`) and `~/.repro/config.toml` | data dir, concurrency, sandbox backend, models, budgets |
| Repository policy | `repro.yml` in the target repo (read from **base**, never head) | invariants, thresholds, protected paths, claim requirements |
| Run options | CLI flags | refs, PR text file, deterministic-only, export formats |

Engine settings resolve in this order: command-line flag, `REPRO_<NAME>` variable, the TOML
file (`REPRO_CONFIG`, else `config.toml` in the data directory), default. Unknown keys and invalid
values are errors naming their source (C01; `engine/README.md` lists the settings).

Policy is read from the base ref because a PR must not be able to weaken the rules it is
judged by. If head changes `repro.yml`, that becomes a gap item and is flagged by default.

## 13. Web cockpit — see ADR-0008, ADR-0009, ADR-0011, DESIGN.md

```
WS / JSONL ─► EventStore (append-only, columnar typed arrays + payload array; validates v)
                 ├─► FoldedProjections (pure reducers; snapshot every N events) ─► signals ─► shell DOM + a11y DOM
                 │                                                            └─► panel view-models (dirty flags)
                 └─► WindowIndex (binary search on ts) ─► TransientProjections f(event, t, speed) ─► GPU instance buffers
Clock: t = live ? now − t0 : replayT (×0.5/1/4/16, scrub, pause) ──► frame(t) renders everything
Workers: layout.worker (d3-force, seeded, cached by graph hash) · atlas.worker (OffscreenCanvas 2D → ImageBitmap)
```

- **EventStore (B02).** Columns (`seq`, presentation time, kind, stage, status) are typed
  arrays next to the parsed events. Presentation time is the running maximum of `ts`, so a
  backwards timestamp never breaks time queries. The store takes only a gap-free sequence: a
  duplicate `seq` is ignored, and a gap stops ingestion so the transport resyncs with `?from=`.
  Unknown kinds, and known kinds with a newer `pv`, are stored but not interpreted.
- **Two kinds of UI state.** *Folded* state (counters, index, agents, grids, log) comes from pure
  reducers with snapshots for fast seek. *Transient* visuals (strands, ring snap) are
  pure functions of the events whose visual window contains `t`. Scrubbing never rebuilds
  accumulated animation state.
- **Stage:** three.js `WebGLRenderer` with `RawShaderMaterial`, instanced layers (edges, nodes,
  markers, strand bullets, dim strands, lines outside the wheel, ring cards, ring ticks, focus
  highlights), about one draw call each. GPU code sits
  behind a `Layer` interface (about 200 lines of glue), so the renderer can be swapped if the
  budget demands it.
- **Indexed state (B05, B08, B09).** Besides folded projections, append-only indexes record
  the store index of each entry, so views ask "as of cursor k" without folding: `GraphIndex`
  (nodes, edges), `TestIndex` (test runs), `ObservationIndex` (trace samples per test × symbol)
  and `ChangeIndex` (changed symbols, selections, and the routes between them). A selected test
  routes to a changed symbol if it was selected for it or for a caller within 3 `calls` hops, or,
  for a module-level change, if its module imports the changed module. Each selection is routed
  with the graph and changes that precede it in the log, so routes are pure in the cursor.
- **Panels:** Canvas 2D, written as pure `draw(ctx, view, size, t)` functions so they can move to
  an OffscreenCanvas worker if profiling shows main-thread contention. A `PanelHost` redraws a
  panel only when its `version(t, cursor, motion)` or the motion settings change, clearing the
  whole backing store first. Equal versions must mean equal drawings; a B10 property test checks
  this frame by frame, which is what makes playing equal to scrubbing.
- **Focus and accessibility (B11).** One focus (claim, file, symbol, check or agent) drives the
  stage highlight and ring pin (`StageFrame.focus`), the panels' outlines, the agent workspace
  and the evidence drawer (`drawerView`, a pure function of focus and cursor). Panels expose
  `targets` (rows and cells with their rectangles) from the same geometry they draw with, for
  hit tests and the keyboard mirror. Stage clicks are hit-tested against the ring's closed-form
  rotation and the web layout.
- **Motion (B10, ADR-0011).** The frame loop passes every layer and panel the replay speed and
  reduced motion. Visual durations are wall-clock, so the stage is a pure function of (events,
  t, motion). A `FlashGovernor` decides, in log order, which bunches of strands are drawn and
  which edges and markers flare, keeping the bright area that rises in any 333 ms under its cap.
- **View and look (B15).** The stage's ring geometry comes from the layout and the viewer's zoom
  (`viewRing`), so every layer, the governor and the hit tests follow the view. The viewer's look
  (`Look`: per-part width and brightness multiples) reaches layers through `StageFrame.look`;
  layers do not read it, the host applies it as shader uniforms, and the governor reads the
  widths it counts. It is kept per viewer in `localStorage`, always read through `clampLook`.
- **Shell:** Preact 11 + signals for header, controls, drawer and the accessible parallel DOM.
- **Determinism:** no `Date.now()` or `Math.random()` in projections. Per-event visual jitter
  comes from `hash32(event.id)`. Layout initial positions are seeded from node-ID hashes (no
  trig), so d3-force output is reproducible.
- **Accessibility:** global pause (WCAG 2.2.2), a `role="log"` mirror of the investigation feed
  with throttled announcements, semantic tables for card and index, keyboard focus, and
  `prefers-reduced-motion` support. A flash governor and wall-clock-clamped motion at high replay
  speeds address WCAG 2.3.1 (ADR-0011).

## 14. Cross-cutting concerns

- **Logging:** structured JSON logs for engine internals. User-visible activity is `log.line`
  events. Secrets are never logged.
- **Errors:** every stage failure becomes events (`status: fail`) plus missing items. A run
  always ends with `run.finished` and, where possible, a card. In the orchestrator (C03) a failed
  or timed-out job emits a `log.line` with status `fail` and a `missing.recorded` item (a timeout's
  reason is `timeout`); a job whose dependency did not succeed is skipped and records its missing
  item; `run.finished` is emitted in a `finally`. Jobs run on daemon threads; timeouts and
  cancellation are cooperative inside Python and forceful for subprocesses (the process tree is
  killed).
- **Windows specifics:** `git -c core.longpaths=true` per command (the user's global config is
  never modified). Run roots are short (`%LOCALAPPDATA%\repro\r\<id8>`). Cleanup goes Job
  Object kill, then `rmtree(onexc=…)` with retry, then `git worktree prune`. Snapshots are
  written from the commit's tree object (`git ls-tree` and one `git cat-file --batch`), not
  `git archive`, which applies the archived tree's `export-ignore` and `export-subst`; files are
  the committed bytes, through extended-length paths on Windows (C05). Opening the
  database retries a transient "disk I/O error" for up to 5 s: Windows releases a killed
  process's file locks with a delay (C02). All paths use
  `pathlib`, and tests cover backslashes and long paths.
- **Versions:** toolchain versions are pinned in lockfiles. The verified-current versions as
  of 2026-10-13 are listed in [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md#toolchain-baseline).

## 15. Key technical risks

| Risk | Impact | Mitigation | Phase |
|---|---|---|---|
| `sys.monitoring` callback overhead unknown for arg/return capture | Slow runs, truncated traces | Measure first. Budgets, target-only local events, DISABLE elsewhere | A08, E01 |
| Trace noise (timestamps, IDs, ordering) makes the Gap panel noisy | Users switch it off | Structural encoder, A/A′ masking, order-only class, reruns | E02–E04 |
| Installing arbitrary repos twice is slow or fails | UNVERIFIABLE rate high | Env cache keyed by lock digest, explicit `environment_failed`, SWE-bench-style prebuilt images for evaluation | D03, J01 |
| Docker unavailable or slow on Windows | Weaker isolation | Honest `detected-only` reporting. Copy snapshots into volumes rather than bind mounts | D01–D02 |
| LLM verdict errors or bias | Wrong card | Evidence-enum schemas, quote validation, order swap, panel, deterministic status rules | G05–G07 |
| Platform vendors add base-vs-head diffing | Positioning erodes | Compete on function-level evidence quality, claim/missing semantics, local-first replay. Publish the benchmark | J |

## 16. Decision index

| ADR | Title | Status |
|---|---|---|
| [0001](adr/0001-record-architecture-decisions.md) | Record architecture decisions | accepted |
| [0002](adr/0002-event-log-source-of-truth.md) | The event log is the source of truth | accepted |
| [0003](adr/0003-event-envelope-versioning.md) | Additive envelope fields for versioning and causation | accepted |
| [0004](adr/0004-layered-isolation-docker-default.md) | Layered isolation with Docker as the default enforcing sandbox | accepted |
| [0005](adr/0005-behaviour-tracing-sys-monitoring.md) | Own `sys.monitoring` tracer, canonical encoder and selection map | accepted |
| [0006](adr/0006-static-analysis-reuse.md) | Reuse `ast`, grimp and griffe for static analysis | accepted |
| [0007](adr/0007-agent-runtime-lockdown.md) | Locked-down agent runtime behind an `LLMBackend` interface | accepted |
| [0008](adr/0008-stage-renderer-threejs.md) | Stage renderer: three.js WebGLRenderer with custom instanced layers | accepted |
| [0009](adr/0009-web-tooling.md) | Web tooling: Biome, Vitest, Playwright | accepted |
| [0010](adr/0010-evaluation-methodology.md) | Evaluation on fresh SWE-format tasks against execution-aware baselines | accepted |
| [0011](adr/0011-motion-safety.md) | Wall-clock-clamped motion and a flash governor | accepted |
| [0012](adr/0012-card-as-attestation.md) | Export the card as an in-toto attestation | accepted |
| [0013](adr/0013-python-quality-tooling.md) | Python quality tooling: Ruff and mypy (strict) | accepted |
| [0014](adr/0014-in-house-schema-codegen.md) | In-house code generation from the event schema | accepted |
| [0015](adr/0015-check-model.md) | The check model: what CHECKS, FLAGGED and the index count | accepted |
