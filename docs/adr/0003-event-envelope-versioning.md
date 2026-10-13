# ADR-0003: Additive envelope fields for versioning and causation

- **Status:** accepted (approved by the project owner on 2026-10-13)
- **Date:** 2026-10-13
- **Phase:** A01 (implemented in A04)

## Context
The original envelope has no explicit version, so old logs cannot be upcast reliably when a
payload changes. Event-sourcing guidance recommends "a version identifier in the envelope or
the type name" plus upcasters (research/04 §5.3). The UI also needs causation, for example
"this tool call belongs to that agent turn", to animate bundles and focus correctly. And the
evaluation needs to know which engine build produced a log.

## Decision
Keep all core fields unchanged. Add four **optional, additive** fields:

| Field | Type | Meaning |
|---|---|---|
| `v` | integer | Envelope schema version (starts at `1`) |
| `pv` | integer | Payload schema version for this `kind`. Upcasters dispatch on `(kind, pv)` |
| `parent` | string \| null | ID of the causing event (e.g. `agent.state` → `verdict.issued`) |
| `producer` | string | `repro/<semver>+<git sha>` of the emitting engine |

Exports map these onto CloudEvents 1.0 (`dataschema` derives from `kind` and `pv`).

## Alternatives considered
| Option | Pros | Cons |
|---|---|---|
| Version in the kind name (`test.finished@2`) | No envelope change | Every consumer's switch must handle versioned names. Causation and producer still missing |
| A single `schema` URI field | Self-describing | Verbose per event, and causation still missing |
| Adopt CloudEvents as the storage envelope | Standard | Extensions must be scalar, so `target` has to move into `data`. That changes core fields (research/04 §5.1) |

## Consequences
If accepted, phase A04 adds these fields to the JSON Schema and the generated types. If
rejected, the fallback is versioned kind names, with causation and producer kept inside
payloads where needed.
