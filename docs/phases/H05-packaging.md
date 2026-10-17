# H05 — Packaging & distribution

| | |
|---|---|
| **Stage** | H — Hardening & first release |
| **Status** | done |
| **Depends on** | H02, H03 |
| **Branch / PR** | `phase/H05-packaging` · [#75](https://github.com/DuhItzAniket/Repro/pull/75) |
| **Started / finished** | 2026-10-17 / 2026-10-17 |

## Objective
A stranger installs Repro with one command and makes a first run, on Windows or Linux, in under
ten minutes, following the documentation alone. The same procedure runs in CI for every
change, so it keeps working.

## Owner decisions (2026-10-17)
- **The name.** The distribution is `repro-engine`, the command `repro`. On PyPI, `repro` is
  taken by an unrelated research library and `repro-cli` by a Docker tool (checked 2026-10-17);
  `repro-engine` was free.
- **Where.** Wheels on GitHub releases now, PyPI later: the owner adds a trusted publisher for
  the release workflow on pypi.org first.

## Scope
- **Wheels that carry what a checkout has elsewhere** (`scripts/build_wheels.py`). The cockpit's
  build goes into `repro-engine` (`repro/api/cockpit`), the event schemas into `repro-events`
  (`repro_events/schema`). Both are copied in for the build only, and each wheel is checked for
  what it must hold. At run time a checkout's own copy wins (`repro.api.ui.find_ui`,
  `repro_events.schemas.default_schema_root`); an installed wheel has only its own.
- **The install, documented** (README, "Install"): one `uv tool install` from the two wheels of
  a release, with Python 3.13. Then `repro doctor`, then `repro run`.
- **The install, checked** (`scripts/install_check.py`). It follows the README's command into a
  tool directory of its own, away from any checkout: `repro --version`, `repro doctor`, a first
  `repro run` on a small repository made for it, and an export of its card checked against the
  schemas the wheel carries. It fails over ten minutes, and prints each step's time. CI's
  `install` job runs it on Ubuntu and Windows for every change.
- **The release workflow** (`.github/workflows/release.yml`). A published release gets the
  wheels of its version attached, after the same check. Run by hand, it builds and checks them
  and keeps them as an artifact.
- **`repro doctor` reports the cockpit**: the checkout's build, the wheel's copy, or none (a
  warning: runs are then served with the API only).

## Out of scope
- **Publishing to PyPI**, until the owner sets up the trusted publisher.
- **An npm package.** The cockpit ships inside the wheel; nothing is published to npm.
- **Installers** (MSI, Homebrew): `uv` installs Python tools on every platform Repro supports.

## Design notes
- **Copied in, not moved.** uv_build packs what is under the package's own directory. Moving
  the cockpit's build or the schemas there would break the workspace's layout: the codegen
  reads the schemas, Vite writes the build. A copy for the build, removed afterwards and
  git-ignored, keeps one source of each.
- **The checkout first.** A developer who once built wheels keeps a git-ignored copy only until
  the script removes it. If one remained, the checkout's own files would still win, so a stale
  copy can never shadow them.
- **The README's command is what CI runs.** The check installs with the direct-reference form
  (`repro-engine @ <url>`) the README uses, with file URLs in place of the release's.

## Acceptance criteria
- [x] AC1 (roadmap): clean-machine install and first run on Windows and Linux in under 10
  minutes, as a documented procedure and a CI job.
- [x] AC2: the wheels carry the cockpit and the schemas, and an installed Repro uses them.
- [x] AC3: a published release gets its wheels attached, checked first.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | CI job `install` (Ubuntu, Windows): `scripts/install_check.py`, its times printed; README "Install" |
| AC2 | `scripts/build_wheels.py` checks each wheel's contents; the install check finds the cockpit and the schemas inside the installed tool; `test_doctor.py::test_the_cockpit_is_found_or_said_missing` |
| AC3 | `.github/workflows/release.yml`, run at Gate H's release |

---
*Filled in at the end of the phase:*

## What shipped
- **Scripts.** `scripts/build_wheels.py` and `scripts/install_check.py`.
- **Code.** `repro.api.ui.find_ui` falls back to the packaged cockpit, and
  `repro_events.schemas.default_schema_root` to the packaged schemas. `repro doctor` reports the
  cockpit (`doctor.check_cockpit`).
- **CI.** The `install` job (Ubuntu, Windows) and `.github/workflows/release.yml`.
- **Docs.** README: the "Install" section and an up-to-date status. CLAUDE.md: the two
  scripts. `.gitignore`: the build-time copies.
- **Tests.** `test_doctor.py::test_the_cockpit_is_found_or_said_missing`. The install check
  itself, in CI.

## Evidence
- **Local**, Windows (`-m "not agent_eval and not chaos"`): 1,896 passed, 4 skipped (2
  POSIX-only, 2 gVisor-only).
- **The install check on this machine**, with uv's cache warm: `uv tool install` 1.8 s,
  `--version` and `doctor` 2.5 s, the first `repro run` 18.7 s, the export and its schema check
  1.3 s; 24.8 s in all.
- **The wheels**, version 0.7.0: `repro_engine` carries `repro/api/cockpit/index.html`, the
  sandbox's hook, its Dockerfile and the prompts; `repro_events` carries the 45 schemas.
- CI run: linked in the PR (#75).

## Deviations from spec
- **No PyPI yet**, by the owner's decision: GitHub releases now, PyPI once its publisher is set
  up. The roadmap's "PyPI/npm availability" was checked for the name; nothing goes to npm.

## Known gaps
- **The ten-minute target is checked from a warm uv cache on CI's runners**: setup-uv's cache
  holds packages from earlier jobs. A first install on a machine with nothing cached also
  downloads Python and the packages; the CI times say how long the rest takes.

## Dependencies added
None.

## Research notes
- uv_build takes what is under the package's directory and nothing else. A copy made for the
  build, checked after it and removed, keeps a monorepo's layout intact.
