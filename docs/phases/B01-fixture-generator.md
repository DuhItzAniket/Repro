# B01 — Deterministic fixture generator & reference log

| | |
|---|---|
| **Stage** | B — Cockpit on fixtures |
| **Status** | done |
| **Depends on** | A07 |
| **Branch / PR** | `phase/B01-fixture-generator` · [#10](https://github.com/DuhItzAniket/Repro/pull/10) |
| **Started / finished** | 2026-10-13 / 2026-10-13 |

## Objective
Give the cockpit a realistic, reproducible event stream before any engine exists: a seeded
generator, a committed reference log and a committed stress log.

## Scope
- `packages/synth` (`@repro/synth`): a seeded PRNG, ULIDs, a timeline that plays the single
  writer, a synthetic repository, a scripted PR story, and the `DEMO` and `STRESS` profiles.
- `apps/web/fixtures/demo-run.jsonl` and `stress-run.jsonl`, with a drift test and
  `pnpm fixtures`.
- The definition of a *check* (ADR-0015). The counts test needs it, and so do B02, B09 and the
  engine stages.
- Cross-language validation: the Python reference validator accepts both fixtures.

## Out of scope
- Projections, the EventStore and the counters UI (B02, B03).
- Fixtures for live/WebSocket replay (C08 uses real engine logs).

## Design notes
- **TypeScript, not Python.** The consumers are TypeScript, and the stress benchmark (B04) can
  generate variants in the browser without loading files. The generated `ReproEvent` types
  check every payload at compile time. Python still validates the committed output.
- **Determinism.** The PRNG is sfc32 seeded by splitmix32, with named sub-streams (`fork`), so
  adding a draw in one place does not reshuffle the rest. The generator uses no `Math.random`,
  no clock and no transcendental functions. ULIDs carry real millisecond time plus seeded
  randomness. Drafts are emitted in any order. `Timeline.build` then sorts by time, assigns
  `seq` with no gaps, resolves `parent` links, and fails if a parent would sort after its child.
  `evidence.seq` is patched to its event's `seq`.
- **One story, scaled by profiles.** Fixed story:
  - four claims (fix, perf, refactor, deps);
  - seven changed symbols, including a module-level change;
  - 17 tests covering F2P, P2F, new, modified (skip added), flaky and P2P;
  - three behaviour diffs (one unstable), a dependency diff, two perf comparisons, and four
    invariants;
  - 12 agents: a reader, four probe writers, four reviewers, an order-swap reviewer, a gap
    reviewer and QA;
  - a rejected verdict followed by a retry, and four missing items.

  The `STRESS` profile adds 1,978 modules, 60 blast-radius symbols and 583 selected tests
  around the same story.
- **Realism details:**
  - three sandboxes run concurrently, and A′ uses another test order;
  - tests run in pytest collection order (file, then line);
  - flips are re-run twice per side, and perf uses ABBA interleaving;
  - the import graph has hubs and package locality;
  - only blast-radius functions are traced;
  - covers and calls edges come from the selection-map pass at the start of the run stage.
- **Check model (ADR-0015).** A check is a `diff.*` or `invariant.result` event. The envelope
  status says `ok`, `fail` (a problem on its own) or `warn` (needs a claim, or could not be
  compared). Pending checks resolve through supported verdicts. The generator's plan is
  recounted from events by an independent implementation in the test.
- **Python validator speed-up (in scope; found while adding the cross-language test).**
  `SchemaSet.event_errors` re-validated every event against all 34 `oneOf` branches as a
  consistency guard, at about 2.8 ms per event. It now caches validators and skips that
  guard when `kind_discriminates` holds. That is a structural property checked once and
  tested in both directions. Stress log: 52.8 s → 10.5 s, with identical results (497 tests).

## Acceptance criteria
- [x] AC1: Same seed gives a byte-identical log (`is byte-identical for the same seed…`, both
      profiles; plus the committed-fixture drift test).
- [x] AC2: Both logs validate against the schema: Ajv in TypeScript for every event of both
      logs, and `repro-events validate` / `validate_log` in Python with 0 errors and 0
      warnings (`test_web_fixtures.py`).
- [x] AC3: Counts match the spec in a test:
  - demo: 1 PR, 4 claims, 12 agents, 147 files, 28 checks, 4 flagged, 2,334 events;
  - stress: exactly 10,000 graph edges, and a peak of 3,068 execution events in one second
    (spec: ≥ 2,000).

  Every `summary` number is recounted from the events.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `scenario.test.ts` determinism per profile; `fixtures.test.ts` (`toMatchFileSnapshot`) |
| AC2 | `scenario.test.ts` Ajv test; `packages/events/python/tests/test_web_fixtures.py` |
| AC3 | `scenario.test.ts` "demo/stress profile matches the B01 spec", recount test, and 15 random seeds (fast-check) |

---

## What shipped
- `@repro/synth`: `generateRun(profile, seed)`, `toJsonl`, `DEMO`, `STRESS`, `FIXTURE_SEED`,
  `Rng`, `hash32`.
- `apps/web/fixtures/demo-run.jsonl` (0.89 MB, 85 KB gzip) and `stress-run.jsonl` (7.3 MB,
  0.65 MB gzip), marked `linguist-generated`.
- `pnpm fixtures` (regenerate) and `@repro/events/testing` (the Ajv harness, exported for other
  packages' tests).
- ADR-0015, ARCHITECTURE §5.3 rule, DESIGN.md header and index definitions.
- Faster `SchemaSet.event_errors` and `SchemaSet.kind_discriminates`.

## Evidence
- Tests: `packages/synth` 34 (rng 12, scenario 20, fixtures 2); pytest 497 (+4:
  `test_web_fixtures` ×2, `test_kind_alone_selects_the_branch`,
  `test_discrimination_is_detected_structurally`).
- Generation time (Windows dev box, Node 25.9.0, inside Vitest): demo about 12 ms, stress about 60 ms.
- CI run: see the PR checks.

## Deviations from spec
- The stress fixture is 600 selected tests, not a separate synthetic burst. A real test batch
  across three sandboxes produces the 2k-event burst, which is closer to what the engine will
  emit.

## Known gaps
- The ring's file cards need file contents, and no v1 event carries them. B06 will render cards
  from what events do carry (symbols and lines per file) or propose a schema addition through
  an ADR.
- The rejected-verdict path does not emit a `verdict_rejected` missing item, because the retry
  succeeds. A fixture where retries are exhausted is left to G06.

## Dependencies added
None to the product. `@repro/synth` uses existing pinned dev tools (TypeScript, Vitest,
fast-check, @types/node) and the workspace `@repro/events`.

## Research notes
ADR-0015's resolution rule (a difference is accepted only when a supported verdict cites it)
puts "claim-relative explained delta" into terms an event log can check. Logged in
`docs/paper/LOG.md`.
