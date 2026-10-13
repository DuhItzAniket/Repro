# Cockpit fixtures

Recorded event logs (JSONL, one event per line) that drive the cockpit without an engine.
They are **generated** by [`@repro/synth`](../../../packages/synth/README.md); do not edit them
by hand.

| File | Profile | Events | Use |
|---|---|---|---|
| `demo-run.jsonl` | `DEMO`, seed 1 | 2,334 | Reference run: development, projections, visual regression |
| `stress-run.jsonl` | `STRESS`, seed 1 | 18,542 | Performance budget: 10k edges, ≥ 2k execution events in one second |

Both describe the same synthetic pull request (`synthetic/timekeeper` #128). The card ends
FLAGGED with 28 checks in the demo (20 passed, 4 flagged, 4 unassessed; ADR-0015).

- Regenerate after a generator change: `pnpm fixtures`, then review the diff.
- CI fails if a committed fixture differs from the generator's output
  (`packages/synth/src/fixtures.test.ts`).
- Both logs pass the TypeScript (Ajv) and Python (`repro-events validate`) validators.
