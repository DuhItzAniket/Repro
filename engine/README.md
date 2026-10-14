# repro-engine

The Repro engine: orchestrator, event bus, storage, sandboxed two-sided execution, behaviour
tracing, diffing, policy, agents and card export. The design is in
[`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).

The import package is `repro` (src layout: `engine/src/repro/`). The console script is `repro`.

```
uv run repro --version
uv run repro doctor          # Python, SQLite, git, uv, Docker and the data paths (--json)
uv run repro run --repo <path> --base <ref> --head <ref>   # the cockpit shows it live
uv run repro replay <run id | log.jsonl>                    # from the start
uv run repro serve           # the cockpit, the read-only API and the event stream
uv run pytest
```

`run`, `replay` and `serve` listen on `127.0.0.1:8780` (loopback only; `--port`, `--open` to
open the browser, `--allow-origin` for a dev server) and serve the built cockpit (`pnpm build`;
the `ui_dir` setting points elsewhere). `run --no-serve` waits for the run and exits 0 if it
completed, 1 if not. `export` is declared and exits with status 2, naming its phase (F05).

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

## Git layer

`repro.gitops` reads an untrusted target repository: `Git` runs hardened commands (long paths,
no hooks, no fsmonitor), `resolve` and `merge_base`; `diff` lists changed files with exact paths
and their changed line ranges; `snapshot` writes a commit's tree, byte for byte, into a
`.git`-less directory, skipping and listing entries that are unsafe on this machine;
`add_worktree` and `remove_worktree` give host-side checkouts that are always cleaned up.

## Static analysis

`repro.analysis` reads a target's Python source with `ast`, never importing it.
`module_names` names each file as Python would import it; `build_table` lists a module's
functions, methods and classes with stable IDs (`pkg.mod:Class.method#0`, `<module>` for the
module's own code); `changed_symbols_between(git, base, head)` gives each symbol the change
touched (`modified`, `renamed`, `moved`, `added`, `removed`), as `symbol.changed` payloads, and
lists the files it could not read. `import_graph` builds one side's module import graph (grimp
for packages, in a process of its own; `ast` for tests and scripts outside packages), and
`analyse(git, base, head, workdir)` returns the changed symbols, both graphs and the blast
radius, with `graph_payloads` and `blast.payload()` giving their events.

## Sandbox

`repro.sandbox.ProcessSandbox(work, limits)` runs a command at L0 to L2 (ADR-0004):
`run(argv, cwd=…, env=…, timeout_s=…, stop=…)` returns an `Execution` (outcome, exit status,
output, whether processes were left running, and the network, subprocess and file-write
attempts the audit hook detected). `detection_evidence` turns detections into evidence records;
`ready_payload(side)` is the `sandbox.ready` payload. Containment is a Job Object on Windows and
a process group with resource limits on POSIX; the network is detected, not enforced (L3, D02).

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
| `ui_dir` | `REPRO_UI_DIR` | this checkout's `apps/web/dist`, if built (`pnpm build`) |

Unknown keys and invalid values are errors that name their source. Paths must be absolute
after `~` is expanded.
