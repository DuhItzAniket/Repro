# ADR-0001: Record architecture decisions

- **Status:** accepted
- **Date:** 2026-10-13
- **Phase:** A01

## Context
Repro is built in many small phases, partly by AI coding agents and over a long period. It may
also be described in a peer-reviewed paper. Decisions made early (event schema, tracing
mechanism, isolation model) constrain everything after them. Without a written record, later
contributors re-argue settled questions or reverse decisions without knowing why they were made.

## Decision
Record every decision that is expensive to reverse as an Architecture Decision Record in
`docs/adr/`, numbered sequentially, using [`0000-template.md`](0000-template.md). ADRs are
immutable once accepted. A change of mind is a new ADR that supersedes the old one.

Changes to the stack, the event schema's core fields, or the scope of a stage need an ADR
accepted by the project owner.

## Alternatives considered
| Option | Why not |
|---|---|
| Decisions only in commit messages / PR descriptions | Not discoverable and not reviewable as a set |
| A single "decisions" section in ARCHITECTURE.md | Loses history and rationale when the architecture is edited |

## Consequences
A little writing overhead per major decision. In return there is a reviewable rationale trail,
which also feeds the paper's design section.
