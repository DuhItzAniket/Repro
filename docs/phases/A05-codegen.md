# A05 — Schema codegen & drift gate

| | |
|---|---|
| **Stage** | A — Foundation |
| **Status** | done |
| **Depends on** | A04 |
| **Branch / PR** | `phase/A05-codegen` · PR link in ROADMAP phase log |
| **Started / finished** | 2026-10-13 / 2026-10-13 |

## Objective
Make the schema the single source of truth for code. Typed models are generated for both
languages, their agreement with the schema is proven by tests, and CI fails as soon as
generated code drifts from the schema.

## Scope
- Generator for TypeScript types and Pydantic v2 models, with a discriminated union over `kind`.
- Equivalence and round-trip tests: JSON Schema (`jsonschema`), Pydantic, and Ajv (TS).
- `pnpm gen` / `uv run repro-events-codegen`, plus a `--check` drift gate in CI and pytest.

## Out of scope
- Runtime validators shipped to the UI bundle. Validation runs in tests and tools; the UI
  (B02) checks only the envelope version.
- Packaging the schema files inside the `repro-events` wheel (H05). `default_schema_root()` is
  source-tree based until then.

## Design notes
See **ADR-0014**. In short: json-schema-to-typescript 16.0.0 was run on the real schema and
produced optional discriminants, index signatures and anonymous types. The in-house generator
supports exactly the hygiene-tested keyword subset and fails loudly otherwise.

Pydantic models are `strict`, `frozen`, `extra="forbid"` and `regex_engine="python-re"` (the
path pattern needs lookaheads). They reject explicit `null` for optional, non-nullable fields,
enforce `minProperties` and `uniqueItems`, and alias keyword-named fields (`class` → `class_`).

## Acceptance criteria
- [x] AC1: `pnpm gen` / `uv run repro-events-codegen` regenerate deterministically (byte-identical reruns; `--check` passes after generation).
- [x] AC2: CI fails on any diff between committed and regenerated code (lint-job step plus `test_generated_files_are_up_to_date`).
- [x] AC3: Round trip passes for all example events (`test_models.py`).

## Evidence
| Check | Result |
|---|---|
| `uv run pytest` | **460 passed**. New: `test_models.py` (78) and `test_codegen.py` (2) |
| Valid examples (34 kinds + envelope + 5 models) | Round-trip **exactly** through Pydantic (`dump(mode="json", exclude_unset, by_alias) == input`) |
| Invalid examples (all) | Rejected by Pydantic **and** `jsonschema` **and** Ajv |
| `pnpm --filter @repro/events test` | **43 passed** (Ajv 2020 strict mode over all examples, registry constants) |
| Type-level assertions | Checked by `tsc --noEmit`. A deliberately wrong assertion fails with TS2344 (probe recorded during the phase) |
| Drift gate | `--check` printed a unified diff and exited 1 after a one-word change to a generated docstring, before regeneration |

**Cross-language chain.** Python parses each committed example and dumps it back byte-equal, so
the JSON the Python models produce is the committed example. Ajv validates those same
committed examples in TypeScript. That covers Python model → JSON → TS validator and back.

## Defects found and fixed during the phase
1. **Type-name collision.** The `$defs/Verdict` enum and `models/verdict` (title `Verdict`)
   mapped to the same generated name, and the model silently resolved to the enum. The enum was
   renamed `VerdictValue`, and the generator now rejects names claimed by two schema locations
   (regression test `test_two_sources_generating_the_same_type_name_is_an_error`).
2. **JSDoc terminator.** The `RelPath` regex contains `*/`, which would close the generated doc
   comment. Comment text is now escaped.
3. **Ajv strict types.** Registry branches lacked `"type": "object"`. Added to the schema rather
   than relaxing Ajv.

## Deviations from spec
- The roadmap named json-schema-to-typescript and datamodel-code-generator. Both were evaluated
  and replaced by the in-house generator (ADR-0014). The roadmap entry was revised explicitly.
- A05 added the drift step to the existing CI `lint` job. A06 restructures CI.

## Known gaps
- Generated TS carries regex and length constraints as documentation only. Runtime validation
  in TS uses Ajv over the schema itself, so nothing diverges.
- `$` in Python regexes matches before a trailing newline (also true for `jsonschema`). The ECMA
  semantics in Ajv do not. A string ending in `\n` could therefore validate in Python but not
  in TS. No v1 field accepts newlines meaningfully. This will be tightened if one ever does.

## Dependencies added
| Package | Version | Licence | Why |
|---|---|---|---|
| pydantic | 2.14.1 (runtime, repro-events) | MIT | Generated models |
| ajv (dev) | 8.20.0 | MIT | TS-side schema validation in tests |
| ajv-formats (dev) | 3.0.1 | MIT | `date-time` format for Ajv |
| @types/node (dev) | 24.19.2 | MIT | Node APIs in TS tests |

## Research notes
The equivalence protocol (every invalid example rejected identically by three independent
validators) is reusable methodology for the paper's artifact section (C5).
