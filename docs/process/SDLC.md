# Repro — Development Lifecycle

This document describes how work on Repro is planned, built, verified, documented and shipped.
Every contributor follows it, human or agent. It is deliberately strict. Repro's job is to say
whether a change can be trusted, so its own changes have to meet the same bar.

## 1. Work hierarchy

| Level | Identifier | Size | Output |
|---|---|---|---|
| **Stage** | Letter, e.g. `C` | 4–12 phases. One coherent capability. | A tagged release (`v0.x.0`), a stage report, full CI matrix green |
| **Phase** | Stage letter + 2 digits, e.g. `C05` | One reviewable unit, roughly 0.5–3 days of focused work | One merged PR, a phase record, updated roadmap row |
| **Task** | Checklist item inside a phase record | Hours | Commits on the phase branch |

The authoritative list of stages and phases is [`docs/ROADMAP.md`](../ROADMAP.md). Phase IDs never
change once published. If a phase is split, the new parts get suffixes (`C05a`, `C05b`). A
dropped phase stays in the table with status `dropped` and a reason.

## 2. Phase lifecycle

```
 READY ──► SPEC ──► BUILD ──► VERIFY ──► DOCUMENT ──► INTEGRATE ──► DONE
```

1. **Ready.** A phase may start only when its *Depends on* phases are `done` and its
   acceptance criteria in the roadmap are testable. If a criterion is vague, fix the roadmap
   first, in its own commit.
2. **Spec.** Copy [`PHASE_TEMPLATE.md`](PHASE_TEMPLATE.md) to
   `docs/phases/<ID>-<slug>.md` and fill in *Objective*, *Scope*, *Out of scope*,
   *Design notes*, *Acceptance criteria* (copied from the roadmap, then refined) and *Test plan*.
   Create the branch `phase/<ID>-<slug>` from an up-to-date `main`.
