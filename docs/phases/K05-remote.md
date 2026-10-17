# K05 — Remote sandbox backends

| | |
|---|---|
| **Stage** | K — Expansion backlog |
| **Status** | in progress |
| **Depends on** | — |
| **Branch / PR** | `phase/K05-remote` · PR pending |
| **Started / finished** | 2026-10-18 / — |

## Objective
Self-hosted E2B / Firecracker for teams (roadmap). The owner decided (2026-10-18) that this
phase gets a design and a local prototype only: the hosted parts need infrastructure Repro does
not run.

## Scope
- **ADR-0018 (proposed)**, with three options:
  - A: a team's own Docker engine, named by a Docker context;
  - B: E2B's runtime self-hosted, one Firecracker microVM per sandbox, as a new sandbox
    class;
  - C: Kata Containers with Firecracker under containerd.

  Its sources are quoted there. B and C would make microVM isolation a new level (L5), a
  change to the event schema's values that needs the owner's approval.
- **The local prototype of A**: the setting `docker_context` (`REPRO_DOCKER_CONTEXT`, a plain
  context name). It is applied to every docker command Repro runs and to the processes it
  starts. It works without new code paths because, since H06, the sandbox sends everything to
  the engine and mounts nothing from the host.
- **Docs**: ARCHITECTURE §8 and the engine README's settings.

## Acceptance criteria
- [x] AC1: a design for remote and microVM sandboxes, with sources.
- [x] AC2: a local prototype: the sandbox runs on an engine named by a context.
- [ ] AC3 (roadmap's full item): E2B or Firecracker, hosted. *Design only, by the owner's
  decision: needs a KVM host or a cloud account.*

## Test plan
| Criterion | Check |
|---|---|
| AC2 | `test_docker_context.py`: the setting takes a plain name and refuses an option-like one. A context is made, in a throwaway Docker configuration, for this machine's engine by its endpoint. Docker reports it as current, and a `DockerSandbox` reads a file from the snapshot through it |

---
*Filled in at the end of the phase:*

## What shipped
- `docs/adr/0018-remote-sandboxes.md` (proposed).
- The `docker_context` setting.
- Tests: `test_docker_context.py` (2, one in a real container).

## Evidence
- A context `repro-k05-<id>` was created for `npipe:////./pipe/dockerDesktopLinuxEngine` (this
  machine's engine) in a temporary `DOCKER_CONFIG`. `docker context show` named it, and the
  sandbox's container printed the snapshot's file through it. The user's Docker
  configuration was not touched.
- CI run: linked in the PR.

## Deviations from spec
- Design only for E2B and Firecracker, by the owner's decision.

## Known gaps
- A remote engine is trusted with the target's code, as the local one is.
- Snapshots and results cross the network: a remote engine adds their transfer time to every
  run. Not measured: no remote engine was available here.

## Dependencies added
None.
