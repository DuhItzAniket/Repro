# F05 — Deterministic card & exports (MD/JSON) + card view

| | |
|---|---|
| **Stage** | F — Policy & deterministic card |
| **Status** | in progress |
| **Depends on** | F04 |
| **Branch / PR** | `phase/F05-card` · PR pending |
| **Started / finished** | 2026-10-15 / — |

## Objective
Give every run its Reproduction Card: assembled by the engine from the run's own log, published
with the run, exported as Markdown or canonical JSON, shown in the cockpit, and assembled again
byte for byte from the log whenever it is replayed or exported.

## Scope
- **Assembly** (`repro.card.assemble`): the status and its reasons (F04), the conditions, the
  claims and verdicts, the gap with what the rules made of each item, the invariants, the missing
  items, and the replay digest, all from the events before `card.published`. What a run did not
  reach (an interpreter, a sandbox, the seeds) is null.
- **Canonical JSON**: sorted keys, no whitespace, UTF-8; `card_sha256` is its SHA-256.
- **The card stage** (`repro.card.job`): the last job, after every other however they ended. It
  waits for its first event to be stored (so every earlier one is), reads the run's log back,
  publishes `card.published` with the card, and records it in the `cards` table;
  `run.finished`'s `card_status` comes from it.
- **Exports**: `repro export RUN|LOG --format md|json [-o FILE]` assembles the card again and
  refuses one that differs from the published card; `repro replay` reports the same check.
- **The card view**: a header button once the run has a card status, opening the card in the
  drawer (semantic tables; each gap item links to its check).
- **Schema** (additive): `card.published` may carry `card`; the card model gains
  `status_reasons`, each gap item's `check`, `kind` and `resolution`, and each invariant's
  `message`; conditions a run may not reach are nullable. The seeds are `environment`
  evidence from the tests job.
- **Golden cards**: every fixture's card, normalised, in `engine/tests/golden/cards/`.

## Out of scope
- The in-toto, SARIF and JUnit exports and the PR comment (H04); claims and verdicts (Stage G).

## Design notes
- **The log is the card's only input.** The card job reads the stored log rather than the
  run's memory, so a replay of the same log, or of an exported one, assembles the same bytes.
  `replay.event_log_sha256` digests that log (canonical JSON lines), and `generated_at` is its
  last event's time, not the clock's.
- **The card travels with the run.** `card.published` carries the card itself (an optional
  field, so additive): the cockpit stays a projection of the events, and a log file holds its
  own card to be checked against.
- **A model completed, not changed.** No card was produced before F05, so the card model is
  completed in place at `card_version` 1.
- **Export is strict, replay reports.** An export that would differ from what the run published
  is refused; a replay shows the log as it is and says whether its card matches.

## Acceptance criteria
- [ ] AC1 (roadmap): golden cards for every fixture.
- [ ] AC2 (roadmap): byte-identical cards from replay.
- [ ] AC3: Markdown and canonical JSON exports; the card view in the cockpit.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_a_run_reproduces_the_fixture[*]`: each fixture's card against `golden/cards/<fixture>.json` (normalised: IDs, times, the machine, timing numbers) |
| AC2 | `check_card` on every run in `test_run_stage.py`: one `card.published`, its digest, the `cards` row, the card assembled again from the stored log byte for byte, `run.finished`'s status; `test_the_card_rests_on_what_precedes_its_publication` |
| AC3 | `test_export_writes_the_card_the_run_published`, `test_a_card_that_differs_from_its_log_is_refused`, `test_markdown`; web: `card.test.ts`, `a11y.test.tsx` (the header button, the drawer, axe) |

---
*Filled in at the end of the phase:*

## What shipped

## Evidence

## Deviations from spec

## Known gaps

## Dependencies added
None.

## Research notes
- ARCHITECTURE §7 (the card), §5 (`card.published`), §11 (`/runs/{id}/card`); ADR-0002 (the
  log as the contract); DESIGN.md "Accessibility" (the card as a semantic table).
