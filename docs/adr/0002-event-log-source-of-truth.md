# ADR-0002: The event log is the source of truth

- **Status:** accepted (ratifies a ground rule from the original brief)
- **Date:** 2026-10-13
- **Phase:** A01

## Context
Repro must be auditable. A verdict is only as trustworthy as our ability to show how it was
reached. The cockpit must support live viewing, replay at several speeds and scrubbing, and
the evaluation (Stage J) must regenerate every card without re-running the LLMs. Event
sourcing gives all three: state at any point is the fold of events up to that point
(Fowler; Azure Architecture Center "Event Sourcing" pattern, research/04 §5.3,
research/05 §5).

## Decision
- The engine **only emits events**. Runs, evidence and cards are persisted alongside the log
  for convenient querying, but every one of them can be reconstructed from it.
- The log is **append-only**. Corrections are new events, never edits.
- `seq` is assigned by a single writer and is the only ordering. `ts` is informational.
- The UI is a **pure projection** of the log. No UI state may depend on wall-clock time,
  randomness, or anything other than (events up to *t*, *t*).
- `repro replay <run-id>` re-emits a stored log with identical semantics to a live run.
- The schema lives in `packages/events`. Producers and consumers are generated from it.

## Alternatives considered
| Option | Why not |
|---|---|
| State-based storage, with the UI polling REST endpoints | Loses replay and scrubbing. Polling contradicts "the UI never polls". The audit trail would be a second, divergent mechanism |
| OpenTelemetry traces as the primary record | Span trees do not model evidence or claims well. The GenAI conventions are still "Development" (research/04 §5.2). OTel is kept as a possible export |

## Consequences
- Determinism becomes testable: golden-log tests compare normalised logs.
- Schema evolution needs discipline: tolerant readers, versioning (ADR-0003) and upcasters.
- Logs can grow large (trace samples, log lines). High-volume kinds are batched, and raw
  observations live in artifacts referenced by digest rather than inline payloads.
