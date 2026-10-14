# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Phase IDs refer to [`docs/ROADMAP.md`](docs/ROADMAP.md).

## [Unreleased]

### Fixed
- The event stream could crash the engine (a segmentation fault, seen once on the Ubuntu runner):
  a client leaving mid-replay cancelled the handler while a SQLite read still ran on a worker
  thread, and the cleanup closed the same connection from another thread. Each stream's reader
  now lives on one thread of its own, so the close queues behind any read in flight. [C05]

### Added
- `repro doctor`: checks Python (3.12+), git (2.40+), uv (the 0.13 baseline), Docker (daemon,
  Linux containers, kernel), the data directory and, on Windows, the run root's length and
  long-path support. Each check is ok, warn or fail with a hint; `--json` prints a report; exit
  status 1 when a required check fails. It does not change the machine. [C01]
- Engine settings from flags, `REPRO_*` variables and a TOML file, validated, with errors naming
  their source; default data paths per platform (`~/.repro`, a short run root under
  `%LOCALAPPDATA%` on Windows); structured JSON logs on stderr with credentials redacted. [C01]
- `repro run`, `replay`, `serve` and `export` are declared with their options and exit with
  status 2, naming the phase that brings them. [C01]
- The store: SQLite (WAL, STRICT tables, numbered migrations) for the run registry, events,
  evidence, artifacts and cards. The schema makes events and evidence append-only and `seq`
  gap-free per run, and ties evidence to its `evidence.created` event. A single writer thread
  batches events into `BEGIN IMMEDIATE` transactions, assigns `seq`, and publishes only after
  the commit; a failed batch is retried group by group. Content-addressed artifacts are written
  atomically and confined to their run's directory. ULIDs with the schema's prefixes; `repro
  doctor` also checks SQLite (3.37+). 100k events round-trip in order, and a writer killed
  mid-transaction or at random leaves a consistent database. [C02]
