# A03 — Code-quality gates

| | |
|---|---|
| **Stage** | A — Foundation |
| **Status** | done |
| **Depends on** | A02 |
| **Branch / PR** | `phase/A03-quality-gates` · [#3](https://github.com/DuhItzAniket/Repro/pull/3) |
| **Started / finished** | 2026-10-13 / 2026-10-13 |

## Objective
Every language has a lint, format and type gate that runs with one command locally and is
enforced in CI. A deliberately broken file fails each gate.

## Scope
- Ruff (lint + format) and mypy `--strict` for Python (ADR-0013).
- Biome (lint + format) plus the existing `tsc --noEmit` for TypeScript and JSON.
- Root scripts and commands. A `lint` job in CI, made a required check.
- Optional pre-commit configuration with local hooks only (no third-party hook repositories).

## Out of scope
- Restructuring CI, secret scanning, licence checks and SHA pinning (A06).

## Acceptance criteria
- [x] AC1: One command per language reports zero issues on the current tree (`pnpm lint`;
      `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`).
- [x] AC2: A deliberately broken file fails each gate (procedure and output recorded below).
- [x] AC3: CI runs the gates in a `lint` job, and `lint` is a required check on `main`.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | Commands run locally and in the CI `lint` job |
| AC2 | Manual procedure: add a violating file, run each gate, confirm a non-zero exit, remove the file. Output recorded below |
| AC3 | CI run on the PR. Branch-protection required checks include `lint` |

---

## What shipped
- **Python:** Ruff 0.17.0 and mypy 2.4.0 in the dev group. `[tool.ruff]` (py312, line length 100,
  20 rule families incl. bandit, pathlib, timezone-aware datetimes, no print, no relative imports;
  tests relax assert/subprocess/magic-number rules; `docs/` excluded because Ruff 0.17 formats
  Python code blocks inside Markdown). `[tool.mypy]` strict + `warn_unreachable` + 4 extra error
  codes over `engine/src`, `engine/tests`, `bench/src`.
- **TypeScript/JSON:** Biome 2.5.15 (`biome.json`: VCS ignore file, recommended preset, LF,
  100 columns, organise imports), `pnpm lint` / `pnpm lint:fix`. `tsc --noEmit` stays as `pnpm typecheck`.
- **CI:** new `lint` job (ubuntu): Biome, Ruff lint (GitHub annotations), Ruff format check, mypy.
  `lint` added to the required checks on `main`.
- **Optional hooks:** `.pre-commit-config.yaml` with local hooks only (Ruff format/check, Biome).
- **Decision:** ADR-0013 (Ruff + mypy strict; pyright/basedpyright/ty/pyrefly considered).

## Evidence
- AC1, clean tree: `uv run ruff check` → "All checks passed!"; `uv run ruff format --check` →
  "15 files already formatted"; `uv run mypy` → "Success: no issues found in 5 source files";
  `pnpm lint` → "Checked 10 files … No fixes applied."
- AC2, deliberate violations (files added, gates run, files removed):
  | Gate | Probe | Result |
  |---|---|---|
  | `ruff check` | `import os, sys`, unused arg, `open()`, `except Exception`, `print` | exit 1, 8 findings (E401, I001, F401×2, ARG001, PTH123, BLE001, T201) |
  | `ruff format --check` | 2-space indent, `x+1` | exit 1, "1 file would be reformatted" |
  | `mypy` | unannotated functions | exit 1, `no-untyped-def` in both files |
  | `biome check` | `any`, unused `var`, `==`, unformatted | exit 1, 2 errors + 2 warnings (noExplicitAny, noUnusedVariables, noDoubleEquals, format) |
- AC3: on PR #3, `lint` and both `build & test` jobs passed. Required checks on `main` are now
  `lint`, `build & test (ubuntu-latest)` and `build & test (windows-latest)`, and #3 auto-merged
  (squash) once they were green.

## Deviations from spec
- None. The type checker choice was left open by the roadmap and is now recorded in ADR-0013.

## Known gaps
- Biome's recommended preset does not flag `var` (style group). Revisit the rule set when the
  real UI code arrives in Stage B rather than tuning it against a placeholder.

## Dependencies added
| Package | Version | Licence | Why |
|---|---|---|---|
| ruff | 0.17.0 | MIT | Python lint + format |
| mypy | 2.4.0 | MIT | Python strict type checking |
| @biomejs/biome | 2.5.15 | MIT OR Apache-2.0 | TS/JSON lint + format |

## Research notes
None.
