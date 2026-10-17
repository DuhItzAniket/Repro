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

## Implementation note (H04)
- The predicate type is `https://github.com/DuhItzAniket/Repro/blob/main/docs/attestation/
  reproduction-card/v0.md`. It carries the major version only, `v0`, not `v0.1` as written
  above: in-toto's TypeURI should resolve to a description, and its parsing rules say the URI
  reflects the major version (minor versions follow the monotonic principle). The predicate is
  version 0.1.
- The predicate holds the card itself with its digest, so card -> attestation -> card is exact
  and checkable. Claims, verdicts, missing items, invariants and the environment are the card's
  own. Beside it: the cited evidence as digested ResourceDescriptors, the event log's digest, and
  copies of the status, isolation level and network for policies.
- The VSA-style summary is not emitted: the copies above serve policies, and a second predicate
  would be a second thing to keep true.
- Schemas: `packages/events/schema/attestation/` (the Statement as Repro writes it, and the
  predicate).

## Implementation note (I03)
- **Signed through GitHub, the subject is the card.** GitHub's artifact attestations
  (`actions/attest`, `gh attestation verify`) take subjects by a `sha256` digest only
  [actions/attest README, checked 2026-10-17], and a commit's git ID is not one. The Action
  signs the card's canonical JSON (`card.json`, exactly the bytes `cardDigest` is of) with
  Repro's predicate; the head commit, the event log's digest and the cited evidence stay in
  the predicate. `repro export --format in-toto` still names the head commit, unsigned.
  Decided by the project owner on 2026-10-17.
- `card_from_attestation` accepts either subject, each checked against the card.
