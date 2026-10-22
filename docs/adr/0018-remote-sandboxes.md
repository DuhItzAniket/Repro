# ADR-0018: Remote sandbox backends for teams

- **Status:** accepted by the owner (2026-10-19). Option A is built (K05); options B and C
  are K09 and K10. C is built (K10), with Cloud Hypervisor in place of Firecracker (the owner's
  choice, 2026-10-21; see C below). They need infrastructure not yet provided (a Linux host with KVM, or a
  cloud account): their code is tested against fakes until a real host exists, and the
  isolation level L5 this acceptance approves enters the schema with B.
- **Date:** 2026-10-18
- **Phase:** K05

## Context
Repro runs a target's code in a container on the same machine (L3, ADR-0004), or under gVisor
(L4, H03). A team may want that work elsewhere: a shared build host, or hardware isolation
with a microVM per run. The roadmap's K05 names "self-hosted E2B / Firecracker". The owner
decided (2026-10-18) that parts needing paid infrastructure get a design and a local
prototype only.

What changed in H06 makes a remote engine cheap. The Docker sandbox no longer bind-mounts
anything from the host. The snapshot, Repro's hook and each environment reach the container
through the engine's own volumes and standard input, and results come back through the engine
(`DockerSandbox`, ARCHITECTURE §8). So nothing in a run needs the engine to share a
filesystem with Repro.

What the candidates offer, read on 2026-10-18:
- **A Docker context** names an engine, including one reached over SSH (`docker context create
  … --docker host=ssh://user@host`). `DOCKER_CONTEXT` selects it for every command
  [docs.docker.com, "Docker contexts" and "Protect the Docker daemon socket"].
- **E2B's runtime** (`e2b-dev/runtime`, Apache-2.0) gives "One Firecracker microVM per sandbox,
  in its own cgroup and network namespace, with a per-sandbox nftables egress firewall". It can
  be self-hosted ("E2B Embed … on a single Linux host with KVM") [V GitHub README].
- **Kata Containers** (Apache-2.0) can use Firecracker as its hypervisor. With containerd it
  needs the `devmapper` snapshotter; `kata-deploy` installs a `kata-fc` RuntimeClass
  [V kata-containers, `docs/how-to/how-to-use-kata-containers-with-firecracker.md`].

## Decision
- **A. A team's own Docker engine (built, K05).** The setting `docker_context`
  (`REPRO_DOCKER_CONTEXT`) names a Docker context that every container command uses. The
  context is the team's engine on another machine, over SSH or TLS. Isolation is what that
  engine gives: L3, or L4 with `docker_runtime = "runsc"` there. The card states it as for a
  local engine.
- **B. E2B self-hosted (design).** A third sandbox beside `ProcessSandbox` and `DockerSandbox`,
  `E2BSandbox`, behind the methods the run stage uses:
  - `run` maps to the runtime's command API;
  - `write_files` and `read_file` map to its file API;
  - the snapshot is uploaded as one archive, as it is streamed to a volume today;
  - its egress firewall denies everything during test runs, which is the network level L3
    enforces;
  - each microVM is its own kernel: a new isolation level, L5, which is a change to the event
    schema's isolation values and needs the owner's approval.

  **As built (K09): `sandbox = "e2b"`, on E2B's self-hosted Embed.** What K09 found, on
  2026-10-22 and 23:
  - Embed runs the whole stack on one Linux host with KVM, kernel 6.8 or newer
    [V e2b-dev/runtime, `embed/compose/README.md`]. WSL2's kernel was 6.6 until WSL 3.0.3,
    which ships 6.18.54 [V microsoft/WSL release 3.0.3].
  - Its builder takes no `COPY --from`, so the template follows Repro's image recipe step by
    step: the same base by digest, the same packages, uv 0.13.0 by its wheels' SHA-256.
  - **E2B's egress firewall was not enforcement there.** Told to deny every address, by
    `allow_internet_access=False`, `deny_out` or `update_network`, E2B stopped names
    resolving, but TCP to an address by number still connected (`1.1.1.1:443`,
    `8.8.8.8:443`, measured in each). So the network is closed by the VM's own kernel:
    - root adds an nftables rule that rejects every packet the target's user sends, but to
      loopback;
    - that user (`repro`, uid 1001) has no sudo, unlike E2B's own `user`;
    - a probe from inside must fail to reach the index by name and two addresses by number,
      or the side has no sandbox.

    E2B's deny is kept as a second layer.
  - A VM's lifetime is at most an hour ("Timeout cannot be greater than 1 hours"), so each
    command renews it.
- **C. Kata with Firecracker (design).** No new sandbox: a containerd host where the `kata-fc`
  runtime class runs Repro's containers. It is reached as in A if that host's engine exposes
  the runtime. A Kubernetes job per side would need its own sandbox class, like B.

  **As built (K10): Kata with Cloud Hypervisor, under Docker.** What K10 found, on 2026-10-21:
  - Firecracker's only storage is "file-backed block device[s]" [V firecracker README]: it
    shares no directory with the VM, so Repro's volumes (the snapshot, the hook, each
    environment) cannot reach it. Kata's guide runs it through containerd alone, with the
    devmapper snapshotter.
  - Kata 4.2.0's static release ships no Firecracker binary. It ships Cloud Hypervisor, QEMU and
    `virtiofsd` [V the release's tarball, unpacked].
  - Docker runs a containerd shim as a runtime (`docker run --runtime io.containerd.kata.v2`;
    a shim's path may be a runtime's `runtimeType`) [V docs.docker.com, "Alternative container
    runtimes"].

  So the owner chose Cloud Hypervisor (2026-10-21), and C is what it meant: no new sandbox.
  - `scripts/kata/setup.sh` gives a Linux host Docker Engine with a runtime `kata`: Kata's shim,
    with its shipped Cloud Hypervisor configuration as its default (Kata's runtime accepts no
    other path).
  - `docker_runtime = "kata"` runs every container of a run in a microVM, its volumes over
    virtio-fs.
  - The level is L5, from a probe: a container of the runtime whose kernel is not the engine's.
  - WSL2 is such a host on Windows 11, which gives it nested virtualization by default. So is
    GitHub's Ubuntu runner: GitHub calls nested virtualization there "technically possible" but
    "not officially supported" [V docs.github.com, "GitHub-hosted runners", 2026-10-21], and
    the setup script ran on it (CI job `kata`).

## Consequences
- A adds no code path: the same `DockerSandbox` talks to another engine. Its cost is latency,
  since snapshots and results cross the network, and the engine host's trust: it runs the
  target's code.
- B and C are where hardware isolation comes from. Both need a Linux host with KVM. K10 found
  two: the owner's machine, in WSL2, and GitHub's runners. C is tested on both; B is not yet.
- Whatever the backend, the card names the isolation level reached. A remote engine is not
  stated as more isolated than it is.
