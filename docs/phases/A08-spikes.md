# A08 — Feasibility spikes

| | |
|---|---|
| **Stage** | A — Foundation |
| **Status** | done |
| **Depends on** | A02 |
| **Branch / PR** | `phase/A08-spikes` · PR link in ROADMAP phase log |
| **Started / finished** | 2026-10-13 / 2026-10-13 |

## Objective
Measure the three unknowns that could invalidate the design before Stages D–E build on them:
- tracer overhead with value capture;
- Docker isolation on Windows;
- container provisioning time.

## Scope
Throwaway measurement scripts (`spikes/A08/`), their raw results, a results report, ADR
updates, and roadmap adjustments. Production code is out of scope.

## Acceptance criteria
- [x] AC1: `sys.monitoring` overhead microbenchmark on 3.12, 3.13 and 3.14 (plus 3.15), with no
      tool / DISABLE / local capture configurations (plus dispatch-only, settrace and budgeted
      variants).
- [x] AC2: Docker sandbox round trip on Windows (Docker Desktop/WSL2), timed per step. Linux-host
      numbers come from the spike workflow on a GitHub runner and are attached at the gate.
- [x] AC3: uv provisioning inside a container for a medium repository, cold and warm (plus
      offline).
- [x] AC4: Numbers are recorded with method and hardware class. ADR-0004 and ADR-0005 are
      updated with measured facts. Go/no-go and initial default budgets are written down.

## Results (summary; full tables in `spikes/A08/RESULTS.md`)
| Question | Measured | Decision |
|---|---|---|
| Tracer loaded, nothing targeted | 0.94–1.06× baseline | free |
| Dispatch per instrumented call | 114–197 ns (monitoring) vs 193–547 ns (settrace) | `sys.monitoring` confirmed |
| Full capture per call | 2.3–11.4 µs; the encoder dominates | **budget 200 calls/(test, fn)**; encoder speed is an E02 requirement |
| Budgeted capture, steady state | 0.92–1.19× baseline | GO |
| Docker `--network none` | connect → ENETUNREACH; DNS fails | L3 is real on Windows Home |
| Per-container overhead | ~0.3–0.9 s | batch tests per container |
| Provisioning, click 8.5.0 | cold 9.9 s · warm 0.91 s · **warm offline 0.79 s** | cache step, then offline installs |

## Defects and surprises found
1. **Sandbox-induced failures.** Docker's `--tmpfs` defaults to `noexec`. Three click tests that
   execute a file they create in `tmp_path` failed only in the hardened container. Mounting
   `/tmp` with `exec` made the hardened result identical to the unhardened one (24/1967/24/1).
   This is now a D02 requirement.
2. **Environment-induced failures.** 24 click pager tests fail in every container because the
   slim image has no `less`. These are identical on base and head (F2F) and must surface as
   environment or pre-existing evidence, never as gap. This is now a D03 requirement (a
   documented base image).
3. **pytest configuration matters.** click deselects about 31,000 parametrised cases by default.
   Test selection must respect each project's pytest configuration (D05).

## Evidence
- Raw data: `spikes/A08/results/tracer-{windows,linux}-py3.{12,13,14,15}.json`,
  `sandbox-windows-docker.json`, `provision-windows-docker.json`.
- Images used (by digest):
  - `ghcr.io/astral-sh/uv@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca`
  - `python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1`
  - `python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f`
  - `python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170`
  - `python:3.15-slim@sha256:ea4f1f290e071bf7d28199cfb3e09f5dbad31b50e9c32fd58f2f2d7be915f3ae`
- Reproduction: `spikes/A08/README.md`. Linux-host rerun: `.github/workflows/spikes.yml`.

## Deviations from spec
- Added Python 3.15 (released 2026-10-09), settrace and budgeted-capture configurations, and an
  offline-provisioning scenario. These answered design questions the original three
  configurations could not.

## Known gaps
- Microbenchmarks only. E01 measures overhead on real test suites.
- Linux-host Docker numbers come from a shared CI VM. They show the trend, not a precise
  comparison.

## Dependencies added
None to the product. Spike-only container images are listed above.

## Research notes
Logged in `docs/paper/LOG.md` (2026-10-13 · A08). These numbers feed RQ5 (cost) and the
threats-to-validity section (sandbox- and environment-induced differences).
