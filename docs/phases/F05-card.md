# F05 — Deterministic card & exports (MD/JSON) + card view

| | |
|---|---|
| **Stage** | F — Policy & deterministic card |
| **Status** | done |
| **Depends on** | F04 |
| **Branch / PR** | `phase/F05-card` · [#58](https://github.com/DuhItzAniket/Repro/pull/58) |
| **Started / finished** | 2026-10-15 / 2026-10-15 |

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
- [x] AC1 (roadmap): golden cards for every fixture.
- [x] AC2 (roadmap): byte-identical cards from replay.
- [x] AC3: Markdown and canonical JSON exports; the card view in the cockpit.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_a_run_reproduces_the_fixture[*]`: each fixture's card against `golden/cards/<fixture>.json` (normalised: IDs, times, the machine, timing numbers) |
| AC2 | `check_card` on every run in `test_run_stage.py`: one `card.published`, its digest, the `cards` row, the card assembled again from the stored log byte for byte, `run.finished`'s status; `test_the_card_rests_on_what_precedes_its_publication` |
| AC3 | `test_export_writes_the_card_the_run_published`, `test_a_card_that_differs_from_its_log_is_refused`, `test_markdown`; web: `card.test.ts`, `a11y.test.tsx` (the header button, the drawer, axe) |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.card`: `assemble`, `canonical`, `digest`, `before_card`, `log_digest`, `counts`,
  `published`, `regenerate` (`Regenerated`), `render` (Markdown); `repro.card.job`:
  `card_job`, `CardStore`, `StoreCards`.
- `StoreWriter.put_card`; `pipeline_jobs(cards=...)`; `run.finished`'s `card_status` from
  `card.published`; `repro export` (md, json, `-o`) and the card check in `repro replay`.
- `repro.sandbox.process.HASH_SEED` (both sandboxes); the tests job's `environment` evidence.
- Schema and examples: `card.published.card`; the card model's `status_reasons`, gap `check`,
  `kind`, `resolution`, invariant `message`, nullable conditions.
- Cockpit: the `card` focus, `focus/card.ts` (`cardView`), the header's card button; drawer
  tables keep their first column's words whole.
- Golden cards for the 17 fixtures (`engine/tests/golden/cards/`, `card_support.normalised`),
  `check_card` on every end-to-end run, `test_card.py` (8); web `card.test.ts` (4) and two
  `a11y.test.tsx` cases.

## Evidence
Each fixture's card through `repro run` (Windows, process sandbox), as its golden file holds
it ("*": a reason that does not decide the status, listed as also incomplete):

| Fixture | Status | Gap | Reasons |
|---|---|---|---|
| `invariants-pass` | VERIFIED | 0 | none |
| `flaky`, `noisy`, `untested` | UNVERIFIABLE | 1, 0, 0 | coverage |
| `api-break` | FLAGGED | 4 | gap (API, behaviour), invariant failed |
| `breaks-one`, `selection`, `test-tamper` | FLAGGED | 2, 4, 10 | gap (two kinds of check) |
| `false-claim`, `honest-fix`, `policy-weaken`, `probe-only`, `silent-change` | FLAGGED | 1, 4, 1, 1, 2 | gap |
| `forbidden-path`, `net-call` | FLAGGED | 0 | invariant failed |
| `new-dep` | FLAGGED | 2 | gap, invariant failed |
| `perf-regress` | FLAGGED | 1 | gap, invariant failed, coverage* |

- Byte for byte: every end-to-end run (the 17 fixtures and the two broken-environment runs)
  assembled its card again from the stored log and got the published bytes, with the same
  digest in `card.published`, the `cards` row and `run.finished`'s status.
- Stability: a second full run matched 16 golden cards; `perf-regress` matched when run alone
  (in the full run its `test_report_is_sorted` timed as a regression while a type check and a
  lint ran beside it, a D07 timing effect, not the card).
- In a browser (headless Edge, a real `api-break` run replayed by `repro replay`): the header's
  "card FLAGGED" button opens the drawer with the four flagged differences linked to their
  checks, `public_api_stable` failed, the missing item and the conditions; Escape closes it and
  returns focus to the button. A first version's five-column gap table wrapped words a letter
  a line in the 380 px drawer; the tables now have two columns.
- CI run: linked in the PR (#58).

## Deviations from spec
- ARCHITECTURE §5 gave `card.published` only a status, a digest and counts: it now carries the
  card too (optional, so additive), so the cockpit and a log file hold the card itself.
- The card model is completed in place at `card_version` 1, since no card was produced before.
- The seeds are evidence (`environment`), so the card reads them from the log.
- `repro replay` reports a card that differs from its log instead of refusing to serve it;
  `repro export` refuses.

## Known gaps
- The synthetic demo log's `card.published` has the status and counts but no card (building
  one would duplicate the status rules in TypeScript); the drawer says so. Real runs carry it.
- `generated_at` is the last logged event's time, not when the card was assembled, so that a
  replay gives the same bytes.
- The cockpit shows the card as published; it does not check `card_sha256` itself.
- The in-toto, SARIF and JUnit exports and the PR comment are H04's.

## Dependencies added
None.

## Research notes
- ARCHITECTURE §7 (the card), §5 (`card.published`), §11 (`/runs/{id}/card`); ADR-0002 (the
  log as the contract); DESIGN.md "Accessibility" (the card as a semantic table).
