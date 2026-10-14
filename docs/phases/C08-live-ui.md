# C08 — Live UI wiring & end-to-end

| | |
|---|---|
| **Stage** | C — Engine core & live stream |
| **Status** | done |
| **Depends on** | B12, C04, C07 |
| **Branch / PR** | `phase/C08-live-ui` · [#36](https://github.com/DuhItzAniket/Repro/pull/36) |
| **Started / finished** | 2026-10-14 / 2026-10-14 |

## Objective
`repro run --repo <repository> --base A --head B` reproduces a change's build stage and shows
it in the cockpit live; `repro replay` shows a stored run, or an event log, from the start; and
the two end in the same state. This is Gate C.

## Scope
- **The pipeline** (`repro.pipeline`): the build stage as orchestrator jobs: both sides'
  snapshots (`snapshot.ready`, now with `tree_sha256`) and the static analysis (C06, C07) as
  `graph.node`, `graph.edge`, `symbol.changed` (with its target), `blast.computed`, and
  `missing.recorded` for what could not be read. Scratch is removed when the run ends.
- **`repro run`** resolves both refs, opens the store, and either serves the cockpit and streams
  the run live from the same process (`--serve`, the default; `--open` opens the browser) or
  waits for the run and exits 0/1 (`--no-serve`).
- **`repro replay <run id | log.jsonl>`**: a stored run over the event stream from the start, or
  a validated event log served at `/replay.jsonl`.
- **`repro serve`** serves the built cockpit (`ui_dir`, by default the checkout's
  `apps/web/dist`) beside the read-only API.
- **The cockpit's sources** (`?run=`, `?run=…&replay`, `?log=`, or the engine's newest run) and
  its **event-stream client**: replay, `caught_up`, live; gaps and the engine's "resync" are
  recovered from the store; lost connections retried with backoff; refusals reported.
- **Gate C test** (`apps/web/gate/gate-c.spec.ts`) and its CI job.

## Out of scope
- Running tests (Stage D), the card (F05), exporting (H04), the per-session token (H03).

## Design notes
- **The store is the judge of continuity.** The client appends each frame's events to the
  cockpit's store, which ignores duplicates and stops at a gap; on a gap the client reconnects
  with `?from=` the last `seq` it holds and the engine's store sends the rest. The engine's own
  4000 "resync" close is handled the same way. Normal closes ("finished", "replayed") end the
  stream; 4404, 4400 and 1008 are reported and not retried; anything else is retried at
  0.5 s, 1 s, 2 s, 4 s, then every 5 s.
- **Live ends like a replay.** Live time follows the wall clock from the newest event; when the
  stream ends, nothing more will come, so the clock waits at the end of the data, as a replay
  does. That is what makes "the same UI state" checkable.
- **Same-origin logs only.** `?log=` accepts a path on the page's own origin (a fixture name, or
  `/replay.jsonl`); a URL to elsewhere falls back to the demo.
- **The port is open before anything starts.** `repro run` binds and listens before it opens
  the store or starts the run, so a busy port fails at once and a browser opened as soon as the
  URL is printed waits in the backlog instead of being refused (found by the Gate C test).
- **Served files** come from Starlette's `StaticFiles` (no following of symlinks out of the
  directory; `..` refused), mounted after the API's routes so `/runs…` always reaches the API.
- **`tree_sha256`** is the SHA-256 of one line per written snapshot entry (mode, blob SHA, a tab,
  path, a newline) in path order: it names exactly what the snapshot holds.

## Acceptance criteria
- [x] AC1 (roadmap): the Gate C scenario passes in CI (Linux) and manually on Windows.
- [x] AC2: the client recovers from gaps, resyncs and lost connections, and reports refusals.
- [x] AC3: `repro run`, `replay` and `serve` behave as documented, including their failures.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `gate-c` CI job; the same spec on Windows with Edge (`REPRO_GATE_CHANNEL=msedge`) |
| AC2 | `src/data/stream.test.ts`, `src/data/source.test.ts` (Vitest, a fake socket) |
| AC3 | `test_run_command.py`, `test_cli.py`, `test_config.py`, `test_gitops_snapshot.py` |

---
*Filled in at the end of the phase:*

## What shipped
- Engine: `repro/pipeline.py` (the build stage's jobs), `repro/api/ui.py` (finding the built
  cockpit), `create_app(ui_dir=, replay_log=)`, the `ui_dir` setting, `Snapshot.tree_sha256`,
  and `repro run`, `replay`, `serve` in `repro/cli.py`.
- Cockpit: `src/data/source.ts` (sources), `src/data/stream.ts` (the event-stream client),
  `main.tsx` wiring, and `summary()` on the `?test` hook.
- Gate C: `apps/web/gate/gate-c.spec.ts`, `playwright.gate.config.ts`, the `gate-c` CI job.
- Tests: `test_run_command.py` (8), `test_cli.py`, `test_config.py` and `test_gitops_snapshot.py`
  updated (pytest 883 → 891: 889 pass and 2 skip on Windows); Vitest `stream.test.ts` and
  `source.test.ts` (27).

## Evidence
- **Gate C on Windows**: the spec passes against `repro run` and `repro replay` on
  pallets/itsdangerous `93ae366..7f4dcf8`, in Edge (`REPRO_GATE_CHANNEL=msedge`), in 6.2 s. The
  live and the replayed cockpit hold the same 72 events in the same order (FNV-1a digest of
  their IDs `204ca4c3` in the manual check), the same 15 modules and 36 imports, the same
  header counters, and the blast radius checked by hand: signer is imported by `__init__`,
  serializer, timed, test_signer and test_timed, the changed test_serializer by test_timed and
  test_url_safe (distance 1), and url_safe reaches signer only through serializer and timed
  (distance 2). Each was checked against the import lines at `7f4dcf8`.
- A manual look in the in-app browser (1440×900): the live run shows the file ring of the
  library's real modules, the import web, the feed (snapshots, analysis, graph, blast radius)
  and the change routes of the five changed symbols.
- `repro run --no-serve` on that change: 72 events in 1.8 s, and its exported log validates
  (`repro-events validate`: 0 errors).
- The Gate C test found two real faults, both fixed: a browser opened as soon as the URL was
  printed was refused (the socket was bound but not yet listening), and on Windows stopping
  `.venv\Scripts\python.exe` left the engine running (a virtual environment's `python.exe` is a
  launcher; the spec ends the process tree).
- Bundle: 197.5 kB gzip (budget 300 kB). CI: [CI run 38604672519](https://github.com/DuhItzAniket/Repro/actions/runs/38604672519) on [#36](https://github.com/DuhItzAniket/Repro/pull/36), all jobs green; the Gate C job's spec passed in 6.7 s.

## Deviations from spec
None.

## Known gaps
- `repro run` keeps serving after the run ends, until Ctrl+C; a run killed outright (not
  Ctrl+C) leaves its scratch directory if it had not finished. `repro doctor` does not yet list
  leftover scratch directories.
- The cockpit served by `repro serve` comes from the checkout's build; packaging it in the
  wheel belongs to H (distribution).
- No content security policy on the served cockpit yet; the API's `Host` and `Origin` checks
  (T16) apply. Hardening the served page is H03's.

## Dependencies added
None.

## Research notes
- Starlette 1.8.0's `StaticFiles.lookup_path` (read in the installed package): absolute paths
  are refused, and without `follow_symlink` the path is resolved with `os.path.realpath` and
  must stay under the directory (`os.path.commonpath`), so neither `..` nor a symlink leaves it.
