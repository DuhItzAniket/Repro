# C04 — API & WebSocket transport

| | |
|---|---|
| **Stage** | C — Engine core & live stream |
| **Status** | in progress |
| **Depends on** | C03 |
| **Branch / PR** | `phase/C04-api-websocket` · PR pending |
| **Started / finished** | 2026-10-14 / — |

## Objective
A client on the same machine can follow a run as it happens and replay it afterwards: a
WebSocket sends every event of the run exactly once, in `seq` order, whether the client connects
at the start, mid-run or after the end, and a client that cannot keep up is told to resync from
where it is without ever slowing the engine down.

## Scope
- **WebSocket** `GET /runs/{run_id}/events?from=<seq>` (ARCHITECTURE §11; research/04 §8):
  1. the client's bounded queue is subscribed to the bus **first**;
  2. stored events with `seq > from` are sent in pages;
  3. queued events already sent are dropped, the rest follow in order;
  4. a `{"type": "caught_up", "seq": n}` frame marks the end of the replay;
  5. live events follow in frames (`{"type": "events", "events": [...]}`) batched every 25 ms;
  6. after `run.finished` the server closes normally (1000, "finished").

  A client whose queue overflows is closed with 4000 "resync"; it reconnects with `?from=` its
  last `seq`. The writer never waits for a client. An unknown run closes with 4404.
- **REST** (read-only): `GET /runs`, `/runs/{id}`, `/runs/{id}/evidence/{ev}`,
  `/runs/{id}/artifacts/{sha256}` (verified against its digest), `/runs/{id}/card` (404 until the
  card exists, F05).
- **Local-only by default** (THREAT_MODEL T13, and a new T16): the server binds `127.0.0.1`.
  - Requests must name a local host (`Host` check), which defeats DNS rebinding.
  - A WebSocket handshake with an `Origin` header must come from an allow-listed origin (the
    server's own and any given with `--allow-origin`), which defeats cross-site WebSocket hijacking
    by a page in the user's browser. OWASP: "Validate the `Origin` header on every handshake",
    with "an explicit allowlist of trusted origins" [V: https://cheatsheetseries.owasp.org/
    cheatsheets/WebSocket_Security_Cheat_Sheet.html, checked 2026-10-14].
- **`repro serve`** starts the API with uvicorn on `127.0.0.1:8780` (a project choice).
- Dependencies: `fastapi`, `uvicorn` and `websockets` (uvicorn's WebSocket implementation), and
  `httpx` for FastAPI's test client (dev).

## Out of scope
- Serving the cockpit and the UI's WebSocket client (C08); live events across processes (C08 runs
  the engine and the server in one process).
- The per-session token (H03, THREAT_MODEL T13).

## Design notes
- The bus calls listeners on the writer's thread; each connection's listener hands events to the
  event loop with `call_soon_threadsafe` and returns at once. The per-connection buffer is bounded
  by event count; overflowing it closes the connection instead of growing or blocking.
- Replay frames carry the stored JSON bodies verbatim (no re-serialisation), so a replayed event
  is byte-identical to the stored one.

## Acceptance criteria
- [x] AC1 (roadmap): no gaps or duplicates when a client connects mid-run (concurrency test).
- [x] AC2 (roadmap): a slow client is dropped and recovers with `?from=`.
- [x] AC3: requests to a non-local host and WebSocket handshakes from a foreign origin are refused.
- [x] AC4: the REST endpoints return runs, evidence and verified artifacts, and refuse what does
      not exist.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_api_stream.py`: clients connecting before, during and after a run of thousands of events, with a writer emitting concurrently |
| AC2 | `test_api_stream.py`: a client that stops reading on a real server is closed with `resync`, then resumes with `?from=` and receives the rest exactly once |
| AC3 | `test_api_security.py` |
| AC4 | `test_api_rest.py` |

---
*Filled in at the end of the phase:*

## What shipped
- `engine/src/repro/api/` (`app.py`, `stream.py`); `repro serve`; `StoreReader.card`;
  `store.artifacts.sha256_of` is public; THREAT_MODEL gains A5 and T16.
- Tests: `test_api_stream.py` (11), `test_api_rest.py` (7), `test_api_security.py` (17),
  `test_cli.py` (+1 net): pytest 713 → 749 (748 pass and 1 skips on Windows).

## Evidence
- Mid-run: clients connecting 0, 50 and 300 ms into a run of 4,000 events written concurrently,
  and four clients at once, each received every `seq` exactly once and in order, one
  `caught_up`, then a normal close after `run.finished`.
- Slow client, on a real uvicorn server (`websockets-sansio`): a client that read nothing while
  60,000 events were written was closed with 4000 "resync" (what it had received was gap-free),
  reconnected with `?from=` its last `seq`, and ended with all 60,001 events exactly once.
  Repeated three times.
- A real server refuses a foreign `Origin` with HTTP 403.
- CI run: linked in the PR.

## Deviations from spec
- The test client is `httpx2` rather than `httpx`: Starlette 1.8's test client deprecates
  `httpx` in its favour (`httpx2` 2.13.1, BSD-3-Clause, pydantic organisation; PyPI JSON API,
  checked 2026-10-14). uvicorn runs its `websockets-sansio` implementation, as its own
  deprecation notice for the legacy `websockets` one advises.

## Known gaps
- Live events need the producing process: `repro serve` alone replays stored runs and closes
  with "replayed"; C08 runs the engine and the server together.
- No per-session token until H03 (T13): any local process can read runs through the API.

## Dependencies added
| Package | Version (locked) | Licence | Why |
|---|---|---|---|
| fastapi | 0.143.1 | MIT | REST and WebSocket API (the decided stack, CLAUDE.md) |
| uvicorn | 0.54.0 | BSD-3-Clause | ASGI server |
| websockets | 17.2 | BSD-3-Clause | uvicorn's WebSocket protocol; the tests' client |
| httpx2 (dev) | 2.13.1 | BSD-3-Clause | Starlette's test client |

## Research notes
