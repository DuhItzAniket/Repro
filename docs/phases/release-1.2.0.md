# Release 1.2.0 — Stage K's first items, the study's harness, and the demo's fixes

| | |
|---|---|
| **Release** | `v1.2.0` |
| **Date** | 2026-10-20 |
| **Kind** | A release without a stage gate, by the owner's decision (2026-10-19) |

## Why there is no gate
Stage J's gate needs the study: its tables regenerated from pinned manifests, the artifact
archived with a DOI, and the paper submitted. On 2026-10-19 the owner deferred the study
(J06 to J10) and asked for what is built to ship. Stage K has no gate of its own in the
roadmap. This release has what a gate's release has: full CI on Ubuntu and Windows, an
annotated tag, and a GitHub release with the wheels. It is also the first published to PyPI.

## The owner's decisions (2026-10-19)
- **The study is deferred.** It needs a budget (about 100 million tokens for S2 as
  registered; Groq's Developer tier was closed to new upgrades that day) and two annotators.
  Its harness and what J06, J09 and J10 prepared ship here.
- **The demo's gaps are fixed first, then the release.**
- **ADR-0017 and ADR-0018 are accepted.** Their remaining parts are K06 to K10.
- **PyPI publishing.** It uses trusted publishing, with one pending publisher per package:
  `repro-engine` through the `pypi` environment, `repro-events` through `pypi-events`. PyPI
  takes one pending publisher per configuration, so the two packages need two environments.
  Both environments only accept release tags (`v*`).
- **Repository settings.** `visual` and `gates` are now required on `main`. The dependency
  graph is on, and pull requests get dependency review.

## What it carries
| Part | PRs | What it brought |
|---|---|---|
| Stage J's harness | [#82](https://github.com/DuhItzAniket/Repro/pull/82)–[#86](https://github.com/DuhItzAniket/Repro/pull/86) (J01–J05) | SWE-format adapter and input contract, ground truth, the baselines, the S0 shake-out, S2's 351 pinned candidates and patch generation |
| Stage J, prepared | [#87](https://github.com/DuhItzAniket/Repro/pull/87), [#93](https://github.com/DuhItzAniket/Repro/pull/93), [#94](https://github.com/DuhItzAniket/Repro/pull/94) (J06, J09, J10) | The registered analysis and pre-registration; the artifact package; paper draft 0 |
| Stage K | [#88](https://github.com/DuhItzAniket/Repro/pull/88)–[#92](https://github.com/DuhItzAniket/Repro/pull/92) (K01–K05) | `repro js-run`, the fleet view, `repro mcp`, `repro symbolic`, the `docker_context` setting |
| The demo's fixes | [#95](https://github.com/DuhItzAniket/Repro/pull/95), [#96](https://github.com/DuhItzAniket/Repro/pull/96), [#97](https://github.com/DuhItzAniket/Repro/pull/97) | Task images within a disk budget; reviewers that can answer on a real repository; calls whose arguments cannot be encoded compared by position |

## The real-world demo (2026-10-18 and 19)
Repro was run on real Pallets code, three ways:
- two changes seeded in the style of a coding agent, on itsdangerous at `672971d`;
- one merged pull request, click#3884.

What it showed, and what changed:

| Scenario | Before the fixes | After |
|---|---|---|
| An agent's "pure refactor" of HMAC key derivation (key and message swapped); all 272 selected tests pass | FLAGGED: 27 stable behaviour differences in `Signer.derive_key`. No reviewer could answer: each request was 10,786 to 19,909 tokens, past Groq's free 8,000 a minute | The same differences, and "no behaviour change" contradicted, citing them, in both orders; the claims that describe the code supported (#96) |
| An agent's "flaky test fix" (30 s of grace added to token expiry, the test edited to match) | FLAGGED: 4 tests passing on base failed on head; the base version of the edited test fails on head; `unsign` no longer raises `SignatureExpired` | Unchanged; the reviewers' requests now fit (#96) |
| click#3884, a merged fix | UNVERIFIABLE: calls of 2 of 4 changed functions, whose arguments include click's `Context`, could not be compared | 395 calls compared (up from 244), none not comparable; the card VERIFIED, deterministic (#97) |

The measurements are in `docs/paper/LOG.md` (2026-10-19 entries).

## CI
- The release PR ([#98](https://github.com/DuhItzAniket/Repro/pull/98)) and `main` after the merge: linked in the PR.

## Published
- The GitHub release `v1.2.0`, with both wheels attached by the release workflow.
- PyPI: `repro-events` and then `repro-engine`, 1.2.0, by the same workflow, checked after
  it ran.

## Deferred
- **The study**, J06 to J10, and Gate J.
- **I04**, the GitHub App, built only if users ask for it.
- **K06 to K10.**
