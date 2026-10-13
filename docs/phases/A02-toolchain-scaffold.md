# A02 — Toolchain & monorepo scaffold

| | |
|---|---|
| **Stage** | A — Foundation |
| **Status** | done |
| **Depends on** | A01 |
| **Branch / PR** | `phase/A02-toolchain-scaffold` · [#1](https://github.com/DuhItzAniket/Repro/pull/1) (merged as `f16730f`) |
| **Started / finished** | 2026-10-13 / 2026-10-13 |

## Objective
Set up a reproducible, cross-platform monorepo that later phases fill in: a pnpm workspace for
TypeScript and a uv workspace for Python, with pinned toolchains. A clean clone installs and runs
a small but real test suite on Windows and Linux.

## Scope
- Root `package.json` (`packageManager`, `engines`, workspace scripts) and `pnpm-workspace.yaml`
  (`apps/*`, `packages/*`).
- `apps/web`: Vite + TypeScript skeleton that builds, typechecks and has one Vitest test.
- `packages/events`: package skeleton and layout README. The schema itself arrives in A04 and
  codegen in A05.
- Root `pyproject.toml` as a uv workspace (`engine`, `bench`), dev dependency group, pytest config.
- `engine`: `repro-engine` distribution, import package `repro` (src layout), `repro --version`
  CLI via Typer, tests.
- `bench`: `repro-bench` package skeleton (filled in Stage J).
- Toolchain pins: `.python-version`, `.node-version`, `packageManager`, `engines`, uv build-backend range.
- `.env.example` documenting environment variables (no values).
- A minimal CI workflow that proves the clean-clone acceptance criterion on Ubuntu and Windows.
  A06 extends it to the full pipeline: lint, types, drift and secret scanning.
- CLAUDE.md "Commands" section filled in with commands that exist.

## Out of scope
- Lint, format and type-check gates (A03). Event schema (A04). Codegen (A05). Full CI and
  repository security (A06).
- Any UI or engine functionality beyond `repro --version` (Stages B and C).

## Design notes
- **Python layout:** `engine/src/repro/` (src layout, so tests run against the installed package,
  not the working directory). ARCHITECTURE §3 is updated to match.
- **Build backend:** `uv_build`, pinned to a minor range.
- **Interpreter:** pinned to 3.13 for development via `.python-version`. `requires-python >=3.12`
  (`sys.monitoring`). uv's default interpreter is never relied on.
- **Node:** `engines.node >=22.12` (Vite 8 / Vitest 5 floor). CI uses the active LTS line via
  `.node-version`.
- **TypeScript:** decide between 7.x (native port) and 6.x here, as ADR-0009 requires. Use 7.x if
  `tsc --noEmit` and Vite/Vitest work with it, and record the result.
- **Tests at this stage:** only checks of real behaviour. The CLI version output comes from
  package metadata, the module entry point works, the web build produces output, and the
  web entry renders the product name.

## Acceptance criteria
- [x] AC1: On a clean clone, `pnpm install --frozen-lockfile` and `uv sync --locked` succeed on Windows and Linux.
- [x] AC2: `pnpm test`, `pnpm typecheck`, `pnpm build` and `uv run pytest` pass on Windows and Linux.
- [x] AC3: The interpreter, Node floor, pnpm version and build backend are pinned explicitly. No floating defaults are relied on.
- [x] AC4: `uv run repro --version` prints the version from package metadata.
- [x] AC5: CLAUDE.md Commands lists only commands that work.

## Test plan
| Criterion | Check |
|---|---|
| AC1, AC2 | CI workflow `ci.yml` matrix (ubuntu-latest, windows-latest) from a fresh checkout. Local clean-clone run on Windows |
| AC3 | Review of pin files. CI uses `--frozen-lockfile` / `--locked` |
| AC4 | `engine/tests/test_cli.py` (CliRunner plus `python -m repro`). CI step `uv run repro --version` |
| AC5 | Every listed command is executed in CI or the local clean-clone run |

---

## What shipped
- **Decisions:** ADRs 0003, 0004, 0007 and 0011 accepted by the project owner. Apache-2.0 `LICENSE` and `NOTICE`.
- **JS:** root `package.json` (pnpm 12.11.2 via `packageManager`, `engines.node >=22.12`,
  workspace scripts `dev`/`build`/`test`/`typecheck`), `pnpm-workspace.yaml`,
  `tsconfig.base.json` (strict, `exactOptionalPropertyTypes`, `noUncheckedIndexedAccess`,
  `verbatimModuleSyntax`), `.node-version` (24, active LTS) for CI.
- **`apps/web`:** Vite 8.3.4 + TypeScript 7.0.2 + Vitest 5.0.4 skeleton (`index.html`,
  `src/app.ts`, `src/main.ts`, one test).
- **`packages/events`:** package skeleton and layout README (schema in A04, codegen in A05).
- **Python:** uv workspace root `pyproject.toml` (virtual root, `package = false`, dev group
  `pytest>=9.1.1`, strict pytest config), `.python-version` 3.13, `uv.lock`.
- **`engine`:** `repro-engine` 0.1.0.dev0, import package `repro`, src layout, `uv_build` backend
  (`>=0.11.6,<0.14`), Typer CLI with `--version`, `python -m repro`, `py.typed`, 4 tests.
- **`bench`:** `repro-bench` skeleton.
- **`.env.example`** (variable names only), **CI workflow** `.github/workflows/ci.yml`, CLAUDE.md
  Commands section, ARCHITECTURE/SDLC path updates, Windows toolchain notes.

## Decisions taken in this phase
- **TypeScript 7.0.2** (native port) over 6.x. `tsc --noEmit` works with the strict base config
  and catches a deliberate type error, and Vite 8 / Vitest 5 build and test with it. This
  closes the open item in ADR-0009.
- **src layout** for the engine (`engine/src/repro`), so tests import the installed package.
- **Node 24** (active LTS, verified against nodejs.org's release index on 2026-10-13) in CI.
  The local Node 25 satisfies `engines`.

## Evidence
- Local (Windows 11, x64), in the working tree and in a fresh `git clone` of the branch:
  `pnpm install --frozen-lockfile` → `pnpm typecheck` → `pnpm test` (1 passed) → `pnpm build` →
  `uv sync --locked` → `uv run --locked pytest` (4 passed) → `uv run --locked repro --version`
  (`repro 0.1.0.dev0`). The clean clone took 5 s with warm caches.
- `pnpm dev` served `index.html` (`<title>Repro</title>`) on :5173.
- `uv.lock` (written by uv 0.11.6) passes `uv lock --check` under uv 0.13.0, the version CI uses.
- Neither lockfile contains machine-specific paths.
- CI: [run 38418581594](https://github.com/DuhItzAniket/Repro/actions/runs/38418581594) on `c490d43` passed on `ubuntu-latest`
  and `windows-latest`, covering every step from checkout to the CLI smoke test. Run 38418489601 on
  `3365420` also completed every step on both OSes before a newer push cancelled it.

## Deviations from spec
- A minimal CI workflow was added in A02 rather than A06. A02's acceptance criterion requires
  Linux evidence. A06 still owns the full pipeline: lint/type/drift gates, secret scanning,
  dependency review and SHA-pinned actions.

## Findings (Windows toolchain)
1. **pnpm 12 vs MAX_PATH.** pnpm 12.11.2 writes
   `node_modules\.pnpm-task-run-state-v1\<64-hex>.<12-hex>-<pid>-<n>.published`. In a clone
   under a deep temp directory the full path was 263 characters, and `pnpm -r typecheck` failed
   with "The system cannot find the path specified (os error 3)". The same commands succeed
   from a short path. Contributors are told to clone to a short path (CLAUDE.md,
   IMPLEMENTATION_PLAN §3).
2. **Corepack is not bundled with Node ≥ 25,** so pnpm is installed with `npm i -g pnpm@12.11.2`.
3. **`uv self update` from 0.11.6 fails** with "The version … was not found for the app uv in
   workspace uv" for 0.13.0 and 0.12.24 alike, so the self-updater can't reach newer releases.
   The local uv stays at 0.11.6 for now. That's harmless for A02 (no untrusted code runs), but
   the ≥ 0.12.18 security floor becomes mandatory in D03, so uv must be reinstalled with the
   official installer before Stage D.
4. **`astral-sh/setup-uv` publishes no floating major tag** (`v10` does not exist; `v10.3.0`
   does). The first CI run failed on this. It is pinned to the exact tag now, and A06 SHA-pins
   all actions.

## Known gaps
- Lint, format and type gates for Python (A03). TS gets `tsc --noEmit` now, and Biome comes in A03.
- No `[tool.uv] required-version` floor yet. Set it to `>=0.12.18` in D03, once the local uv is
  reinstalled.
- PR #1 was merged by the owner with a merge commit, before squash-only merging was configured.
  From now on `main` is protected: PRs only, both CI checks required and up to date, linear
  history, conversation resolution, no force-push or deletion, enforced for admins, squash-only,
  auto-merge allowed, and branches deleted after merge.

## Dependencies added
| Package | Version | Licence | Why |
|---|---|---|---|
| typescript | 7.0.2 | Apache-2.0 | Type checking |
| vite | 8.3.4 | MIT | Dev server and build |
| vitest | 5.0.4 | MIT | JS unit tests |
| typer | 0.27.3 | MIT | Engine CLI |
| pytest | 9.1.1 | MIT | Python tests |
| uv_build | >=0.11.6,<0.14 | MIT OR Apache-2.0 | Build backend |

Transitive dependencies are recorded in `pnpm-lock.yaml` and `uv.lock`. A licence allow-list
check arrives in A06.

## Research notes
None for the paper. Toolchain findings stay in this record.
