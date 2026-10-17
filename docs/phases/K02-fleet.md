# K02 — Fleet dashboard

| | |
|---|---|
| **Stage** | K — Expansion backlog |
| **Status** | in progress |
| **Depends on** | — |
| **Branch / PR** | `phase/K02-fleet` · PR pending |
| **Started / finished** | 2026-10-18 / — |

## Objective
Many PRs and agents at once (roadmap: "the 64 papers view"): every run an engine holds, live,
on one page, each opening into the cockpit.

## Scope
- **API: `GET /fleet?limit=64`** (1 to 500), behind the session token like every data route.
  Each run as `/runs` gives it, plus its card's status once it has one, and the repository and
  pull request its `run.started` names. A run whose first event is not `run.started` has
  neither.
- **The page: `fleet.html`**, a second entry of the web build. It shares the cockpit's design
  tokens and its session token (sessionStorage, per origin).
  - A grid of up to 64 tiles, polled every two seconds.
  - A tile's state is the run's ("running") until it ends, then its card's (VERIFIED,
    FLAGGED, UNVERIFIABLE). A run that ended with no card is "failed".
  - **Motion maps to events.** A tile flashes once when its run has written events since the
    last poll, and never because time passed (DESIGN.md "Motion"). With
    `prefers-reduced-motion` it does not flash.
  - Every tile is a link with a spoken label: title, repository, status, event count. The
    counts line is a polite live region.
- **The model is pure and tested** (`src/fleet/model.ts`): states, titles, flashes, counts,
  and the response checked.

## Out of scope
- Agents across engines, or a server that aggregates several data directories: one engine,
  one data directory.

## Acceptance criteria
- [x] AC1: every run of a data directory on one page, its state live.
- [x] AC2: motion only for events; reduced motion respected.
- [x] AC3: a tile opens its run in the cockpit.
- [x] AC4: the route needs the session token.

## Test plan
| Criterion | Check |
|---|---|
| AC1, AC3 | `model.test.ts` (5); `test_api_rest.py`: the fleet's fields, a run with no `run.started`, the limit; checked in a browser against a real data directory, as below |
| AC2 | `model.test.ts`: a tile flashes only when its event count grew since the last poll, never on the first poll |
| AC4 | `test_api_security.py`: `/fleet` without the token, or with a wrong one, is 401 |

---
*Filled in at the end of the phase:*

## What shipped
- `GET /fleet`; `apps/web/fleet.html`, `src/fleet/{model,main}.tsx`, `fleet.css`; the build's
  second entry.
- Docs: the quickstart's "Many runs at once".
- Tests: `model.test.ts` (5), one in `test_api_rest.py`, `/fleet` in `test_api_security.py`.

## Evidence
- **In a browser**, `repro serve` on a data directory holding J04's six twine runs:
  - the page listed them, each titled by its pull request's title, all UNVERIFIABLE;
  - a full run started meanwhile appeared as "running", flashed as its events grew from 127
    to 143, and turned UNVERIFIABLE at 154;
  - its tile opened the run in the cockpit, the token carried over;
  - no console errors.
- **Bundle**: 201.89 kB gzipped across both pages, under the 300 kB gate.
- CI run: linked in the PR.

## Deviations from spec
None.

## Known gaps
- Polling, not the event stream: one stream per run does not scale to 64 tiles. The two-second
  poll reads one summary row per run.
- The flash plays once while the class stays on: a run that writes events at every poll
  flashes at its first growth only, until a poll finds it unchanged.

## Dependencies added
None.
