# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Phase IDs refer to [`docs/ROADMAP.md`](docs/ROADMAP.md).

## [Unreleased]

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
