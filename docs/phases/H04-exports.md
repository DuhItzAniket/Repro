# H04 — Exports: in-toto, JUnit, SARIF

| | |
|---|---|
| **Stage** | H — Hardening & first release |
| **Status** | done |
| **Depends on** | F05 |
| **Branch / PR** | `phase/H04-exports` · [#74](https://github.com/DuhItzAniket/Repro/pull/74) |
| **Started / finished** | 2026-10-17 / 2026-10-17 |

## Objective
The card leaves Repro in the formats other tools already read: an in-toto attestation for
policies and signing, SARIF for code scanning, JUnit XML for CI test reports. Each holds to its
specification and schema, says what the card says and no more, and the attestation gives the
card back exactly.

## Scope
- **The in-toto Statement** (ADR-0012), `repro export --format in-toto`. A Statement v1 whose
  subject is the head commit, with Repro's predicate, v0.1. The predicate holds:
  - the card itself and its digest;
  - the evidence the card cites, as resource descriptors with each record's SHA-256;
  - the event log's digest;
  - copies of the status, isolation level and network, for policies.

  `card_from_attestation` returns the card only when every digest and copy holds.
- **The predicate, published**: its schema, and the in-toto Statement as Repro writes it, in
  `packages/events/schema/attestation`; its description at
  `docs/attestation/reproduction-card/v0.md`, where the predicate type points.
- **SARIF 2.1.0**, `--format sarif`. One result per gap item, failed invariant, judged claim
  and missing item, with `kind` and `level` as the specification pairs them, and the files the
  evidence names as locations.
- **JUnit XML**, `--format junit` (Apache Ant's format). One test case per claim and one for
  the card's status; what could not be checked goes to `system-out`.
- **Checked against their schemas.** Repro's own; OASIS's SARIF 2.1.0 schema (Errata 01); the
  JUnit XSD of windyroad/JUnit-Schema. The third-party two are kept in `engine/tests/data/
  schemas`, unmodified, with their notices, sources and digests.

## Out of scope
- **Signing.** A local statement is unsigned; CI signs, with `actions/attest` (I03).
- **A VSA-style summary predicate** (ADR-0012's option): the copies in the predicate serve
  policies, and a second predicate would be a second thing to keep true.
- **Uploading SARIF** to code scanning, or posting JUnit to a CI system: Stage I.

## Design notes
- **The card inside the predicate.** The ADR lists what the predicate holds: claims, verdicts,
  missing items, invariants, the environment. The card already holds each of these, exactly as
  the run published it. Holding it whole, with its digest, makes the round trip exact and
  checkable. The predicate adds what in-toto consumers look for: digested resource descriptors
  for the evidence, and the event log's digest.
- **The predicate type carries its major version only.** in-toto's TypeURI should resolve to a
  description and reflect the major version; minor versions only add fields. So the URI ends in
  `v0`, not ADR-0012's `v0.1`, and it is a page in this repository.
- **What a result is in SARIF.** A missing item and an unverifiable claim are `kind: open`,
  "insufficient information to decide". An unexplained difference waiting on a person is
  `review`. Only a flagged gap item, a failed invariant and a contradicted claim are `fail`. Any
  other kind must have level `none`, so nothing that could not be checked shows as a warning or
  a pass.
- **No machine in the report.** JUnit's required `hostname` is `repro`, never the machine's
  name: a report may be shared.

## Acceptance criteria
- [x] AC1 (roadmap): outputs validate against their specs and schemas.
- [x] AC2 (roadmap): card -> attestation -> card round trip.
- [x] AC3: the predicate schema is published and documented where the predicate type points.
- [x] AC4: a tampered attestation (card, subject, copies, type) gives no card.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_exports.py`: the Statement and predicate against their schemas, SARIF against OASIS's, JUnit against the XSD; also through `repro export` on a real run |
| AC2 | `test_exports.py::test_card_to_attestation_to_card_is_exact`, and the real run's |
| AC3 | `packages/events/schema/attestation/`; `docs/attestation/reproduction-card/v0.md`; Ajv's strict mode loads both schemas (`pnpm --filter @repro/events test`) |
| AC4 | `test_exports.py::test_a_tampered_attestation_gives_no_card` |

---
*Filled in at the end of the phase:*

## What shipped
- **Code.** `repro.card.exports`: `attestation`, `card_from_attestation`, `sarif`, `junit`,
  `cited`. `repro export --format in-toto|sarif|junit`. The CLI's "not available yet" path is
  gone: every command and format works.
- **Schemas.** `packages/events/schema/attestation/in-toto-statement-v1.schema.json` and
  `reproduction-card-v0.schema.json` (codegen leaves them alone; Ajv's strict mode and the
  Python registry load them).
- **Docs.**
  - `docs/attestation/reproduction-card/v0.md`, the predicate's description.
  - ADR-0012's implementation note; ARCHITECTURE's exports.
  - CLAUDE.md and `engine/README.md` (the formats).
  - `engine/tests/data/schemas/README.md`, with the vendored schemas' provenance.
- **Tests.** `test_exports.py` (13 cases). `test_cli.py` loses the test of the unfinished
  command.
- **Dependencies.** `xmlschema` (MIT) for the tests, in the dev group.

## Evidence
- Local, Windows (`-m "not agent_eval and not chaos"`): 1,895 passed, 4 skipped (2 POSIX-only,
  2 gVisor-only).
- `test_exports.py`: 13 passed, against the vendored schemas: OASIS SARIF 2.1.0 Errata 01, SHA-256
  `c3b4bb2d…`; JUnit.xsd, SHA-256 `147ff89e…`.
- `pnpm --filter @repro/events test`: 47 passed, with the attestation schemas loaded in strict
  mode. `repro-events-codegen --check`: no drift.
- CI run: linked in the PR (#74).

## Deviations from spec
- **The predicate type ends in `v0`**, not ADR-0012's `v0.1`: in-toto's TypeURI carries the
  major version (ADR-0012's implementation note).
- **No VSA-style summary predicate**, which ADR-0012 left optional.

## Known gaps
- **Locations are files only.** SARIF results carry no line regions: evidence names a test or a
  symbol, not a line.
- **The demo card covers each verdict only after one is altered.** No fixture log yet holds an
  unverifiable verdict; the test changes one supported verdict to cover the mapping.

## Dependencies added
- `xmlschema` 4.3.2 (MIT), with `elementpath` 5.1.4 (MIT), dev group only.

## Research notes
- A predicate that embeds the artifact it attests, plus that artifact's digest, makes the
  attestation self-checking: a consumer needs no second fetch to know what was claimed, and any
  edit shows.
