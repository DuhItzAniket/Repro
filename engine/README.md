# repro-engine

The Repro engine: orchestrator, event bus, storage, sandboxed two-sided execution, behaviour
tracing, diffing, policy, agents and card export. The design is in
[`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).

The import package is `repro` (src layout: `engine/src/repro/`). The console script is `repro`.

```
uv run repro --version
uv run repro doctor          # Python, SQLite, git, uv, Docker and the data paths (--json)
uv run pytest
```

`repro serve` serves the read-only API and the event stream on `127.0.0.1:8780` (loopback only;
`--allow-origin` for a dev server). `run`, `replay` and `export` are declared and exit with
status 2, naming the phase that brings them (C08, C08, F05).

## Store

`repro.store` keeps runs, events, evidence and artifacts in `<data_dir>/repro.db` (SQLite, WAL)
and `<data_dir>/runs/<run_id>/`. `StoreWriter` is the only writer: it batches submitted events
into transactions, gives each its run's next `seq`, and resolves callers' futures after the
commit. `StoreReader` pages through a run's events read-only. `ArtifactStore` writes
content-addressed files atomically. The schema itself enforces append-only events and evidence
and gap-free `seq` (ARCHITECTURE §11).

## Bus and orchestrator

`repro.bus.EventBus` is the one way events enter the store: it builds the envelope, removes
recognised credentials, validates the event against its kind's generated model, and submits it
to the writer; subscribers get events only after they are committed. `repro.orchestrator` runs a
run's jobs as a DAG on daemon threads (at most `concurrency` at once), with per-job timeouts and
cancellation; failures, timeouts and skipped jobs are recorded as `fail` events and missing
items, and `run.finished` is always emitted.

## API

`repro.api.create_app` serves `GET /runs`, `/runs/{id}`, `/runs/{id}/evidence/{ev}`,
`/runs/{id}/artifacts/{sha256}` and `/runs/{id}/card`, and the WebSocket
`/runs/{id}/events?from=<seq>`: replay, a `caught_up` frame, then live events from the bus, each
exactly once in `seq` order. A client that falls behind is closed with 4000 "resync" and resumes
with `?from=`. Requests must name a local host; WebSocket origins must be allow-listed.

## Settings

Each setting comes from, in order: a command-line flag, a `REPRO_*` environment variable, the
TOML file (`REPRO_CONFIG`, else `config.toml` in the data directory), the default.

| Setting | Variable | Default |
|---|---|---|
| `data_dir` | `REPRO_DATA_DIR` | `~/.repro` (`%USERPROFILE%\.repro`) |
| `run_root` | `REPRO_RUN_ROOT` | `%LOCALAPPDATA%\repro\r` on Windows, `<data_dir>/r` elsewhere |
| `log_level` | `REPRO_LOG_LEVEL` | `info` (`debug`, `info`, `warning`, `error`) |
| `log_format` | `REPRO_LOG_FORMAT` | `json` (one object per line on stderr), or `text` |
| `concurrency` | `REPRO_CONCURRENCY` | the CPU count, at most 4 (1–64) |
| `sandbox` | `REPRO_SANDBOX` | `auto` (`docker`, `process`) |

Unknown keys and invalid values are errors that name their source. Paths must be absolute
after `~` is expanded.
