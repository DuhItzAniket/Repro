# A08 feasibility spikes: results

Measured on 2026-10-13. The raw JSON is in `results/`, and every number below can be
regenerated with the commands in [`README.md`](README.md). Linux-host numbers from a GitHub
runner (`.github/workflows/spikes.yml`, run 38429323214) are in `results/linux-gha/` and §4.

**Hardware and software (local).** x86-64 workstation, 24 logical CPUs, 16 GB RAM, Windows 11.
Docker Desktop 29.8.2 with the WSL2 backend (Linux containers in a VM on the same hardware).
CPython 3.12.13 / 3.13.13 / 3.14.4 / 3.15.0 (uv-managed) on Windows, and the official
`python:3.x-slim` images on Linux (3.12.15 / 3.13.16 / 3.14.8 / 3.15.0, digests in the run log
of the phase record).

---

## 1. `sys.monitoring` tracer overhead (ADR-0005)

**Method** (`tracer_bench.py`, stdlib only). Two workloads, each with one *target* function:
- `fib`: recursive `fib(22)`, 57,313 target calls per run, tiny integer arguments.
- `records`: `normalise_record(dict)` over 20,000 records whose arguments are dicts with lists.

Configurations:

| Config | Mechanism | Callbacks | Notes |
|---|---|---|---|
| `none` | — | — | baseline |
| `disable_all` | `sys.monitoring` | every code object returns `DISABLE` | |
| `target_dispatch` | `sys.monitoring` | `PY_START` + local `PY_RETURN` on the target, doing nothing | |
| `target_capture` | `sys.monitoring` | arguments read from the callee frame at `PY_START`; arguments and return value structurally encoded and BLAKE2b-hashed | |
| `target_capture_budget` | `sys.monitoring` | as `target_capture` for the first 200 calls, then `DISABLE` | |
| `settrace_dispatch` | `sys.settrace` | equivalent of `target_dispatch` | |
| `settrace_capture` | `sys.settrace` | equivalent of `target_capture` | |

Each configuration runs in a fresh process: 1 uninstrumented warm-up, 1 instrumented warm-up,
then 15 timed repetitions with GC collected between them. Configurations are interleaved over 5
rounds, and the reported value is the median of the round medians. Across rounds the spread
(max/min of round medians) was at most 1.07 for capture configurations.

| OS | Python | workload | baseline ms | disable_all × | dispatch ns/call (monitoring / settrace) | capture µs/call (monitoring / settrace) | budgeted capture × |
|---|---|---|---|---|---|---|---|
| Linux (container) | 3.12.15 | fib | 1.11 | 1.05 | 120 / 291 | 2.48 / 3.16 | 1.01 |
| Linux (container) | 3.12.15 | records | 11.98 | 0.96 | 145 / 502 | 9.77 / 13.10 | 0.98 |
| Linux (container) | 3.13.16 | fib | 1.16 | 0.99 | 114 / 194 | 2.46 / 2.53 | 0.98 |
| Linux (container) | 3.13.16 | records | 12.58 | 0.94 | 153 / 314 | 9.84 / 10.10 | 0.92 |
| Linux (container) | 3.14.8 | fib | 1.10 | 0.99 | 120 / 193 | 2.45 / 2.54 | 0.94 |
| Linux (container) | 3.14.8 | records | 11.35 | 0.98 | 150 / 442 | 9.87 / 10.39 | 1.00 |
| Linux (container) | 3.15.0 | fib | 1.07 | 1.04 | 120 / 214 | 2.60 / 2.78 | 1.02 |
| Linux (container) | 3.15.0 | records | 11.37 | 1.00 | 150 / 385 | 9.81 / 10.16 | 0.98 |
| Windows | 3.12.13 | fib | 1.47 | 1.06 | 158 / 335 | 2.48 / 3.26 | 1.19 |
| Windows | 3.12.13 | records | 11.33 | 1.00 | 185 / 547 | 10.66 / 14.03 | 0.95 |
| Windows | 3.13.13 | fib | 1.43 | 0.96 | 152 / 237 | 2.33 / 2.52 | 1.00 |
| Windows | 3.13.13 | records | 10.57 | 0.99 | 197 / 427 | 9.77 / 10.08 | 1.01 |
| Windows | 3.14.4 | fib | 1.64 | 0.95 | 173 / 258 | 2.85 / 3.05 | 0.96 |
| Windows | 3.14.4 | records | 10.38 | 0.96 | 195 / 474 | 11.36 / 11.88 | 0.94 |
| Windows | 3.15.0 | fib | 1.03 | 1.03 | 118 / 198 | 2.49 / 2.64 | 0.99 |
| Windows | 3.15.0 | records | 9.06 | 1.00 | 197 / 477 | 9.44 / 9.87 | 0.98 |

