# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Phase IDs refer to [`docs/ROADMAP.md`](docs/ROADMAP.md).

## [Unreleased]

### Added
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

### Fixed
- Stage geometry is rebuilt when a layer's buffers grow. three.js caches the maximum instance
  count per geometry and would otherwise draw no more instances than the first capacity. [B05]

### Changed
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
