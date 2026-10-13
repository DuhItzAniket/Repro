# Stage A gate — Foundation

| | |
|---|---|
| **Phases** | A01–A08 |
| **Release** | `v0.1.0` |
| **Gate date** | 2026-10-13 |

## Stage acceptance criteria
| Criterion (ROADMAP Gate A) | Result | Evidence |
|---|---|---|
| CI green on `ubuntu-latest` and `windows-latest` from a clean clone | pass | Required checks `lint`, `test (ubuntu-latest)`, `test (windows-latest)`, `security` green on every merged PR (#1–#8) and on this gate PR. A local clean clone also passed (A02) |
| A schema change regenerates TS and Pydantic types | pass | `pnpm gen` / `uv run repro-events-codegen` (A05). A05 changed the schema twice (`VerdictValue` rename, `type: object` on registry branches) and regenerated both outputs |
| CI fails on drift | pass | `repro-events-codegen --check` in the `lint` job plus `test_generated_files_are_up_to_date`. Demonstrated failing on a stale docstring during A05 |
| Spike results recorded in ADRs and phase records | pass | `spikes/A08/RESULTS.md`; "Measured" sections in ADR-0004 and ADR-0005; `docs/phases/A08-spikes.md` |

## CI matrix
| OS | Python | Node | Result | Run |
|---|---|---|---|---|
| ubuntu-latest | 3.13 (`.python-version`) | 24 (`.node-version`) | pass | see the gate PR checks |
| windows-latest | 3.13 | 24 | pass | see the gate PR checks |

Typical full CI wall clock: about 1.5–2 minutes (PR #6: 1 min 49 s; `main` after #7: 1 min 27 s).

## Metrics at gate (measured)
| Metric | Value |
|---|---|
| Tests | pytest **493** passed; Vitest **48** passed (13 test files) |
| Event schema | 34 kinds; 43 schema documents; 41 example files (every kind, model and the envelope has valid and invalid cases) |
| Generated code | TypeScript 1,392 lines; Pydantic 1,106 lines (in-house generator, ADR-0014) |
| Hand-written Python (engine, events tooling, licence checker) | 1,430 lines, all under `mypy --strict` |
| Quality gates | Ruff (20 rule families), mypy strict, Biome, tsc strict, drift check, gitleaks (full history), licence allow-list |
| Decisions | 14 ADRs (0001–0014), all accepted |
| Tracer feasibility | budgeted capture at about baseline speed; dispatch 114–197 ns per call (A08) |
| Sandbox feasibility | `--network none` verified on Windows Home; offline provisioning 0.79 s (click 8.5.0) |

## Retrospective
**Went well**
- The planning baseline held. Every phase landed in order through a protected, squash-only flow
  with required checks. Auto-merge made phase-to-phase handover fast.
- The schema's tests caught real defects before any consumer existed:
  - a type-name collision (`Verdict`);
  - a regex that broke generated JSDoc;
  - an SPDX parser bug (`"MIT OR"` accepted).
- A08 measured instead of guessing. It found two sandbox requirements (`exec` tmpfs, base-image
  tooling) that would otherwise have shown up as false flags in Stage D.

**Slipped or surprised us**
- **Tooling:**
  - The first CI run failed: `astral-sh/setup-uv` has no `v10` major tag.
  - `dependency review` failed because the repository's Dependency graph is disabled. The job is
    now gated on a repository variable.
  - pnpm 12's task-state files exceed MAX_PATH under deep checkout paths.
  - Corepack is not bundled with Node ≥ 25.
  - uv 0.11.6 cannot self-update.
- **Process:** PR #1 was merged as a merge commit before squash-only merging was configured.
  This is harmless, but it is the one non-linear point in `main`'s history.

**Roadmap changes made during the stage (explicit edits)**
- A05: in-house codegen instead of json-schema-to-typescript and datamodel-code-generator,
  based on a trial run on the real schema (ADR-0014).
- A06: our own licence checker instead of dependency-review licence rules. Dependency review
  is limited to vulnerabilities and is off until the Dependency graph is enabled.
- A07: fixture expectations use TOML instead of YAML.
- D02/D03: the `/tmp` tmpfs must be mounted `exec`; a documented base image is required;
  provisioning uses a cache step followed by offline installs (from A08).

## Carried-over gaps
| Gap | Owner phase |
|---|---|
| Local uv 0.11.6 must be reinstalled (≥ 0.12.18 Windows security fix) before untrusted installs | before D03 (owner action) |
| `required-version` floor for uv (`>=0.12.18`) | D03 |
| Dependency graph disabled, so `dependency review` is off | owner setting, then set `DEPENDENCY_REVIEW=true` |
| Schema files not yet packaged inside the `repro-events` wheel | H05 |
| Only the `honest-fix` fixture exists | each phase adds the fixtures it asserts |
| Tracer overhead measured on microbenchmarks only | E01 |
| Linux-host spike numbers come from a shared CI VM | indicative only. Recorded under `spikes/A08/results/linux-gha/` |

## Research log entries
`docs/paper/LOG.md`: 2026-10-13 A01 (research baseline), A04 (evidence-constrained output by
construction), A08 (feasibility measurements).
