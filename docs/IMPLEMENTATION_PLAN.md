# Repro — Implementation Plan

This document links the architecture ([ARCHITECTURE.md](ARCHITECTURE.md)) to the phased
roadmap ([ROADMAP.md](ROADMAP.md)). It covers the toolchain, how the work is sequenced and why,
the interfaces that hold the system together, the risk register, and the metrics tracked along
the way.

## 1. Sequencing rationale

1. **Contract first (A04–A05).** The event schema is the boundary between engine and UI, so it
   is written before either side.
2. **Measure the unknowns early (A08).** Three facts could invalidate the design and are not
   published anywhere:
   - the cost of `sys.monitoring` with argument capture;
   - Docker sandbox latency on Windows;
   - the time to provision an environment inside a container.

   They are measured before Stages D and E depend on them.
3. **Cockpit on fixtures before the engine (B before C).** The visual product is built and
   performance-tuned against a deterministic log. That forces the UI to be a pure projection
   and gives the engine a concrete target event stream.
4. **Evidence before opinion (D → E → F → G).** The deterministic card (F05) works with no LLM.
   Agents are added on top and can only cite what the engine produced. If the agents
   underperform, Repro is still a useful tool.
5. **Isolation in the core path (D01–D02).** Docker moves from "M7+ option" to Stage D (ADR-0004),
   because "network off" cannot be claimed without an OS boundary.
6. **Evaluation last, but designed now (ADR-0010).** Stage J needs Stage H's installable tool. Its
   protocol is fixed in advance so that the engineering doesn't drift toward the benchmark.

## 2. Toolchain baseline

Versions verified current on **2026-10-13** (sources in `docs/research/03–05`). Exact pins
are set in lockfiles during the phase that introduces each tool and recorded in that phase's
record. Repro **never** relies on a tool's floating default. For example, uv ≥ 0.13 defaults
to Python 3.15, which was released only on 2026-10-09.

| Tool | Version baseline | Notes |
|---|---|---|
| Python (engine) | ≥ 3.12, pin 3.13 for development | `sys.monitoring` needs 3.12+ |
| Python (targets) | 3.12–3.15 supported for tracing | Older targets run without traces (explicit missing item) |
| uv | ≥ 0.13 | ≥ 0.12.18 is required for the Windows wheel path-traversal fix |
| git | ≥ 2.40 | `-c core.longpaths=true` per command on Windows |
| Node.js | ≥ 22.12 | Required by Vite 8 and Vitest 5 |
| pnpm | 12.11.2, pinned via `packageManager` | `npm i -g pnpm@12.11.2` (corepack is not bundled with Node ≥ 25) |
| Docker | Desktop (WSL2) on Windows; Engine on Linux | Default L3 sandbox (ADR-0004) |
| fastapi / uvicorn | 0.143.0 / 0.54.0 | |
| pydantic | 2.14.1 | |
| claude-agent-sdk | 0.2.165 (bundles CLI 2.1.294) | Pin exactly. Releases arrive every few days |
| Schema codegen | in-house `repro-events-codegen` (ADR-0014) | json-schema-to-typescript 16.0.0 / datamodel-code-generator 0.83.0 evaluated and not used |
| ajv / ajv-formats | 8.20.0 / 3.0.1 | Draft 2020-12 validation in TypeScript tests |
| pytest / hypothesis | 9.1.1 / 6.169.0 | |
| grimp / griffe | 3.17 / 2.3.2 | griffe with `allow_inspection=False`; the `griffelib` distribution (E05) |
| three | 0.186.1 (r186) | `WebGLRenderer` only |
| vite / vitest / playwright | 8.3.4 / 5.0.4 / 1.64.0 | |
| biome | 2.5.15 | |
| preact / @preact/signals | 11.0.1 / 2.11.3 | |
| d3-force | 3.0.0 | |
| size-limit | 14.2.0 | gzip, 300 kB |
| JetBrains Mono | `@fontsource-variable/jetbrains-mono` 5.3.0 (OFL-1.1) | Ship `OFL.txt` with the font |

