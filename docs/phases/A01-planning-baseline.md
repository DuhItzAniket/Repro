# A01 — Research, architecture & plan baseline

| | |
|---|---|
| **Stage** | A — Foundation |
| **Status** | done |
| **Depends on** | — |
| **Branch / PR** | bootstrap commit on `main` (the repository was empty) |
| **Started / finished** | 2026-10-13 / 2026-10-13 |

## Objective
Replace the initial project brief with a researched, verified and complete plan: product
positioning, final architecture, decisions, process, roadmap, test strategy, threat model and a
research-paper tracker. Every later phase builds on this.

## Scope
- Six research tracks with source verification tags.
- Synthesis and positioning. Architecture and ADRs. Roadmap of stages and phases. Implementation
  plan. SDLC process and templates. Test strategy, threat model and paper tracker.
- Repository hygiene for a public repo: `.gitignore`, `.gitattributes`, `.editorconfig`,
  `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, PR template, and a noreply commit identity.

## Out of scope
- Any runnable code (A02 onward).
- Licence choice. This is the owner's decision and is recorded under Known gaps.

## Acceptance criteria
- [x] AC1: Every external claim in the docs is sourced and tagged; detailed notes are in `docs/research/`.
- [x] AC2: Decisions needing the owner are recorded as `proposed` ADRs (0003, 0004, 0007, 0011).
- [x] AC3: The roadmap gives every phase deliverables or acceptance criteria and dependencies (76 scheduled phases, A–J).
- [x] AC4: No personal data in the repository or commit metadata. Third-party reference media excluded.
- [x] AC5: Docs cross-link correctly (link check run before commit).

## What shipped
- `docs/RESEARCH.md` plus `docs/research/01–06` (about 560 unique source URLs, each claim tagged).
- `docs/PRODUCT.md` (repositioned), `docs/ARCHITECTURE.md` (final), `docs/DESIGN.md` (amended).
- `docs/adr/0001–0012`.
- `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/TEST_STRATEGY.md`, `docs/THREAT_MODEL.md`.
- `docs/process/` (SDLC, phase and stage-gate templates). `.github/pull_request_template.md`.
- `docs/paper/` (tracker, evaluation protocol, research log, `references.bib`).
- `README.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `reference/README.md`.

## Evidence
- Spot checks on arXiv for the three claims the positioning depends on most (Testora, PatchDiff,
  PR-MCI). The results are logged in `docs/paper/LOG.md`.
- Pre-commit scans: personal-data patterns and relative-link check (see the commit).

## Deviations from spec
- The original M0–M8 milestones were restructured into Stages A–K (mapping in ROADMAP).
- The original benchmark plan was replaced (ADR-0010).
- The original tagline was retired, because the research found it no longer true.

## Known gaps
- **Licence not chosen** (owner decision). Until then the repository is "all rights reserved".
- Literature discovery for 2025–2026 is incomplete (research tool search budget). A follow-up
  search is scheduled before J10.
- Proposed ADRs 0003, 0004, 0007 and 0011 await owner approval. A04, D01/D02, G01 and B10
  depend on them.

## Dependencies added
None (documentation only).

## Research notes
See the `docs/paper/LOG.md` entry for 2026-10-13.
