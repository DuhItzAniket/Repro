# K10 — Kata Containers microVMs (L5)

| | |
|---|---|
| **Stage** | K — Expansion |
| **Status** | done |
| **Depends on** | K05 (ADR-0018) |
| **Branch / PR** | `phase/K10-kata-firecracker` · [#116](https://github.com/DuhItzAniket/Repro/pull/116) |
| **Started / finished** | 2026-10-21 / 2026-10-21 |

## Objective
ADR-0018's option C, accepted by the owner on 2026-10-19: Repro's containers in Kata Containers
microVMs, each with a kernel of its own, as isolation level L5. The roadmap named Firecracker
and a containerd host. The phase found that Firecracker cannot take Repro's volumes. The owner
chose Cloud Hypervisor instead (2026-10-21), under Docker (see Deviations).

## Scope
- **A host** (`scripts/kata/setup.sh`, run once with sudo):
  - Ubuntu 24.04 on amd64 with `/dev/kvm` and systemd;
  - Docker Engine 29.8.2 from Docker's apt repository, its key checked by fingerprint;
  - Kata Containers 4.2.0's static release, checked by SHA-256, with its shipped Cloud
    Hypervisor configuration as the runtime's default;
  - Docker's runtime `kata`, which is Kata's shim by its path;
  - a self-test: a container whose kernel is not the host's, and a volume shared with it.
- **The sandbox:**
  - `docker_runtime = "kata"` (`REPRO_DOCKER_RUNTIME`) passes the runtime to every container
    that runs the target's code, as `runsc` does;
  - the level is probed when the sandbox starts. A container of the runtime runs `uname -r`
    with no network, and its kernel is compared with `docker info`'s. Only a different kernel
    is L5, whatever the runtime's name;
  - at L5 the process limit is also uid 1000's `nproc` (Evidence).
- **The schema:** `L5` as an isolation level and `kata` as a sandbox backend in `run.started`,
  as ADR-0018 asked and the owner accepted.
- **The pipeline:** `run.started` names the backend `kata` when the runtime's name is Kata's.
  The card's level comes from `sandbox.ready`, which is the probe's.
- **CI:** a job `kata` runs the setup script and the container tests on GitHub's runner. It is
  not required.
- **Docs:**
  - ADR-0018's option C as built;
  - ARCHITECTURE §8;
  - THREAT_MODEL T2, T4, §5 and §7;
  - the settings, troubleshooting and reading-a-card guides;
  - the attestation predicate's `isolationLevel`;
  - CONTRIBUTING and TEST_STRATEGY's jobs.

## Out of scope
- Kata under containerd alone or a Kubernetes runtime class: Repro drives Docker.
- Firecracker (Deviations).
- E2B's self-hosted sandbox (K09).
- `repro doctor` predicting L4 or L5: it reports L3 for Docker whatever the runtime, as it has
  since H03.

## Acceptance criteria
- [x] AC1: a Linux host with KVM gets a Docker runtime that runs each container in a microVM,
  and a self-test proves it.
- [x] AC2: with `docker_runtime = "kata"`, the container sandbox's suite passes in microVMs. The
  suite covers the escape attempts, the limits, the network and the volumes.
- [x] AC3: the card states L5 only when the container's kernel is not the engine's.
- [x] AC4: a run end to end in microVMs gives the same evidence as at L3. Its card says L5, and
  `run.started` names `kata`.
- [x] AC5: the process limit holds at L5.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | The script's self-test, on the owner's WSL2 and in CI's `kata` job |
| AC2 | `test_sandbox_docker.py` with `REPRO_DOCKER_RUNTIME=kata` (the module's `LEVEL` is L5 then) |
| AC3 | `test_sandbox_docker.py::test_the_ready_payload_reports_the_network_enforced` at L5 in microVMs and L3 under runc |
| AC4 | `test_run_stage.py::test_a_run_under_kata_is_l5`; `test_run_command.py`'s backend for `kata` |
| AC5 | `test_sandbox_docker.py::test_a_fork_bomb_meets_the_pids_limit` in microVMs |

---
*Filled in at the end of the phase:*

## What shipped
- **Engine:**
  - `sandbox/docker.py`: the probe (`own_kernel`), L5, and `--ulimit nproc` at L5;
  - `pipeline.run_backend`: `kata`;
  - the runner's backend type and the card's levels.
- **Schema:** `IsolationLevel` gains `L5` and `SandboxBackend` gains `kata`, with the generated
  TypeScript types and Pydantic models.
- **Host:** `scripts/kata/setup.sh`.
- **CI:** the `kata` job.
- **Tests:**
  - `test_a_run_under_kata_is_l5`;
  - the `kata` case of `run_backend`;
  - the container module's level and fork-bomb check at L5.

## Evidence
Measured on 2026-10-21. **The owner's machine:**
- WSL2's Ubuntu 24.04.4 on Windows 11 (kernel 6.6.87.2-microsoft-standard-WSL2), with nested
  virtualization (Windows 11's default);
- Docker Engine 29.8.2 and Kata 4.2.0;
- Cloud Hypervisor v51.1, by the release's `versions.yaml`;
- the guest kernel 6.18.35.

**Results there:**
- **The setup's self-test:**
  - the host kernel was 6.6.87.2-microsoft-standard-WSL2 and the guest kernel 6.18.35;
  - a volume written and read in the microVM.
- **The first run of the container module in microVMs:** 24 passed and 1 skipped (gVisor
  only), in 492 s. One failed, the fork bomb: 30 processes started against a limit of 16.
- **Why:** in a Kata container, `/sys/fs/cgroup/pids.max` reads `max` with `--pids-limit 16`.
  Docker's limit does not reach the VM's kernel.
- **The fix, measured before it was made:**
  - in a microVM as uid 1000, with `--ulimit nproc=16:16`, a process spawned 15 children, and
    the 16th failed with `EAGAIN`;
  - without the setting, it spawned 40 of 40;
  - under runc on the same engine, the same setting stopped the container's first `exec`:
    WSL's own uid 1000 already had processes. So the setting is used only on a kernel of the
    container's own.
- **After the fix:** RESULTS_WSL.

**CI's `kata` job:** RESULTS_CI.

## Deviations from spec
- **Cloud Hypervisor, not Firecracker.** This was the owner's choice on 2026-10-21, on these
  findings:
  - Firecracker's storage is block devices only, and it shares no directory with the VM, so
    Repro's volumes (the snapshot, the hook, the environments) cannot reach it;
  - Kata 4.2.0's static release ships no Firecracker binary;
  - Cloud Hypervisor shares the volumes over virtio-fs.

  Sources are in ADR-0018.
- **Docker, not a containerd runtime class.** Docker runs Kata's shim as a runtime, so the
  sandbox, its hardening and its tests are unchanged. That is ADR-0018's "no new sandbox".
- **The process limit at L5** is `nproc`. Kata's VM ignores the pids limit, so uid 1000's
  `nproc` stands in for it.

## Known gaps
- GitHub calls nested virtualization on its runners "not officially supported". The `kata`
  job may stop working without notice, which is why it is not required.
- The probe adds one container to each sandbox's start: PROBE_TIME in a microVM. With no
  runtime set, nothing is probed.
- Kata's guest kernel and image come from its release, checked by its SHA-256 and trusted as
  the host's kernel is.
- The setup script supports Ubuntu 24.04 on amd64 only, since its pins are noble's.
- `repro doctor` does not predict L4 or L5 (Out of scope). The card states what a run reached.

## Dependencies added
None to Repro. The setup script installs host software, which is not distributed with Repro:
- Docker Engine 29.8.2;
- Kata Containers 4.2.0 (Apache-2.0), whose release includes Cloud Hypervisor (Apache-2.0
  and BSD-3-Clause) and virtiofsd.
