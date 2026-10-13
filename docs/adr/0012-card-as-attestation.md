# ADR-0012: Export the Reproduction Card as an in-toto attestation

- **Status:** accepted (additive export. The canonical JSON card is unchanged)
- **Date:** 2026-10-13
- **Phase:** A01 (implemented in H04, signed in CI in I03)

## Context
Teams increasingly gate merges on signed, machine-verifiable statements about artifacts. The
in-toto Attestation Framework (Statement v1, DSSE envelope) allows custom predicates. The
vetted SCAI predicate models "attribute + evidence as ResourceDescriptor", which is close to
"claim + cited evidence". SLSA's Verification Summary Attestation allows custom
`verifiedLevels` that don't start with `SLSA_`. GitHub's `actions/attest@v4` signs custom
predicates up to 16 MB (research/04 §3).

## Decision
- Export the card as an **in-toto Statement v1**:
  - `subject` is the head commit (`digest.gitCommit`);
  - `predicateType` is a Repro-owned URI, versioned (`…/reproduction-card/v0.1`);
  - the predicate holds claims and verdicts (evidence as digested ResourceDescriptors),
    missing items, invariants, environment, isolation level, and the event-log digest.
- Optionally also emit a small VSA-style summary with properties such as
  `REPRO_CLAIMS_VERIFIED` and `REPRO_NO_UNEXPLAINED_GAP`.
- Local runs produce **unsigned** statements. Signing happens only in CI (Sigstore through
  `actions/attest`). Nothing implies trust that isn't there.
- The predicate documentation states plainly that the attestation records *what was run and
  observed*. It does not certify correctness, and LLM verdicts are labelled as judgements.

## Consequences
The predicate needs a published, versioned schema in `packages/events`. Once teams depend on
it, field changes follow semver.
