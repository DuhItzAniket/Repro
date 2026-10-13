# A06 — CI pipeline & repository security

| | |
|---|---|
| **Stage** | A — Foundation |
| **Status** | done |
| **Depends on** | A03, A05 |
| **Branch / PR** | `phase/A06-ci-security` · [#6](https://github.com/DuhItzAniket/Repro/pull/6) |
| **Started / finished** | 2026-10-13 / 2026-10-13 |

## Objective
CI that a reviewer can trust. Every gate runs on every PR, supply-chain inputs are pinned, and
secrets and disallowed licences cannot reach `main` unnoticed.

## Scope
- Restructured workflow: `lint`, `test` (Ubuntu + Windows), `security`, `dependency review`.
- Secret scanning, licence allow-list, vulnerability review, SHA-pinned actions, Dependabot.
- Branch-protection required checks updated to the new job names.

## Design notes
- **gitleaks CLI, not gitleaks-action.** gitleaks-action v2+ is no longer MIT-licensed. For
  organisation repositories it needs a licence key and reports the repository name and owner
  to a licence service (per its README, checked 2026-10-13). The gitleaks CLI is MIT-licensed,
  so it runs from the official image pinned **by digest** (v8.30.1), over the **full history**
  (`fetch-depth: 0`), with git's `safe.directory` set through environment config for the
  read-only mount.
- **Own licence checker** (`scripts/check_licenses.py`) instead of dependency-review licence
  rules:
  - It evaluates SPDX expressions (`AND`/`OR`/`WITH`, parentheses) over every **installed**
    Python distribution (PEP 639 `License-Expression`, then trove classifiers, then free text)
    and every pnpm package.
  - Unknown or malformed licences fail.
  - Exceptions need a written justification in the script.
  - Dependency review still runs on PRs for **vulnerabilities** (fail on high).
- **Least privilege:** `permissions: contents: read` workflow-wide; `persist-credentials: false`
  on every checkout; per-job timeouts; concurrency cancels superseded runs.
- **Pinning:** all actions are pinned to full commit SHAs (resolved from release tags with the
  GitHub API) with the tag noted in a comment. Dependabot (weekly, grouped) keeps them current.
- `tsc` now runs once in `lint` (it does not depend on the OS). The matrix job runs behaviour:
  tests, build, CLI.

## Acceptance criteria
- [x] AC1: Workflow runs lint, types, unit tests, schema drift and secret scanning on Ubuntu + Windows (secret scanning and lint on Ubuntu; behaviour on both).
- [x] AC2: A fake secret or a disallowed licence fails the check (verified locally, see Evidence).
- [x] AC3: Caching for uv and pnpm. Branch-protection settings documented (CONTRIBUTING.md).
- [x] AC4: Dependabot configured.
- [x] AC5: A clean PR passes on both OSes in under 10 minutes (see CI timings below).

## Evidence
- **Secret scan, positive control.** In a throwaway local repo (never pushed), a commit with a
  randomly generated `ghp_…` token gave gitleaks v8.30.1 `leaks found: 1`, exit code 1. Clean
  control: this repository's history gave "18 commits scanned … no leaks found". A fake
  secret was deliberately **not** pushed in a public PR: it would add noise to public history
  and could trip GitHub push protection.
- **Licence gate, positive control.** Removing `MPL-2.0` from the allow-list for one run
  flagged `pathspec` (Python) and `lightningcss` / `lightningcss-win32-x64-msvc` (npm) and
  exited 1. With the real allow-list: "all dependencies are on the allow-list".
- **SPDX parser unit tests** (`scripts/tests/`, 15 cases): permissive expressions, `WITH`,
  parentheses, disallowed (GPL, AGPL, SSPL, proprietary), empty and malformed (`"MIT OR"`)
  expressions. The malformed case caught a parser bug during the phase.
- **Workflow static check:** actionlint (pinned image digest recorded during the phase) reports
  no findings.
- **Local suite:** pytest 475 passed. Ruff, mypy, Biome and the drift check are clean.
- **CI timings:** recorded in the PR (see the PR checks).

## Deviations from spec
- Licence checking moved from dependency-review rules to our own script, because it covers
  installed packages in both ecosystems and fails closed on unknown licences.
- No fake-secret PR on GitHub. The positive control was run locally (rationale above).

## Known gaps
- `dependency review` is not a required check yet, because its coverage of `pnpm-lock.yaml` and
  `uv.lock` through GitHub's dependency graph is not verified. Promote it once a Dependabot or
  advisory run shows it working.
- Branch protection lives in GitHub settings, not in the repository. It is documented in
  CONTRIBUTING.md and applied through the API in this phase.

## Dependencies added
None at runtime. The CI images are gitleaks v8.30.1 (MIT, by digest) and, locally only,
actionlint.

## Research notes
None.