3. **Build.** Make small commits that follow [Conventional Commits](https://www.conventionalcommits.org/)
   and end the subject with the phase ID: `feat(engine): add worktree manager [C05]`.
   Schema changes go first (`packages/events`), then producers, then consumers.
4. **Verify.** Run everything CI runs, locally: lint, format check, type check, unit tests,
   plus the integration and end-to-end suites the phase touches. Every acceptance criterion
   has at least one automated check, or a written reason why it is manual with the manual
   procedure recorded in the phase record.
5. **Document.** Complete the phase record: *What shipped*, *Evidence* (test names, CI run
   link, screenshots or measurements), *Deviations from spec*, *Known gaps*, *Research notes*.
   Update the roadmap row (status, date, PR link), [`CHANGELOG.md`](../../CHANGELOG.md)
   (`Unreleased`), and any doc the change made stale. Write an ADR for every decision that
   is hard to reverse (see §6).
6. **Integrate.** Open a PR titled `[<ID>] <phase title>` using the PR template. CI must
   be green. Squash-merge into `main`, then push.
7. **Done.** The roadmap row reads `done` and links the PR. The phase branch is deleted.

### Definition of Ready (phase)
- Dependencies done; acceptance criteria are concrete and testable.
- Any decision that needs the project owner (stack, event-schema core fields, scope) is approved.

### Definition of Done (phase)
- [ ] All acceptance criteria met and demonstrated by automated checks (or documented manual procedure).
- [ ] Lint, format, type check and tests pass locally and in CI (Ubuntu + Windows).
- [ ] No new warnings left unexplained. No `TODO` without a linked issue or roadmap phase.
- [ ] Phase record complete. Roadmap row, CHANGELOG and affected docs updated.
- [ ] Secrets and privacy check passes (§7).
- [ ] Squash-merged to `main` and pushed.

## 3. Stage gate

A stage ends with a **gate**, which is a short review that the stage delivered what it promised.

1. Full CI matrix green on `main` (Ubuntu + Windows; Python and Node versions as pinned).
2. Stage acceptance criteria from the roadmap demonstrated end to end and recorded in
   `docs/phases/<STAGE>-gate.md` (template: [`STAGE_GATE_TEMPLATE.md`](STAGE_GATE_TEMPLATE.md)).
3. Retrospective: what slipped, what we learned, roadmap adjustments (made as explicit
   roadmap edits, never silently).
4. Release: bump the version, move CHANGELOG `Unreleased` to the version, annotated tag
   `vX.Y.0`, GitHub release notes generated from the CHANGELOG.
5. Research log: anything paper-relevant from the stage goes into
   [`docs/paper/LOG.md`](../paper/LOG.md).

## 4. Branching, commits, versioning

- `main` is always releasable and protected: no direct pushes after the bootstrap commit,
  PRs only, CI required, linear history (squash merges).
- Branches: `phase/<ID>-<slug>`, and `fix/<slug>` for hot fixes, which still reference the phase
  that introduced the bug.
- Commits: Conventional Commits (`feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`,
  `ci`, `chore`) with scopes `events`, `engine`, `web`, `cli`, `agents`, `bench`, `docs`, `ci`.
- Versioning: [SemVer](https://semver.org/). Each stage gate bumps the minor version while
  `0.x`. `v1.0.0` is cut at the end of Stage H (first release a stranger can install and
  trust on their own repo). The event schema carries its own `schema_version`, versioned
  independently (see `docs/ARCHITECTURE.md`).

## 5. Quality bars

| Area | Bar |
|---|---|
| Python | Ruff (lint + format), type checking in strict mode for `engine/src/repro/**`, pytest. Branch coverage ≥ 85 % on engine core packages from Stage C on. |
| TypeScript | Biome (lint + format), `tsc --noEmit` strict, Vitest. Projections/store coverage ≥ 90 %. |
| Schema | Generated TS and Pydantic types are checked in and CI fails on drift. |
| UI perf | 60 fps budget and JS size budget enforced by automated checks from Stage B on (see DESIGN.md). |
| Determinism | Same inputs produce the same event log (modulo timestamps/IDs). Golden-log tests guard this. |
| Agents | Every agent behaviour change is measured against the agent eval set before merge (Stage G on). |
| Docs | A claim about the outside world cites a source. A number is either measured (and the measurement is reproducible) or not stated. |

**On quality of writing and code.** Be concrete. A doc says what the thing does, how we know,
and what it doesn't do. Don't write filler, marketing adjectives, or claims with no evidence
behind them. Code has comments only where intent isn't obvious. Don't add abstractions until
a second real use exists.

## 6. Architecture Decision Records

Decisions that are expensive to reverse are recorded in `docs/adr/NNNN-title.md` (template:
[`docs/adr/0000-template.md`](../adr/0000-template.md)): context, decision, alternatives
considered, consequences. An ADR is `proposed` until the project owner accepts it. Changes to the
stack, the event schema's core fields, or a stage's scope **require** an accepted ADR.

## 7. Secrets, privacy and licensing

The repository is public.

- **Never commit** credentials, tokens, API keys, `.env` files, personal data (names, emails,
  phone numbers, home paths like `C:\Users\<name>`), or machine-specific configuration.
- Commits use the GitHub **noreply** email. Personal emails do not appear in history.
- CI runs a secret scanner (introduced in phase A06) on every PR. A finding blocks the merge.
- Test fixtures and demo repositories contain synthetic data only.
- Do not commit third-party media or code we have no right to redistribute. Dependencies' licences
  are checked when added and recorded in the phase record.
- API keys for agents are read from the environment at runtime and are never logged, written
  into event payloads, or stored in the run database. Event logs are scrubbed of environment
  variables before storage.

## 8. Research discipline

Repro may become a peer-reviewed paper. Treat engineering artefacts as future evidence:

- Record design decisions with their rationale (ADRs). Reviewers will ask "why".
- Every evaluation number must be regenerable from a script and a pinned dataset/version.
- Keep the experiment log ([`docs/paper/LOG.md`](../paper/LOG.md)) append-only and dated,
  including negative results and things that did not work.
- Citations in docs are verified against the primary source. Unverified claims are marked as such.
