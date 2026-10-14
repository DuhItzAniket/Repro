# C02 — Storage & evidence store

| | |
|---|---|
| **Stage** | C — Engine core & live stream |
| **Status** | done |
| **Depends on** | C01 |
| **Branch / PR** | `phase/C02-storage` · [#30](https://github.com/DuhItzAniket/Repro/pull/30) |
| **Started / finished** | 2026-10-14 / 2026-10-14 |

## Objective
Runs, their events, their evidence and their artifacts are stored durably and in order: one
writer batches events into transactions and gives each its `seq`, readers page through a run's
log, and a crash at any moment leaves a database that opens, passes its integrity check and
holds only whole batches.

## Scope
- **Database** (`repro.store.db`, ARCHITECTURE §11): SQLite at `<data dir>/repro.db`, WAL,
  `synchronous=NORMAL`, `busy_timeout`, `foreign_keys=ON`, connections in explicit-transaction
  mode. Read-only connections for readers. SQLite 3.37 or newer (STRICT tables); `repro doctor`
  reports the version.
- **Schema and migrations** (`repro.store.schema`): numbered migrations tracked by
  `PRAGMA user_version`, each applied in its own transaction; a database from a newer Repro is
  refused rather than opened. Tables:
  - `runs`: the run registry (repo, base, head, producer, status, created and finished times);
  - `events`: `PRIMARY KEY (run_id, seq)`, `UNIQUE (id)`, the envelope's indexed fields and the
    canonical JSON body;
  - `evidence`: one row per evidence item, tied to the `evidence.created` event that introduced
    it by `(run_id, seq)`;
  - `artifacts`: content-addressed files of a run, `PRIMARY KEY (run_id, sha256)`;
  - `cards`: one card per run (filled from F05).

  The database enforces the event-log rules itself: events and evidence are append-only
  (triggers abort updates and deletes), each run's `seq` starts at 1 and has no gaps (a trigger
  checks every insert), and evidence needs its event.
- **Writer** (`repro.store.writer`): the single writer. One thread owns the only write
  connection. Callers submit events without `seq` (singly or as an atomic group, optionally with
  an evidence record); the thread gathers them into a batch (up to N events or a few
  milliseconds), opens `BEGIN IMMEDIATE`, assigns each run's next `seq`, inserts, commits, and
  only then resolves the callers' futures and calls the commit hook (C03 publishes from there).
  A batch that fails is retried group by group, so one bad group does not lose the others. The
  run registry and artifact rows are written through the same thread. `checkpoint()` runs
  `wal_checkpoint(TRUNCATE)` (at run end).
- **Reader** (`repro.store.reader`): a run's events from a `seq`, in order and in pages, the last
  `seq`, runs, evidence by ID, artifacts by digest.
- **Artifacts** (`repro.store.artifacts`): files under `<data dir>/runs/<run_id>/<path>`, written
  to a temporary file, hashed while written, flushed and renamed into place; recorded by SHA-256.
  The same content at the same path is stored once. Paths are relative POSIX paths inside the run
  directory: absolute paths, drive letters, `..`, backslashes and over-long paths are rejected.
- **IDs and time** (`repro.ids`, `repro.clock`): ULIDs with the schema's prefixes (`run_`,
  `evt_`, `ev_`), monotonic within a millisecond, and the RFC 3339 UTC timestamps the schema uses.

## Out of scope
- Building events (IDs, timestamps, payload validation, secret scrubbing) and publishing them to
  subscribers: the bus, C03. The writer takes envelopes as given, without `seq`.
- Card assembly (F05); the `cards` table exists so the schema is complete.
- Retention and deleting runs: append-only now; a later migration would add it.

## Design notes
- The `seq` rule is enforced twice: the writer assigns it, and a trigger rejects any insert that
  is not the run's next number, so no other code path can create a gap or a duplicate.
- WAL with `synchronous=NORMAL`: SQLite documents that WAL mode "is always consistent with
  synchronous=NORMAL", that a committed transaction "might roll back following a power loss or
  system crash", and that transactions "are durable across application crashes regardless of the
  synchronous setting" [V: https://www.sqlite.org/pragma.html#pragma_synchronous, checked
  2026-10-14]. So a killed engine loses no committed batch; a power loss may lose the last ones,
  never consistency. The crash tests kill a writer process outright, at random points and in the
  middle of a transaction.
- STRICT tables need SQLite 3.37.0 or later [V: https://www.sqlite.org/stricttables.html,
  checked 2026-10-14]; the Python 3.12 and 3.13 builds used here ship 3.50.4 (measured).
- No new dependency: `sqlite3` is in the standard library; the engine now depends on the
  workspace's `repro-events` for the evidence model.

## Acceptance criteria
- [x] AC1 (roadmap): 100k events written and read back in order.
- [x] AC2 (roadmap): a crash mid-batch leaves a consistent database (test).
- [x] AC3 (roadmap): `UNIQUE(run_id, seq)` is enforced.
- [x] AC4: events and evidence cannot be edited or deleted; `seq` has no gaps.
- [x] AC5: artifacts are content-addressed, written atomically and confined to their run's
      directory.
- [x] AC6: a database from a newer schema is refused; migrations are idempotent.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_store_writer.py::test_100k_events_round_trip` (timed) |
| AC2 | `test_store_crash.py`: a process killed mid-transaction, and one killed at random while writing |
| AC3 | `test_store_schema.py`: a duplicate `(run_id, seq)` is rejected by the database |
| AC4 | `test_store_schema.py`: triggers; `test_store_writer.py`: seq across batches and runs |
| AC5 | `test_store_artifacts.py` |
| AC6 | `test_store_schema.py` |

---
*Filled in at the end of the phase:*

## What shipped
- `engine/src/repro/store/`: `db.py`, `schema.py` (migration 1), `writer.py`, `reader.py`,
  `artifacts.py`; `repro/ids.py` (ULIDs) and `repro/clock.py` (timestamps, now also used by the
  logs); `repro doctor` checks SQLite (3.37+, required).
- Tests: `test_store_schema.py` (15), `test_store_writer.py` (19), `test_store_crash.py` (4),
  `test_store_artifacts.py` (28), `test_ids.py` (7), `test_doctor.py` (+3): pytest 590 → 666
  (665 pass and 1 skips on Windows).

## Evidence
- 100k `log.line` events submitted one by one through the writer (each checked against the
  envelope model) and read back in order: written in 2.6 s, read in 0.2 s, on the development
  machine (Windows 11, i7-14650HX, SSD; single measurement, printed by the test).
- Crash: a child process killed with a transaction open (`os._exit`), and killed outright at
  0.05, 0.3 and 0.9 s while committing batches of 25-event groups. Each time the database passed
  `PRAGMA integrity_check` and `foreign_key_check`, held only whole groups with `seq` from 1
  without gaps, and took the next event at the next `seq`.
- CI run: linked in the PR.

## Deviations from spec
- `artifacts` is keyed by `(run_id, sha256, path)` with `(run_id, path)` unique, rather than
  `(run_id, sha256)`: two observations with equal bytes are two artifacts at two paths, and a
  path never changes content. Lookup by digest returns the first path.

## Known gaps
- Building, validating and publishing events is the bus (C03); the writer checks only the
  envelope shape, not each kind's payload schema.
- No retention or deletion of runs yet (append-only triggers would be relaxed by a migration).
- The `cards` table has no writer method until the card exists (F05).

## Dependencies added
None (the standard library's `sqlite3`; the workspace's `repro-events`).

## Research notes
