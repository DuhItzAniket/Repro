# Stage I gate — GitHub integration

| | |
|---|---|
| **Phases** | I01–I03 (I04 deferred) |
| **Release** | `v1.1.0` |
| **Gate date** | 2026-10-18 |

## Stage acceptance criteria
| Criterion (ROADMAP Gate I) | Result | Evidence |
|---|---|---|
| On a test repository, opening a PR produces a Repro check run | pass | [DuhItzAniket/repro-gate-i#1](https://github.com/DuhItzAniket/repro-gate-i/pull/1), a pull request from the repository's own branch, whose workflow uses the Action pinned to `main` at 0ec5397. Its run (39059765543) made the check run `Repro`: `failure`, "FLAGGED: the run found a problem", 2 `diff.behaviour` differences (`result_changed`), one annotation at `to_celsius`. The job took 54 s, in containers (L3, Docker 28.0.4), 2 tests selected |
| … a sticky card comment | pass | One comment, written by `github-actions[bot]`, 1,962 characters, starting with Repro's marker |
| … and (on public repos) a signed attestation | pass | Attestation 56995801 for `card.json`, `sha256:ee5e28ea…`, with Repro's predicate type, signed with a certificate from Sigstore's public-good instance and entered in its transparency log. `gh attestation verify card.json --repo DuhItzAniket/repro-gate-i --predicate-type <Repro's>` exits 0. The certificate names the repository, the trigger `pull_request` and the issuer `https://token.actions.githubusercontent.com`. Without `--predicate-type`, it exits 1, as its manual says. `card.json` was rebuilt from the card inside the attestation's own predicate: its canonical bytes hash to the subject, and `card_from_attestation` accepts the statement |
| Re-running updates rather than duplicates them | pass | **Re-running the workflow** (attempt 2) updated the comment. GitHub itself set the first attempt's check runs aside: the head lists one `Repro` check run, the new attempt's. **A new run on the same commit** (the pull request closed and reopened, run 39060088517) reported "check run Repro: updated" and "comment: updated". After both, the head has one `Repro` check run and the pull request one comment |

## Phases
| Phase | PR | Commit on `main` | What it brought |
|---|---|---|---|
| I01 | [#78](https://github.com/DuhItzAniket/Repro/pull/78) | 694aac9 | `repro run --pr <url>`: the pull request read from the REST API, fetched into Repro's own mirror (a fork's too), compared with its merge base |
| I02 | [#79](https://github.com/DuhItzAniket/Repro/pull/79) | 270f98b | `repro report <run>`: the check run, one sticky comment found by marker and author, the job summary |
| I03 | [#80](https://github.com/DuhItzAniket/Repro/pull/80) | 0ec5397 | The GitHub Action (composite, containers only), the card kept and signed with `actions/attest`, forks not posted to unless opted in |
| I04 | — | — | Deferred: the roadmap builds the GitHub App only if users ask for it |

## CI matrix
| Job | Python | Node | Result | Run |
|---|---|---|---|---|
| test, ubuntu-latest (Docker: L3 suites required) | 3.13 | 24 | pass (11 min 27 s) | [CI run 39059721874](https://github.com/DuhItzAniket/Repro/actions/runs/39059721874) on `main` at 0ec5397 (all of Stage I) |
| test, windows-latest | 3.13 | 24 | pass (25 min 20 s) | [CI run 39059721874](https://github.com/DuhItzAniket/Repro/actions/runs/39059721874) on `main` at 0ec5397 (all of Stage I) |
| chaos, ubuntu-latest and windows-latest | 3.13 | — | pass (54 s; 1 min 45 s) | [CI run 39059721874](https://github.com/DuhItzAniket/Repro/actions/runs/39059721874) on `main` at 0ec5397 (all of Stage I) |
| install, ubuntu-latest (L3) and windows-latest (L2) | 3.13 | 24 | pass (55 s; 1 min 34 s) | [CI run 39059721874](https://github.com/DuhItzAniket/Repro/actions/runs/39059721874) on `main` at 0ec5397 (all of Stage I) |
| gvisor, ubuntu-latest (L4) | 3.13 | — | pass (1 min 17 s) | [CI run 39059721874](https://github.com/DuhItzAniket/Repro/actions/runs/39059721874) on `main` at 0ec5397 (all of Stage I) |
| agent evals, ubuntu-latest | 3.13 | — | pass (1 min 4 s) | [CI run 39059721874](https://github.com/DuhItzAniket/Repro/actions/runs/39059721874) on `main` at 0ec5397 (all of Stage I) |
| Gate E, Gate D, Gate C, ubuntu-latest | 3.13 | 24 | pass (1 min 36 s; 1 min 58 s; 49 s) | [CI run 39059721874](https://github.com/DuhItzAniket/Repro/actions/runs/39059721874) on `main` at 0ec5397 (all of Stage I) |
| visual, ubuntu-latest + Playwright image | — | 24 | pass (3 min 42 s) | [CI run 39059721874](https://github.com/DuhItzAniket/Repro/actions/runs/39059721874) on `main` at 0ec5397 (all of Stage I) |
| lint, security, gates, dependency audit | 3.13 | 24 | pass | [CI run 39059721874](https://github.com/DuhItzAniket/Repro/actions/runs/39059721874) on `main` at 0ec5397 (all of Stage I) |
| dependency review | — | — | skipped: off until the repository's Dependency graph is enabled | [CI run 39059721874](https://github.com/DuhItzAniket/Repro/actions/runs/39059721874) on `main` at 0ec5397 (all of Stage I) |

The Action itself is not run by this repository's CI: running Repro on Repro's own pull requests would run its whole suite three times. Gate I runs it on GitHub, on the test repository, above; its steps are tested in `test_github_action.py`.

## Measured at the gate
| Metric | Value |
|---|---|
| Tests | pytest 1,963 collected (1,918 at Gate H); Vitest 395 (unchanged: Stage I changed no web code); Gates C, D and E; the agent evals; the chaos tests; the install check |
| Code | 23,921 lines of Python under `engine/src` (22,806 at Gate H), 933 of them in `repro/integrations`; 20,395 in `engine/tests` (19,461), 906 of them for GitHub; `action.yml` 114 lines; counted with `wc -l` over tracked files |
| The Action on GitHub | 54 s for the job on `repro-gate-i` (`ubuntu-latest`, L3, 2 tests), Repro installed from the Action's checkout |
| A comment's length | GitHub accepted a 70,000-character comment on 2026-10-17 (UTC), so the limit is higher; Repro cuts its card under 60,000 |

## Retrospective
- **The design came from where the token lives.** Two of Stage I's three phases changed shape
  once GitHub's permission model was read closely. A fork's pull request has a read-only token
  under `pull_request`, and `pull_request_target`'s write token sits where the fork's code runs.
  Hence a separate `repro report` that runs no target code, forks not posted to by default (the
  owner's decision), and containers only in the Action, since a contained process would share
  the job's user and its token.
- **GitHub's rules shaped two choices.** Its attestations take `sha256` subjects only, so the
  signed subject is the card itself, made exactly the card's canonical bytes so that its digest
  is the card's own (the owner's decision). And `gh attestation verify` assumes SLSA provenance
  unless told the predicate type, so the guide names it.
- **A re-run is not a new run.** Re-running a workflow sets the earlier attempt's check runs
  aside, so there is nothing to update; a new run on the same commit finds the earlier check run
  and updates it. Both end with one check run, but only testing on GitHub showed which path each
  takes.
- **A measured number replaced an assumed one.** The roadmap's "under 60k characters" assumed a
  limit GitHub does not document; GitHub accepted 70,000. The cut stays at 60,000, now known to be
  conservative rather than necessary.
