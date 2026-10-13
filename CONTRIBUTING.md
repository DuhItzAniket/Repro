# Contributing to Repro

Repro is developed phase by phase against a public roadmap. Before you open a PR:

1. Read [`docs/process/SDLC.md`](docs/process/SDLC.md). It covers the phase lifecycle,
   Definition of Done, branching and commit conventions.
2. Find the phase you are working on in [`docs/ROADMAP.md`](docs/ROADMAP.md) and create its
   phase record from [`docs/process/PHASE_TEMPLATE.md`](docs/process/PHASE_TEMPLATE.md).
3. Work on a branch `phase/<ID>-<slug>`. Use Conventional Commits that end with the phase ID,
   e.g. `fix(engine): handle detached HEAD in worktree manager [C05]`.
4. Open a PR using the template. `main` is protected: changes land only through PRs that pass
   the required checks (`lint`, `test (ubuntu-latest)`, `test (windows-latest)`, `security`) on
   an up-to-date branch. Merges are squash-only, which keeps history linear.

## What CI checks

| Job | Checks |
|---|---|
| `lint` | Biome, `tsc --noEmit`, Ruff lint + format, mypy (strict), generated-code drift |
| `test` (Ubuntu, Windows) | Vitest, web build, pytest, CLI smoke test |
| `security` | gitleaks over the full history; licence allow-list for every Python and JS dependency |
| `dependency review` (PRs) | Known vulnerabilities (high and above) in dependencies the PR adds or changes |

All actions are pinned to commit SHAs. Dependabot proposes weekly updates for actions, npm and
uv dependencies.

## Dependencies and licences

New dependencies must be under a licence in the allow-list in `scripts/check_licenses.py`
(permissive licences, plus MPL-2.0 for unmodified use and OFL-1.1 for fonts). Record each new
dependency with its version and licence in the phase record.

Ground rules that are easy to get wrong:

- **The event schema is the contract.** Change `packages/events` first, regenerate types,
  then update producers and consumers.
- **Target repositories are untrusted code.** Never run them outside the isolation layer.
- **Nothing is silently unverified.** If a check could not run, it is reported as `missing`.
- **No secrets or personal data** in code, fixtures, logs or commit metadata.

Development commands are listed in [`CLAUDE.md`](CLAUDE.md) ("Commands").