## 3. Developer environment (Windows first)

1. Upgrade uv to ≥ 0.13, then `uv python install 3.13`. Many Windows machines still default to
   an older Python. If `uv self update` reports "version … was not found" (seen with uv 0.11.6
   in A02), reinstall uv with the official installer or winget instead.
2. Install pnpm at the version pinned in `package.json` (`npm i -g pnpm@<version>`). Corepack is
   no longer bundled with Node ≥ 25.
3. Clone to a short path. pnpm 12's task-state files under `node_modules` fail beyond the
   260-character Windows path limit (observed in A02).
4. Install Docker Desktop with the WSL2 backend. This works on Windows Home, whereas Windows
   Sandbox and Hyper-V do not. Without Docker, Repro still runs but reports `isolation: process`.
5. Repository-local git settings: `core.autocrlf=false` (`.gitattributes` enforces LF) and
   `core.longpaths=true`. Repro itself never changes the user's global git configuration.
6. Keep run roots short (`%LOCALAPPDATA%\repro\r\<id8>`). Don't put untrusted target code on a
   trusted Dev Drive, because Defender switches to asynchronous scanning there.

`repro doctor` (C01) checks all of the above and prints what is missing.

## 4. Workstreams

| Workstream | Stages | Main modules |
|---|---|---|
| Contract | A04–A05, then ongoing | `packages/events` |
| Cockpit | B, C08, E07 | `apps/web` |
| Engine core | C | `orchestrator`, `bus`, `store`, `api`, `gitops`, `analysis` |
| Execution & isolation | D | `sandbox`, `envs`, `runner`, `plugin` |
| Evidence | E | `plugin/tracer`, `plugin/encoder`, `diff` |
| Policy & card | F, H04 | `policy`, `card` |
| Agents | G | `agents`, `runner/probes` |
| Integrations | I | `integrations/github` |
| Evaluation | J | `bench/` |
| DevEx / CI / security | A, H, ongoing | `.github/`, tooling |

## 5. Core interfaces

Python protocols are sketched below and fixed in the phase that introduces each one. Each has a
fake implementation for tests.

```python
class SandboxBackend(Protocol):                       # D01/D02
    level: IsolationLevel                             # L0..L4, reported on the card
    def prepare(self, snapshot: Path, spec: EnvSpec) -> SandboxHandle: ...
    def run(self, h: SandboxHandle, cmd: list[str], *, timeout_s: float,
            network: Literal["none", "index-only"]) -> RunResult: ...
    def collect(self, h: SandboxHandle, rel: str, dest: Path) -> None: ...
    def destroy(self, h: SandboxHandle) -> None: ...

class Provisioner(Protocol):                          # D03
    def detect(self, snapshot: Path) -> ProjectKind | None: ...
    def provision(self, sb: SandboxBackend, h: SandboxHandle, python: str) -> EnvReport: ...

class Differ(Protocol):                               # D06, D07, E04, E05
    kind: str
    def diff(self, ctx: DiffContext) -> Iterable[Evidence]: ...

class Invariant(Protocol):                            # F02/F03
    name: str
    def evaluate(self, ctx: PolicyContext, cfg: Mapping[str, Any]) -> InvariantResult: ...

class LLMBackend(Protocol):                           # G01
    async def run(self, req: AgentRequest) -> AgentResult: ...   # structured output + usage

class Exporter(Protocol):                             # F05, H04
    media_type: str
    def export(self, card: Card) -> bytes: ...
```

The UI side has three interfaces: `Projection<S>` (`init`, `apply(state, event, meta)` with
`meta = { index, time }`, optional `clone` for snapshots; fixed in B02), `Layer` (`init(gl)`,
`update(view, t)`, `draw()`), and `Panel` (`draw(ctx, view, t)`, `isDirty(version)`).

## 6. Engineering notes per stage

- **A:** keep generated code checked in. Contributors should never need to run codegen to build.
  The drift gate enforces consistency.