- The event bus: builds envelopes (ULID, time, `v`, the kind's `pv`, producer), scrubs GitHub
  tokens, AWS access key IDs, PEM private keys and `Bearer` credentials, validates each event
  against its kind's generated model, and publishes to subscribers only after the commit. [C03]
- The orchestrator: a run's jobs as a DAG on daemon threads with a concurrency limit, per-job
  timeouts and cancellation (subprocess trees are killed). Failed, timed-out and skipped jobs
  become `fail` events and missing items; `stage.started`/`stage.finished` frame each stage; and
  `run.finished` (outcome, duration, counts) is always emitted, followed by the run registry and
  a WAL checkpoint. A golden log pins a stub pipeline. [C03]
- The API (`repro serve`, FastAPI and uvicorn): read-only REST for runs, evidence, verified
  artifacts and cards, and a WebSocket that replays a run then follows it live, every event
  exactly once in `seq` order (subscribe first, replay in pages, deduplicate, `caught_up`). A
  client that falls behind is closed with "resync" and resumes losslessly with `?from=`; the
  writer never waits for clients. Local only: requests must name a local host (DNS rebinding),
  WebSocket origins must be allow-listed (cross-site WebSocket hijacking, THREAT_MODEL T16), and
  `repro serve` listens on loopback only. [C04]
- The git layer: hardened git commands (long paths; the repository's hooks, fsmonitor and diff
  drivers never run), ref resolution and merge bases, diffs with exact paths from `--raw -z`
  and changed line ranges from `-U0`, `.git`-less snapshots written byte for byte from the tree
  object (not `git archive`, which honours `export-ignore`), with unsafe entries skipped and
  listed, and worktrees whose cleanup waits out Windows file locks. [C05]
- Changed symbols: each file's module name from its packages (`__init__.py`), a symbol table
  from `ast` (functions, methods, classes and module code, with stable `module:qualname#ordinal`
  IDs), and, for two commits, the symbols that were modified, renamed, moved, added or removed,
  as `symbol.changed` payloads. A symbol is modified only if its own code changed: comments,
  reformatting and edits to nested definitions do not count against it. Overloads and other
  repeated names are aligned by code, renames and moves matched by AST similarity, and a file
  whose package changed above it moves with it. Files that do not parse, are too complex to
  parse or have no importable module name are reported, never guessed. [C06]
- Import graphs and blast radius: each side's module import graph, from grimp for packages and
  from `ast` for test files and scripts outside packages, and the blast radius of a change: the
  modules importing its symbols' modules, directly or not, with their distance, over both sides'
  imports. grimp runs in a process of its own and never resolves a target name through
  `sys.path`, so no target code runs whatever the package names (THREAT_MODEL T19). Unparsable
  files, unsafe paths and a slow grimp are reported. `graph.node`, `graph.edge` and
  `blast.computed` payloads. New dependency: grimp 3.17 (BSD-2-Clause). [C07]

## [0.2.0] - 2026-10-14

Stage B — Cockpit on fixtures. Gate record: `docs/phases/B-gate.md`.

### Added
- Model coverage gate: projections and store at least 90% (lines, statements, functions) in CI
  (`pnpm coverage`, SDLC.md §5). [Gate B]
- `@repro/synth`: a deterministic synthetic-run generator (seeded sfc32, ULIDs, single-writer
  ordering) with `DEMO` and `STRESS` profiles. Committed fixtures
  `apps/web/fixtures/demo-run.jsonl` (2,334 events, 28 checks, 4 flagged) and
  `stress-run.jsonl` (18,542 events, 10,000 edges, a 3k-event one-second burst), a drift test,
  and `pnpm fixtures`. [B01]
- ADR-0015, the check model: which events are checks, what their status means, and how
  verdicts resolve pending checks. It defines the CHECKS and FLAGGED counters and the
  change×check index. [B01]
- `@repro/events/testing` export (Ajv harness) for other packages' tests. [B01]
- Cockpit data layer (`apps/web/src/model`): a columnar `EventStore` with gap and duplicate
  handling, `Folder` snapshots with exact seek, `WindowIndex` and `KindIndex`, a
  `PresentationClock` (replay ×0.5–×16, live, global pause), and the `run`, `summary`,
  `checks` (ADR-0015), `claims` and `agents` projections behind one cockpit state. [B02]
- Cockpit shell (Preact 11 + signals): a header with five counters and a 7-stage progress bar,
  a stage frame, and eight panel frames. Geometry comes from a single `computeLayout` (desktop
  and narrow rules), the frame loop re-renders only on new information, and the cockpit replays
  the demo fixture (`?log=stress` for the stress run). [B03]
- Design tokens from DESIGN.md and self-hosted JetBrains Mono (variable woff2), with the OFL
  licence emitted next to the font files. [B03]
- WebGL stage foundation: `StageHost` (three.js `WebGLRenderer`), pure `StageLayer`s with
  preallocated instance buffers uploaded only on change, an instanced anti-aliased segment
  primitive (GLSL ES 3.00), adaptive DPR, allocation-free frame statistics and a perf HUD
  (`?hud`). [B04]
- GPU-free render-model harness (`hashRenderModels`) and a stress benchmark (`bench.html`) with
  a pixel sanity check. On an integrated GPU, 10k edges and 2,048 streaks hold 60 fps at DPR 2.
  Results are in `docs/perf/`. [B04]
- Dependency web on the stage: `GraphIndex`, a deterministic d3-force layout in a worker
  (containment links, radial equalisation, cached by graph hash), static edges revealed and
  flared by a shader recency term, blast-radius markers, and event-triggered Bézier bundles. On
  an integrated GPU, 10k edges hold the frame budget at DPR 2. [B05]
- Ring of file cards: one instanced draw call over a text atlas drawn in a worker
  (OffscreenCanvas → ImageBitmap). Each card is built from the events about its file (path,
  imports, symbols, changes). The rotation is closed-form, with 500 ms ease-out-cubic snaps to
  the focused file, plus a tick scale and rims. Segment layers can now turn in the shader with
  no per-frame uploads. [B06]
- Event streams: up to 2,048 live streaks on per-file lanes, with eased heads,
  velocity-stretched tails and DESIGN.md state tints, as a pure function of (events, t). Plus
  callouts: at most two bordered boxes naming the latest findings. With every stage layer real,
  the stress burst holds the frame budget on an integrated GPU. [B07]
- Canvas 2D panels: investigation feed (150 ms row insert), execution lanes (BASE with the A′
  repeat run, HEAD, and a BASE · HEAD · BOTH toggle), agent workspace (typed tool calls, block
  cursor while working), and behaviour diff field (A/A′/H agreement per test × symbol, module
  histogram). Each panel is a pure view plus draw, redrawn only when its version changes, and is
  covered by golden draw-call recordings. `TestIndex` and `ObservationIndex` join the cockpit
  model. [B08]
- The second row of panels: change routes (FILE · SYMBOL · TEST · CHECK with progress pills),
  signals (pass rate, behaviour drift and perf Δ with check ticks; "illustrative until run
  completes" while partial), agents / dispatch (12 slots, segmented bars, flagged agents), and
  the change×check index (claims and unclaimed changes × every check, with row status). A
  `ChangeIndex` routes selected tests to changed symbols through `calls` edges and module
  imports, using only the log before each selection. The index counts the same checks as its
  footer and the header. [B09]
- Replay transport along the bottom of the stage: Play/Pause, ×0.5–×16, a scrubber, Live and
  Reduce motion. Space pauses everything except a focused control. [B10]
- Motion safety (ADR-0011): every visual duration is wall-clock at any replay speed, and the
  stage, panels and callouts are pure functions of (events, t, motion). A flash governor keeps
  the bright area that rises in any 333 ms under half of WCAG 2.3.1's 87,296 CSS px² flashing
  area, at every speed, on both fixtures. `prefers-reduced-motion` and the in-app toggle stop
  streaks, bundles, flares, drift and panel animation. [B10]
- Focus: click or keyboard on index rows and cells, route rows, dispatch slots, ring cards and
  web nodes. The stage outlines the focus and pins its file on the ring, the agent workspace
  follows a focused agent, and an evidence drawer shows the claim's verdict text and quotes,
  the check's evidence and trace samples, the file's changes, routed tests and related checks.
  [B11]
- Accessible parallel DOM: a throttled `role="log"` for the feed (at most one summary every 2 s),
  semantic tables for the index and the drawer, button lists for routes and agents, a file
  picker, a described stage canvas, and landmarks. axe-core 4.14.0 reports no violations in
  jsdom (CI) and in Chromium. [B11]
- UI quality gates in CI. Each one rejects an injected regression of its kind in a self-test.
  [B12]
  - Visual regression: Playwright 1.64.0, Chromium and SwiftShader in an image pinned by digest,
    baselines generated in CI, a `renderAt(t)` hook.
  - Allocation: a flat heap over 1,000 frames of the stress burst, and a per-frame stage budget.
  - Size: size-limit, 300 kB gzip; currently 188.5 kB.
  - Perf: a calibrated frame-cost gate against a CI baseline, also nightly.
- Visual parity with the reference. [B13]
  - The ring's arc spans the stage height (radius 0.9·H, 3 o'clock point at 0.46·W).
  - At most 64 larger file cards, with legible 4–5 px text.
  - Stream lanes within the visible arc (±28°).
  - A stream residue: each event's faint, static trace along its lane, faded by the shader over
    90 s of run time.
- Reference parity, second pass, against a sharper copy of the reference (1080×1350), at the
  owner's Gate B review. [B14]
  - Layout: on landscape screens the eight panels sit beside the stage in 4 rows × 2, so the
    stage keeps the reference's near-square shape (904×844 at 1440×900). Portrait screens get the
    reference's own arrangement, with the stage on top.
  - Ring: geometry measured on the reference (inner radius 1.02·H, band 0.215 of it). It is an
    opaque drum with a lit bezel and ruler combs. Code cards fill the band at their natural size:
    a `// package / module` header, numbered rows of symbols and imports, a neighbour dot grid and
    labels.
  - Web: a chord layout, with modules on a circle under the band in the force simulation's order
    and edges as arcs, so the stage shows the reference's hairball of long curves. The run's
    nodes, symbols and tests, sit in front as small circles.
  - Strands (bundles): when an event names a function, a test or a file and its section of the
    wheel (its file's card) is on screen, a bunch fires there. It holds one dim strand from each
    of the nodes connected to it nearest that section (a function's tests and callers, a test's
    functions, a file's own nodes, from the log so far; at most 8), with a white bullet shooting
    along each. The strands converge side by side on the section, stay
    attached to their nodes, follow the section as the ring turns, and fade after 1 s. The ring
    turns once per 24 s of wall-clock time, the reference's measured speed. The mesh's arcs are
    curvier and dimmer, and none leaves the wheel.
  - Nodes (symbols and tests) are scattered across the whole visible part of the web by one
    placement rule: height by the simulation's order, depth by role (tests deeper in).
  - Lines outside the wheel answer a hit: when a bunch lands, its section's recent events shoot
    out from the outer rim at their places on that section, then rebound into the rim and vanish
    (a bounce, 0.6 s), turning with the wheel. Nothing leaves the wheel without a hit; the
    per-event streaks (B07) and the long-lived rays (B13's residue) are removed.
- Stage settings and the whole wheel, at the owner's seventh B14 review. [B15]
  - A Settings menu (in the transport) with a thickness and a brightness slider for strands,
    bullets, mesh, nodes and lines outside, and a reset; kept per viewer in the browser. The
    strands' and lines' brightness can only go down from their flash-safe ceiling; the flash
    governor counts bullets and mesh flares at the chosen width.
  - A view from the reference's arc out to the whole wheel (Arc, Whole wheel, a zoom slider).
    Every layer, the governor, hit tests and callouts follow it; the mesh dims as it crowds a
    smaller disc, and card text is mipmapped.
  - The run's nodes are placed over the whole disc: angle by the simulation's order, distance
    from the centre by role.
  - Callout boxes stay inside the stage; zoomed out they were cut off at its right edge.

### Fixed
- The feed and execution panels could keep showing a stale drawing between version steps (the
  view moved continuously while the version stepped). Both now quantise like their versions, and
  `versionOf` no longer wraps after 4,096 phases. Found by B10's "scrub = play" property. [B10]
- Panel canvases are cleared in device pixels, so no sub-pixel sliver keeps stale content and
  Chrome can discard pending draw operations. Canvas sides are clamped to 4,096 CSS px. [B09]
- Stage geometry is rebuilt when a layer's buffers grow. three.js caches the maximum instance
  count per geometry and would otherwise draw no more instances than the first capacity. [B05]

### Changed
- The dim strands and the lines outside the wheel blend with MAX at no more than 0.32, under
  WCAG's 10% luminance change, so they are not flashes (ADR-0011 note). The flash governor
  aggregates one bunch per section of the wheel per window. Segment arcs no longer overlap at
  their joints. The B04 proxy pins use a fixed stage, independent of the cockpit layout. [B14]
- `--text-dim` is `#868686` (was the reference's `#6e6e6e`, 3.9:1) to reach WCAG 1.4.3's
  4.5:1. `--text-faint` is no longer used for text, and callouts and the transport are opaque.
  [B11]
- `SchemaSet.event_errors` caches validators and skips the redundant whole-`oneOf` check when
  `kind` discriminates the registry (`SchemaSet.kind_discriminates`). It is about 5× faster
  with identical results. [B01]

## [0.1.0] - 2026-10-13

Stage A — Foundation. Gate record: `docs/phases/A-gate.md`.

### Added
- Project brief, research synthesis, final architecture, stage/phase roadmap, SDLC process,
  ADRs, threat model, test strategy and research-paper tracker. [A01]
- pnpm workspace (`apps/web`, `packages/events`) and uv workspace (`engine`, `bench`) with
  pinned toolchains: pnpm 12.11.2, Node >= 22.12, TypeScript 7.0.2, Vite 8.3.4, Vitest 5.0.4,
  Python 3.13 (requires >= 3.12), `uv_build`. [A02]
- `repro` CLI entry point with `--version`. [A02]
- CI workflow: clean-checkout install, typecheck, tests, build and CLI smoke test on Ubuntu
  and Windows. [A02]
- Apache-2.0 `LICENSE` and `NOTICE`. [A02]
- Quality gates: Ruff (lint + format) and strict mypy for Python (ADR-0013), Biome for
  TS/JSON, `pnpm lint`, an optional local pre-commit config, and a required CI `lint` job. [A03]
- Event schema v1 (JSON Schema 2020-12): envelope with ADR-0003 fields, a registry of 34 event
  kinds with stage and payload-version constraints, payload schemas, and claim, evidence,
  verdict, missing-item, artifact and card models, all with valid and invalid examples. [A04]
- `repro-events` Python package: schema registry, field-precise event validation, and
  draft-07 derivation of agent output schemas. [A04]
- In-house schema codegen (ADR-0014): TypeScript types (`ReproEvent` union, `EVENT_KINDS`,
  `KIND_STAGES`) and strict Pydantic v2 models with a discriminated `Event` union; `pnpm gen`;
  CI drift gate; equivalence tests across JSON Schema, Pydantic and Ajv. [A05]
- CI pipeline: `lint`, `test` (Ubuntu, Windows), `security` (gitleaks over full history,
  licence allow-list), PR dependency review; SHA-pinned actions; Dependabot for actions, npm and
  uv. [A06]
- Test harness: Hypothesis (dev/ci profiles) and fast-check; `repro-events validate` /
  `normalise` CLI for event logs (schema plus log invariants, including evidence-before-citation);
  golden-file fixture; deterministic fixture-repository builder with the `honest-fix` fixture. [A07]
- Feasibility spikes with results (`spikes/A08/`): `sys.monitoring` tracer overhead on CPython
  3.12–3.15 (Windows/Linux), Docker L3 sandbox round trip, and container provisioning of a real
  project. A spike workflow reproduces them on a Linux runner. [A08]

### Changed
- Common enum `Verdict` renamed `VerdictValue` (it collided with the `Verdict` model). [A05]
- Event registry branches declare `"type": "object"` (Ajv strict mode). [A05]
- ADRs 0003 (envelope versioning fields), 0004 (Docker as the default sandbox), 0007 (agent
  runtime) and 0011 (motion safety) accepted. [A02]

[Unreleased]: https://github.com/DuhItzAniket/Repro/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/DuhItzAniket/Repro/releases/tag/v0.1.0
