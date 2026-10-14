# Stage C gate — Engine core & live stream

| | |
|---|---|
| **Phases** | C01–C08 |
| **Release** | `v0.3.0` |
| **Gate date** | 2026-10-14 |

## Stage acceptance criteria
| Criterion (ROADMAP Gate C) | Result | Evidence |
|---|---|---|
| `repro run --repo <small OSS lib> --base A --head B` shows that repo's real import graph and blast radius in the cockpit live | pass | The `gate-c` CI job (Linux) runs `apps/web/gate/gate-c.spec.ts` against the real engine on pallets/itsdangerous (BSD-3-Clause) at `93ae366..7f4dcf8`, cloned at run time: every one of its 15 modules, 36 imports, the 5 changed symbols and a blast radius checked by hand against the import lines at `7f4dcf8`. The same spec passes on Windows in Edge (6.2 s), and the live cockpit was checked by eye in the browser |
| `repro replay` reproduces the same UI state | pass | The spec replays the stored run from a new process and requires a summary identical to the live one: the same events in the same order (an FNV-1a digest of their IDs), the same modules, counters, blast radius and end time. Manually on Windows: 72 events, digest `204ca4c3` in both |

## Phases
| Phase | PR | What it brought |
|---|---|---|
| C01 | [#29](https://github.com/DuhItzAniket/Repro/pull/29) | Engine skeleton: layered settings, data paths, JSON logs, `repro doctor`, the CLI |
| C02 | [#30](https://github.com/DuhItzAniket/Repro/pull/30) | The store: SQLite (WAL, STRICT), append-only gap-free events in the schema, one batching writer, artifacts |
| C03 | [#31](https://github.com/DuhItzAniket/Repro/pull/31) | The event bus (validation, credential scrubbing) and the orchestrator (a DAG with timeouts and cancellation; `run.finished` always) |
| C04 | [#32](https://github.com/DuhItzAniket/Repro/pull/32) | Read-only REST and the replay-then-live WebSocket; local `Host` and allow-listed `Origin` (T16) |
| C05 | [#33](https://github.com/DuhItzAniket/Repro/pull/33) | The git layer: hardened commands (T17), exact-path diffs, snapshots from tree objects with unsafe entries skipped (T18), worktrees |
| C06 | [#34](https://github.com/DuhItzAniket/Repro/pull/34) | Module names, `ast` symbol tables, changed symbols by own code, renames and moves |
| C07 | [#35](https://github.com/DuhItzAniket/Repro/pull/35) | Import graphs (grimp in an isolated process, T19; `ast` outside packages) and the blast radius |
| C08 | [#36](https://github.com/DuhItzAniket/Repro/pull/36) | `repro run`, `replay`, `serve` with the cockpit; the cockpit's event-stream client; Gate C's end-to-end test |

## CI matrix
| OS | Python | Node | Result | Run |
|---|---|---|---|---|
| ubuntu-latest | 3.13 | 24 | pass | [CI run 38604672519](https://github.com/DuhItzAniket/Repro/actions/runs/38604672519) on [#36](https://github.com/DuhItzAniket/Repro/pull/36) |
| windows-latest | 3.13 | 24 | pass | [CI run 38604672519](https://github.com/DuhItzAniket/Repro/actions/runs/38604672519) on [#36](https://github.com/DuhItzAniket/Repro/pull/36) |
| ubuntu-latest, Gate C (Chromium from Playwright 1.64.0) | 3.13 | 24 | pass | [CI run 38604672519](https://github.com/DuhItzAniket/Repro/actions/runs/38604672519) on [#36](https://github.com/DuhItzAniket/Repro/pull/36) |
| ubuntu-latest + Playwright image (visual) | — | 24 | pass | [CI run 38604672519](https://github.com/DuhItzAniket/Repro/actions/runs/38604672519) on [#36](https://github.com/DuhItzAniket/Repro/pull/36) |

## Metrics at gate (measured)
| Metric | Value |
|---|---|
| Tests | pytest 891 (889 pass and 2 POSIX-only tests skip on Windows); Vitest 374 (`@repro/events` 47, `@repro/synth` 34, `@repro/web` 293); 8 visual screenshots; Gate C |
| Engine code | 5,690 lines of Python under `engine/src` (46 at Gate B) and 4,679 in `engine/tests` |
| Web code | 11,776 lines of TypeScript outside tests and 5,300 in tests, under `apps/web/src` |
| JavaScript, gzip | 197.5 kB of the 300 kB budget (196.0 kB at Gate B) |
| `repro run --no-serve` on itsdangerous `93ae366..7f4dcf8` | 72 events in 1.8 s; static analysis 0.47 s with the blobs local (26 s in a blobless clone, which fetches each blob on first read) |
| Static analysis of this repository's C05 change | 77 modules, 155 imports, 0.70 s |
| Store | 100k events written in 2.6 s and read in 0.2 s (C02) |

## Retrospective
- **Tests found real faults, every phase.** A SQLite connection closed by one thread while
  another read from it crashed the event stream on the Ubuntu runner (C05 fixed C04's stream).
  "A changed line is a changed symbol" was wrong as soon as a fixture added a comment (C06
  compares own code). grimp's default package finder would have analysed the wrong code for a
  target package named like a loaded module, and could have run target code through `sys.path`
  (C07, T19). The Gate C test found a socket printed before it listened, and a venv launcher
  that outlived its kill on Windows (C08).
- **Real repositories early.** Running the analysis on this repository's own history before the
  pinned test existed caught a wrong module-naming rule (`engine.src.repro…`), and the itsdangerous
  run showed the cost of blobless clones.
- **Privacy in commit metadata.** GitHub authors squash merges with the account's default
  email: `main`'s merge commits #1–#34 carry the owner's personal address, although every commit
  made here used the noreply one. The owner turned on email privacy on 2026-10-14; from #35 on,
  merges carry the noreply address and are checked after each merge.

## Gaps and owed items
- **Owner:** decide whether to rewrite the 32 merge commits on `main` that carry the personal
  address (#1–#34, both tags); this needs a force-push of `main` and re-tagged releases, and old
  clones keep them.
- **Owner (from Stage B):** a 60 fps check on a mid laptop; making `visual`, `gates` and now
  `gate C` required checks; enabling the Dependency graph; Dependabot #17.
- The cockpit served by the engine comes from the checkout's build (packaging: Stage H); no
  content security policy on it yet (H03).
- Analysis gaps are listed per phase: dynamic imports, PEP 420 namespace packages, module-level
  blast radius until Stage E's dynamic map.
