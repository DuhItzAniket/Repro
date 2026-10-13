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

### Changed
- ADRs 0003 (envelope versioning fields), 0004 (Docker as the default sandbox), 0007 (agent
  runtime) and 0011 (motion safety) accepted. [A02]
