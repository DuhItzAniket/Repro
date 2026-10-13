# A04 — Event schema v1

| | |
|---|---|
| **Stage** | A — Foundation |
| **Status** | done |
| **Depends on** | A02 (developed on top of A03's gates) |
| **Branch / PR** | `phase/A04-event-schema` · [#4](https://github.com/DuhItzAniket/Repro/pull/4) |
| **Started / finished** | 2026-10-13 / 2026-10-13 |

## Objective
Define the contract between the engine and every consumer. That covers the event envelope, every
v1 event kind, and the evidence, claim, verdict and card models. Each comes with valid and
invalid examples and is tested, so later phases build against a stable, machine-checked schema.

## Scope
- JSON Schema 2020-12 documents under `packages/events/schema/`.
- Examples under `packages/events/examples/`.
- `repro-events` Python package: schema registry, validators, draft-07 derivation for agent
  output (ADR-0007).

## Out of scope
- Generated TS and Pydantic types, cross-language round trip (A05). CI drift gate (A05/A06).
- The per-claim verdict schema with an evidence-ID enum. A05 provides the generic converter,
  and G05 builds the per-claim schema on top of it.

## Design notes
- **Registry = `event.schema.json`.** Its `oneOf` has one branch per kind. Each branch fixes
  `kind` (const), the allowed `stage`(s), `pv` (const 1), and `payload` (`$ref` to
  `payloads/<kind>.schema.json`). Tooling reads the kind list from this file, so there is no
  second registry to drift.
- **No `$id`; relative file references.** Generators and validators (json-schema-to-typescript,
  datamodel-code-generator, ajv, Python `referencing`) all resolve relative file paths. Owning
  a URI namespace is not needed and is not claimed.
- **Closed objects everywhere** (`additionalProperties: false`). All fields are required, and
  "absent" is an explicit `null`, so consumers never guess between missing and null.
- **Identifiers:** `evt_`/`run_`/`ev_` + Crockford-base32 ULID. Claim ids `C<n>`. Agent ids
  `a<nn>`. Symbol ids `module:qualname#ordinal`. Repo-relative POSIX paths, which reject drive
  letters, leading `/`, backslashes and `..`, so Windows paths can never leak into events.
- **Timestamps** must be UTC with a `Z` suffix. This is enforced by `pattern`, not only
  `format`, because format checking is optional in validators.
- **Envelope (ADR-0003):** `v` (const 1), `pv`, and `producer` are required in v1, since no older
  logs exist to stay compatible with. `parent` is optional.
- **Sides:** `base`, `base_repeat` (A′, noise measurement), `head`.
- **Constraint-preserving draft-07 derivation.** `to_draft07()` inlines every `$ref`, drops only
  bookkeeping keywords, and **rejects** keywords draft-07 cannot express rather than silently
  weakening the schema. A hygiene test forbids those keywords in all source schemas, so
  derivation always succeeds.
- **Precise errors.** `SchemaSet.event_errors()` reports envelope errors first, then validates
  against the matching kind's branch, so messages point at `$.payload.<field>` instead of
  "not valid under any of the given schemas".

## Acceptance criteria
- [x] AC1: Every kind has a schema with at least one valid and one invalid example, validated in tests.
- [x] AC2: An "every kind has a schema" test passes. It checks that payload files and kinds
      match one-to-one, that each kind has an examples file, and that the kinds match the
      ARCHITECTURE §5.2 table.
- [x] AC3: Envelope (with ADR-0003 fields), evidence, claim, verdict and card schemas exist with examples.
- [x] AC4: The draft-07, `$ref`-free variant generator exists and is tested.

## Test plan → evidence
| Criterion | Tests (`packages/events/python/tests/`) |
|---|---|
| AC1 | `test_examples.py::test_valid_event_examples_pass[*]`, `::test_invalid_event_examples_fail[*]` (34 kinds; every invalid example carries a reason) |
| AC2 | `test_kinds.py` (registry ↔ payload files ↔ examples ↔ ARCHITECTURE table) |
| AC3 | `test_examples.py::test_envelope_examples`, `::test_model_examples[*]` |
| AC4 | `test_agent_schema.py`: self-contained draft-07 for all 40 payload/model schemas, agreement with the source on all model examples and all valid payloads, rejection of unsupported keywords and recursion, keywords next to `$ref` preserved |
| Hygiene | `test_schema_files.py`: 2020-12 meta-validation, no `$id`, no unsupported keywords, every `$ref` resolves, payloads and models are closed objects with titles |

Result: `uv run pytest`: **380 passed** (Windows, Python 3.13). Ruff, mypy (strict) and Biome are clean.

## What shipped
- `schema/`: `common`, `envelope`, `event` (34 kinds), `payloads/` × 34, and `models/` × 6
  (claim, evidence, verdict, missing, artifact, card).
- `examples/`: `events/` × 34, `models/` × 5, and `envelope.json` (15 invalid envelope cases:
  ids, seq, timestamp offset, stage, kind, agent, four path-escape forms, empty target, `v`,
  `producer`, unknown field, status).
- `python/` (`repro-events`): `schemas.py` (`SchemaSet`, `KindInfo`, `event_errors`) and
  `agent_schema.py` (`to_draft07`, `UnsupportedSchemaError`).
- Docs: `packages/events/README.md` (layout, rules, "adding a kind" checklist), ARCHITECTURE
  §5–7 aligned (required v1 fields, sides, `policy_change` evidence type, `test`/`docs` claim
  kinds), PRODUCT claim kinds.

## Deviations from spec
- Added `policy_change` (evidence type) and `test`/`docs` (claim kinds). These are needed
  for ARCHITECTURE §12 (policy edits in head are gap items) and for PRs that claim only test or
  doc changes. Both are additive and documented.
- The initial schema files were produced by a one-off generator script so the ~40 documents
  stay consistent. From now on the committed JSON files are the source of truth. The script is
  not part of the repository.

## Known gaps
- `format: date-time` is checked only where the validator supports it. The `pattern` carries the
  real constraint.
- Large arrays (e.g. `blast.computed.affected`) have no size cap yet. Revisit when real repos
  stream through in Stage C.

## Dependencies added
| Package | Version | Licence | Why |
|---|---|---|---|
| jsonschema | 4.26.0 | MIT | Schema validation |
| referencing | 0.37.0 | MIT | Cross-file `$ref` resolution |
| types-jsonschema (dev) | 4.26.0.20261006 | Apache-2.0 | Type stubs for strict mypy |

## Research notes
The draft-07 derivation and the "reject, don't weaken" rule are part of contribution C2
(evidence-constrained adjudication). Logged in `docs/paper/LOG.md`.
