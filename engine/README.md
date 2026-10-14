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

`run`, `replay`, `serve` and `export` are declared and exit with status 2, naming the phase that
brings them (C03, C08, C04, F05).

## Store

`repro.store` keeps runs, events, evidence and artifacts in `<data_dir>/repro.db` (SQLite, WAL)
and `<data_dir>/runs/<run_id>/`. `StoreWriter` is the only writer: it batches submitted events
into transactions, gives each its run's next `seq`, and resolves callers' futures after the
commit. `StoreReader` pages through a run's events read-only. `ArtifactStore` writes
content-addressed files atomically. The schema itself enforces append-only events and evidence
and gap-free `seq` (ARCHITECTURE §11).

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
