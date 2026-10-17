# Repro for contributors

How the code is laid out and how a run moves through it, in one page. The full design is in
[ARCHITECTURE.md](../ARCHITECTURE.md); how work is done (phases, reviews, releases) is in
[CONTRIBUTING.md](../../CONTRIBUTING.md) and [the SDLC](../process/SDLC.md).

## The repository
| Path | What |
|---|---|
| `engine/` | The engine and the `repro` command (Python 3.13, `uv`) |
| `apps/web/` | The cockpit (TypeScript, Vite, three.js for the stage, Preact for the shell) |
| `packages/events/` | The event schema (`schema/`), the source of truth for both, with generated TypeScript and Pydantic types and `repro-events` (validation, codegen) |
| `bench/` | Benchmarks and evaluations (`repro_bench`): the agents' evals, the scale benchmark |
| `scripts/` | Repository tooling: licences, the release's wheels, the install check |
| `docs/` | Design, decisions (`adr/`), each phase's record (`phases/`), research, this guide |

## A run, end to end
`repro run` (`engine/src/repro/cli.py`) resolves the two refs, then hands
`pipeline.pipeline_jobs` to the orchestrator (`orchestrator/`), which runs jobs by stage, in
parallel where they do not depend on each other:

1. **read**: with agents on, the PR's claims (`agents/reader.py`).
2. **build**: each commit is copied without its `.git` (`gitops/snapshot.py`). The static
   analysis finds the changed functions and what imports them (`analysis/`), and the policy is
   read from base (`policy/loader.py`).
3. **run**: a sandbox per side (`sandbox/`: a contained process, or a container), an
   environment per side (`provision/`), then the tests (`runner/`):
   - the tests to run are chosen from a map of what each test ran on base (`runner/selection.py`);
   - base runs twice and head once, traced (`runner/twosided.py`, the pytest plugin in
     `sandbox/_hook/`);
   - flips are rerun, probes run on generated inputs (`runner/probes.py`), and the passing
     tests are timed (`runner/perf.py`).
4. **diff**: outcomes, behaviour (`runner/behaviour.py`), public API (`analysis/api.py`),
   dependencies (`provision/deps.py`) and timings become evidence.
5. **check**: the policy's invariants (`policy/invariants.py`).
6. **review**: with agents on, each claim is judged against the evidence, and every verdict is
   checked before it counts (`agents/stages.py`).
7. **card**: the status, by fixed rules (`policy/status.py`), and the card (`card/`).

## The event stream is the contract
Jobs do not share results through return values to the outside world. Every job reports
through **events** (`bus.py`), each validated against the schema and scrubbed of credentials
before it is stored (`store/`, SQLite, append-only). Everything else reads the events:
- the card is assembled from them (`card/assemble.py`);
- the API serves them, and the cockpit is a projection of them (`apps/web/src/model/`);
- `repro replay` and `repro export` rebuild the card from them and check it.

So a run can always be replayed from its log. To add something a run reports, change the schema
in `packages/events/schema` first (`pnpm gen` regenerates the types), then the job that emits
it, then what reads it.

## Common changes
- **A new check.**
  - A payload schema in `packages/events/schema/payloads/`, and an evidence type in
    `common.schema.json`.
  - The job that produces it, in `run_stage.py` or `pipeline.py`.
  - How the status rules treat it (`policy/gap.py`, `policy/status.py`).
  - Its place on the card, and in the cockpit's panels.
- **A new invariant.** Its schema in `policy/repro-yml.schema.json`, its evaluation in
  `policy/invariants.py`, its weakenings in `policy/loader.py`, and
  [the reference](repro-yml.md).
- **Something a run cannot check.**
  - A reason in `MissingReason` (`common.schema.json`), a `missing.recorded` event saying what
    would resolve it, and a row in [the failure catalogue](../FAILURES.md).
  - Never a pass.

## Tests
`uv run pytest` and `pnpm test`. What each kind of test covers is in
[TEST_STRATEGY.md](../TEST_STRATEGY.md). The parts you will meet first:
- **Fixture repositories** (`engine/tests/fixtures/specs.py`): small git repositories, built for
  each test, each with the evidence it must give (`fixtures/<name>.toml`).
- **Golden files** (`engine/tests/golden/`): cards and logs; `--update-goldens` rewrites them,
  and the diff is reviewed.
- **Cassettes** (`engine/tests/cassettes/`): the agents' calls, recorded once and replayed
  offline, so the tests never reach a model.
- **Markers**: `chaos` (each failure of the catalogue, end to end) and `agent_eval` (the agents'
  metrics against their thresholds) run in CI jobs of their own.
