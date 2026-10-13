# Contributing to Repro

Repro is developed phase by phase against a public roadmap. Before you open a PR:

1. Read [`docs/process/SDLC.md`](docs/process/SDLC.md). It covers the phase lifecycle,
   Definition of Done, branching and commit conventions.
2. Find the phase you are working on in [`docs/ROADMAP.md`](docs/ROADMAP.md) and create its
   phase record from [`docs/process/PHASE_TEMPLATE.md`](docs/process/PHASE_TEMPLATE.md).
3. Work on a branch `phase/<ID>-<slug>`. Use Conventional Commits that end with the phase ID,
   e.g. `fix(engine): handle detached HEAD in worktree manager [C05]`.
4. Open a PR using the template. CI must pass on Ubuntu and Windows.

Ground rules that are easy to get wrong:

- **The event schema is the contract.** Change `packages/events` first, regenerate types,
  then update producers and consumers.
- **Target repositories are untrusted code.** Never run them outside the isolation layer.
- **Nothing is silently unverified.** If a check could not run, it is reported as `missing`.
- **No secrets or personal data** in code, fixtures, logs or commit metadata.

Development commands are listed in [`CLAUDE.md`](CLAUDE.md#commands) and the README once
the scaffold exists (phase A02).
