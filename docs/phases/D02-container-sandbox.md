# D02 — Container backend (L3)

| | |
|---|---|
| **Stage** | D — Sandboxed two-sided execution |
| **Status** | in progress |
| **Depends on** | D01 |
| **Branch / PR** | `phase/D02-container-sandbox` · PR pending |
| **Started / finished** | 2026-10-14 / — |

## Objective
Target commands run in a hardened Linux container, where the network is off for real: the only
level at which Repro reports `network: enforced`. An escape suite proves the boundary, and
`repro doctor` says which level runs on this machine will reach.

## Scope
- **`repro.sandbox.DockerSandbox(work, git, commit, limits=…, image=…)`**: the commit streamed
  into a Docker volume of its own and owned by uid 1000; `run(argv, cwd=…, env=…,
  timeout_s=…, stop=…)` in a fresh container per command; `read_file` to read results back;
  `close` removes the volume.
- **Hardening** (ADR-0004, measured in A08): `--network none`, `--read-only`, `/tmp` tmpfs
  mounted `exec`, `--cap-drop ALL`, `--security-opt no-new-privileges`, `--user 1000:1000`,
  `--pids-limit`, `--memory` with `--memory-swap` equal (no swap), `--cpus`. No host
  variables; no host mounts but Repro's audit hook, read-only.
- **`gitops.tar_tree`**: a commit as a deterministic tar stream for a Linux container: modes and
  symbolic links exactly as git stores them on any host, unsafe entries skipped and listed as in
  a snapshot.
- **`repro doctor`**: an `isolation` check: L3 when Docker has Linux containers (and the
  `sandbox` setting allows it), else L2 or L1, with the network detected only; `sandbox =
  docker` without Docker fails.
- **CI**: the Ubuntu job requires Docker for the escape suite (`REPRO_REQUIRE_DOCKER=1`).

## Out of scope
- Provisioning the target's environment and the read-only uv cache (D03); gVisor (L4,
  optional on Linux CI).

## Design notes
- **From the tree object, not a host directory.** A snapshot written on Windows cannot hold
  executable bits or symbolic links the way git stores them; streaming the tree object keeps
  them exact on any host, and nothing large is held in memory (A08 copied a `git archive` tar;
  `git archive` would also honour `export-ignore`, see C05).
- **No host directory is writable from inside.** Results (the audit log, test outputs) are read
  back from the stopped container with `docker cp`; the only bind mount is the audit hook, which
  is Repro's own file and read-only.
- **Detection stays on at L3.** The hook still records attempts Python sees, now blocked, so a
  blocked attempt is still evidence of what the code tried.
- **A container's processes end with it.** When the first process exits, the kernel ends the
  others in its PID namespace, so nothing is left running.
- **Pinned image.** `ghcr.io/astral-sh/uv:python3.13-bookworm-slim` by digest, the image A08
  measured; it is pulled once if missing. D03 settles the documented base image with common
  CLI tools.

## Acceptance criteria
- [ ] AC1 (roadmap): the escape suite (raw `_socket`, `ctypes`, subprocess network access,
      writes outside the work dir, host `.git` tampering) is blocked at L3.
- [ ] AC2 (roadmap): the card reports `network: enforced` only here (`sandbox.ready`).
- [ ] AC3 (roadmap): capability detection in `repro doctor`.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_sandbox_docker.py`: the five escapes, each on its own; the hardening read from `/proc/self/status`; the host `.git` fingerprint before and after |
| AC2 | `test_sandbox_docker.py` (L3, enforced) and `test_sandbox.py` (L2, detected-only) |
| AC3 | `test_doctor.py`: `check_isolation` for each setting and machine |

---
*Filled in at the end of the phase:*

## What shipped
- `engine/src/repro/sandbox/docker.py` (`DockerSandbox`, `docker_available`, the pinned image);
  `gitops.tar_tree` and `TarredTree`; `Limits.cpus`, `Execution.oom_killed`; the `isolation`
  doctor check; `REPRO_REQUIRE_DOCKER` in CI's Ubuntu job.
- THREAT_MODEL T1, T2 and T3 updated.
- Tests: `test_sandbox_docker.py` (14), `test_gitops_snapshot.py` (+1), `test_doctor.py` (+5).
  pytest 906 → 926 (924 pass and 2 skip on Windows with Docker Desktop).

## Evidence
- **Windows with Docker Desktop 29.8.2 (WSL2)**: all 14 L3 tests pass. Raw `_socket` and a
  `ctypes` call to libc's `connect` (which no Python audit event sees) are refused, a
  subprocess cannot reach the network, writes to `/etc`, `/usr/local/lib`, the hook mount and
  `/root` fail, no `.git` exists anywhere in the container, and the host repository's `.git` is
  unchanged. Inside: uid 1000, `CapEff` 0, `NoNewPrivs` 1. Executable bits and a symbolic link
  arrive intact; a script in `/tmp` runs. A 2 GiB allocation against 512 MiB is killed, a
  bounded fork bomb stops at the pids limit, and a timeout kills the container.
- Loading a small commit into a volume takes 0.94 s and a command 1.1 s on this machine (A08:
  0.3–0.9 s per container).
- No volume or container is left after the suite.
- CI run: linked in the PR (Ubuntu runs the suite; Windows runners have no Linux containers
  and skip it).

## Deviations from spec
- The roadmap's "subprocess `curl`": the pinned image has no `curl`, so the test uses `curl`
  where present and otherwise a separate Python process reaching the network.

## Known gaps
- L4 (gVisor) is not used yet.
- Each command starts a fresh container (about a second here); D06 batches a side's tests into
  one run.
- The image is pulled once on first use; a pull needs the network on the host.

## Dependencies added
None (the Docker CLI, detected at run time).

## Research notes
- Docker resource constraints: with `--memory-swap` equal to `--memory`, "the container
  doesn't have access to swap". https://docs.docker.com/engine/containers/resource_constraints/
  **[V]** 2026-10-14
- A08 (2026-10-13, `spikes/A08/RESULTS.md` §2): `--network none` refuses connections and DNS
  for real on Docker Desktop (WSL2); `--tmpfs` is `noexec` unless asked, which broke real test
  suites.
