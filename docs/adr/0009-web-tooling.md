# ADR-0009: Web tooling — Biome, Vitest, Playwright, size-limit

- **Status:** accepted (the original M0 allowed "Biome or ESLint+Prettier")
- **Date:** 2026-10-13
- **Phase:** A01 (set up in A02–A03, B12)

## Context
Versions and facts verified on 2026-10-13 (research/05 §6):
- Biome 2.5.15 is one binary for lint and format, with type-aware rules that don't need tsc.
- ESLint 10 is flat-config only. ESLint 9 reached end of life on 2026-08-06.
- Vite 8 (Rolldown) is the build tool. Vitest 5.0.4 requires Node ≥ 22.12.
- Playwright 1.64.0 does `toHaveScreenshot` comparison. WebGL in headless Chromium must
  explicitly opt into SwiftShader for deterministic software rendering.
- size-limit 14.2.0 provides CI bundle budgets.

## Decision
- **Biome** for lint and format, plus `tsc --noEmit` in strict mode. typescript-eslint is added
  later, scoped, only if a concrete gap appears.
- **Vitest** for unit, property (fast-check) and allocation tests. **Playwright** (Chromium,
  pinned Docker image, SwiftShader) for visual regression and end-to-end tests. Baselines are
  generated **in CI only**.
- **size-limit** with gzip, `300 kB` budget, enforced on every PR.
- Node ≥ 22.12 (`engines` field). pnpm is pinned through `packageManager`.
- TypeScript major version (6.x vs the native 7.x) is decided in A02, after checking Biome and
  Vite compatibility.

## Consequences
A single fast lint/format tool on both Windows and Linux. Visual baselines are Linux-only, so
Windows developers rely on the GPU-free render-model golden tests locally.