**Findings**
1. **Loading the tracer is free when nothing is a target.** With every code object returning
   `DISABLE`, the run takes 0.94–1.06× baseline, which is within noise on every OS and version.
   This confirms the PEP 669 design claim for our usage.
2. **Keeping a target instrumented costs 114–197 ns per call** with `sys.monitoring`, against
   **193–547 ns** with `sys.settrace`. That makes monitoring 1.3–3.6× cheaper per call.
3. **Capturing values costs 2.3–2.9 µs per call for small arguments and 9.4–11.4 µs for dict
   arguments.** Encoding dominates: with full capture, `settrace` is only 2–35 % slower than
   `sys.monitoring`. **The structural encoder, not the monitoring mechanism, is the
   performance-critical component.**
4. **Budgeted capture returns to baseline.** Capturing the first 200 calls and then
   `DISABLE` gives 0.92–1.19× baseline in steady state. The one-off cost of a full budget is about
   200 × 2–11 µs ≈ 0.5–2.3 ms per target function per test.
5. The results agree across Python 3.12–3.15 and across Windows and Linux. 3.15's `DISABLE`
   semantics for local events matched the earlier versions in this design.

**Decision: GO** for the ADR-0005 tracer.
- Initial defaults: **budget = 200 fully encoded calls per (test, function)**; after that,
  counts only; then `DISABLE`.
- E02 must treat encoder speed as a first-class requirement: fast paths for scalars, iteration
  instead of recursion, and early truncation.
- E01 re-measures on real test suites.

**Limits.** These are microbenchmarks. Real suites have more targets, deeper call stacks and
import costs. The encoder used is a minimal structural one: E02's will do more (normalisation,
guards) and may be slower or, once optimised, faster.

---

## 2. Docker sandbox round trip (ADR-0004, L3)

**Method** (`sandbox_roundtrip.py`):
1. Build the `honest-fix` fixture and take a `.git`-less `git archive` snapshot of head
   (20 KB).
2. Create a volume and copy the snapshot in through `tar` on stdin (no bind mount).
3. Provision a venv with pytest, with network on and no shared cache.
4. Run pytest in a hardened container: `--network none --read-only --tmpfs /tmp:exec
   --cap-drop ALL --security-opt no-new-privileges --user 1000:1000 --pids-limit 256
   --memory 1g --cpus 2`.
5. Run a network probe under the same flags.
6. Collect the JUnit XML from the volume, then remove the volume.

Image: `ghcr.io/astral-sh/uv@sha256:531f855b…44ca` (Python 3.13). Three repetitions.

| Step | Median (s) | Runs (s) |
|---|---|---|
| volume create | 0.147 | 0.144 / 0.147 / 0.148 |
| snapshot copy | 0.330 | 0.330 / 0.328 / 0.341 |
| provision (no cache, network) | 8.99 | 11.04 / 8.99 / 8.60 |
| test run, hardened | 0.899 | 0.990 / 0.892 / 0.899 |
| network probe | 0.404 | 0.406 / 0.404 / 0.389 |
| collect JUnit | 0.338 | 0.370 / 0.329 / 0.338 |
| volume remove | 0.159 | 0.161 / 0.159 / 0.158 |
| **total** | **11.25** | 13.44 / 11.25 / 10.88 |

The first-ever image pull took 138 s. That is a one-off, excluded above.

**Network enforcement, verified.** Inside the hardened container:
- `connect(1.1.1.1:443)` → `OSError [Errno 101] Network is unreachable`;
- resolving `pypi.org` → `gaierror [Errno -3] Temporary failure in name resolution`.

**L3 is real on Windows Home with Docker Desktop (WSL2).**

**Findings**
1. Per-container overhead is about **0.3–0.9 s** (create, start, Python startup). For each run
   Repro needs about 4–6 containers per side, i.e. roughly 2–5 s of fixed cost.
2. **`--tmpfs` is `noexec` by default.** In spike 3 this made three click tests fail with
   `PermissionError` (they write and execute a fake `less` in `tmp_path`). **D02 must mount
   `/tmp` with `exec`.** Otherwise the sandbox *itself* introduces failures. With `exec`, the
   hardened result equals the unhardened one.
3. Provisioning without a cache is dominated by downloads (see spike 3).

---

## 3. Environment provisioning in a container: real project

**Method** (`provision_bench.py`). Project: `pallets/click` 8.5.0 (commit `8b19813f`,
166 files, BSD-3-Clause), with its own `uv.lock`. The repository is cloned on the host but only
archived there; nothing from it executes on the host.

