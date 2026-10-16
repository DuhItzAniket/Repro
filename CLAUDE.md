# Repro

> Every agent-written change, reproduced and verified before it merges.

Repro is a verification cockpit for code changes written by AI coding agents (and by humans). For
a pull request or branch, Repro:

1. checks out **base** and **head** as isolated snapshots;
2. runs them, base twice to measure noise;
3. records what each side actually *does*: test outcomes and function-level behaviour traces;
4. diffs that behaviour, plus the tests, API, dependencies and performance;
5. checks declared invariants;
6. has reviewer agents judge the PR's claims **against that evidence**.

The result is a **Reproduction Card** per change: VERIFIED, FLAGGED or UNVERIFIABLE, with the
evidence and an explicit list of what could not be checked.

The UI is a live, animated "mission control" in the visual language of the Paper Lab reference
video (kept locally in `reference/`, not committed). The animation is not decoration: every line,
streak and pulse on screen is a projection of a real pipeline event.

Positioning: execution-capable AI reviewers and base-vs-head prior art exist (Testora,
PatchDiff, BERT; see `docs/RESEARCH.md`). Never claim otherwise. Repro's edge is function-level
evidence, claim attribution, and the Missing list, all local and replayable.

## Read these before writing code

| File | What it holds |
|---|---|
| `docs/ROADMAP.md` | Stages A–K and every phase with acceptance criteria. **Work phase by phase.** |
| `docs/process/SDLC.md` | Phase lifecycle, Definition of Done, stage gates, branching, commits, privacy |
| `docs/ARCHITECTURE.md` | Pipeline, event model, evidence, isolation, agents, storage, UI architecture |
| `docs/IMPLEMENTATION_PLAN.md` | Sequencing, toolchain baseline (verified versions), interfaces, risks |
| `docs/PRODUCT.md` | Problem, positioning, the card, scope and non-goals |
| `docs/DESIGN.md` | Visual language, panels, motion and accessibility rules, perf budget |
| `docs/TEST_STRATEGY.md` / `docs/THREAT_MODEL.md` | How we test; what we defend against |
| `docs/adr/` | Decisions. `proposed` ADRs need the owner's approval before implementation |
| `docs/RESEARCH.md`, `docs/research/` | Landscape, literature and technical research, source-tagged |
| `docs/paper/` | Paper tracker, evaluation protocol, research log, verified bibliography |

## Ground rules

1. **Evidence before opinion.** Deterministic checks are ground truth: tests, traces, AST/API
   diffs and invariants. LLM agents interpret, explain and judge claims, but every agent verdict
   must cite evidence IDs produced by the engine. A verdict with no evidence is rejected.
2. **The event stream is the contract.** The engine only emits events, and the UI is a pure
   projection of the event stream. Any run must be replayable from its stored event log.
   Change the schema in `packages/events` first, then producers, then consumers.
3. **Never "unverified" silently.** If something could not be checked, it appears on the card as
   an explicit `missing` item, never as a pass. The card states the isolation level actually
   achieved.
4. **Motion carries meaning.** No random decorative animation outside the idle state. If an
   element moves, it maps to an event. See `docs/DESIGN.md#motion`.
5. **Isolation.** Target repos are untrusted code. They run only from `.git`-less snapshots in
   throwaway sandboxes (a container with `--network none` when Docker is available), never in
   the Repro source tree and never in a linked worktree on the host.
6. **Small, tested steps.** One phase per branch (`phase/<ID>-<slug>`). Each phase ends with:
   - passing tests;
   - a completed phase record in `docs/phases/`;
   - an updated ROADMAP row and CHANGELOG;
   - a squash-merged PR, pushed to GitHub.

   Each stage ends with a gate: full CI on Ubuntu + Windows and a tagged release.
7. **Ask the owner** before changing the stack, the event schema's core fields, or a stage's
   scope, and before implementing any `proposed` ADR.
8. **Public repository: no personal or sensitive data.** No secrets, tokens, `.env` files,
   personal names or emails, or home-directory paths in code, docs, fixtures or commit metadata.
   Commits use the GitHub noreply email. Third-party media (e.g. the reference video) is never
   committed.
9. **Authentic research only.** Every external fact in docs carries a source and a verification
   tag. Never invent citations, versions or numbers. A number is either measured reproducibly or
   not stated. Paper-relevant results go into `docs/paper/LOG.md`.

## Stack (decided; ask before changing)

