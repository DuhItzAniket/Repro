# @repro/synth

Deterministic synthetic Repro runs. The cockpit (Stage B) is built and performance-tested
against these event logs before any engine exists, so the UI is a pure projection of the event
stream from day one (IMPLEMENTATION_PLAN §1).

```ts
import { DEMO, FIXTURE_SEED, generateRun, toJsonl } from "@repro/synth";

const run = generateRun(DEMO, FIXTURE_SEED); // { events, summary, profile, seed }
const jsonl = toJsonl(run.events); // byte-identical for the same profile and seed
```

## The story

Every profile plays the same scripted pull request against a fictional library,
`synthetic/timekeeper`. PR #128 makes four claims:

| Claim | Kind | What the run finds | Verdict |
|---|---|---|---|
| C1 `parse_date` returns aware datetimes for offset inputs | fix | two F2P tests, a new DST test, a behaviour diff | supported |
| C2 `expand_rrule` is about twice as fast | perf | ABBA timing ratio 0.49 (the first verdict attempt is rejected for a bad quote) | supported |
| C3 `format_duration` refactor with no behaviour change | refactor | `'2h 0m'` → `'2h'` behaviour diff and a P2F test | contradicted (order swap agrees) |
| C4 adds `example-tzdb` | deps | dependency diff, but the `no_new_dependencies` invariant fails | supported |

The run also shows a skip marker added to a breaking test (test tampering), a flaky test and an
unstable order-only diff (both masked), a test too fast to time, a changed function no test
reaches, and four probe writers whose probes find nothing new. The card ends FLAGGED.

Everything is invented: the repository, package `example-tzdb`, SHAs, digests and token counts.
`cost.estimate` uses a flat synthetic rate (`SYNTHETIC_RATES`), not any model's price. The
producer is `repro/0.2.0+synthetic`.

## Profiles

| Profile | Files | Graph edges | Selected tests | Checks | Events | Purpose |
|---|---|---|---|---|---|---|
| `DEMO` | 147 | 1,500 | 17 | 28 (20 passed, 4 flagged, 4 unassessed) | 2,334 | Reference log for the cockpit and visual tests |
| `STRESS` | 2,000 | 10,000 | 600 | 611 | 18,542 | Performance: 10k edges, a burst of over 2,000 execution events in one second |

Checks follow ADR-0015. The committed fixtures (`apps/web/fixtures/*-run.jsonl`) use seed
`FIXTURE_SEED` (1).

## Determinism

- No `Math.random`, no clock, no transcendental math. The PRNG is sfc32 seeded through
  splitmix32 (`rng.ts`), and every concern draws from its own named stream (`fork`).
- Ids are real ULIDs whose random part comes from a seeded stream.
- Events are drafted in any order, then ordered by time like the single writer would
  (`timeline.ts`). `seq` has no gaps and `parent` always points backwards.

## Tests

`pnpm --filter @repro/synth test`:
- the same seed gives byte-identical JSONL; another seed differs;
- every event passes Ajv (draft 2020-12) against `packages/events/schema`;
- log invariants: seq, ids, parents, stages per kind, evidence created before cited;
- graph references resolve; verdict quotes are substrings of the cited evidence;
- every count in `summary` matches an independent recount from the events, including the
  check model;
- the B01 spec numbers, and for 15 random seeds a valid run with the same check counts;
- the committed fixtures equal the generator's output (`fixtures.test.ts`).

`packages/events/python/tests/test_web_fixtures.py` also validates both fixtures with the
Python reference validator.

After an intended generator change, run `pnpm fixtures` and review the fixture diff.