Provisioning: `uv sync --locked --no-default-groups --group tests --link-mode copy` into a
fresh project volume with a separate uv cache volume. Tests: the full suite in the hardened
container (network off, `/work` read-only).

| Scenario | Provision (s) | Test run (s) | pytest result |
|---|---|---|---|
| cold (empty cache, network) | 9.90 | 5.58 | 24 failed, 1967 passed, 24 skipped, 1 xfailed |
| warm (cache reused, network) | 0.91 | 5.54 | same |
| **warm offline** (`--network none`, `UV_OFFLINE=1`) | **0.79** | 5.30 | same |

**Findings**
1. **Offline installs from a warm cache work and are about 12× faster than cold.** They need
   no network at all, which validates the D03 design: populate the cache in a separate,
   index-only step, then provision every environment offline.
2. **24 tests fail in every configuration, hardened or not.** They are click's pager tests,
   which need a `less` binary that the slim image lacks. The same failures occur on base and
   head, so they are **F2F (pre-existing)** and must never flag a change. They are still
   evidence that the environment is incomplete. D03/D06 must report such cases as
   `environment` / pre-existing items rather than hide them, and D03 needs a documented base
   image with common CLI tools.
3. Container overhead on a real suite: pytest reports 3.7–4.0 s, while wall-clock is
   5.3–5.6 s, so about 1.5 s goes to container start, interpreter start and collection.
4. click's pytest configuration deselects 31,000 parametrised cases by default ("31000
   deselected"). Test selection (D05) must respect a project's own pytest configuration.

---

## 4. Linux host (GitHub-hosted runner)

Same scripts, run by `.github/workflows/spikes.yml` (run 38429323214) on an `ubuntu-latest`
runner: 4 vCPUs (AMD EPYC 9V45), 15 GiB RAM, Docker on a native Linux host. This is a shared
VM, so treat the numbers as indicative.

| Python | workload | baseline ms | disable_all × | dispatch ns/call (monitoring / settrace) | capture µs/call (monitoring / settrace) | budgeted × |
|---|---|---|---|---|---|---|
| 3.12.15 | fib | 1.16 | 1.13 | 105 / 170 | 1.82 / 2.12 | 1.14 |
| 3.12.15 | records | 9.02 | 0.93 | 166 / 346 | 7.16 / 8.68 | 0.88 |
| 3.13.16 | fib | 1.26 | 1.01 | 106 / 142 | 1.80 / 1.84 | 0.98 |
| 3.13.16 | records | 9.19 | 0.89 | 152 / 284 | 7.70 / 8.16 | 0.94 |
| 3.14.8 | fib | 0.97 | 0.99 | 102 / 150 | 2.30 / 2.33 | 1.00 |
| 3.14.8 | records | 9.34 | 0.89 | 112 / 278 | 8.09 / 8.24 | 0.92 |
| 3.15.0 | fib | 0.98 | 0.98 | 106 / 147 | 2.40 / 2.43 | 0.98 |
| 3.15.0 | records | 8.85 | 0.95 | 136 / 325 | 8.13 / 8.33 | 0.97 |

Sandbox round trip, three runs:
- total 1.93–1.98 s, of which provisioning was 0.84–0.86 s and the hardened test run 0.60–0.62 s;
- network blocked (`Errno 101`).

Provisioning pallets/click:
- cold 0.85 s, warm 0.59 s, warm offline 0.54 s;
- suite 6.5 s, with the same **24 environment-caused failures** as on Windows.

**Agreement with §1–3.** Every conclusion holds on a native Linux host:
- disabled tracer at about baseline;
- `sys.monitoring` dispatch 1.4–2.5× cheaper than `settrace`;
- capture dominated by encoding;
- budgeted capture at about baseline;
- L3 network enforcement works;
- offline provisioning is the fastest path.

The native host's much faster provisioning (0.85 s vs 9.9 s cold) reflects network proximity
to PyPI, not Docker. Windows-specific cost sits in Docker Desktop's VM boundary: a hardened
container run took 0.60 s here vs 0.90 s on Windows.

## Go / no-go and defaults

| Question | Answer | Default set |
|---|---|---|
| Is a `sys.monitoring` tracer with value capture affordable? | **Go**, with budgets | 200 encoded calls per (test, function), then count-only, then `DISABLE` |
| Is Docker L3 isolation viable on Windows Home? | **Go** | `--network none`, read-only root, `/tmp` tmpfs **with exec**, cap-drop ALL, non-root, pids/memory/cpu limits |
| Can environments be provisioned fast and offline? | **Go** | Cache-populating step (index-only egress), then offline `uv sync --locked --link-mode copy` |
| Fixed cost per run | ~2–5 s of container overhead plus provisioning | Reuse warm caches. Batch tests per container |
