# ADR-0013: Python quality tooling — Ruff and mypy (strict)

- **Status:** accepted (decided in A03 under the owner's delegation for Stage A)
- **Date:** 2026-10-13
- **Phase:** A03

## Context
The SDLC requires lint, format and strict type checking for the engine. ROADMAP A03 leaves the
type checker open (mypy or pyright). Versions checked on PyPI on 2026-10-13: Ruff 0.17.0 (MIT),
mypy 2.4.0 (MIT). Candidates (research/03 §4):
- **pyright** is Node-based, and its PyPI wrapper fetches a Node runtime.
- **basedpyright** bundles Node.
- **ty** (Astral) and **pyrefly** (Meta) are pre-1.0.

Three constraints shape the choice:
1. The engine is security-sensitive and mostly plain Python.
2. Stage C adds Pydantic. Pydantic ships a mypy plugin.
3. CI runs on Windows and Linux, so tooling should not download extra runtimes.

## Decision
- **Ruff** for lint and format, `target-version = py312`, line length 100. The rule set adds,
  beyond the defaults: bugbear, pyupgrade, simplify, Ruff-specific, pytest-style,
  comprehensions, naming, bandit (`S`), perflint, tidy-imports (no relative imports), pathlib
  (`PTH`, which enforces the CLAUDE.md pathlib rule), timezone-aware datetimes (`DTZ`, since event
  timestamps are UTC), no `print` (`T20`), unused arguments, return style, pylint subsets,
  commented-out code (`ERA`), and blind `except` (`BLE`). Tests relax `S101`/`S603`/`S607`
  (assert, subprocess) and magic numbers.
- **mypy `--strict`**, plus `warn_unreachable` and extra error codes (`ignore-without-code`,
  `redundant-expr`, `truthy-bool`, `possibly-undefined`), over engine, bench and events sources
  and tests.
- Revisit ty or pyrefly once they reach 1.0 and support the Pydantic models generated in A05.

## Alternatives considered
| Option | Why not now |
|---|---|
| pyright / basedpyright | Node runtime in the Python toolchain. No Pydantic plugin needed, but heavier on Windows CI |
| ty / pyrefly | Pre-1.0. Strictness and diagnostics are still changing |
| flake8 + black + isort | Three tools where Ruff is one, and much slower |

## Consequences
Contributors run `uv run ruff check`, `uv run ruff format --check` and `uv run mypy`. CI
enforces all three in the `lint` job. Strict mypy means no untyped defs, so generated Pydantic
models (A05) must type-check too.
