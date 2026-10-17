# I02 — Check run, sticky comment & job summary

| | |
|---|---|
| **Stage** | I — GitHub integration |
| **Status** | done |
| **Depends on** | I01 |
| **Branch / PR** | `phase/I02-reporting` · [#79](https://github.com/DuhItzAniket/Repro/pull/79) |
| **Started / finished** | 2026-10-17 / 2026-10-17 |

## Objective
A run's card reaches the pull request it is about: a check run on its head commit, one comment
on the pull request that each run updates, and the job's summary when Repro runs in GitHub
Actions.

## Scope
- **`repro report <run id | log.jsonl>`**: the card the run published, checked against its log as
  `repro export` checks it, reported to the pull request the run read (`--pr` names another).
  It runs no target code, so a workflow can report from a run made elsewhere, as a fork's pull
  request needs (below).
- **The check run** `Repro` on the head commit (`POST /repos/{owner}/{repo}/check-runs`; an
  earlier one of that name is updated, `PATCH .../check-runs/{id}`, so a rerun replaces it).
  Conclusion: VERIFIED `success`, FLAGGED `failure`, UNVERIFIABLE `neutral`. Its output holds the
  status, the reasons and the Markdown card. Annotations at the lines of the changed code a
  flagged difference or an unreached function concerns, 50 a request, the rest added by updates,
  which append [GitHub REST API docs, "Check runs", checked 2026-10-17]. Creating check runs
  needs a GitHub App's token, which a workflow's `GITHUB_TOKEN` is with `checks: write`
  [GitHub docs, "Workflow syntax", `permissions`, checked 2026-10-17].
- **The sticky comment**: one comment, found by a hidden marker among the pull request's
  comments and written by the same identity (the token's user, or a bot for an app's token),
  updated in place; otherwise created (`/repos/{owner}/{repo}/issues/{n}/comments`, which pull
  requests share with issues) [GitHub REST API docs, "Issue comments", checked 2026-10-17].
- **The job summary**: in GitHub Actions, the Markdown card appended to `GITHUB_STEP_SUMMARY`,
  under the 1 MiB a step may write [GitHub docs, "Workflow commands", checked 2026-10-17].
- **What each target needs**, and what failed, said in words: `repro report` reports each target
  it could not update and exits 1; the others are still made.

## Out of scope
- The Action that runs Repro and reports (I03), and how it handles a fork's pull request.
- A GitHub App's webhooks (I04).

## Design notes
- **Reporting is a separate command.** A pull request from a fork gets a read-only
  `GITHUB_TOKEN`, and `pull_request_target`, which has a write token, runs in the base
  repository's context even for a public fork [GitHub docs, "Workflow syntax", `permissions`,
  checked 2026-10-17]. Running a fork's code where a write token is available is what Repro's
  isolation exists to avoid; reporting from a run made elsewhere keeps the two apart. I03 decides
  how the Action uses it.
- **Lengths.** GitHub documents no maximum for a comment's body or a check run's text. The card
  is cut at a line under 60,000 characters (the roadmap's figure), with a note that
  `repro export` gives it whole; the real limit is measured at Gate I against GitHub itself.
- **The comment's author.** A marker alone could match a comment someone else wrote to have it
  overwritten; Repro updates only its own identity's comment.

## Acceptance criteria
- [x] AC1 (roadmap): conclusions mapped; annotations in batches of 50; one sticky comment found
  by its marker, under 60k characters; the job summary.
- [x] AC2: rerunning updates the check run and the comment rather than adding new ones.
- [x] AC3: a target Repro cannot update (no permission, no network) is reported, and the others
  are still made.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | A stateful fake GitHub API (check runs, comments): the requests `repro report` makes, the annotations' batches, a long card cut, the summary file |
| AC2 | Two reports of one run: one check run, updated; one comment, updated |
| AC3 | The fake refuses comments (403): the check run is made, the comment reported, exit 1 |

---
*Filled in at the end of the phase:*

## What shipped
- **`repro.integrations.github.report`**:
  - `check_run`: the check run updated, or created when there is none to update (another app's
    of that name), annotations 50 a request;
  - `comment`: found among all the comments, a page of 100 at a time, by its marker and its
    author (the token's user, or a bot for an app's token);
  - `job_summary`;
  - `annotations` (from the log: a flagged difference's evidence, or an unreached function,
    at its lines on head);
  - `cut`;
  - `report` (one target's failure does not stop the others).
- **`GitHubApi`** writes (`request`) and reads listings page by page (`pages`, following `next`
  links on the same server only).
- **`repro report <run> [--pr] [--no-check] [--no-comment]`**: exit 1 when a target could not be
  made, 2 when the run names no pull request.
- **The Markdown card's headline and reasons** are public (`headline`, `why`), so the check run's
  summary is the card's own.
- **Docs**: the quickstart, troubleshooting (what each target needs), the engine README (and a
  stale sentence from before H04 corrected), ARCHITECTURE §4, THREAT_MODEL T12, CLAUDE.md.
- **Tests**: `test_github_report.py` (11), against `github_support.FakeGitHub`, a stateful fake;
  the ingestion tests now share its fixture repository and pull request.

## Evidence
- **Locally**: `test_github_report.py` 11 passed, `test_github_ingest.py` 23, and the card, CLI
  and threat-model tests.
- CI run: linked in the PR (#79).

## Deviations from spec
- **`action_required` is not used.** The roadmap allows FLAGGED as `failure` or
  `action_required`; `failure` is what a required check blocks on, and the check run's page
  already links the evidence.

## Known gaps
- **Against GitHub itself** nothing has been posted yet: Gate I does so, on the owner's public
  test repository, and measures the real limit on a comment's length.
- **Annotations** mark changed code only: a difference found through a test that changed no
  function has no line to point to, and appears in the check run's text instead.

## Dependencies added
None.

## Research notes
- A check run, a comment and a summary are three ways to put one card where a reviewer looks;
  a rerun that adds a second of any of them is noise a reviewer learns to ignore. Each is
  therefore found and updated, and the comment only if Repro's own identity wrote it.
