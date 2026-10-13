# @repro/events

The event schema is the contract between the engine and the cockpit (ADR-0002). This package is
its single source of truth.

| Path | Contents | Phase |
|---|---|---|
| `schema/common.schema.json` | Shared identifiers (ULID-based ids, symbol and test ids, repo-relative paths), enums, value objects | A04 |
| `schema/envelope.schema.json` | Fields every event carries: core fields plus `v`, `pv`, `parent`, `producer` (ADR-0003) | A04 |
| `schema/event.schema.json` | A complete event. Its `oneOf` is **the registry of kinds**: each branch fixes `kind`, the allowed `stage`(s), `pv`, and the payload schema | A04 |
| `schema/payloads/<kind>.schema.json` | One closed payload schema per kind (34 in v1) | A04 |
| `schema/models/*.schema.json` | Claim, evidence, verdict, missing item, artifact reference, Reproduction Card | A04 |
| `examples/` | For every kind, model and the envelope: valid examples and invalid examples, each with a reason | A04 |
| `examples/logs/sample-run.jsonl` | A coherent 45-event run used by log tooling and golden tests | A07 |
| `python/` | `repro-events`: schema registry, validators, draft-07 agent-schema derivation, codegen, generated Pydantic models (`models.py`) | A04/A05 |
| `src/generated/types.ts` | Generated TypeScript types, `ReproEvent` union, `EVENT_KINDS`, `KIND_STAGES` | A05 |

## Rules

- Schemas are JSON Schema draft 2020-12, with no `$id`. Files reference each other by relative
  path.
- Keywords that draft-07 or the code generators cannot express (`prefixItems`,
  `unevaluated*`, `$dynamicRef`, …) are not used. A test enforces this.
- Change the schema first, add or adjust examples, run `pnpm gen`, then update producers and
  consumers. Generated files are committed; CI fails if they are stale.
- Adding a kind or an optional field is additive. Changing or removing a field bumps the
  kind's `pv` (or the envelope `v`) and needs an upcaster.
- A new kind needs: a branch in `event.schema.json`, `payloads/<kind>.schema.json`,
  `examples/events/<kind>.json` with at least one valid and one invalid example, and a row in
  ARCHITECTURE §5.2. Tests fail if any of these is missing.

## Commands

```
pnpm gen                                     # regenerate TS types + Pydantic models (ADR-0014)
uv run repro-events validate LOG.jsonl       # schema + log invariants (seq, ids, evidence-before-citation)
uv run repro-events normalise LOG.jsonl      # canonical, id/time-normalised JSONL
uv run repro-events-codegen --check          # drift check
uv run pytest packages/events/python/tests   # schema hygiene, registry, examples, models, codegen
pnpm --filter @repro/events test             # Ajv validation of all examples + type assertions
```
