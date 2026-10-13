# ADR-0004: Layered isolation with Docker as the default enforcing sandbox

- **Status:** accepted (approved by the project owner on 2026-10-13)
- **Date:** 2026-10-13
- **Phase:** A01 (implemented in D01–D02, hardened in H03)

## Context
Target repositories are untrusted. The original plan relied on a socket guard inside the
pytest plugin to keep the network off. Research shows this is not a security boundary.
- Python's own docs say audit hooks are "not suitable for implementing a sandbox".
- In-process socket patches are bypassed with `_socket`, `ctypes`, C extensions or subprocesses
  (research/03 §6.1).

Other findings:
- Network-off can only be enforced at an OS boundary: a namespace, a container or a VM.
- Windows Sandbox and Hyper-V are unavailable on Windows Home, and bare WSL is not isolation.
  Docker Desktop's WSL2 backend works on Home editions (research/03 §6.2).
- A linked git worktree shares the host repo's `.git`, so untrusted code running in one could
  tamper with host git config and hooks (research/03 §8).
- uv's default `hardlink` mode on Windows shares files with the cache (research/03 §7).

## Decision
1. Isolation is **layered** (L0 process → L1 detection → L2 containment → L3 container
   enforcement → L4 gVisor/microVM). The card states the **highest layer actually achieved**.
   Network is reported as `enforced` only at L3 or above. Otherwise it is reported as
   `detected-only`.
2. **Docker is the default L3 backend** when available, on Windows (Docker Desktop/WSL2) and
   Linux. Without Docker, Repro still runs at L0–L2 and says so.
3. Target code runs only from **`.git`-less snapshots** copied into container volumes, never
   from a live linked worktree on the host.
4. Installs run in a separate sandbox step whose only egress is the package index, or offline
   from wheels prefetched on the host. Sandboxed uv uses `--link-mode copy` with a read-only cache.
5. Linux CI may add gVisor (`runsc`) as L4.

## Alternatives considered
| Option | Why not |
|---|---|
| In-process guards only | Not a boundary. It would make Repro's "network off" claim false |
| Windows Sandbox / Hyper-V VMs | Unavailable on Windows Home, and Windows Sandbox runs only one instance at a time |
| Hosted sandboxes (E2B, Modal) as the default | Sends code to a third party, which breaks the local-first promise. Kept as a later optional backend (K05) |
| Run everything inside WSL | WSL is not isolation: it has Windows interop and `/mnt/c` |

## Consequences
- Contributors on Windows should install Docker Desktop for full isolation. `repro doctor`
  detects capabilities.
- Running Linux containers on Windows changes the platform the tests run on. Base and head
  share it, so the *diff* stays valid. The platform is recorded on the card.
- Container start-up and volume copies add latency. Phase D02 measures this and caches
  environment images keyed by lockfile digest.