- **B:** start B04 with the stress fixture and measure on a real mid laptop before building the
  layers. Shaders live in `.glsl` files imported with `?raw`. No object allocation inside
  `frame()`; B12 gates a flat heap and a per-frame allocation budget.
- **C:** the single-writer bus is the only code that assigns `seq`. All other components emit
  through it. Write the WebSocket gap-free test first, then the code.
- **D:** every sandbox feature gets an escape or containment test in the same PR. The plugin is
  stdlib-only and tested in a matrix of Python 3.12–3.15 inside containers.
- **E:** the encoder is the most security- and correctness-sensitive code. It gets property tests,
  a hostile-object fuzz corpus, and review of every change.
- **F:** status rules are a pure function `(evidence, verdicts, policy) → status`, tested
  exhaustively over rule combinations.
- **G:** prompts are versioned files. Any prompt or model change must show eval-set metrics in
  its PR (G09 gate).
- **H–I:** release automation produces the same artifacts locally and in CI.
- **J:** the benchmark code never imports engine internals. It drives the CLI or API like a user.

## 7. Risk register

| # | Risk | Likelihood | Impact | Mitigation | Trigger to revisit | Phase |
|---|---|---|---|---|---|---|
| R1 | Tracer overhead too high for real suites | M | H | A08 spike. Budgets, target-only events, DISABLE | Overhead > A08 budget on the reference repo | A08, E01 |
| R2 | Trace noise makes the Gap panel unreliable | M | H | Structural encoder, A/A′ masking, reruns | False-flag rate on clean fixtures > 0 | E02–E04 |
| R3 | Existing tests rarely reach divergences | H | H | Differential probes (E06, G07) | Catch rate on S1 pilot below baselines | E06, G07, J04 |
| R4 | Environment provisioning fails often | H | M | Env cache, explicit `environment_failed`, SWE-format images for evaluation | UNVERIFIABLE(env) > 20 % on pilot | D03, J01 |
| R5 | Docker unavailable or slow on Windows | M | M | Honest L2 fallback. Volumes, not bind mounts | A08 latency budget exceeded | A08, D02 |
| R6 | LLM verdict bias or errors | M | H | Evidence-enum schemas, validation, order swap, panel, deterministic rules | Flip rate > threshold on eval set | G05–G09 |
| R7 | Prompt injection through PR content | M | H | No built-in tools, delimited untrusted text, read-only tools, deny hooks | Any injection fixture alters behaviour | G01, G03 |
| R8 | WebGL budget not met on mid laptops | L | M | B04 stress benchmark, `Layer` swap path, adaptive DPR | p95 frame time > 16.7 ms | B04–B07 |
| R9 | Agent SDK churn (frequent releases) | H | L | Exact pin, `LLMBackend` protocol, cassettes | Breaking change on upgrade | G01 |
| R10 | Competitors ship base-vs-head diffing | M | M | Lead on function-level evidence, claims/missing, local replay, published benchmark | — | J |
| R11 | Benchmark labels too uncertain | M | H | Two-tier auto labels, two annotators, κ, budget for UNCERTAIN | κ < 0.6 on the pilot | J02, J06 |
| R12 | Licensing of datasets and images | M | M | Reference unlicensed data by ID, never re-host. Pseudonymise logins | — | J01, J09 |

## 8. Metrics tracked across phases

| Metric | Source | From |
|---|---|---|
| CI duration per tier | GitHub Actions | A06 |
| Engine branch coverage (core packages) | pytest-cov (separate pass) | C |
| JS bundle (gzip) | size-limit | B |
| Frame time p50/p95 on stress fixture | perf HUD / nightly | B04 |
| Wall-clock per run on 3 reference repos | engine timings | D |
| Tracer overhead ratio | E01 benchmark harness | E01 |
| False-flag count on clean fixtures | integration suite | E |
| UNVERIFIABLE rate on fixtures and pilot | integration / J04 | F |
| Agent eval: claim P/R, verdict accuracy, citation validity, flip rate, $ per PR | G09 harness | G |

Metrics are recorded in phase records and stage gates, never estimated.
