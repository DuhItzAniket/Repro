# Release 1.3.0 — JavaScript and TypeScript, end to end

| | |
|---|---|
| **Release** | `v1.3.0` |
| **Date** | 2026-10-20 |
| **Kind** | A release without a stage gate, as 1.2.0 was: Stage K has none in the roadmap |

## What it carries
| Part | PRs | What it brought |
|---|---|---|
| ADR-0017, phases 2 and 3 | [#100](https://github.com/DuhItzAniket/Repro/pull/100), [#105](https://github.com/DuhItzAniket/Repro/pull/105) (K06, K07) | Which tests a JavaScript change reaches (V8 coverage per test), and its functions' calls compared base against head |
| ADR-0017, phase 4 | [#107](https://github.com/DuhItzAniket/Repro/pull/107), [#110](https://github.com/DuhItzAniket/Repro/pull/110) (K08, K11) | `repro run` on JavaScript and TypeScript: the card; L3 in Repro's Node image; the public API and edited tests' assertions from a pinned TypeScript compiler; base's version of an edited test on head |
| Fixes | [#106](https://github.com/DuhItzAniket/Repro/pull/106), [#108](https://github.com/DuhItzAniket/Repro/pull/108), [#109](https://github.com/DuhItzAniket/Repro/pull/109) | `run.started` names the sandbox the run uses; event timestamps in `seq` order; `net-call`'s timing no longer at the floor |
| Dependencies | [#101](https://github.com/DuhItzAniket/Repro/pull/101)–[#104](https://github.com/DuhItzAniket/Repro/pull/104) | Dependabot's updates, the release workflow's `download-artifact` 8.0.2 among them (its v8 notes checked: our zipped artifact is still unzipped) |

## Security
K11 found that a JavaScript install ran the project's code under `--ignore-scripts`: pnpm's
`.pnpmfile.cjs`, and Yarn 1's `yarn-path`. Both are off now, on the host and in containers.
K08's host installs had the same exposure; no released version had JavaScript runs through
`repro run` before 1.3.0 (1.2.0's `repro js-run` installed the same way).

## The real-world check
unjs/defu (Vitest, pnpm), two changes written as an agent might (`docs/paper/LOG.md`,
2026-10-20):
- dropping `"constructor"` from `_defu`'s key guard passes every test, and is FLAGGED: `_defu`
  returns `{constructor: …}` where base returned `{}`;
- a refactor that keeps behaviour is VERIFIED.

## CI
- The release PR and `main` after the merge: linked in the PR.

## Published
- The GitHub release `v1.3.0`, with both wheels attached by the release workflow.
- PyPI: `repro-events` and then `repro-engine`, 1.3.0, by the same workflow, checked after it
  ran.
- **Checked:** both wheels installed from PyPI with `uvx --from repro-engine==1.3.0`; `repro
  --version` printed 1.3.0 and `repro doctor` passed every check.
- GitHub Marketplace: the Action is listed as
  [Repro Reproduction Card](https://github.com/marketplace/actions/repro-reproduction-card),
  v1.3.0, under Code review and Testing. The owner published it from the release on
  2026-10-21.

## Still open
- K09 and K10 need a Linux host with KVM.
- The study (J06 to J10) is deferred by the owner.
- I04, the GitHub App, is deferred until users ask for it: it needs an App registration and a
  host for its webhooks.
