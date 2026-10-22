# Release 1.4.0 — L5 microVMs and the GitHub App

| | |
|---|---|
| **Release** | `v1.4.0` |
| **Date** | 2026-10-22 |
| **Kind** | A minor release: two new features, no breaking change |

## What it carries
| Part | PRs | What it brought |
|---|---|---|
| K10 | [#116](https://github.com/DuhItzAniket/Repro/pull/116) | Isolation level L5: `docker_runtime = "kata"` runs each container in a Kata Containers microVM with Cloud Hypervisor, the level probed from the container's kernel; `scripts/kata/setup.sh`; the CI job `kata` on GitHub's nested virtualization |
| I04 | [#117](https://github.com/DuhItzAniket/Repro/pull/117) | `repro app register` and `repro app serve`: Repro as a GitHub App on the operator's machine, through a smee.io relay or a port of its own (ADR-0019) |

## Compatibility
- The event schema gains values, not fields: `L5` as an isolation level and `kata` as a sandbox
  backend. A log written by 1.3.x reads as before. A reader older than 1.4.0 refuses a log
  that names `L5` or `kata`.
- Nothing changes for a run without `docker_runtime = "kata"` or the App.

## Published
Filled in once the GitHub release is published: the wheels, PyPI and Zenodo.
