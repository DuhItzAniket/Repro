# ADR-0018: Remote sandbox backends for teams

- **Status:** accepted by the owner (2026-10-19). Option A is built (K05); options B and C
  are K09 and K10. They need infrastructure not yet provided (a Linux host with KVM, or a
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
- **C. Kata with Firecracker (design).** No new sandbox: a containerd host where the `kata-fc`
  runtime class runs Repro's containers. It is reached as in A if that host's engine exposes
  the runtime. A Kubernetes job per side would need its own sandbox class, like B.

## Consequences
- A adds no code path: the same `DockerSandbox` talks to another engine. Its cost is latency,
  since snapshots and results cross the network, and the engine host's trust: it runs the
  target's code.
- B and C are where hardware isolation comes from. Both need a Linux host with KVM, which
  Repro's CI and its owner's machine do not have, so neither can be tested here.
- Whatever the backend, the card names the isolation level reached. A remote engine is not
  stated as more isolated than it is.