- **Monorepo:** pnpm workspaces (TS) + `uv` (Python).
- **Web UI (`apps/web`):** Vite + TypeScript. Stage rendering is three.js `WebGLRenderer` with
  custom instanced `RawShaderMaterial` layers (ADR-0008). Panels are Canvas 2D. The shell is
  Preact + signals. Tooling is Biome, Vitest, Playwright and size-limit (ADR-0009).
- **Engine (`engine/`):** Python 3.12+ (development pins 3.13), FastAPI + WebSocket, SQLite
  (WAL, single writer). First target language: **Python repos with pytest**. Reused libraries:
  grimp and griffe (ADR-0006). Tracer, encoder and selection map are Repro's own (ADR-0005).
- **Isolation:** layered, with Docker as the default enforcing sandbox (ADR-0004).
- **Agents:** Claude Agent SDK (Python `claude-agent-sdk`, pinned exactly), locked down, behind
  an `LLMBackend` protocol (ADR-0007). Models are configurable via env. A second backend for
  OpenAI-compatible APIs (Groq, local servers) is accepted in ADR-0016; Stage G's recordings
  and evaluation use Groq's gpt-oss-120b.
- **CLI:** `repro` (Python, Typer): `run`, `replay`, `serve`, `doctor`, `export`.

## Commands (keep accurate; add a command only once it works)

Prerequisites: Node ≥ 22.12, pnpm 12.11.2 (`npm i -g pnpm@12.11.2`; corepack is not bundled
with Node ≥ 25), uv, and Python 3.13 (`uv python install 3.13`).

```
pnpm install            # JS deps for all workspace packages (apps/*, packages/*)
uv sync                 # Python workspace (engine, bench) into .venv, with the dev group
pnpm dev                # web UI dev server (Vite) on :5173
pnpm typecheck          # tsc --noEmit across JS packages
pnpm test               # Vitest across JS packages
pnpm build              # production build of apps/web
uv run pytest           # Python tests
uv run repro --version  # engine CLI
uv run repro doctor     # can this machine run Repro? (--json for a report)
uv run repro run --repo <path> --base <ref> --head <ref>   # live in the cockpit (C08)
uv run repro replay <run id | log.jsonl>                    # replayed from the start
uv run repro export <run id | log.jsonl> --format md|json  # the card, checked against the log (F05)
uv run repro serve      # cockpit + read-only API + event stream on 127.0.0.1:8780

pnpm lint               # Biome lint + format check (TS/JSON); pnpm lint:fix to apply
uv run ruff check       # Python lint (rules: pyproject.toml, ADR-0013)
uv run ruff format      # Python format (--check in CI)
uv run mypy             # strict type check of engine, bench and tests
pnpm gen                # regenerate TS types + Pydantic models from packages/events/schema
uv run repro-events-codegen --check   # drift gate (CI): fails if generated code is stale
uv run python scripts/check_licenses.py   # licence allow-list over all installed deps (CI)
uv run repro-events validate <log.jsonl>   # schema + log invariants of an event log
pnpm fixtures                             # regenerate apps/web/fixtures/*.jsonl (review the diff!)
uv run pytest --update-goldens            # rewrite golden files, lock new prompt versions (review the diff!)
pnpm --filter @repro/web exec playwright test -c playwright.gate.config.ts
                        # Gate C end to end; needs pnpm build, uv sync and REPRO_GATE_REPO
                        # (a clone of pallets/itsdangerous); REPRO_GATE_CHANNEL=msedge on Windows
```

Optional: `uvx pre-commit install` enables local hooks for Ruff and Biome.

CI (`.github/workflows/ci.yml`) runs the same commands from a clean checkout on Ubuntu and
Windows, with `--frozen-lockfile` / `--locked`.

## Platform notes

The developer works on **Windows** (x64).
- Keep scripts cross-platform: no bash-only scripts in the critical path, use `pathlib`, avoid
  symlinks, and test path handling with backslashes.
- `sys.monitoring` needs Python 3.12+. Install it with `uv python install`. Never rely on uv's
  default interpreter (3.15 since uv 0.13).
- Use uv ≥ 0.12.18 for the Windows wheel path-traversal fix.
- Pass `-c core.longpaths=true` to git per command. Never modify the user's global git config.
- Docker Desktop (WSL2 backend) provides the L3 sandbox on Windows, including Home editions.
- Keep the checkout path short on Windows (about 100 characters or less). pnpm 12 writes
  `node_modules\.pnpm-task-run-state-v1\<~100-char name>` and fails with "path not found" once
  the full path passes 260 characters (observed in A02).
