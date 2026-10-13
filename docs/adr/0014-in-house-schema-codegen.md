# ADR-0014: In-house code generation from the event schema

- **Status:** accepted (decided in A05 under the owner's delegation for Stage A)
- **Date:** 2026-10-13
- **Phase:** A05

## Context
The event schema (A04) must produce TypeScript types and Pydantic v2 models that agree with it
exactly, including a **discriminated union over `kind`** in both languages. The research
baseline recommended json-schema-to-typescript 16.0.0 for TS and datamodel-code-generator
0.83.0 for Python, with a hand-written discriminated-union step. It flagged that
datamodel-code-generator treats `discriminator` as OpenAPI-only (research/04 §6).

A05 tried json-schema-to-typescript 16.0.0 on the real `event.schema.json` (2026-10-13):
- The union came out as `EventEnvelope & (RunStarted | …)`. Each per-kind branch had
  **optional** discriminants (`kind?: "run.started"`, `stage?`, `payload?`) and an
  `[k: string]: unknown` index signature, because the branches add constraints but do not
  repeat `required` and `additionalProperties`. Narrowing on `kind` is therefore unreliable.
- Nested objects became anonymous inline types, and the shared definitions (`EventId`,
  `Stage`, `SymbolId`, …) collapsed to `string` or repeated inline unions. Panel and projection
  code needs those names.

Fixing this would mean restructuring the schema around one generator's naming heuristics,
then doing the same for a second generator in Python. Pydantic equivalence also needs features
those generators don't give us:
- strict mode;
- `regex_engine="python-re"` (the path pattern uses lookaheads);
- explicit-null rejection for optional, non-nullable fields;
- `minProperties`;
- `uniqueItems`;
- aliases for keyword-named fields (`class`).

## Decision
Generate both languages with `repro_events.codegen` (about 600 lines, stdlib only). It
supports **exactly** the keyword subset the schema hygiene test allows. Anything else is a
`CodegenError`, never a silent `Any`. Properties:
- **Names:** `$defs` key for shared definitions; `title` for models; `PascalCase(kind)+Payload`
  for payloads; `Parent+Property` for nested objects. Two schema locations producing the same
  name is an error (a real collision, `Verdict`, was caught this way).
- **TypeScript:** named aliases and interfaces, JSDoc with constraints, `ReproEvent`
  discriminated union, `EventKind`, `EVENT_KINDS`, `KIND_STAGES`.
- **Python:** closed, strict, frozen Pydantic v2 models, per-kind event classes, an
  `Annotated[Union, Field(discriminator="kind")]` `Event`, and `EVENT_ADAPTER`.
- **Equivalence is tested, not assumed:**
  - every valid example round-trips exactly through the Pydantic models;
  - every invalid example is rejected by the Pydantic models, by `jsonschema`, and by Ajv
    (TypeScript);
  - TS type-level assertions are checked by `tsc`.
- **Drift gate:** `repro-events-codegen --check` runs in CI and in a pytest test.

## Alternatives considered
| Option | Why not |
|---|---|
| json-schema-to-typescript + datamodel-code-generator | Loose discriminants and index signatures in the union, anonymous nested types, lost aliases (observed). Pydantic strictness features would still need custom work, and there are two toolchains to keep in agreement |
| quicktype | Python output is dataclass-based, not Pydantic |
| TypeSpec / Protobuf as the source | Adds a compiler. JSON payloads, SQLite JSON and Pydantic validation are second-class (research/04 §6) |

## Consequences
- We own about 600 lines of generator code. Unsupported constructs fail loudly, so extending
  the schema with a new construct means extending the generator in the same PR.
- Generated files are committed, excluded from formatters and linters, but type-checked
  (`tsc`, `mypy --strict`).
- Revisit if the schema needs constructs beyond the subset (e.g. recursive types) and an
  off-the-shelf generator handles them faithfully.
