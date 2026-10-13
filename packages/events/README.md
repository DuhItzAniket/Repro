# @repro/events

The event schema is the contract between the engine and the cockpit (ADR-0002). This package is
its single source of truth.

| Path | Contents | Phase |
|---|---|---|
| `schema/` | JSON Schema 2020-12: envelope (ADR-0003 fields), one schema per event kind, evidence, claim, verdict, card | A04 |
| `src/` | Generated TypeScript types (json-schema-to-typescript) and validators | A05 |
| `python/` | Generated Pydantic v2 models, published to the uv workspace as `repro-events` | A05 |

Rules:
- Change the schema first, regenerate, then update producers and consumers.
- Generated files are committed, and CI fails if they drift from the schema (A05/A06).
- Adding a kind or an optional field is additive. Changing or removing a field bumps `pv`
  (payload version) or `v` (envelope version) and needs an upcaster.
